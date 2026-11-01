#!/usr/bin/env python3
"""Local structural validation; public portal review is separate."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent


def validate(root=ROOT):
    portable = json.loads((root / 'plugin.json').read_text())
    codex = json.loads((root / '.codex-plugin/plugin.json').read_text())
    claude = json.loads((root / '.claude-plugin/plugin.json').read_text())
    assert portable['name'] == codex['name'] == claude['name'] == 'opensync'
    assert portable['version'] == codex['version'] == claude['version']
    assert portable['extensions']['com.openai']['requires_local_executor'] is True
    assert codex['requires_local_executor'] is True
    assert not (root / '.mcp.json').exists()
    assert not (root / 'hooks').exists()
    extension = portable['extensions']['com.openai']
    for value in [extension['onboardingSkill'], extension['interface']['logo'], extension['interface']['composerIcon']]:
        path = (root / value).resolve()
        assert path.is_relative_to(root.resolve()) and path.is_file(), value
    skills = list((root / 'skills').glob('*/SKILL.md'))
    assert len(skills) == 4
    for path in skills:
        text = path.read_text()
        assert text.startswith('---\nname: ')
        assert '\ndescription: ' in text
        assert (path.parent / '../../scripts/kb.py').resolve().is_file()
    marketplace = json.loads((root / '.agents/plugins/marketplace.json').read_text())
    assert marketplace['plugins'][0]['source']['path'] == './'
    result = subprocess.run([sys.executable, str(root / 'scripts/kb.py'), '--version'], cwd=root.parent, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    print('Validated four skills, bundled CLI, both host manifests, local-executor flag, assets, and marketplace.')


if __name__ == '__main__':
    validate()
