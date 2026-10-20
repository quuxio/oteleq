"""Qualify real Python package imports with generated tests and source guards."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

from qualify_generation import command


def fixture(destination: Path, prefix: str) -> tuple[Path, Path]:
    source = destination / 'application'
    package = source / prefix / 'pkg'
    package.mkdir(parents=True)
    (package / '__init__.py').write_text('BIAS=3\ndef selected_init(value:int)->int:\n assert __name__=="pkg"\n return value+BIAS\n')
    (package / 'helper.py').write_text('def twice(value:int)->int:return value*2\n')
    (package / 'api.py').write_text('from .helper import twice\nfrom pkg import BIAS\nstate=0\ndef selected(value:int)->int:\n global state\n assert __name__=="pkg.api" and __package__=="pkg"\n state+=twice(value)+BIAS\n return state\n')
    policy = destination / 'equivalence.toml'
    policy.write_text('schema_version=1\nlanguages=["python"]\n[adapters.python]\nimport_roots=[' + json.dumps(prefix or '.') + ']\n[functions]\ninclude=["*.selected","*.selected_init"]\n[[fixtures]]\nfunction="*.selected"\ncases=[[7]]\n[[fixtures]]\nfunction="*.selected_init"\ncases=[[7]]\n')
    return source, policy


def check_report(path: Path) -> int:
    report = json.loads(path.read_text())
    assert report['source_preserved'] and not report['blocked'] and len(report['cases']) == 2
    assert len([entry for entry in report['inventory'] if entry['status'] == 'excluded']) == 1
    launches = 0
    for case in report['cases']:
        assert case['exit_code'] == 0
        expected = 10 if case['function'].endswith('selected_init') else 17
        bundle = json.loads((path.parent / case['case'] / 'typed-bundle.json').read_text())['cases'][0]
        for lane in ('baseline', 'instrumented_on'):
            assert len(bundle[lane]) == 2
            for attempt in bundle[lane]:
                launches += 1
                observation = attempt['observation']
                assert not observation['gaps'] and observation['outcome']['kind'] == 'return'
                result = observation['outcome']['graph']['roots']['result']
                assert result['kind'] == 'integer' and int(result['value']) == expected
                if lane == 'instrumented_on':
                    assert attempt['execution']['witness']['functions'] == {case['function']: 1}
    return launches


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--otelc-root', type=Path, required=True)
    parser.add_argument('--report-dir', type=Path, required=True)
    parser.add_argument('--cli', type=Path, required=True)
    args = parser.parse_args()
    cli, root, destination = args.cli.resolve(strict=True), args.otelc_root.resolve(strict=True), args.report_dir.resolve()
    repo = Path(__file__).resolve().parents[1]
    if destination.is_relative_to(root) or destination.is_relative_to(repo):
        parser.error('report directory must be new and outside both repositories')
    destination.mkdir(mode=0o700, exist_ok=False)
    os.environ['OTELEQ_PYTHON'] = sys.executable
    os.environ['OTELEQ_CLI'] = str(cli)
    launches, cases, controls = 0, 0, 0
    for name, prefix in [('regular', ''), ('src-layout', 'src')]:
        folder = destination / name
        folder.mkdir()
        source, policy = fixture(folder, prefix)
        workspace = Path(command([cli, 'plan', '--source', source, '--otelc-root', root,
                                  '--workspace-parent', folder, '--config', policy], folder, 'plan'))
        command([cli, 'generate', '--workspace', workspace], folder, 'generate')
        command([cli, 'run', '--workspace', workspace, '--report-dir', folder / 'comparison'], folder, 'comparison')
        launches += check_report(folder / 'comparison/report.json')
        cases += 2
        framework = json.loads(command([sys.executable, workspace / 'tests/test_equivalence.py'], folder, 'framework'))
        launches += check_report(Path(framework['report']))
        exported = folder / 'exported'
        command([cli, 'export-tests', '--workspace', workspace, '--destination', exported], folder, 'export-dry-run')
        assert not exported.exists()
        command([cli, 'export-tests', '--workspace', workspace, '--destination', exported, '--apply'], folder, 'export-apply')
        exported_result = json.loads(command([sys.executable, exported / 'tests/test_equivalence.py'], folder, 'exported-framework'))
        launches += check_report(Path(exported_result['report']))
        dependency = source / prefix / 'pkg/helper.py'
        before = dependency.read_bytes()
        try:
            dependency.write_bytes(before + b'\n# altered local dependency control\n')
            report_dir = folder / 'changed-dependency'
            command([cli, 'run', '--workspace', workspace, '--report-dir', report_dir], folder, 'changed-dependency', expected=4)
            assert not report_dir.exists()
            controls += 1
        finally:
            dependency.write_bytes(before)
        plan = json.loads((workspace / 'plan.json').read_text())
        assert all(hashlib.sha256((source / path).read_bytes()).hexdigest() == value
                   for path, value in plan['source_manifest'].items())
    result = {'claim': 'equivalence over these tests and observations', 'artefact_class': 'diagnostic',
              'cli_sha256': hashlib.sha256(cli.read_bytes()).hexdigest(), 'projects': 2, 'cases': cases,
              'actual_application_launches': launches, 'generated_unittest_runs': 4,
              'changed_local_dependency_controls_rejected': controls, 'source_preserved': True,
              'scope': 'Explicit regular Python source packages and src layout, module-local state and scalar calls; no namespace, installed project metadata, imported-root or shipping qualification.'}
    (destination / 'QUALIFICATION.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
