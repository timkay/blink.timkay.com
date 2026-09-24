#!/usr/bin/env python3
import csv,datetime as dt,json,sqlite3,sys,time
from pathlib import Path
from zoneinfo import ZoneInfo

csv_path=Path(sys.argv[1]); db_path=Path(sys.argv[2])
tz=ZoneInfo('America/Los_Angeles'); now=int(time.time())
def parse_start(row):
    date=dt.datetime.strptime(row['session_date'],'%B %d, %Y').date()
    raw=row.get('session_start','').strip()
    for fmt in ('%I:%M %p, %b %d, %Y PDT','%I:%M %p, %B %d, %Y PDT'):
        try:return int(dt.datetime.strptime(raw,fmt).replace(tzinfo=tz).timestamp())
        except ValueError:pass
    return int(dt.datetime.combine(date,dt.time(12),tzinfo=tz).timestamp())
def num(row):
    raw=row.get('total_energy') or row.get('summary_energy') or ''
    try:return float(raw.split()[0])
    except (ValueError,IndexError):return None
c=sqlite3.connect(db_path); c.execute('BEGIN')
existing=[]
for data in c.execute('SELECT data FROM sessions'):
    d=json.loads(data[0]); existing.append(d)
added=0
for row in csv.DictReader(csv_path.open()):
    station=row.get('charging_station','').split(',')[0].strip(); kwh=num(row)
    if not station.startswith('BAE') or kwh is None:continue
    started=parse_start(row); day=dt.datetime.fromtimestamp(started,tz).date().isoformat()
    if any(d.get('station')==station and d.get('kwh')==kwh and dt.datetime.fromtimestamp(d.get('started',0),tz).date().isoformat()==day for d in existing):continue
    ident='backfill-'+station+'-'+day+'-'+str(kwh)+'-'+str(added)
    entry=dict(id=ident,station=station,started=started,updated=now,state='ended',kwh=kwh,elapsed=row.get('connection_time',''),end_time=row.get('session_end',''),source='Blink charge history backfill')
    c.execute('INSERT OR IGNORE INTO sessions VALUES(?,?)',(ident,json.dumps(entry)));c.execute('INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,0)',(ident,station,now,'backfilled station history',json.dumps(entry)));existing.append(entry);added+=1
c.commit();print('added',added,'station-identified sessions')
