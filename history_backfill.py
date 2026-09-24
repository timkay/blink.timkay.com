"""Incremental UI-only station-history backfill; one day per controller step."""
import datetime as dt
import hashlib
import json
import re
import time
from zoneinfo import ZoneInfo

def records(root):
    from controller import texts, SERIAL
    found={}
    for node in reversed(list(root.iter('node'))):
        values=texts(node)
        if values.count('Date')!=1 or values.count('Serial Number')!=1:continue
        def field(label):
            try:return values[values.index(label)+1]
            except (ValueError,IndexError):return ''
        serial=field('Serial Number')
        if not SERIAL.fullmatch(serial):continue
        try:
            start=dt.datetime.strptime(field('Date')+' '+field('Start Time'),'%B %d, %Y %I:%M %p').replace(tzinfo=ZoneInfo('America/Los_Angeles'))
            energy=float(field('Energy').split()[0])
        except (ValueError,IndexError):continue
        if not field('Charging Time') or not field('End Time'):continue
        ident='history-'+hashlib.sha256((serial+start.isoformat()).encode()).hexdigest()[:24]
        found[ident]=dict(id=ident,station=serial,started=int(start.timestamp()),updated=int(time.time()),state='ended',kwh=energy,elapsed=field('Charging Time'),end_time=field('End Time'),source='Blink charge history')
    return found

def step(c):
    from controller import texts,find,stamp
    job=c.get('history_backfill')
    if not job or job.get('complete'):return
    c.mode='backfilling six-month station history'
    root=c.tab('Account')
    for _ in range(5):
        if find(root,'History') is not None:break
        root=c.back()
    c.choose(root,'History');root=c.screen();c.choose(root,'Blink Pro');root=c.screen()
    month=next((m for m in job['months'] if m not in job.get('months_done',[])),None)
    if not month:job['complete']=True;c.save('history_backfill',job);return
    for _ in range(12):
        if find(root,month) is not None:break
        c.adb('shell','input','swipe','360','1300','360','600','350');root=c.screen()
    c.choose(root,month);root=c.screen()
    day=None;previous=None
    for _ in range(25):
        days=[v for v in texts(root) if re.fullmatch(r'[A-Z][a-z]+ \d{1,2}, 20\d\d',v)]
        for value in days:
            date=dt.datetime.strptime(value,'%B %d, %Y').date().isoformat()
            if date>=job['cutoff'] and value not in job.get('days_done',[]):day=value;break
        if day:break
        signature=tuple(texts(root))
        if signature==previous:
            job.setdefault('months_done',[]).append(month);c.save('history_backfill',job);return
        previous=signature
        c.adb('shell','input','swipe','360','1300','360','620','350');root=c.screen()
    if not day:raise RuntimeError('Backfill could not reach end of month')
    c.choose(root,day);root=c.screen()
    if 'Details' not in texts(root):raise RuntimeError('Backfill expected session Details')
    entries={};previous=None;bottom=False
    for index in range(25):
        # Save the actual UI evidence before parsing, including multi-session days.
        evidence=c.dbpath.parent/'history-backfill';evidence.mkdir(exist_ok=True)
        import xml.etree.ElementTree as ET
        ET.ElementTree(root).write(evidence/(day.replace(' ','_')+f'-{index}.xml'),encoding='utf-8')
        entries.update(records(root))
        signature=tuple(texts(root))
        if signature==previous:bottom=True;break
        previous=signature
        c.adb('shell','input','swipe','360','1300','360','800','350');root=c.screen()
    if not entries or not bottom:raise RuntimeError('Incomplete history detail scan: '+day)
    for entry in entries.values():
        if dt.datetime.fromtimestamp(entry['started'],ZoneInfo('America/Los_Angeles')).strftime('%B %d, %Y').replace(' 0',' ')!=day:raise RuntimeError('History date mismatch')
        for ident,payload in c.db.execute('SELECT id,data FROM sessions').fetchall():
            old=json.loads(payload)
            if old.get('station')==entry['station'] and abs(old.get('started',0)-entry['started'])<60 and abs((old.get('kwh') or 0)-entry['kwh'])<0.011:
                entry['id']=ident;break
        c.db.execute('INSERT OR REPLACE INTO sessions VALUES(?,?)',(entry['id'],json.dumps(entry)))
        c.event('backfilled station history',entry,entry['station'])
    c.db.commit()
    job.setdefault('days_done',[]).append(day);job['sessions']=job.get('sessions',0)+len(entries);job['last_day']=day
    c.save('history_backfill',job)
    print('History backfill:',day,len(entries),'sessions; total',job['sessions'],flush=True)
