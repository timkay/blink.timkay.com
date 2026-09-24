#!/usr/bin/env python3
"""Provision only this dashboard's secrets/schema; never print secret values."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import tomllib
import urllib.request

root=Path(__file__).resolve().parent
folder=root/'.secrets';folder.mkdir(mode=0o700,exist_ok=True)
def private(name,data):
    path=folder/name
    if not path.exists():
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'w') as f:f.write(data)
    return path.read_text().strip()
admin=private('admin-key.txt',secrets.token_urlsafe(32))
device=private('device-key.txt',secrets.token_urlsafe(32))
private('controller.json',json.dumps({'url':'https://blink.timkay.com','device_token':device,'device':'127.0.0.1:36007'}))
config=tomllib.loads((Path.home()/'.config/.wrangler/config/default.toml').read_text())
token=config['oauth_token']
account='20dc0a4b86f9149d47ed8bcbbb2462e5'
def api(path,data,method='POST'):
    config='\n'.join(['url = '+json.dumps('https://api.cloudflare.com/client/v4/accounts/'+account+path),
        'request = '+json.dumps(method),'header = '+json.dumps('Authorization: Bearer '+token),
        'header = "Content-Type: application/json"','data = '+json.dumps(json.dumps(data))])
    r=subprocess.run(['curl','-4','--silent','--show-error','--max-time','25','--config','-'],input=config,text=True,capture_output=True,check=True)
    response=json.loads(r.stdout)
    if not response.get('success'):raise RuntimeError(response.get('errors'))
    return response
for statement in (root/'dashboard/schema.sql').read_text().split(';'):
    if statement.strip():api('/d1/database/1dd4d4c4-ef6c-4ee6-9178-96d94233e136/query',{'sql':statement})
print('Database schema ready',flush=True)
for name,value in [('ADMIN_TOKEN',admin),('DEVICE_TOKEN',device)]:
    api('/workers/scripts/blink-timkay/secrets',{'name':name,'text':value,'type':'secret_text'},'PUT')
    print(name,'configured',flush=True)
