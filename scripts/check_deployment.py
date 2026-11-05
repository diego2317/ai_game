#!/usr/bin/env python3
"""Verify one deployed origin. --exercise-demo creates an isolated demo room.

Usage: python3 scripts/check_deployment.py https://YOUR-DOMAIN
       INSTRUCTOR_SECRET=... python3 scripts/check_deployment.py URL --exercise-demo
Only Python's standard library is required. Credentials are never printed.
"""
import argparse
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import re
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url')
    parser.add_argument('--exercise-demo', action='store_true')
    args = parser.parse_args()
    parsed = urlparse(args.url)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password:
        parser.error('Use a full http(s) application URL without credentials.')
    base = f'{parsed.scheme}://{parsed.netloc}'

    def call(path, body=None, token=None, json_response=True):
        headers = {'Content-Type':'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        request = Request(base+path, data=None if body is None else json.dumps(body).encode(), headers=headers)
        with urlopen(request, timeout=30) as response:
            data = response.read()
            return json.loads(data) if json_response else data.decode()

    try:
        health = call('/api/health')
        if health.get('status') != 'ok' or health.get('milestone') != 5:
            raise RuntimeError('The health check did not report the current application version.')
        page = call('/instructor', json_response=False)
        assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', page)
        if not assets:
            raise RuntimeError('The production frontend assets were not found.')
        for asset in assets:
            with urlopen(base+asset, timeout=30) as response:
                if response.status != 200 or not response.read(1):
                    raise RuntimeError('A frontend asset was unavailable.')
        print('PASS: database health, instructor page, and frontend assets on one origin.')
        if args.exercise_demo:
            secret = os.environ.get('INSTRUCTOR_SECRET', '')
            if not secret:
                raise RuntimeError('Set INSTRUCTOR_SECRET to exercise a new demonstration room.')
            created = call('/api/rooms', {'secret':secret, 'demo':True})
            prefix = f'/api/rooms/{created["code"]}'
            token = created['token']
            for phase in ('annotation', 'training'):
                call(prefix+'/phase', {'phase':phase}, token)
            for team in range(3):
                call(prefix+f'/teams/{team}/train', {'request_id':uuid.uuid4().hex}, token)
            call(prefix+'/phase', {'phase':'testing'}, token)
            call(prefix+'/phase', {'phase':'reveal'}, token)
            result = call(prefix+'/instructor', token=token)
            if not result['reveal']['demo'] or sum(t['economy']['runs_used'] for t in result['teams']) != 3:
                raise RuntimeError('The demonstration did not produce three trained models and a reveal.')
            call(prefix+'/reset', {'confirmation':created['code'], 'generation':0, 'request_id':uuid.uuid4().hex}, token)
            restored = call(prefix+'/instructor', token=token)
            if restored['phase'] != 'lobby' or restored['generation'] != 1:
                raise RuntimeError('Room reset failed.')
            print('PASS: separate demo room, three real fits, evaluation, reveal, and reset.')
    except HTTPError as error:
        raise SystemExit(f'FAIL: server returned HTTP {error.code}. Check URL, deployment logs, and instructor key.')
    except (URLError, RuntimeError, KeyError, ValueError) as error:
        # Do not echo URLs, bodies, or Authorization headers.
        raise SystemExit(f'FAIL: {type(error).__name__}. Check the application URL and deployment logs.')


if __name__ == '__main__':
    main()
