"""Direct actual-provider controls; broader routes and negative corpus remain pending."""
import hashlib
import json
import os
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'source/tests'))
from qualify_generation import command

CASES = [
    ('cjs', '.cjs', None, 'commonjs'), ('mjs', '.mjs', None, 'module'),
    ('js-default', '.js', None, 'commonjs'), ('js-module', '.js', 'module', 'module'),
    ('js-commonjs', '.js', 'commonjs', 'commonjs'), ('js-detected', '.js', None, 'module'),
    ('cts', '.cts', None, 'commonjs'), ('mts', '.mts', None, 'module'),
    ('ts-default', '.ts', None, 'commonjs'), ('ts-module', '.ts', 'module', 'module'),
    ('ts-commonjs', '.ts', 'commonjs', 'commonjs'),
]


def scalar(language, value):
    return {'kind': 'float', 'type': language + '.float64', 'bits': struct.pack('>d', value).hex()}


def check_graphs(observation, language):
    assert observation['gaps'] == []
    for key, value in [('before', 2.0), ('after', 9.0)]:
        graph = observation[key]
        assert set(graph['roots']) == {'arguments', 'global:state'}
        assert graph['roots']['global:state'] == scalar(language, value)
        argument = graph['roots']['arguments']
        assert len(graph['nodes']) == 1
        node = graph['nodes'][0]
        assert node['id'] == argument['node_id'] and node['type'] == 'ecmascript.array.prototype:Array'
        fields = node['fields']
        assert fields['property:0'] == scalar(language, 7.0)
        assert fields['property:length'] == scalar(language, 1.0)
    assert observation['outcome'] == {'kind': 'return', 'value': {'roots': {'result': scalar(language, 16.0)}, 'nodes': []}}


def main():
    destination = ROOT / 'module-matrix-direct'
    destination.mkdir(exist_ok=False)
    cli = ROOT / 'quux-oteleq'
    provider = Path('/Users/sclarke/github/otelc-qualification/2026-10-20/integrated-provider/d6d03b7/provider')
    os.environ['OTELEQ_PYTHON'] = sys.executable
    results = []
    for name, suffix, package_type, expected_format in CASES:
        folder = destination / name
        folder.mkdir()
        source = folder / 'application'
        source.mkdir()
        language = 'typescript' if suffix in ('.ts', '.mts', '.cts') else 'javascript'
        filename = 'sample' + suffix
        annotation = ':number' if language == 'typescript' else ''
        export = 'export ' if name == 'js-detected' else ''
        text = 'let state=2;\n' + export + 'function selected(n' + annotation + '){state+=n;return state+n;}\n'
        text += 'console.log(typeof require==="function"?"commonjs":"module");\n'
        (source / filename).write_text(text)
        original = hashlib.sha256((source / filename).read_bytes()).hexdigest()
        package = None
        if package_type:
            (source / 'package.json').write_text(json.dumps({'type': package_type}) + '\n')
            package = {'path': 'package.json', 'sha256': hashlib.sha256((source / 'package.json').read_bytes()).hexdigest()}
        config = folder / 'equivalence.toml'
        config.write_text('schema_version=1\nlanguages=' + json.dumps([language]) + '\n[functions]\ninclude=["sample.selected"]\n'
                          '[[fixtures]]\nfunction="sample.selected"\ncases=[[7]]\n'
                          'expected_baseline={kind="return_value",value={kind="float",type="' + language + '.float64",bits="4030000000000000"}}\n')
        workspace = Path(command([cli, 'plan', '--source', source, '--otelc-root', provider,
                                  '--workspace-parent', folder, '--config', config], folder, 'plan'))
        command([cli, 'generate', '--workspace', workspace], folder, 'generate')
        comparison = folder / 'comparison'
        command([cli, 'run', '--workspace', workspace, '--report-dir', comparison], folder, 'run')
        report = json.loads((comparison / 'report.json').read_text())
        assert report['exit_code'] == 0 and report['source_preserved'] and not report['blocked']
        assert len(report['cases']) == 1
        case = report['cases'][0]
        bundle = json.loads((comparison / case['case'] / 'typed-bundle.json').read_text())['cases'][0]
        for lane in ('baseline', 'instrumented_on'):
            assert len(bundle[lane]) == 2
            for index, attempt in enumerate(bundle[lane]):
                check_graphs(attempt['observation'], language)
                execution = attempt['execution']
                assert execution['capture_complete'] and execution['termination'] == {'kind': 'exit', 'code': 0}
                assert bytes(execution['channels']['stdout']) == (expected_format + '\n').encode()
                assert execution['channels']['stderr'] == []
                current = comparison / case['case'] / (lane + '-' + str(index))
                context = json.loads((current / 'node-context.json').read_text())
                assert context['original']['format'] == context['caller']['format'] == expected_format
                assert context['original']['package'] == context['caller']['package'] == package
                assert context['original']['source_sha256'] == original
                assert context['caller']['source_sha256'] == hashlib.sha256((current / 'project' / filename).read_bytes()).hexdigest()
                capture = json.loads((current / 'http-capture.json').read_text())
                assert capture['errors'] == []
                if lane == 'baseline':
                    assert not capture['bodies'] and execution['witness'] is None
                else:
                    health = json.loads((current / 'runtime.json').read_text())
                    assert health['export_finished'] and health['function_calls'] == 1 and health['export_loss'] == 0
                    assert all(value == 0 for value in health['losses'].values())
                    assert health['functions'] == {'sample.selected': {'count': 1, 'unwinds': 0}}
                    assert health['traces']['completed_trees'] == 1
                    assert health['traces']['active_trees'] == health['traces']['queued_trees'] == 0
                    assert capture['bodies'] and execution['witness'] is not None
        assert hashlib.sha256((source / filename).read_bytes()).hexdigest() == original
        results.append({'context': name, 'language': language, 'format': expected_format, 'actual_application_launches': 4})
        (destination / 'progress.json').write_text(json.dumps(results, indent=2) + '\n')
    summary = {'status': 'direct controls passed; generated/detached/replay/reduction and negative corpus pending',
               'claim': 'equivalence over these tests and observations', 'contexts': results,
               'actual_application_launches': sum(item['actual_application_launches'] for item in results)}
    (destination / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
