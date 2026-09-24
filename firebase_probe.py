#!/usr/bin/env python3
"""Test normal Firebase anonymous auth, then read only our Blink account API.

The Firebase API key below is public client configuration from the installed APK.
It is not an account credential. User tokens stay in private phone storage.
"""
import json
import os
from pathlib import Path
import urllib.request
import urllib.error

folder = Path.home() / '.config/blink-monitor'
target = folder / 'firebase.json'
api_key = os.environ.get('BLINK_FIREBASE_API_KEY')
if not api_key:
    raise SystemExit('Set BLINK_FIREBASE_API_KEY to the public Firebase client key from the installed app')
if target.exists():
    firebase = json.loads(target.read_text())
else:
    req = urllib.request.Request(
        'https://identitytoolkit.googleapis.com/v1/accounts:signUp?key=' + api_key,
        data=json.dumps({'returnSecureToken': True}).encode(),
        headers={'Content-Type': 'application/json',
                 'X-Android-Package': 'com.blinknetwork.mobile2',
                 'X-Android-Cert': '5495BDC0B6E16C2DC1F97E51A01665A9BBAC6463'})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            firebase = json.load(r)
    except urllib.error.HTTPError as e:
        data = json.load(e)
        print('Firebase sign-in HTTP', e.code, data.get('error', {}).get('message'))
        raise SystemExit(1)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(firebase, f)
print('Firebase ID token obtained; expires in', firebase.get('expiresIn'), 'seconds')
tokens = json.loads((folder / 'tokens.json').read_text())
headers = {'Authorization': 'Bearer ' + tokens['access_token'],
           'X-Firebase-IdToken': firebase['idToken'],
           'Accept': 'application/json', 'x-app-version': '3.1.39',
           'device-os-version': '15', 'os-type': 'Android', 'device-locale': 'en-US',
           'X-Android-Package': 'com.blinknetwork.mobile2',
           'X-Android-Cert': '5495BDC0B6E16C2DC1F97E51A01665A9BBAC6463'}
for path in ('mobile/v1/users', 'mobile/v2/users/active-sessions'):
    try:
        with urllib.request.urlopen(urllib.request.Request('https://apigw.blinknetwork.com/' + path,
                headers=headers), timeout=20) as r:
            data = json.load(r)
            print(path, r.status, 'keys:', list(data) if isinstance(data, dict) else type(data).__name__)
    except urllib.error.HTTPError as e:
        print(path, 'HTTP', e.code)
