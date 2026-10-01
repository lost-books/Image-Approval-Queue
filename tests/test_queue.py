import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

queue_module = load_module('image_queue', ROOT / 'scripts/queue.py')
import_module = load_module('add_images', ROOT / 'scripts/add_images.py')


class QueueTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.manifest = self.root / 'manifest.json'
        self.items = [{'id': 'r1/a v1', 'path': 'image.svg', 'round': 1}, {'id': 'r2/a-v2', 'path': 'image.svg', 'round': 2, 'variant_of': 'r1/a v1'}]
        self.write_manifest()
        (self.root / 'image.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        self.q = queue_module.Queue(self.manifest)
        self.server = queue_module.make_server(self.q)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def write_manifest(self):
        self.manifest.write_text(json.dumps({'promotion_label': 'Promote', 'images': self.items}))

    def post(self, choice, token=None):
        req = Request(self.url+'/api/decision', data=json.dumps(choice).encode(), headers={'X-Queue-Token': token or self.q.token, 'Content-Type': 'application/json'})
        with urlopen(req) as response:
            return json.load(response)

    def test_controls_persist_independently_across_rounds(self):
        self.post({'id': 'r1/a v1', 'status': 'approved'})
        self.assertEqual(json.loads(self.q.decisions.read_text())['images']['r1/a v1']['status'], 'approved')
        self.post({'id': 'r1/a v1', 'promoted': True})
        self.post({'id': 'r1/a v1', 'status': 'rejected'})
        cleared = self.post({'id': 'r1/a v1', 'status': 'pending'})
        self.assertTrue(cleared['promoted'])
        self.assertEqual(len(cleared['history']), 4)
        self.assertEqual(cleared['history'][-1]['before']['status'], 'rejected')
        self.assertEqual(self.post({'id': 'r1/a v1', 'promoted': False})['history'][-1]['value'], False)
        restarted = queue_module.Queue(self.manifest)
        self.assertEqual(restarted.ledger(), self.q.ledger())
        self.assertNotIn('r2/a-v2', restarted.ledger()['images'])
        self.items.reverse()
        self.items.append({'id': 'r3/new', 'path': 'image.svg'})
        self.write_manifest()
        self.assertEqual(queue_module.Queue(self.manifest).ledger()['images']['r1/a v1']['status'], 'pending')

    def test_legacy_cover_mark_migrates_without_erasing_history(self):
        old = {'version': 1, 'images': {'r1/a v1': {'status': 'approved', 'marked_cover': True, 'history': [{'at': 'older', 'marked_cover': True}]}}}
        self.q.decisions.write_text(json.dumps(old))
        with urlopen(self.url+'/api/queue') as response:
            state = json.load(response)
        self.assertEqual(state['promotion_label'], 'Promote')
        self.assertTrue(state['decisions']['r1/a v1']['promoted'])
        self.assertEqual(json.loads(self.q.decisions.read_text()), old)
        changed = self.post({'id': 'r1/a v1', 'promoted': False})
        self.assertFalse(changed['promoted'])
        self.assertTrue(changed['marked_cover'])
        self.assertEqual(changed['history'][0], old['images']['r1/a v1']['history'][0])
        self.assertEqual(len(changed['history']), 2)
        self.assertFalse(queue_module.Queue(self.manifest).ledger()['images']['r1/a v1']['promoted'])

    def test_http_validation_and_image_lookup(self):
        with urlopen(self.url+'/image/r1%2Fa%20v1') as response:
            self.assertEqual(response.headers['Content-Type'], 'image/svg+xml')
        for choice in [{'id': 'unknown', 'status': 'approved'}, {'id': 'r1/a v1', 'status': 'bad'}, {'id': 'r1/a v1', 'promoted': 'true'}, {'id': 'r1/a v1', 'marked_cover': True}, {'id': 'r1/a v1', 'status': 'approved', 'promoted': True}]:
            with self.assertRaises(HTTPError) as error:
                self.post(choice)
            self.assertEqual(error.exception.code, 400)
            error.exception.close()
        with self.assertRaises(HTTPError) as error:
            self.post({'id': 'r1/a v1', 'status': 'approved'}, 'bad-token')
        self.assertEqual(error.exception.code, 403)
        error.exception.close()
        self.assertFalse(self.q.decisions.exists())

    def test_invalid_state_and_duplicate_ids_fail_closed(self):
        self.q.decisions.write_text('{bad json')
        with self.assertRaises(ValueError):
            queue_module.Queue(self.manifest)
        self.assertEqual(self.q.decisions.read_text(), '{bad json')
        self.items.append(self.items[0])
        self.write_manifest()
        with self.assertRaises(ValueError):
            queue_module.Queue(self.manifest)


class RoundImportTest(unittest.TestCase):
    def test_import_is_repeatable_and_overwrites_become_new_variants(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'image.svg'
            source.write_text('<svg>first</svg>')
            manifest = root / 'queue' / 'manifest.json'
            first = import_module.add_images(manifest, [source], '1')
            self.assertEqual(len(first), 1)
            self.assertEqual(import_module.add_images(manifest, [source], '1'), [])
            snapshot = manifest.parent / first[0]['path']
            self.assertEqual(snapshot.read_text(), '<svg>first</svg>')
            source.write_text('<svg>second</svg>')
            second = import_module.add_images(manifest, [source], '2', variant_of=first[0]['id'], promotion_label='Promote')
            self.assertNotEqual(second[0]['id'], first[0]['id'])
            self.assertEqual(second[0]['variant_of'], first[0]['id'])
            self.assertEqual(snapshot.read_text(), '<svg>first</svg>')
            self.assertEqual((manifest.parent / second[0]['path']).read_text(), '<svg>second</svg>')
            self.assertEqual(len(json.loads(manifest.read_text())['images']), 2)


if __name__ == '__main__':
    unittest.main()
