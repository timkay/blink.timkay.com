#!/usr/bin/env python3
"""Phone-local Blink observer and serialized, fail-closed command executor.

Owns UIAutomator exclusively. Local SQLite is the durable source/outbox; HTTP
sync runs separately so a network timeout never blocks charging observation.
"""
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sqlite3
import subprocess as sp
import threading
import time
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from monitor import notify

ROOT=Path(__file__).resolve().parent
CONFIG=Path.home()/'.config/blink-monitor/controller.json'
SERIAL=re.compile(r'^BAE\d{6}$')
STATUSES={'Available','In Use','Unavailable','Connected','Offline','Faulted','Charging','Reserved'}
COMPLETE={'Charge Complete','Completed','Please unplug the connector'}
END={'Thank you for charging!','You are all charged up!','Charging session has been completed. Please move your vehicle.'}
PRIMARY_LOCATION='1850 Gateway Drive'
SECONDARY_LOCATION='Redwood City - CN37-12'
LOCATION_COUNTS={PRIMARY_LOCATION:19,SECONDARY_LOCATION:21}
SITES=json.loads((ROOT/'sites.json').read_text())
LOCATION_COUNTS.update({s['name']:s['ports'] for s in SITES})
SECONDARY_LOCATIONS=[s['name'] for s in SITES if s['name']!=PRIMARY_LOCATION]

def stamp(): return int(time.time())
def texts(root): return [n.get('text') for n in root.iter('node') if n.get('text')]
def find(root,label):
    return next((n for n in root.iter('node') if n.get('text')==label or n.get('content-desc')==label or n.get('resource-id')==label),None)
def center(node):
    x1,y1,x2,y2=map(int,re.findall(r'\d+',node.get('bounds','')))
    if x2<=x1 or y2<=y1: raise ValueError('Target not visible')
    return (x1+x2)//2,(y1+y2)//2
def station_rows(root,ports=False):
    result={}
    if ports:
        for node in root.iter('node'):
            desc=node.get('content-desc','')
            if node.get('clickable')!='true' or not desc.startswith('selectedPortIcon '):continue
            ids=[v for v in texts(node) if SERIAL.fullmatch(v)]
            statuses=[v for v in texts(node) if v in STATUSES]
            if not ids or not statuses:continue
            label=desc.split(',')[0].removeprefix('selectedPortIcon ').strip()
            ident=ids[0]+'~'+re.sub(r'[^A-Za-z0-9-]+','_',label)
            result[ident]=(statuses[0],node)
        return result
    # Smallest subtree containing exactly one serial and a status keeps rows paired.
    for node in reversed(list(root.iter('node'))):
        values=texts(node); ids={v for v in values if SERIAL.fullmatch(v)}
        statuses={v for v in values if v in STATUSES}
        if len(ids)==1 and len(statuses)==1:
            ident=next(iter(ids))
            if ident not in result: result[ident]=(next(iter(statuses)),node)
    return result
def reading(root):
    vals={n.get('content-desc'):n.get('text','') for n in root.iter('node')}
    def num(k):
        m=re.search(r'\d+(?:[.,]\d+)?',vals.get(k,''))
        return float(m[0].replace(',','.')) if m else None
    labels=set(texts(root))
    # Completion wording wins over cached power. Zero alone is never completion.
    state='ended' if 'Start Charge' in labels and labels&END else 'stopped' if labels&COMPLETE else 'charging' if (num('currentSpeedValue') or 0)>0 else 'waiting for data'
    return dict(state=state,kw=num('currentSpeedValue'),kwh=num('energyDeliveredVal'),elapsed=vals.get('chargeTimeVal',''))

class Controller:
 def __init__(self):
    self.cfg=json.loads(CONFIG.read_text()); self.device=self.cfg.get('device','127.0.0.1:36007')
    self.dbpath=ROOT/'data/watch.sqlite3'; self.dbpath.parent.mkdir(exist_ok=True)
    self.db=sqlite3.connect(self.dbpath); self.db.execute('PRAGMA journal_mode=WAL')
    self.db.executescript('''CREATE TABLE IF NOT EXISTS stations(id TEXT PRIMARY KEY,status TEXT,checked INTEGER);
      CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,station TEXT,time INTEGER,kind TEXT,data TEXT,synced INTEGER DEFAULT 0);
      CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,data TEXT);
      CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value TEXT);
      CREATE TABLE IF NOT EXISTS commands(id TEXT PRIMARY KEY,data TEXT,state TEXT,result TEXT);''')
    self.db.execute('CREATE TABLE IF NOT EXISTS station_locations(id TEXT PRIMARY KEY,location TEXT NOT NULL)');self.db.commit()
    self.lock=threading.Lock(); self.mode='starting'; self.error=None
    self.session=self.get('session'); self.changed=stamp(); self.last_energy=None;self.alarm=0;self.last_sample=0
    self.next_scan=0; self.next_history=0;self.active=False;self.stop=threading.Event()
    self.visible_location=None;self.scan_directions={};self.initial_session_check=True
    self.sync_wakeup=threading.Event()
    self.candidate=None
    self.ui_failures=0;self.recovery_level=0;self.last_recovery=0
 def get(self,key):
    row=self.db.execute('SELECT value FROM state WHERE key=?',(key,)).fetchone();return json.loads(row[0]) if row else None
 def save(self,key,value):
    self.db.execute('INSERT OR REPLACE INTO state VALUES(?,?)',(key,json.dumps(value)));self.db.commit()
 def event(self,kind,data,station=None):
    self.db.execute('INSERT INTO events VALUES(?,?,?,?,?,0)',(str(uuid.uuid4()),station,stamp(),kind,json.dumps(data)));self.db.commit()
 def run(self,*args,timeout=15):
    return sp.run(args,text=True,capture_output=True,check=True,timeout=timeout).stdout
 def adb(self,*args):return self.run('adb','-s',self.device,*args)
 def screen(self):
    self.adb('shell','uiautomator','dump','/sdcard/blink-controller.xml')
    xml=self.adb('exec-out','cat','/sdcard/blink-controller.xml');root=ET.fromstring(xml)
    if not any(n.get('package')=='com.blinknetwork.mobile2' for n in root.iter('node')):
        raise RuntimeError('Blink not visible (phone locked or another app open)')
    return root
 def tap(self,node):
    if node is None: raise RuntimeError('Expected UI target missing')
    x,y=center(node); self.adb('shell','input','tap',str(x),str(y));time.sleep(.35)
 def choose(self,root,label):
    node=find(root,label)
    if node is None:raise RuntimeError('Expected UI target missing: '+label)
    self.tap(node)
 def recover_ui(self,error):
    self.ui_failures+=1
    if self.ui_failures<3:return
    cooldown=60 if self.recovery_level<2 else 300
    if self.last_recovery and stamp()-self.last_recovery<cooldown:return
    self.last_recovery=stamp()
    # A dead ADB connection is not an app failure. Never claim recovery succeeded.
    self.run('adb','connect',self.device)
    if self.adb('get-state').strip()!='device':raise RuntimeError('ADB unavailable; cannot recover Blink')
    force=self.recovery_level>0
    self.mode='recovering Blink UI'
    self.event('UI recovery',{'force_stop':force,'error':str(error),'failures':self.ui_failures})
    if force:self.adb('shell','am','force-stop','com.blinknetwork.mobile2')
    self.adb('shell','input','keyevent','KEYCODE_WAKEUP')
    self.adb('shell','am','start','-n','com.blinknetwork.mobile2/com.blinkmobile.MainActivity')
    self.recovery_level+=1;self.active=False;self.next_scan=0
    # Preserve session/alarms/commands. Only a fresh observation establishes health.
    # Defer optional history so its broken navigation cannot starve station scans.
    self.next_history=stamp()+600
    time.sleep(2)
 def dismiss(self,root):
    if set(texts(root)) & (END|{'Charge session started'}):
        ok=find(root,'Ok')
        if ok is not None:self.tap(ok);return self.screen()
    return root
 def tab(self,label):
    self.visible_location=None
    root=self.dismiss(self.screen());self.choose(root,label);return self.screen()
 def back(self):self.adb('shell','input','keyevent','4');return self.screen()
 def location(self,name=PRIMARY_LOCATION):
    root=self.screen()
    header=find(root,'locationName')
    rows=station_rows(root)
    known_location=bool(rows) and getattr(self,'visible_location',None)==name and all(
        self.db.execute('SELECT location FROM station_locations WHERE id=?',(ident,)).fetchone()==(name,)
        for ident in rows)
    if (header is not None and header.get('text')==name) or known_location:
        self.visible_location=name
        return root
    root=self.tab('My Location')
    for _ in range(4):
        if 'Favorite' in texts(root):break
        root=self.back()
    if 'Favorite' not in texts(root):raise RuntimeError('Could not reach pinned locations')
    for _ in range(8):
        match=find(root,name)
        if match is not None:
            try:center(match);break
            except ValueError:pass
        self.adb('shell','input','swipe','380','1300','380','400','300');root=self.screen()
    self.choose(root,name);root=self.screen()
    if name not in texts(root):raise RuntimeError('Selected location did not confirm '+name)
    self.visible_location=name
    if not hasattr(self,'scan_directions'):self.scan_directions={}
    self.scan_directions[name]='down'
    return root
 def show_stations(self):
    self.location()
    self.adb('shell','input','swipe','380','1310','380','640','450')
    self.mode='waiting — station statuses visible'
 def scroll_to_top(self,location,root):
    previous=None
    for _ in range(10):
        header=find(root,'locationName')
        if header is not None and header.get('text')==location:
            try:center(header);break
            except ValueError:pass
        signature=tuple(texts(root))
        if signature==previous:break
        previous=signature
        self.adb('shell','input','swipe','380','620','380','1300','200')
        root=self.screen()
    self.scan_directions[location]='down'
    return root
 def scan(self,target=None,location=PRIMARY_LOCATION):
    if target:
        mapped=self.db.execute('SELECT location FROM station_locations WHERE id=?',(target,)).fetchone()
        if mapped:location=mapped[0]
        # Command verification begins at the top, regardless of the passive scan's position.
        self.visible_location=None
        if not hasattr(self,'scan_directions'):self.scan_directions={}
        self.scan_directions[location]='down'
    self.mode='checking '+location
    root=self.location(location)
    if not hasattr(self,'scan_directions'):self.scan_directions={}
    direction=self.scan_directions.get(location,'down')
    expected=LOCATION_COUNTS[location]
    allrows={};last=None
    tabs=next((s.get('tabs',[]) for s in SITES if s['name']==location),[])
    tab_index=0
    if tabs:self.choose(root,tabs[0]);root=self.screen()
    for _ in range(24):
        rows=station_rows(root,ports=location in SECONDARY_LOCATIONS and location!=SECONDARY_LOCATION)
        changed=False
        for ident,(status,node) in rows.items():
            old=self.db.execute('SELECT status FROM stations WHERE id=?',(ident,)).fetchone()
            if not old or old[0]!=status:
                self.event('station status',{'status':status,'location':location},ident);changed=True
            self.db.execute('INSERT OR REPLACE INTO stations VALUES(?,?,?)',(ident,status,stamp()))
            self.db.execute('INSERT OR REPLACE INTO station_locations VALUES(?,?)',(ident,location))
            allrows[ident]=status
        self.db.commit()
        if changed and hasattr(self,'sync_wakeup'):self.sync_wakeup.set()
        if target in rows:return root,rows[target]
        if not target and len(allrows)>=expected:break
        signature=tuple(texts(root))
        if signature==last:
            if tab_index+1<len(tabs):
                root=self.scroll_to_top(location,root);tab_index+=1
                self.choose(root,tabs[tab_index]);root=self.screen();last=None;direction='down';continue
            break
        last=signature
        start,end=('1300','620') if direction=='down' else ('620','1300')
        self.adb('shell','input','swipe','380',start,'380',end,'400');root=self.screen()
    self.scan_directions[location]='up' if direction=='down' else 'down'
    if target:raise RuntimeError('Requested station not found in pinned location')
    if not allrows:raise RuntimeError('Station list contained no readable station rows')
    charging=[ident for ident,status in allrows.items() if status=='Charging']
    if charging or location==PRIMARY_LOCATION:self.candidate=charging[0] if len(charging)==1 else None
    if self.session and self.session.get('state')=='stopped':
        observed=self.session.get('station') or self.session.get('station_candidate')
        if observed and allrows.get(observed)=='Available':
            self.event('session ended by station availability',{'station':observed},observed)
            self.end_session('Blink station became Available after completion')
    self.event('scan complete',{'location':location,'count':len(allrows),'expected':expected})
    if location==PRIMARY_LOCATION:self.availability_alert(allrows)
    if len(allrows)!=expected:self.error=f'Partial scan at {location}: {len(allrows)}/{expected} stations; unseen rows retain old timestamps'
    self.scroll_to_top(location,root)
    return allrows
 def availability_alert(self,rows):
    armed=self.get('availability_alert')
    if not armed or not armed.get('armed'):return
    available=sorted(ident for ident,status in rows.items() if status=='Available')
    if not available:return
    message='Blink charger available at Gateway Drive. Station '+', '.join(s[-3:] for s in available)+'.'
    try:
        # Use the alarm stream: the user previously silenced Termux notifications.
        self.run('termux-tts-speak','-s','ALARM',message,timeout=30)
        self.save('availability_alert',dict(armed=False,triggered=stamp(),stations=available))
        self.event('availability alert',{'stations':available,'message':message})
        try:self.run('termux-vibrate','-d','1500')
        except Exception:pass
        try:self.run('termux-notification','--id','703','--title','Blink charger available','--content',', '.join(available)+' at 1850 Gateway Drive','--priority','max','--sound')
        except Exception:pass
    except Exception as e:
        self.error='Availability speech failed; alert remains armed: '+str(e)
 def scheduled_scan(self):
    primary_scans=self.get('primary_scans_since_secondary') or 0
    secondary_index=self.get('secondary_index') or 0
    location=SECONDARY_LOCATIONS[secondary_index%len(SECONDARY_LOCATIONS)] if primary_scans>=4 else PRIMARY_LOCATION
    secondary=location!=PRIMARY_LOCATION
    try:self.scan(location=location)
    except Exception:
        # A failed remote site must not trap the observer away from Gateway.
        if secondary:
            self.save('secondary_index',(secondary_index+1)%len(SECONDARY_LOCATIONS))
            self.save('primary_scans_since_secondary',0)
            self.next_scan=0
        raise
    if secondary:self.save('secondary_index',(secondary_index+1)%len(SECONDARY_LOCATIONS))
    self.save('primary_scans_since_secondary',0 if secondary else primary_scans+1)
    delay=0 if secondary else (30 if getattr(self,'active',False) or getattr(self,'session',None) else 5)
    self.next_scan=stamp()+delay
    return location
 def completion_alert(self):
    if not self.session or self.session.get('state')!='stopped':return
    if stamp()-self.alarm<300 or (ROOT/'acknowledged').exists():return
    # Rate-limit attempts too, so a failed notification cannot cause speech spam.
    self.alarm=stamp()
    errors=[]
    try:self.run('termux-tts-speak','-s','ALARM','Blink charging is complete. Please unplug your car.',timeout=30)
    except Exception as e:errors.append('Speech: '+str(e))
    try:notify('CHARGING STOPPED — unplug your car','Blink reports completion. Reminders every 5 minutes.',True)
    except Exception as e:errors.append('Notification: '+str(e))
    if errors:self.error='; '.join(errors)
 def open_active(self):
    self.mode='checking active session';root=self.tab('Search')
    for _ in range(4):
        if find(root,'Active session') is not None:break
        if 'Station Port' not in texts(root) and find(root,'Google Map') is not None:break
        root=self.back()
    active=find(root,'Active session')
    if active is None:return None
    sheet=find(root,'Bottom Sheet')
    if sheet is not None:
        bounds=list(map(int,re.findall(r'\d+',sheet.get('bounds',''))))
        if len(bounds)==4 and bounds[1]<250:
            self.adb('shell','input','swipe','360',str(bounds[1]+15),'360','1080','450')
            root=self.screen();active=find(root,'Active session')
            if active is None:return None
    self.tap(active);root=self.screen()
    if 'Station Port' not in texts(root):raise RuntimeError('Active session did not open expected screen')
    return root
 def update_session(self,root):
    r=reading(root);labels=texts(root)
    if self.session and 'Start Charge' in labels:r['state']='ended'
    if not self.session:
        if 'Stop Charge' not in labels and r['state'] not in ('charging','stopped'):return
        self.session={'id':str(uuid.uuid4()),'started':stamp(),'station':None,'source':'live UI','start_is_observation':True}
        self.alarm=0
        self.event('session observed',r)
        (ROOT/'acknowledged').unlink(missing_ok=True)
    if self.candidate:self.session['station_candidate']=self.candidate
    if r['kwh'] is not None:self.session['kwh']=max(self.session.get('kwh') or 0,r['kwh'])
    self.session.update({k:v for k,v in r.items() if k!='kwh'},updated=stamp())
    self.db.execute('INSERT OR REPLACE INTO sessions VALUES(?,?)',(self.session['id'],json.dumps(self.session)));self.save('session',self.session)
    if stamp()-self.last_sample>=30 or r['state'] in ('stopped','ended'):
        self.event('session reading',r,self.session.get('station'));self.last_sample=stamp()
    if r['kwh']!=self.last_energy:self.changed=stamp();self.last_energy=r['kwh']
    self.completion_alert()
    if r['state']=='ended':self.end_session('Blink reports session ended');return
    eta=max(0,(5.65-(r['kwh'] or 0))/(r['kw'] or 1)*3600-(stamp()-self.changed)) if r['state']=='charging' else 0
    command=['am','start-foreground-service','-n','com.timkay.blinkoverlay/.OverlayService','--es','state',r['state'],
        '--es','reading',f"{r['kw'] or 0:.2f} kW | {r['kwh'] or 0:.2f} kWh",'--el','changed',str(self.changed*1000),'--el','finish',str(int((stamp()+eta)*1000) if eta else 0)]
    self.adb('shell',shlex.join(command))
 def end_session(self,reason):
    if self.session:
        self.session.update(state='ended',updated=stamp(),end_reason=reason)
        self.db.execute('INSERT OR REPLACE INTO sessions VALUES(?,?)',(self.session['id'],json.dumps(self.session)))
        self.event('session ended',self.session,self.session.get('station'))
    self.session=None;self.save('session',None);self.next_history=0
    self.adb('shell','am','stopservice','-n','com.timkay.blinkoverlay/.OverlayService')
    for ident in ('701','702'):
        try:self.run('termux-notification-remove',ident)
        except Exception:pass
    (ROOT/'acknowledged').unlink(missing_ok=True)
 def history(self):
    self.mode='reading your recent sessions';root=self.tab('Account')
    for _ in range(4):
        if find(root,'History') is not None:break
        root=self.back()
    self.choose(root,'History');root=self.screen();self.choose(root,'Blink Pro');root=self.screen()
    month=next((t for t in texts(root) if re.fullmatch(r'[A-Z][a-z]+ 20\d\d',t)),None)
    if not month:return
    self.choose(root,month);root=self.screen()
    day=next((t for t in texts(root) if re.fullmatch(r'[A-Z][a-z]+ \d{1,2}, 20\d\d',t)),None)
    if not day:return
    self.choose(root,day);root=self.screen()
    values=texts(root); chunks=[]
    for t in values:
        if t=='Date':chunks.append([])
        if chunks:chunks[-1].append(t)
    for chunk in chunks:
        def field(label):
            try:return chunk[chunk.index(label)+1]
            except (ValueError,IndexError):return ''
        serial=field('Serial Number')
        if not SERIAL.fullmatch(serial):continue
        try:
            date=dt.datetime.strptime(field('Date')+' '+field('Start Time'),'%B %d, %Y %I:%M %p').astimezone()
            kwh=float(field('Energy').split()[0])
        except ValueError:continue
        ident='history-'+hashlib.sha256((serial+date.isoformat()).encode()).hexdigest()[:24]
        entry=dict(id=ident,station=serial,started=int(date.timestamp()),updated=stamp(),state='ended',kwh=kwh,elapsed=field('Charging Time'),end_time=field('End Time'),source='Blink charge history')
        old=self.db.execute('SELECT data FROM sessions WHERE id=?',(ident,)).fetchone()
        if not old:self.event('confirmed session history',entry,serial)
        # Replace a matching live observation rather than double-counting it.
        duration=re.search(r'(\d+) min',entry['elapsed']); seconds=int(duration[1])*60+120 if duration else 86400
        for liveid,payload in self.db.execute('SELECT id,data FROM sessions').fetchall():
            live=json.loads(payload)
            if live.get('source')=='live UI' and entry['started']-60<=live['started']<=entry['started']+seconds:
                entry['id']=liveid;ident=liveid
                if self.session and self.session['id']==liveid:self.end_session('Confirmed in Blink charge history')
                break
        self.db.execute('INSERT OR REPLACE INTO sessions VALUES(?,?)',(ident,json.dumps(entry)))
    self.db.commit()
 def execute(self,cmd):
    # Claimed commands are persisted BEFORE any UI action and never replayed.
    self.mode='verifying start request';pressed=False
    try:
        if stamp()>cmd['expires']:raise RuntimeError('Request expired')
        if self.active or self.session:raise RuntimeError('A session is already active')
        root,(status,node)=self.scan(cmd['station'])
        if status!='Connected':raise RuntimeError('Exact station is no longer Connected: '+status)
        if find(root,'Start charge') is not None or find(root,'Start Charge') is not None:
            raise RuntimeError('A prior selection is still open; refusing ambiguous start')
        self.tap(find(node,cmd['station']));root=self.screen()
        # Blink exposes selection controls over the list, not a separate detail page.
        # Require a fresh selection and re-read the exact row before starting.
        if cmd['station'] not in texts(root):raise RuntimeError('Station detail does not expose exact serial; refusing to guess')
        selected=station_rows(root).get(cmd['station'])
        if selected is None or selected[0]!='Connected':raise RuntimeError('Selected station row does not confirm Connected')
        start=find(root,'Start charge')
        if start is None:start=find(root,'Start Charge')
        if start is None:raise RuntimeError('Start Charge is not visible')
        if stamp()>cmd['expires']:raise RuntimeError('Request expired during verification')
        self.event('start button about to be pressed',{'command':cmd['id']},cmd['station'])
        self.tap(start);pressed=True
        result='Start pressed once; awaiting confirmation. Never automatically retry.';state='uncertain'
        for _ in range(3):
            root=self.screen();labels=texts(root)
            if 'Charge session started' in labels or 'Stop Charge' in labels:
                state='confirmed';result='Blink confirmed the session started';
                self.session=dict(id=str(uuid.uuid4()),station=cmd['station'],started=stamp(),source='live UI',start_is_observation=True)
                self.save('session',self.session);self.active=True;break
        self.db.execute('UPDATE commands SET state=?,result=? WHERE id=?',(state,result,cmd['id']))
    except Exception as e:
        self.db.execute('UPDATE commands SET state=?,result=? WHERE id=?',('uncertain' if pressed else 'rejected',str(e),cmd['id']))
    self.db.commit();self.next_scan=0
 def network(self):
    db=sqlite3.connect(self.dbpath,timeout=20)
    def request(path,body):
        config='\n'.join(['url = '+json.dumps(self.cfg['url']+'/api/'+path),
            'header = '+json.dumps('Authorization: Bearer '+self.cfg['device_token']),
            'header = "Content-Type: application/json"','data = '+json.dumps(json.dumps(body))])
        r=sp.run(['curl','--fail-with-body','--silent','--show-error','--max-time','15','--config','-'],input=config,text=True,capture_output=True,check=True)
        return json.loads(r.stdout)
    while not self.stop.is_set():
        try:
            ev=db.execute('SELECT id,station,time,kind,data FROM events WHERE synced=0 ORDER BY time LIMIT 100').fetchall()
            stations=[dict(id=i,status=s,checked=t,location=loc or PRIMARY_LOCATION) for i,s,t,loc in db.execute('SELECT s.id,s.status,s.checked,l.location FROM stations s LEFT JOIN station_locations l ON l.id=s.id')]
            sessions=[json.loads(r[0]) for r in db.execute('SELECT data FROM sessions ORDER BY rowid DESC LIMIT 100')]
            request('ingest',dict(stations=stations,events=[dict(id=i,station=s,time=t,kind=k,data=json.loads(d)) for i,s,t,k,d in ev],sessions=sessions,device={'mode':self.mode,'error':self.error,'observer_checked':self.get_observer_time(db)}))
            db.executemany('UPDATE events SET synced=1 WHERE id=?',[(e[0],) for e in ev]);db.commit()
            for ident,state,result in db.execute("SELECT id,state,result FROM commands WHERE state IN ('confirmed','rejected','uncertain')").fetchall():
                request('result',dict(id=ident,state=state,result=result));db.execute("UPDATE commands SET state='reported' WHERE id=?",(ident,));db.commit()
            cmd=request('claim',{}).get('command')
            if cmd:db.execute("INSERT OR IGNORE INTO commands VALUES(?,?,'ready',NULL)",(cmd['id'],json.dumps(cmd)));db.commit()
        except Exception as e:
            print('sync:',type(e).__name__,str(e),flush=True)
        self.sync_wakeup.wait(10);self.sync_wakeup.clear()
 def get_observer_time(self,db):
    row=db.execute("SELECT value FROM state WHERE key='observer_checked'").fetchone();return json.loads(row[0]) if row else 0
 def loop(self):
    self.run('termux-wake-lock');self.run('adb','connect',self.device)
    self.adb('shell','settings','put','global','stay_on_while_plugged_in','7')
    self.adb('shell','am','start','-n','com.blinknetwork.mobile2/com.blinkmobile.MainActivity')
    # Never replay an action interrupted by a process crash.
    self.db.execute("UPDATE commands SET state='uncertain',result='Controller restarted during execution; inspect phone before retrying' WHERE state='executing'");self.db.commit()
    threading.Thread(target=self.network,daemon=True).start()
    while True:
        try:
            self.error=None
            scans_paused=bool(self.get('normal_scans_paused'))
            if self.get('history_backfill_disabled'):
                self.next_history=stamp()+86400
            if not scans_paused:self.completion_alert()
            backfill=self.get('history_backfill')
            if backfill and not backfill.get('complete') and not self.get('history_backfill_disabled') and stamp()>=getattr(self,'next_backfill',0):
                from history_backfill import step
                try:step(self)
                finally:
                    self.next_backfill=stamp()+20
                    if not scans_paused:
                        root=self.open_active();self.active=root is not None
                        if root is not None:self.update_session(root)
                        else:self.show_stations()
            if scans_paused:
                self.mode='normal monitoring paused — history backfill only'
                time.sleep(2)
                continue
            cmd=self.db.execute("SELECT id,data FROM commands WHERE state='ready' LIMIT 1").fetchone()
            if cmd:
                self.db.execute("UPDATE commands SET state='executing' WHERE id=?",(cmd[0],));self.db.commit();self.execute(json.loads(cmd[1]))
            if stamp()>=self.next_scan:
                self.scheduled_scan()
                if self.initial_session_check or self.active or self.session or self.candidate:
                    root=self.open_active();self.active=root is not None;self.initial_session_check=False
                    if root is None and self.session:
                        if self.session.get('state')!='stopped':self.session['state']='unconfirmed'
                        self.save('session',self.session)
                        self.error='Active-session indicator missing; retaining session until history confirms end'
                else:root=None
                if root is None:self.mode='watching station list — fast checks'
            elif self.active:root=self.screen()
            else:root=None
            if root is not None:
                if 'Station Port' not in texts(root):raise RuntimeError('Active charging screen was displaced')
                self.mode='monitoring charge';self.update_session(root)
                if not self.session:self.active=False
            elif stamp()<self.next_scan and stamp()>=self.next_history and not (self.get('availability_alert') or {}).get('armed'):
                self.history();self.next_history=stamp()+600;self.show_stations()
            self.save('observer_checked',stamp())
            self.ui_failures=0;self.recovery_level=0
        except Exception as e:
            self.error=str(e);self.mode='waiting for readable phone';print('UI:',str(e),flush=True)
            try:self.recover_ui(e)
            except Exception as recovery_error:
                self.error=str(recovery_error)
                print(dt.datetime.now().isoformat(),'Recovery:',str(recovery_error),flush=True)
        time.sleep(2)

if __name__=='__main__':
    lock=open(ROOT/'monitor.lock','w')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('Another monitor owns phone navigation')
    Controller().loop()
