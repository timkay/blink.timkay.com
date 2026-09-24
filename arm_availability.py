#!/usr/bin/env python3
"""Arm a durable one-shot alert without changing charging state."""
import json
from pathlib import Path
import sqlite3
import time
db=sqlite3.connect(Path(__file__).resolve().parent/'data/watch.sqlite3',timeout=20)
db.execute('INSERT OR REPLACE INTO state VALUES(?,?)',('availability_alert',json.dumps({'armed':True,'requested':int(time.time())})))
db.commit()
print('Availability alert armed; only fresh Available readings trigger speech.')
