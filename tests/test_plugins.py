import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from package_plugins import package
from validate_plugin import validate


class PluginTests(unittest.TestCase):
    def test_manifest_and_listing_limits(self):
        validate()
        d = json.loads((ROOT / 'plugin.json').read_text(encoding='utf-8'))
        interface = d['extensions']['com.openai']['interface']
        self.assertLessEqual(len(interface['shortDescription']), 30)
        self.assertLessEqual(len(interface['displayName']), 30)
        self.assertTrue(d['extensions']['com.openai']['requires_local_executor'])

    def test_clean_extracted_packages_execute_without_installation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            note = root / 'note.md'
            note.write_text('# Independent runtime\nCitations survive packaging.\n')
            archives = package(root / 'archives')
            for archive in archives:
                extracted = root / archive.stem
                with zipfile.ZipFile(archive) as z:
                    self.assertFalse(any('__pycache__' in n or n.endswith('.sqlite') for n in z.namelist()))
                    z.extractall(extracted)
                script = extracted / 'scripts/kb.py'
                args = [sys.executable, str(script), '--home', str(root / archive.stem / 'kb')]
                sync = subprocess.run(args + ['sync', str(note), '--no-schedule'], cwd=root, capture_output=True, text=True, timeout=10)
                self.assertEqual(sync.returncode, 0, sync.stderr)
                result = subprocess.run(args + ['search', 'citations'], cwd=root, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)[0]['title'], 'Independent runtime')

    def test_sdist_builds_a_valid_wheel_without_build_dependencies(self):
        import tarfile
        import importlib.util
        spec = importlib.util.spec_from_file_location("opensync_backend", ROOT / "_build_backend.py")
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = backend.build_sdist(folder)
            with tarfile.open(root / archive) as source:
                for member in source.getmembers():
                    target = (root / member.name).resolve()
                    self.assertTrue(target.is_relative_to(root.resolve()))
                    self.assertTrue(member.isfile())
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with source.extractfile(member) as stream:
                        target.write_bytes(stream.read())
            extracted = root / "opensync_kb-0.1.1"
            code = 'import _build_backend; print(_build_backend.build_wheel("."))'
            result = subprocess.run([sys.executable, "-c", code], cwd=extracted, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            with zipfile.ZipFile(extracted / result.stdout.strip()) as wheel:
                self.assertIn("opensync/cli.py", wheel.namelist())
                self.assertIn("opensync_kb-0.1.1.dist-info/RECORD", wheel.namelist())

    def test_archives_are_reproducible(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = package(root / 'one')
            second = package(root / 'two')
            self.assertEqual([p.read_bytes() for p in first], [p.read_bytes() for p in second])
