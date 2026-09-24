#!/usr/bin/env python3
"""Record the phone monitor's UI snapshots without competing UI dumps."""
import datetime as dt
import json
from pathlib import Path
import subprocess
import time
import xml.etree.ElementTree as ET

folder = Path('data') / ('handle-test-' + dt.datetime.now().strftime('%Y%m%d-%H%M%S'))
folder.mkdir(parents=True)
last = None
end_seen = None
deadline = time.monotonic() + 1200
with (folder / 'events.jsonl').open('a') as log:
    while time.monotonic() < deadline:
        stamp = dt.datetime.now().astimezone().isoformat()
        try:
            xml = subprocess.run(['adb', '-s', '100.85.197.127:36007', 'exec-out',
                'cat', '/sdcard/blink-monitor.xml'], capture_output=True, text=True,
                check=True, timeout=10).stdout
            root = ET.fromstring(xml)
            texts = [n.get('text') for n in root.iter('node') if n.get('text')]
            fields = {n.get('content-desc'): n.get('text') for n in root.iter('node')
                      if n.get('content-desc') in ('currentSpeedValue', 'energyDeliveredVal', 'chargeTimeVal', 'parkingFee')}
            event = dict(timestamp=stamp, fields=fields, texts=texts)
            log.write(json.dumps(event) + '\n')
            log.flush()
            signature = json.dumps([fields, texts])
            if signature != last:
                (folder / (str(time.time_ns()) + '.xml')).write_text(xml)
                print(json.dumps(event), flush=True)
                last = signature
            if 'Thank you for charging!' in texts and 'Start Charge' in texts:
                end_seen = end_seen or time.monotonic()
                if time.monotonic() - end_seen >= 30:
                    print('Session-ended screen observed for 30 seconds; observation finished.', flush=True)
                    break
        except Exception as error:
            print(stamp, type(error).__name__, str(error), flush=True)
        time.sleep(3)
print('Evidence saved to', folder, flush=True)
