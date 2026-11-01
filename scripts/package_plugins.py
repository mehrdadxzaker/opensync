#!/usr/bin/env python3
"""Build deterministic, self-contained Codex and Claude plugin ZIPs."""
import hashlib
from pathlib import Path
import zipfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from opensync import __version__

ROOT = Path(__file__).resolve().parent.parent


def package(destination=None):
    destination = destination or ROOT / 'dist'
    destination.mkdir(parents=True, exist_ok=True)
    common = [ROOT / 'README.md', ROOT / 'LICENSE', ROOT / 'pyproject.toml', ROOT / '_build_backend.py']
    for folder in ('opensync', 'skills', 'assets', 'docs'):
        common.extend(p for p in (ROOT / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')
    common.append(ROOT / 'scripts/kb.py')
    paths = []
    for host in ('codex', 'claude'):
        target = destination / f'opensync-{host}-{__version__}.zip'
        extra = [ROOT / 'plugin.json', ROOT / '.codex-plugin/plugin.json'] if host == 'codex' else [ROOT / '.claude-plugin/plugin.json', ROOT / 'commands/kb.md']
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(common + extra):
                info = zipfile.ZipInfo(path.relative_to(ROOT).as_posix(), (2026, 11, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, path.read_bytes())
        paths.append(target)
        print(str(target))
    (destination / 'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n' for p in paths))
    return paths


if __name__ == '__main__':
    package()
