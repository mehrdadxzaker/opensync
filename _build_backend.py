"""Minimal standard-library PEP 517 backend for this pure Python package."""
from __future__ import annotations
import base64
import csv
import hashlib
import io
from pathlib import Path
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parent
NAME = 'opensync_kb'
VERSION = '0.1.0'
DIST = f'{NAME}-{VERSION}.dist-info'


def metadata():
    return ('Metadata-Version: 2.3\nName: opensync-kb\nVersion: ' + VERSION + '\nSummary: Sync anything to a local, searchable knowledge base.\nAuthor: Mehrdad Zaker\nLicense: MIT\nRequires-Python: >=3.10\nProvides-Extra: pdf\nRequires-Dist: pypdf>=5,<7; extra == "pdf"\nDescription-Content-Type: text/markdown\n\n' + (ROOT / 'README.md').read_text()).encode()


def get_requires_for_build_wheel(config_settings=None):
    return []


def get_requires_for_build_sdist(config_settings=None):
    return []


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    target = Path(wheel_directory) / f'{NAME}-{VERSION}-py3-none-any.whl'
    files = {p.relative_to(ROOT).as_posix(): p.read_bytes() for p in (ROOT / 'opensync').glob('*.py')}
    files[DIST + '/METADATA'] = metadata()
    files[DIST + '/WHEEL'] = b'Wheel-Version: 1.0\nGenerator: opensync-stdlib\nRoot-Is-Purelib: true\nTag: py3-none-any\n'
    files[DIST + '/entry_points.txt'] = b'[console_scripts]\nkb = opensync.cli:main\nopensync = opensync.cli:main\n'
    files[DIST + '/licenses/LICENSE'] = (ROOT / 'LICENSE').read_bytes()
    record = io.StringIO(newline='')
    writer = csv.writer(record)
    for name, data in sorted(files.items()):
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()
        writer.writerow([name, 'sha256=' + digest, len(data)])
    writer.writerow([DIST + '/RECORD', '', ''])
    files[DIST + '/RECORD'] = record.getvalue().encode()
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, (2026, 11, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return target.name


def build_sdist(sdist_directory, config_settings=None):
    target = Path(sdist_directory) / f'{NAME}-{VERSION}.tar.gz'
    top = f'{NAME}-{VERSION}'
    paths = [ROOT / n for n in ('pyproject.toml', '_build_backend.py', 'README.md', 'LICENSE')]
    paths += list((ROOT / 'opensync').glob('*.py'))
    with tarfile.open(target, 'w:gz') as archive:
        for path in sorted(paths):
            archive.add(path, arcname=top + '/' + path.relative_to(ROOT).as_posix())
        data = metadata()
        info = tarfile.TarInfo(top + '/PKG-INFO')
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    return target.name
