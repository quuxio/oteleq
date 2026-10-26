"""Final-revision actual-provider plan/build regression, separate from the full route corpus."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import qualify_native_project as qualification

root = Path(__file__).resolve().parent
provider = Path('/Users/sclarke/github/otelc-qualification/2026-10-21/native-main-transform/58abcf5/provider')
manifest = provider.parent / 'manifest.json'
supplied = Path('/Users/sclarke/github/oteleq-qualification/work/native-final-smoke-target/debug/quux-oteleq')
cli = root / 'quux-oteleq'
shutil.copy2(supplied, cli)
cli.chmod(0o555)
os.environ['OTELEQ_PYTHON'], os.environ['OTELEQ_CLI'] = sys.executable, str(cli)
results = []
for name, language, optimisation, difference in qualification.CASES:
    folder = root / name
    folder.mkdir()
    workspace, source, original = qualification.prepare(cli, provider, folder, language, optimisation, difference)
    captures = folder / 'comparison'
    qualification.command([cli, 'run', '--workspace', workspace, '--report-dir', captures], folder, 'run', expected=int(difference))
    launches, report = qualification.check_report(captures / 'report.json', difference=difference)
    assert {p.relative_to(source).as_posix(): qualification.digest(p) for p in source.rglob('*') if p.is_file()} == original
    results.append({'name': name, 'actual_application_launches': launches, 'expected_difference': difference, 'source_preserved': True})
provider_manifest = json.loads(manifest.read_text())
for name, expected in provider_manifest['files_sha256'].items():
    assert qualification.digest(provider / name) == expected, name
record = {'runtime_source_head': '09980b2639fbe6af5366f6a53160186baf46eedc', 'runtime_cli_sha256': qualification.digest(cli),
    'provider_source_head': provider_manifest['source_head'], 'provider_manifest_sha256': qualification.digest(manifest),
    'provider_files_unchanged': len(provider_manifest['files_sha256']), 'cases': results,
    'actual_application_launches': sum(result['actual_application_launches'] for result in results),
    'qualifier_sha256': qualification.digest(root / 'qualify_native_project.py'),
    'source_preserved': True, 'scope': 'Final review-refactor public plan/generate/run regression only; detached/replay/reduction scope stays bound to the separate 64-launch corpus.'}
qualification.write(root / 'validation.json', record)
print(json.dumps(record, indent=2))
