#!/usr/bin/env python3
"""Read-only auth diagnostics; never print tokens or account response values."""
import base64
import concurrent.futures
import json
from pathlib import Path
import urllib.request
import urllib.error

tokens = json.loads((Path.home() / '.config/blink-monitor/tokens.json').read_text())
claims = json.loads(base64.urlsafe_b64decode(tokens['access_token'].split('.')[1] + '==='))
print('Token metadata:', {k: claims.get(k) for k in ('iss', 'aud', 'azp', 'scope', 'exp')})
base = 'https://apigw.blinknetwork.com/'
headers = {'Authorization': 'Bearer ' + tokens['access_token'], 'Accept': 'application/json'}
common = {'x-app-version': '3.1.39', 'device-os-version': '15', 'os-type': 'Android',
          'device-locale': 'en-US', 'X-Android-Package': 'com.blinknetwork.mobile2',
          'X-Android-Cert': '5495BDC0B6E16C2DC1F97E51A01665A9BBAC6463'}
jobs = [('oidc userinfo', 'https://account.blinknetwork.com/auth/realms/blinkcharging/protocol/openid-connect/userinfo', headers)]
for path in ('mobile/v1/users', 'mobile/v1/active-sessions?isHome=false', 'mobile/v2/users/active-sessions'):
    jobs.append((path + ' bearer', base + path, headers))
    jobs.append((path + ' common', base + path, dict(headers, **common)))

def probe(job):
    label, url, h = job
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=15) as response:
            data = json.load(response)
            shape = list(data) if isinstance(data, dict) else {'type': type(data).__name__, 'length': len(data) if isinstance(data, list) else None}
            return label, response.status, shape
    except urllib.error.HTTPError as error:
        return label, error.code, {'www-authenticate': error.headers.get('WWW-Authenticate')}
    except Exception as error:
        return label, type(error).__name__

with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    for result in pool.map(probe, jobs):
        print(result, flush=True)
