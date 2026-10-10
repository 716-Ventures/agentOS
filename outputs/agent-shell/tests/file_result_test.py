"""File JSON must survive broker paging without lost hashes or Unicode bytes."""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services'))
import assistant
import broker
import files


class FileResults(unittest.TestCase):
    def collect(self, raw, truncated=False):
        with tempfile.TemporaryDirectory() as tmp, patch.object(broker, 'STATE', Path(tmp)):
            job = dict(id='a' * 32, status='succeeded', exit_code=0, output_truncated=truncated)
            (Path(tmp) / (job['id'] + '.log')).write_bytes(raw)
            def poll(op, job_id, offset=0):
                self.assertEqual(op, 'poll')
                self.assertEqual(job_id, job['id'])
                return broker.view(job, offset)
            with patch.object(assistant, 'broker_request', side_effect=poll):
                return assistant.collect_file_result(broker.view(job))

    def test_complete_64k_content_and_hash_survive_all_pages(self):
        for content in ('a' * 65536, '界' * 21845, '😀' * 16384):
            with self.subTest(sample=content[:1]), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'note'
                path.write_text(content, encoding='utf-8')
                expected = files.run({'op': 'read', 'path': str(path)})
                # Exercise the actual helper's CLI encoding, not a substitute serializer.
                raw = subprocess.check_output([sys.executable, str(Path(files.__file__)),
                    json.dumps({'op': 'read', 'path': str(path)})])
                self.assertGreater(len(raw), 32768)
                result = self.collect(raw)
                self.assertNotIn('error', result)
                measured = result['file_result']['metadata'].pop('measured_at')
                self.assertGreaterEqual(measured, expected['metadata'].pop('measured_at'))
                self.assertEqual(result['file_result'], expected)
                self.assertEqual(result['file_result']['content'], content)
                self.assertEqual(result['file_result']['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
                self.assertEqual(result['next_offset'], len(raw))

    def test_helper_preserves_surrogate_escaped_filename_in_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'missing-\udcff')
            raw = subprocess.check_output([sys.executable, str(Path(files.__file__)),
                json.dumps({'op':'read','path':path})])
            raw.decode('utf-8')
            self.assertEqual(self.collect(raw)['file_result']['path'], path)

    def test_live_poll_keeps_incomplete_utf8_suffix_for_next_page(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(broker, 'STATE', Path(tmp)):
            job = dict(id='b' * 32, status='running')
            path = Path(tmp) / (job['id'] + '.log')
            path.write_bytes(b'x' * 32767 + '界'.encode())
            first = broker.view(job)
            self.assertEqual(first['output'], 'x' * 32767)
            self.assertEqual(first['next_offset'], 32767)
            last = broker.view(job, first['next_offset'])
            self.assertEqual(last['output'], '界')
            self.assertEqual(last['next_offset'], path.stat().st_size)

    def test_terminal_invalid_utf8_tail_advances_without_hanging(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(broker, 'STATE', Path(tmp)):
            job = dict(id='b' * 32, status='failed')
            (Path(tmp) / (job['id'] + '.log')).write_bytes(b'output\xf0')
            page = broker.view(job)
            self.assertEqual(page['output'], 'output\ufffd')
            self.assertEqual(page['next_offset'], 7)

    def test_truncated_json_is_an_explicit_error_not_a_file_result(self):
        result = self.collect(b'{"content":"partial', truncated=True)
        self.assertIn('exceeded', result['error'])
        self.assertNotIn('file_result', result)

    def test_invalid_or_non_object_json_is_an_explicit_error(self):
        for raw in (b'{"content":"partial', b'[]', b''):
            with self.subTest(raw=raw):
                result = self.collect(raw)
                self.assertIn('invalid', result['error'])
                self.assertNotIn('file_result', result)

    def test_non_advancing_broker_page_is_rejected(self):
        job = dict(id='a' * 32, status='succeeded', output='{', next_offset=1)
        with patch.object(assistant, 'broker_request', return_value={'output':'more','next_offset':1}):
            with self.assertRaisesRegex(ValueError, 'did not advance'):
                assistant.collect_file_result(job)
