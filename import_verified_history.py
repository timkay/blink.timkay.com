#!/usr/bin/env python3
"""Import only manually verified UI evidence; does not navigate or control phone."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
root=Path(__file__).resolve().parent
db=sqlite3.connect(root/'data/watch.sqlite3',timeout=20)
for row in json.loads(Path(sys.argv[1]).read_text()):
    start=dt.datetime.fromisoformat(row['date']+'T'+row['start']).astimezone()
    ident='history-'+hashlib.sha256((row['station']+start.isoformat()).encode()).hexdigest()[:24]
    entry=dict(id=ident,station=row['station'],started=int(start.timestamp()),updated=int(time.time()),state='ended',kwh=row['kwh'],elapsed=row['elapsed'],end_time=row['end'],source='Blink charge history')
    db.execute('INSERT OR IGNORE INTO sessions VALUES(?,?)',(ident,json.dumps(entry)))
    db.execute('INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,0)',(ident,row['station'],int(time.time()),'confirmed session history',json.dumps(entry)))
db.commit()
print('Verified history imported')
