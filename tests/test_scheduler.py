from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from opensync import scheduler


class SchedulerTests(unittest.TestCase):
    def test_macos_install_is_idempotent_and_uninstall_cleans_up(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            home = root / 'store with spaces'
            home.mkdir()
            def result(returncode):
                return SimpleNamespace(returncode=returncode, stderr='', stdout='')
            with patch('opensync.scheduler.sys.platform', 'darwin'), patch('opensync.scheduler.os.getuid', return_value=1000, create=True), patch('opensync.scheduler.Path.home', return_value=root), patch('opensync.scheduler.subprocess.run', side_effect=[result(1), result(0)]) as run:
                installed = scheduler.install(home)
                self.assertTrue(installed['installed'])
                data = plistlib.loads(Path(installed['path']).read_bytes())
                self.assertEqual(data['ProgramArguments'], scheduler.command(home))
                self.assertTrue(any('bootstrap' in call.args[0] for call in run.call_args_list))
            with patch('opensync.scheduler.sys.platform', 'darwin'), patch('opensync.scheduler.os.getuid', return_value=1000, create=True), patch('opensync.scheduler.Path.home', return_value=root), patch('opensync.scheduler.subprocess.run', return_value=result(0)) as run:
                scheduler.install(home)
                self.assertEqual(run.call_count, 1)
                self.assertTrue(scheduler.status(home)['installed'])
                scheduler.uninstall(home)
                self.assertFalse(Path(installed['path']).exists())
                self.assertFalse((home / 'scheduler.json').exists())

    def test_systemd_paths_are_quoted_and_specifiers_escaped(self):
        plan = scheduler.plan(Path('/tmp/a %path $value'), 'linux')
        self.assertIn('%%path $$value', plan['service'])
        self.assertIn('"/tmp/a %%path $$value"', plan['service'])
