#!/usr/bin/env python3
"""Update the controller's phone-local ADB listener without exposing credentials."""
import json
import os
from pathlib import Path
import sys
port = int(sys.argv[1])
if not 1 <= port <= 65535:
    raise SystemExit('Invalid port')
path = Path.home() / '.config/blink-monitor/controller.json'
config = json.loads(path.read_text())
config['device'] = f'127.0.0.1:{port}'
temporary = path.with_suffix('.tmp')
fd = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
with os.fdopen(fd, 'w') as output:
    json.dump(config, output)
os.replace(temporary, path)
print('Local ADB device:', config['device'])
