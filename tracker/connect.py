"""Run locally: python -m tracker.connect. Never copy Codex's private auth store."""
import argparse
import asyncio
import json
import os
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs,urlsplit

import httpx

from .plus import authorization,exchange


def main():
    parser=argparse.ArgumentParser(description='Connect your ChatGPT plan using the documented open-source sign-in flow')
    parser.add_argument('--host-id',required=True,help='Host ID shown in tracker settings; use the Railway host ID for a Railway deployment')
    parser.add_argument('--output',default='data/chatgpt.credentials.json')
    args=parser.parse_args()
    callback={}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass  # OAuth codes must never appear in request logs.
        def do_GET(self):
            p=urlsplit(self.path)
            if p.path!='/auth/callback':
                self.send_error(404); return
            values={k:v[0] for k,v in parse_qs(p.query).items()}
            if not secrets.compare_digest(values.get('state',''),pending['state']):
                self.send_error(400,'State mismatch'); return
            callback.update(values)
            self.send_response(200)
            self.send_header('Content-Type','text/plain; charset=utf-8')
            self.send_header('Cache-Control','no-store')
            self.end_headers()
            self.wfile.write(b'Sign-in received. Return to your terminal for the connection result. You may close this tab.')

    with HTTPServer(('127.0.0.1',0),Handler) as server:
        redirect=f'http://127.0.0.1:{server.server_port}/auth/callback'
        url,pending=authorization(args.host_id,redirect)
        print('Opening OpenAI sign-in. This uses your ChatGPT plan, not an API key.')
        webbrowser.open(url)
        print('If the browser did not open, visit this authorization URL:\n'+url)
        server.timeout=1
        deadline=time.monotonic()+600
        while not callback and time.monotonic()<deadline:
            server.handle_request()
    if not callback:
        raise SystemExit('Sign-in timed out; no credentials saved.')

    async def finish():
        async with httpx.AsyncClient(timeout=30) as client:
            return await exchange(client,pending,callback,args.host_id)
    try:
        record=asyncio.run(finish())
    except Exception:
        raise SystemExit('OpenAI could not complete plan authorization. Check account eligibility and try again. No credentials saved.') from None
    path=Path(args.output)
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temp=path.with_suffix('.tmp')
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as f:
        json.dump(record,f)
    os.replace(temp,path)
    os.chmod(path,0o600)
    print(f'Connection saved to {path}. Import this file in tracker settings over HTTPS, then delete the local transfer file. The tracker owns token renewal after import.')


if __name__=='__main__':
    main()
