from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from opensync.cli import main, duration
from opensync import scheduler


class CLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / 'knowledge'
        self.file = self.root / 'note.md'
        self.file.write_text('# OpenSync\nShared knowledge for agents.\n')

    def call(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(['--home', str(self.home), *args])
        return code, json.loads(out.getvalue() or err.getvalue())

    def test_cli_end_to_end(self):
        code, result = self.call('sync', str(self.file), '--every', '6h', '--no-schedule')
        self.assertEqual(code, 0)
        self.assertTrue(result['results'][0]['ok'])
        _, hits = self.call('search', 'agents')
        self.assertEqual(len(hits), 1)
        _, doc = self.call('read', hits[0]['document_id'])
        self.assertIn('agents', doc['text'])
        _, sources = self.call('sources')
        self.assertFalse(sources[0]['stale'])
        _, status = self.call('status')
        self.assertEqual(status['documents'], 1)
        _, export = self.call('export')
        self.assertEqual(export['sources'][0]['every_seconds'], 21600)
        code, _ = self.call('remove', '1')
        self.assertEqual(code, 1)
        code, _ = self.call('remove', '1', '--yes')
        self.assertEqual(code, 0)
        self.assertTrue(self.file.exists())

    def test_lists_relative_paths_and_deduplication(self):
        sources = self.root / 'sources.txt'
        sources.write_text('# comment\nnote.md\n\nnote.md\n')
        code, result = self.call('sync', '--from', str(sources), '--no-schedule')
        self.assertEqual(code, 0)
        self.assertEqual(len(result['results']), 1)

    def test_stdin_list(self):
        with patch('sys.stdin', io.StringIO(str(self.file) + '\n')):
            self.assertEqual(self.call('sync', '--from', '-', '--no-schedule')[0], 0)

    def test_batch_partial_failure_preserves_good_sources(self):
        code, result = self.call('sync', str(self.file), 'ftp://bad', str(self.root / 'missing.txt'), '--no-schedule')
        self.assertEqual(code, 1)
        self.assertEqual(len(result['results']), 3)
        self.assertEqual(sum(r['ok'] for r in result['results']), 1)
        self.assertEqual(len(self.call('search', 'agents')[1]), 1)

    def test_empty_list_fails_without_scheduling(self):
        with patch('sys.stdin', io.StringIO('# empty\n')), patch('opensync.scheduler.install') as install:
            self.assertEqual(self.call('sync', '--from', '-')[0], 1)
            install.assert_not_called()

    def test_schedule_failure_reports_index_success(self):
        with patch('opensync.scheduler.install', side_effect=RuntimeError('no timer')):
            code, result = self.call('sync', str(self.file))
        self.assertEqual(code, 1)
        self.assertTrue(result['results'][0]['ok'])
        self.assertFalse(result['schedule']['installed'])

    def test_worker_once_and_invalid_poll(self):
        self.call('sync', str(self.file), '--no-schedule')
        self.assertEqual(self.call('worker', '--once')[0], 0)
        self.assertEqual(self.call('worker', '--poll', '1', '--once')[0], 1)

    def test_scheduler_plans_use_absolute_paths(self):
        mac = scheduler.plan(self.home, 'darwin')
        self.assertEqual(mac['payload']['StartInterval'], 60)
        self.assertEqual(mac['arguments'][-1], 'refresh')
        self.assertTrue(Path(mac['arguments'][1]).is_absolute())
        linux = scheduler.plan(self.home, 'linux')
        self.assertIn('OnUnitActiveSec=60', linux['timer'])
        self.assertEqual(scheduler.plan(self.home, 'win32')['backend'], 'worker')
        self.assertNotEqual(scheduler.label(self.home), scheduler.label(self.root))

    def test_timer_entrypoint_from_unrelated_directory(self):
        self.call('sync', str(self.file), '--no-schedule')
        proc = subprocess.run(scheduler.command(self.home), cwd=self.root, capture_output=True, text=True, timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['results'], [])

    def test_intervals(self):
        self.assertEqual(duration('6h'), 21600)
        self.assertEqual(duration('15m'), 900)
        self.assertEqual(duration('1d'), 86400)
        import argparse
        for invalid in ('0h', '6', 'forever', '-1m'):
            with self.assertRaises(argparse.ArgumentTypeError):
                duration(invalid)


if __name__ == '__main__':
    unittest.main()
