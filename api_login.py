#!/usr/bin/env python3
"""Interactive Blink API login. Password stays in memory; tokens stored mode 600."""
import getpass
import json
import os
from pathlib import Path
import urllib.request
import urllib.parse
import urllib.error

TOKEN_URL = 'https://account.blinknetwork.com/auth/realms/blinkcharging/protocol/openid-connect/token'
def main():
    email = input('Blink email: ')
    password = getpass.getpass('Blink password: ')
    payload = urllib.parse.urlencode(dict(client_id='mobile-app', grant_type='password',
        username=email, password=password, scope='openid email profile offline_access')).encode()
    req = urllib.request.Request(TOKEN_URL, data=payload,
        headers={'Content-Type': 'application/x-www-form-urlencoded'})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            tokens = json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            d = json.loads(body)
            print('Login rejected:', e.code, d.get('error'), d.get('error_description'))
        except ValueError:
            print('Login rejected: HTTP', e.code)
        return
    del password, payload, req
    folder = Path.home() / '.config' / 'blink-monitor'
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = folder / 'tokens.json'
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(tokens, f)
    print('Login successful; tokens saved privately. Access-token lifetime:', tokens.get('expires_in'))
    for path in ['mobile/v1/active-sessions?isHome=false', 'mobile/v2/users/active-sessions']:
        req = urllib.request.Request('https://apigw.blinknetwork.com/' + path,
            headers={'Authorization': 'Bearer ' + tokens['access_token'], 'Accept': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.load(r)
                print(path, 'HTTP', r.status, json.dumps(data)[:5000])
        except urllib.error.HTTPError as e:
            print(path, 'HTTP', e.code, e.read().decode()[:400])

if __name__ == '__main__':
    main()
