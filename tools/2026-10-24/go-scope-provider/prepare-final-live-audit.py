"""Reuse the independent fixed-workload oracle for exact committed-head data."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent
text = (ROOT / 'audit-development-02.py').read_text()
text = text.replace("REPO = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-go-public-provider')",
                    "REPO = ROOT / 'source-e765f0d'")
text = text.replace('spec.loader.exec_module(oracle)', "spec.loader.exec_module(oracle)\noracle.ROOT = ROOT / 'public-e765f0d-01/comparison'")
text = text.replace('public-development-02', 'public-e765f0d-01')
text = text.replace('source-development-01.json', 'source-e765f0d.json')
text = text.replace('dirty_development_snapshot=True', 'dirty_development_snapshot=False')
text = text.replace('frozen uncommitted builtin-shadow direct workflow only; retained, tagged, SDK full gate and full Go remain open',
                    'exact committed e765f0d builtin-shadow direct workflow only; retained, tagged, SDK corrected full gate and full Go remain open')
with (ROOT / 'audit-public-e765f0d.py').open('x') as output:
    output.write(text)
