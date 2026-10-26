"""Assemble a checked unittest route for offline HTML/JUnit presentation."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent


def read(path: Path):
    return json.loads(path.read_text())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=('initial', 'changed', 'added', 'different'), default='different')
    args = parser.parse_args()
    actual = ROOT / 'actual'
    checked = read(actual / (args.stage + '.checked.json'))
    records = [json.loads(line) for line in (actual / (args.stage + '.stdout')).read_text().splitlines()][1:]
    assert len(records) == checked['cases']
    header, cases, receipts = None, [], []
    for record in records:
        path = Path(record['report'])
        data = read(path)
        assert len(data['cases']) == 1 and data['source_preserved'] and not data['blocked']
        metadata = {key: value for key, value in data.items() if key not in ('cases', 'exit_code')}
        if header is None:
            header = copy.deepcopy(metadata)
        assert metadata == header
        cases.extend(data['cases'])
        receipts.append({'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    assert len({case['case'] for case in cases}) == len(cases)
    result = {**header, 'cases': cases, 'exit_code': max(case['exit_code'] for case in cases)}
    destination = ROOT / ('presentation-' + args.stage)
    source = ROOT / ('presentation-' + args.stage + '-report.json')
    assert not source.exists() and not destination.exists()
    source.write_text(json.dumps(result, indent=2) + '\n')
    cli = Path(read(ROOT / 'freeze.json')['cli'])
    rendered = subprocess.run([str(cli), 'render-report', str(source), '--output-dir', str(destination)],
                              capture_output=True, check=False)
    (ROOT / ('presentation-' + args.stage + '.stdout')).write_bytes(rendered.stdout)
    (ROOT / ('presentation-' + args.stage + '.stderr')).write_bytes(rendered.stderr)
    assert rendered.returncode == result['exit_code']
    summary = {'stage': args.stage, 'cases': len(cases), 'exit_code': result['exit_code'],
               'report': str(source), 'presentation': str(destination), 'original_reports': receipts,
               'raw_reports_not_modified': True, 'rendering_does_not_launch_applications': True}
    (ROOT / ('presentation-' + args.stage + '-receipt.json')).write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({key: value for key, value in summary.items() if key != 'original_reports'}, indent=2))


if __name__ == '__main__':
    main()
