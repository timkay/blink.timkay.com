#!/usr/bin/env python3
"""Phone-local Blink screen monitor. Never presses Stop Charge."""
import argparse
import csv
import datetime as dt
import fcntl
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess as sp
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
DATA.mkdir(exist_ok=True)
ACK = ROOT / 'acknowledged'

def run(*args, timeout=15):
    return sp.run(args, capture_output=True, text=True, timeout=timeout, check=True).stdout

def notify(title, body, alarm=False):
    cmd = ['termux-notification', '--id', '702' if alarm else '701',
           '--title', title, '--content', body, '--ongoing',
           '--priority', 'max' if alarm else 'low',
           '--button1', 'I unplugged', '--button1-action',
           shlex.quote(shutil.which('touch') or 'touch') + ' ' + shlex.quote(str(ACK))]
    cmd += ['--sound', '--vibrate', '500,300,500'] if alarm else ['--alert-once']
    run(*cmd)

def parse(xml):
    root = ET.fromstring(xml)
    values = {n.get('content-desc'): n.get('text') for n in root.iter('node') if n.get('text')}
    def number(key):
        match = re.search(r'\d+(?:[.,]\d+)?', values.get(key, ''))
        return float(match[0].replace(',', '.')) if match else None
    return number('currentSpeedValue'), number('energyDeliveredVal'), values.get('chargeTimeVal', '')

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--device', default='127.0.0.1:36007')
    p.add_argument('--target-kwh', type=float, default=5.65)
    p.add_argument('--interval', type=int, default=5)
    a = p.parse_args()
    lock = open(ROOT / 'monitor.lock', 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('Monitor already running')
    ACK.unlink(missing_ok=True)
    run('termux-wake-lock')
    adb = ['adb', '-s', a.device]
    run('adb', 'connect', a.device)
    # Stay awake while USB-powered; restore the previous setting on clean exit.
    old_awake = run(*adb, 'shell', 'settings', 'get', 'global', 'stay_on_while_plugged_in').strip()
    run(*adb, 'shell', 'settings', 'put', 'global', 'stay_on_while_plugged_in', '7')
    logfile = DATA / (dt.datetime.now().strftime('%Y%m%d-%H%M%S') + '.csv')
    zero = 0
    seen_charging = False
    stopped = False
    last_alarm = 0
    last_good = time.time()
    last_change = time.time()
    last_energy = None
    status = {}
    try:
        with logfile.open('w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['timestamp', 'kw', 'kwh', 'charge_time', 'eta_minutes', 'state', 'error'])
            while not ACK.exists():
                now = time.time()
                stamp = dt.datetime.now().astimezone().isoformat()
                if stopped and now - last_alarm >= 300:
                    try:
                        notify('CHARGING STOPPED — unplug your car',
                               'Previously confirmed by Blink. Tap I unplugged to end reminders.', True)
                        last_alarm = now
                    except Exception:
                        pass
                try:
                    run(*adb, 'shell', 'uiautomator', 'dump', '/sdcard/blink-monitor.xml')
                    xml = run(*adb, 'exec-out', 'cat', '/sdcard/blink-monitor.xml')
                    labels = {n.get('text', '').strip().casefold() for n in ET.fromstring(xml).iter('node')}
                    if 'start charge' in labels and ('thank you for charging!' in labels or stopped):
                        status = dict(timestamp=stamp, state='session ended', reading='Session ended — reminders off',
                                      finish=0, changed=now)
                        writer.writerow([stamp, '', '', '', '', 'session ended', 'Start Charge shown after completion'])
                        f.flush()
                        (ROOT / 'status.json').write_text(json.dumps(status, indent=2))
                        print(json.dumps(status), flush=True)
                        break
                    complete = any(n.get('text', '').strip().casefold() == 'charge complete'
                                   for n in ET.fromstring(xml).iter('node'))
                    kw, kwh, elapsed = parse(xml)
                    if kw is None or kwh is None:
                        raise ValueError('Blink status is not visible; open its round charging-status button')
                    last_good = now
                    if kwh != last_energy:
                        last_change, last_energy = now, kwh
                    stale = now - last_change > 300 and kw > 0.1
                    seen_charging |= kw > 0.1
                    zero = zero + 1 if kw <= 0.1 else 0
                    if kw > 0.1 and not complete:
                        stopped = False
                    if complete or (seen_charging and zero >= 2):
                        stopped = True
                    eta = max(0, (a.target_kwh - kwh) / kw * 60 - (now-last_change)/60) if kw > 0.1 and not stopped else None
                    minutes = math.ceil(eta) if eta is not None else None
                    countdown = f'{minutes // 60}:{minutes % 60:02d}' if minutes is not None else 'unknown'
                    state = 'stopped' if stopped else 'charging' if kw > 0.1 else 'confirming stop'
                    body = f'{kw:.2f} kW | {kwh:.2f} kWh | elapsed {elapsed}. Started empty; target {a.target_kwh:.2f} kWh.'
                    if stopped and now - last_alarm >= 300:
                        notify('CHARGING STOPPED — unplug your car', body + ' Repeats every 5 minutes until acknowledged.', True)
                        last_alarm = now
                    writer.writerow([stamp, kw, kwh, elapsed, round(eta, 2) if eta is not None else '', state, ''])
                    status = dict(timestamp=stamp, kw=kw, kwh=kwh, countdown=countdown, state=state,
                                  changed=last_change, finish=now+eta*60 if eta is not None else 0,
                                  reading=f'{kw:.2f} kW | {kwh:.2f} kWh', stale=stale)
                except Exception as e:
                    writer.writerow([stamp, '', '', '', '', 'unavailable', str(e)])
                    status.update(timestamp=stamp, state='stopped' if stopped else 'unavailable', error=str(e))
                    try:
                        run('adb', 'connect', a.device)
                    except Exception:
                        pass
                f.flush()
                try:
                    command = ['am','start-foreground-service','-n',
                        'com.timkay.blinkoverlay/.OverlayService', '--es','state',status['state'],
                        '--es','reading',status.get('reading','Waiting for Blink'),
                        '--el','changed',str(int(status.get('changed',0)*1000)),
                        '--el','finish',str(int(status.get('finish',0)*1000))]
                    run(*adb, 'shell', shlex.join(command))
                except Exception as e:
                    print('overlay: '+str(e), flush=True)
                (ROOT / 'status.json').write_text(json.dumps(status, indent=2))
                print(json.dumps(status), flush=True)
                for _ in range(max(0, math.ceil(a.interval-(time.time()-now)))):
                    if ACK.exists():
                        break
                    time.sleep(1)
    finally:
        try:
            run(*adb, 'shell', 'am', 'stopservice', '-n', 'com.timkay.blinkoverlay/.OverlayService')
        except Exception:
            pass
        for ident in ('701', '702'):
            try:
                run('termux-notification-remove', ident)
            except Exception:
                pass
        try:
            run(*adb, 'shell', 'settings', 'put', 'global', 'stay_on_while_plugged_in', old_awake)
        except Exception:
            pass

if __name__ == '__main__':
    main()
