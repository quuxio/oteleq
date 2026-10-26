"""Prepare the exact committed-head live experiment in a fresh directory."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent
text = (ROOT / 'qualify-development-02.py').read_text()
replacements = {'source-development-01.json': 'source-e765f0d.json',
                'target-development-01': 'target-e765f0d-public',
                'public-development-02': 'public-e765f0d-01',
                '"head": INDEX["parent_head"]': '"head": INDEX["head"]',
                '"dirty_development_snapshot": True': '"dirty_development_snapshot": False',
                'frozen uncommitted source-scope-v1 development direct workflow with builtin shadows; retained routes and full Go remain open':
                    'committed source-scope-v1 direct workflow with builtin shadows; retained routes and full Go remain open'}
for before, after in replacements.items():
    assert text.count(before) == 1, before
    text = text.replace(before, after)
with (ROOT / 'qualify-public-e765f0d.py').open('x') as output:
    output.write(text)
