"""Qualify the explicit cached-loader matrix, receivers, effects and retained workflows."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import generation
import python_inputs
import python_cache_effect_workflows as effects
import python_cache_receiver_workflows as receivers
import qualify_python_caches as matrix
import qualify_python_generated_origins as origins
from qualify_project_tests import command

COMPONENTS = ('matrix', 'receivers', 'effects')
COUNTS = ('actual_application_launches', 'sdk_processes', 'reports', 'complete_raw_and_typed_observations',
          'copied_original_observations', 'recomputed_comparisons', 'prelaunch_input_mutation_refusals',
          'altered_comparison_refusals')


def process_records(folder: Path) -> dict[str, str]:
    """A retained-only audit must preserve operation receipts and process-start records."""
    names = {'process.json', 'python-application-start.json', 'python-sdk-execution.json'}
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in folder.rglob('*.json')
            if path.name.endswith('.started.json') or path.name in names}


def run_component(name: str, cli: Path, provider: Path, folder: Path, catalogue: dict) -> None:
    """New execution always requires a new owned output directory."""
    assert name in COMPONENTS
    if name == 'matrix':
        folder.mkdir(mode=0o700)
        generation.write(folder / 'provider-inputs.json', catalogue)
        for mode in matrix.MODES:
            root = folder / mode
            workspace, inputs = matrix.prepare(root, mode, cli, provider)
            command([cli, 'run', '--workspace', workspace, '--report-dir', root / 'comparison'], root, 'run')
            matrix.check_report(root / 'comparison/report.json', mode); inputs.verify_originals()
    else:
        (receivers if name == 'receivers' else effects).run(cli, provider, folder, catalogue)


def audit_component(name: str, cli: Path, provider: Path, folder: Path, catalogue: dict,
                    interpreter: dict) -> dict:
    """Compare existing data without re-executing applications or deliberate input mutations."""
    assert name in COMPONENTS and folder.is_dir()
    before = process_records(folder)
    assert before
    if name == 'matrix':
        result = matrix.recheck(folder, cli, provider, catalogue)
    else:
        result = (receivers if name == 'receivers' else effects).retained(
            folder, cli, provider, catalogue, interpreter)
    assert process_records(folder) == before
    return {**result, 'operation_and_process_records_held': len(before), 'new_application_launches_in_audit': 0}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--otelc-root', type=Path, required=True)
    parser.add_argument('--report-dir', type=Path, required=True)
    parser.add_argument('--cli', type=Path, required=True)
    parser.add_argument('--component', choices=(*COMPONENTS, 'all'), default='all')
    parser.add_argument('--recheck', action='store_true')
    parser.add_argument('--audit-dir', type=Path)
    args = parser.parse_args(argv)
    if sys.flags.optimize:
        parser.error('qualification requires assertions; disable Python optimisation')
    cli, provider, folder = args.cli.resolve(strict=True), args.otelc_root.resolve(strict=True), args.report_dir.resolve()
    if any(folder.is_relative_to(root) for root in (provider, ROOT)):
        parser.error('qualification output must be external to the application and SDK')
    if args.recheck != (args.audit_dir is not None):
        parser.error('--recheck requires a new --audit-dir; execution does not use --audit-dir')
    destination = args.audit_dir.resolve() if args.recheck else folder
    if args.recheck:
        if any(destination.is_relative_to(root) for root in (provider, ROOT, folder)):
            parser.error('audit output must be outside the SDK, application and original evidence directory')
        destination.mkdir(mode=0o700)
    os.environ.update(OTELEQ_PYTHON=sys.executable, OTELEQ_CLI=str(cli), PYTHONDONTWRITEBYTECODE='1')
    catalogue = python_inputs.artefacts(provider, {'python': Path(sys.executable).absolute()})
    interpreter = origins.interpreter_probe()
    if args.component == 'all' and not args.recheck:
        folder.mkdir(mode=0o700)
    selected = COMPONENTS if args.component == 'all' else (args.component,)
    components = {}
    for name in selected:
        target = folder / name if args.component == 'all' else folder
        if not args.recheck:
            run_component(name, cli, provider, target, catalogue)
        components[name] = audit_component(name, cli, provider, target, catalogue, interpreter)
    assert python_inputs.artefacts(provider, {'python': Path(sys.executable).absolute()}) == catalogue
    result = {'claim': 'equivalence over these tests and observations', 'artefact_class': 'diagnostic',
              'cli_sha256': generation.capture.file_digest(cli), 'python_hexversion': sys.hexversion,
              'components': components, 'totals': {key: sum(row.get(key, 0) for row in components.values())
                                                  for key in COUNTS},
              'scope': 'Explicit ordinary cached-loader diagnostic workflows on this pinned runtime/provider. '
                       'Broader loaders, async/resources, live controls, shipping artefacts and all full-project '
                       'acceptance areas require separate evidence.'}
    result['evidence_directory'] = str(folder)
    generation.write(destination / ('retained-audit.json' if args.recheck else 'qualification.json'), result)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
