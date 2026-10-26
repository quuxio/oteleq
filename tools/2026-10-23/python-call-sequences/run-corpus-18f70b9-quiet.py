"""Run one immutable Python corpus and preserve all original terminal evidence."""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).parent
SOURCE = ROOT / 'source-18f70b9'
CLI = ROOT / 'quux-oteleq-18f70b9'
MANIFEST = Path('/Users/sclarke/github/otelc-qualification/2026-10-20/integrated-provider/d6d03b7/manifest.json')
PROVIDER = MANIFEST.parent / 'provider'


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify() -> dict:
    manifest = json.loads(MANIFEST.read_text())
    counts = {}
    for group in ('source_sha256', 'products_sha256', 'dependencies'):
        for name, expected in manifest[group].items():
            path = PROVIDER / name
            if isinstance(expected, str):
                assert digest(path) == expected, name
            elif 'sha256' in expected:
                assert digest(path) == expected['sha256'], name
            else:
                assert path.is_symlink() and os.readlink(path) == expected['symlink'], name
                assert str(path.resolve()) == expected['resolved'], name
        counts[group] = len(manifest[group])
    python = manifest['tools']['python']
    assert digest(Path(python['resolved'])) == python['sha256']
    assert digest(Path(sys.executable).resolve()) == python['sha256']
    seal = json.loads((ROOT / 'source-18f70b9.json').read_text())
    assert all(digest(SOURCE / name) == expected for name, expected in seal['files'].items())
    build = json.loads((ROOT / 'build-cli-18f70b9.json').read_text())
    assert build['exit_code'] == 0 and build['commit'] == seal['commit']
    assert digest(CLI) == build['cli_sha256']
    return {'provider_commit': manifest['source_commit'], 'provider_counts': counts,
            'provider_manifest_sha256': digest(MANIFEST), 'selected_tool_roles': 1,
            'python_sha256': python['sha256'], 'consumer_commit': seal['commit'],
            'consumer_files': len(seal['files']), 'cli_sha256': digest(CLI)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('route', choices=('qualification', 'compatibility'))
    args = parser.parse_args()
    folder = ROOT / (args.route + '-18f70b9-quiet')
    receipt = ROOT / (args.route + '-run-18f70b9-quiet.json')
    assert not folder.exists() and not receipt.exists()
    script = 'qualify_python_sequences.py' if args.route == 'qualification' else 'qualify_receivers.py'
    command = [sys.executable, str(SOURCE / 'tests' / script), '--cli', str(CLI),
               '--otelc-root', str(PROVIDER), '--report-dir', str(folder)]
    record = {'started_at': datetime.datetime.now(datetime.UTC).isoformat(),
              'route': args.route, 'trial': 'quiet-host', 'previous_attempt': 'qualification-run-18f70b9.json', 'argv': command, 'before': verify()}
    receipt.write_text(json.dumps(record, indent=2) + '\n')
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1',
                       OTELEQ_PYTHON=sys.executable, OTELEQ_CLI=str(CLI))
    environment.pop('OTELC_CONFIG', None)
    with (ROOT / (args.route + '-run-18f70b9-quiet.log')).open('w') as output:
        result = subprocess.run(command, cwd=SOURCE, env=environment,
                                stdout=output, stderr=subprocess.STDOUT)
    record.update(exit_code=result.returncode, after=verify(),
                  finished_at=datetime.datetime.now(datetime.UTC).isoformat())
    assert record['before'] == record['after']
    receipt.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({'route': args.route, 'exit_code': result.returncode,
                      'source_files_preserved': record['after']['consumer_files'],
                      'provider_records_preserved': sum(record['after']['provider_counts'].values())}))
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
