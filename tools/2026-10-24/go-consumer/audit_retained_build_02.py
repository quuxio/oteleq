"""Recheck retained native products with independent caller-pinned Go readers."""

import hashlib
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
CONSUMER = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-go-source-provider')
SDK = ROOT.parent / 'go-benchmark-review-fdd434b/fixed-source-b95780c'
sys.path[:0] = [str(CONSUMER / 'adapters/generation'), str(CONSUMER / 'examples')]
import go_build as build
import go_files as files


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def run():
    result = ROOT / 'build-reader-real-02'
    result.mkdir(mode=0o700)
    started = time.monotonic()
    index = json.loads((SDK.parent / 'fixed-source-b95780c-index.json').read_text())
    before = {name: files.file(SDK / name)[:2] for name in index['files']}
    assert all(value[0]['sha256'] == index['files'][name] for name, value in before.items())
    tools, _ = files.read(SDK / 'build/go-upstream/toolchain.json')
    assert tools['go'] == '/Users/sclarke/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.27.3.darwin-arm64/bin/go'
    assert tools['weaver'] == str(SDK / 'build/go-upstream/bin/otelc')
    assert tools['bundle'] == str(ROOT.parent / 'go-source-review-67b1b0d/source/build/go-module-cache/go.opentelemetry.io/otelc@v1.0.1/tool/data/otelc-bundle.tgz')
    assert tools['bundle_sha256'] == '4a928c69ce269e37c98413c93159713fa7bcd8169c5d6b4de167305dc5ca9bb2'
    settings, _ = files.read(ROOT / 'build-reader-real-01/settings.stdout')
    _, _, raw = files.file(ROOT / 'build-reader-real-01/modules.stdout', files.MAX_METADATA_BYTES, keep=True)
    text, modules, decoder = raw.decode().strip(), [], json.JSONDecoder()
    while text:
        row, end = decoder.raw_decode(text)
        modules.append(row)
        text = text[end:].lstrip()
    json.dumps(modules, allow_nan=False)
    intent = build.Intent(
        ROOT / 'prototype-execution-01/bundle',
        files.freeze(ROOT / 'prototype-execution-01/application'),
        files.freeze(SDK / 'adapters/go'), '.',
        (build.Target('example.com/oteleqfixture.Add', 'main.go', 5, 1),),
        tools, settings, modules,
        files.freeze(ROOT / 'prototype-build-01/bundle/context'))
    with patch('subprocess.run', side_effect=AssertionError('retained reader executed a command')), \
            patch('subprocess.Popen', side_effect=AssertionError('retained reader started a target')):
        actual = build.read(intent)
        actual.verify()
    assert all(files.file(SDK / name)[:2] == value for name, value in before.items())
    source = {name: files.identity(CONSUMER / 'adapters/generation' / name)['sha256']
              for name in ('go_provider.py', 'go_files.py', 'go_build.py')}
    write(result / 'result.json', {
        'result': 'passed', 'seconds': round(time.monotonic() - started, 3),
        'consumer_sources': source, 'provider': index['head'],
        'provider_source_files_held': len(before), 'build_schema': actual.receipt['schema_version'],
        'compiler_recipe_commands': len(actual.receipt['commands']),
        'compiler_evidence_files_held': len(actual.evidence),
        'original_inputs_held': len(intent.original.identities),
        'private_sdk_inputs_held': len(actual.sdk.identities),
        'independently_pinned_context_inputs': len(intent.context.identities),
        'selected_functions': [row['name'] for row in actual.receipt['selection']['functions']],
        'new_target_applications': 0,
        'scope': 'Retained historical build2/health3 compatibility only. Caller module metadata was independently read in the prior retained audit; expected context comes from the earlier build-only fixture. This does not establish pre-build source closure, independent helper transformation, generated runtime admission or the upcoming build3/config2/health4 API.'})
    print(json.dumps({'result': 'passed', 'compiler_evidence_files': len(actual.evidence), 'provider_source_files_held': len(before), 'new_target_applications': 0}))


if __name__ == '__main__':
    run()
