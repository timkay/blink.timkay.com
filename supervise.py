#!/usr/bin/env python3
"""Restart controller after an unexpected exit; never replay claimed commands."""
import fcntl
from pathlib import Path
import subprocess
import sys
import time
root=Path(__file__).resolve().parent
lock=open(root/'supervisor.lock','w')
fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
while True:
    code=subprocess.call([sys.executable,str(root/'controller.py')],cwd=root)
    print('Controller exited',code,'— restarting in 10 seconds',flush=True)
    time.sleep(10)
