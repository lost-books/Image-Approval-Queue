#!/usr/bin/env python3
"""Standalone image approval queue. Python 3.9+, no dependencies."""
import argparse
import json
import mimetypes
import os
import secrets
import tempfile
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote


class Queue:
    def __init__(self, manifest, decisions=None):
        self.manifest = Path(manifest).resolve()
        self.decisions = Path(decisions).resolve() if decisions else self.manifest.with_name(self.manifest.stem + '.decisions.json')
        if self.decisions == self.manifest:
            raise ValueError('Manifest and decisions must be different files')
        self.lock = threading.Lock()
        self.token = secrets.token_urlsafe(32)
        self.images()
        self.ledger()

    def images(self):
        data = json.loads(self.manifest.read_text())
        images = data['images']
        if not isinstance(images, list):
            raise ValueError('images must be a list')
        label = data.get('promotion_label', 'Promote')
        if not isinstance(label, str) or not label.strip() or len(label) > 80:
            raise ValueError('promotion_label must be a short, nonempty string')
        ids = set()
        for item in images:
            if not isinstance(item.get('id'), str) or not item['id'] or item['id'] in ids:
                raise ValueError('Every image needs a unique, nonempty string id')
            ids.add(item['id'])
            if not isinstance(item.get('path'), str) or not item['path']:
                raise ValueError('Every image needs a path')
        return images

    def promotion_label(self):
        return json.loads(self.manifest.read_text()).get('promotion_label', 'Promote')

    def ledger(self):
        data = json.loads(self.decisions.read_text()) if self.decisions.exists() else {'version': 1, 'images': {}}
        if not isinstance(data.get('images'), dict):
            raise ValueError('Invalid decision ledger; refusing to overwrite')
        for entry in data['images'].values():
            if not isinstance(entry, dict) or entry.get('status', 'pending') not in ('pending', 'approved', 'rejected') or type(entry.get('promoted', False)) is not bool or type(entry.get('marked_cover', False)) is not bool or not isinstance(entry.get('history', []), list):
                raise ValueError('Invalid decision entry; refusing to overwrite')
            # Legacy cover marks become promotions. Keep the old field and history
            # intact for audit; a later Promote click takes precedence.
            entry.setdefault('promoted', entry.get('marked_cover', False))
        return data

    def save(self, choice):
        if not isinstance(choice, dict) or set(choice) not in ({'id', 'status'}, {'id', 'promoted'}):
            raise ValueError('Specify id and exactly one decision field')
        if choice['id'] not in {i['id'] for i in self.images()}:
            raise ValueError('Unknown image id')
        field = 'status' if 'status' in choice else 'promoted'
        if (field == 'status' and choice[field] not in ('pending', 'approved', 'rejected')) or (field == 'promoted' and type(choice[field]) is not bool):
            raise ValueError('Invalid decision')
        with self.lock:
            ledger = self.ledger()
            entry = ledger['images'].setdefault(choice['id'], {'status': 'pending', 'promoted': False, 'history': []})
            before = {'status': entry.get('status', 'pending'), 'promoted': entry['promoted']}
            entry[field] = choice[field]
            entry['updated_at'] = datetime.now(timezone.utc).isoformat()
            entry.setdefault('history', []).append({'at': entry['updated_at'], 'field': field, 'value': choice[field], 'before': before})
            self.decisions.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=self.decisions.name + '.', dir=self.decisions.parent)
            try:
                with os.fdopen(fd, 'w') as f:
                    json.dump(ledger, f, indent=2)
                    f.write('\n')
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, self.decisions)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            return entry


def make_server(queue, port=0):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, data, kind='application/json', status=200):
            if not isinstance(data, bytes):
                data = json.dumps(data).encode()
            self.send_response(status)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            try:
                if self.path == '/':
                    return self.send((Path(__file__).resolve().parent.parent / 'assets/queue.html').read_bytes(), 'text/html; charset=utf-8')
                if self.path == '/api/queue':
                    return self.send({'images': queue.images(), 'decisions': queue.ledger()['images'], 'promotion_label': queue.promotion_label(), 'token': queue.token})
                if self.path.startswith('/image/'):
                    image_id = unquote(self.path[len('/image/'):])
                    item = next((i for i in queue.images() if i['id'] == image_id), None)
                    if item is None:
                        return self.send({'error': 'Unknown image'}, status=404)
                    path = (queue.manifest.parent / item['path']).resolve()
                    mime = mimetypes.guess_type(path)[0]
                    if mime not in ('image/png', 'image/jpeg', 'image/webp', 'image/gif', 'image/avif', 'image/svg+xml'):
                        return self.send({'error': 'Unsupported image format'}, status=415)
                    return self.send(path.read_bytes(), mime)
                self.send({'error': 'Not found'}, status=404)
            except Exception as e:
                self.send({'error': str(e)}, status=500)

        def do_POST(self):
            if self.path != '/api/decision':
                return self.send({'error': 'Not found'}, status=404)
            if self.headers.get('X-Queue-Token') != queue.token:
                return self.send({'error': 'Invalid session token'}, status=403)
            try:
                size = int(self.headers.get('Content-Length', 0))
                if not 0 < size <= 8192:
                    raise ValueError('Invalid request size')
                choice = json.loads(self.rfile.read(size))
                self.send(queue.save(choice))
            except (ValueError, TypeError, KeyError) as e:
                self.send({'error': str(e)}, status=400)
            except Exception as e:
                self.send({'error': 'Save failed: ' + str(e)}, status=500)
    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--decisions', type=Path)
    parser.add_argument('--port', default=0, type=int)
    args = parser.parse_args()
    queue = Queue(args.manifest, args.decisions)
    # OS lock prevents competing processes from losing updates to the same ledger.
    import fcntl
    queue.decisions.parent.mkdir(parents=True, exist_ok=True)
    with open(str(queue.decisions) + '.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error('This decision ledger is already open in another queue process')
        server = make_server(queue, args.port)
        print(f'Image approval queue: http://127.0.0.1:{server.server_port}/', flush=True)
        print(f'Decisions: {queue.decisions}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == '__main__':
    main()
