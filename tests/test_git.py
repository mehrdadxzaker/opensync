from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import hashlib

from opensync.adapters import git_documents
from opensync.core import KnowledgeBase


class GitTests(unittest.TestCase):
    def test_isolated_cache_sync_updates_deletes_and_preserves_on_failure(self):
        # Use a local Git fixture; translate only the clone URL in the mocked
        # subprocess boundary so the production adapter performs no network I/O.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            remote = root / 'fixture'
            remote.mkdir()
            def git(*args):
                subprocess.run(['git', '-C', str(remote), *args], check=True, capture_output=True, timeout=10)
            git('init', '-b', 'main')
            git('config', 'user.name', 'Fixture')
            git('config', 'user.email', 'fixture@example.invalid')
            file = remote / 'guide.md'
            file.write_text('# Planning\nOriginal robotic planning\n')
            git('add', '.')
            git('commit', '-m', 'Initial fixture')
            real_run = subprocess.run
            calls = []
            def run(args, **kwargs):
                args = list(args)
                calls.append(args[:])
                if 'clone' in args:
                    args[-2] = str(remote)
                return real_run(args, **kwargs)
            uri = 'git+https://example.invalid/owner/repo.git'
            with KnowledgeBase(root / 'kb') as kb:
                ident = kb.register(uri, 'git', 60)
                with patch('opensync.adapters.subprocess.run', run):
                    self.assertTrue(kb.refresh(ident)['ok'])
                hit = kb.search('robotic')[0]
                self.assertEqual(hit['location'], uri + '#guide.md')
                self.assertEqual(file.read_text(encoding='utf-8'), '# Planning\nOriginal robotic planning\n')
                file.write_text('# Learning\nNew policy learning\n')
                git('add', '.')
                git('commit', '-m', 'Update fixture')
                with patch('opensync.adapters.subprocess.run', run):
                    self.assertEqual(kb.refresh(ident)['updated'], 1)
                self.assertEqual(kb.search('robotic'), [])
                self.assertEqual(len(kb.search('policy')), 1)
                with patch('opensync.adapters.subprocess.run', side_effect=RuntimeError('fetch failed')):
                    self.assertFalse(kb.refresh(ident)['ok'])
                self.assertTrue(kb.search('policy')[0]['stale'])
                file.unlink()
                (remote / 'other.txt').write_text('replacement')
                git('add', '-A')
                git('commit', '-m', 'Delete fixture')
                with patch('opensync.adapters.subprocess.run', run):
                    self.assertEqual(kb.refresh(ident)['deleted'], 1)
                self.assertEqual(kb.search('policy'), [])
            self.assertTrue(all('core.hooksPath=' in ' '.join(c) for c in calls))
