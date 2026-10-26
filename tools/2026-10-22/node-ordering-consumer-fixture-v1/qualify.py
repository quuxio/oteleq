"""Qualify the immutable plain Node ordering fixture against a fixed oracle."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPEATS = 32
NODE_VERSIONS = (
    (Path('/opt/homebrew/opt/node@24/bin/node'), 'v24.21.0'),
    (Path('/opt/homebrew/opt/node/bin/node'), 'v26.11.0'),
)
ENVIRONMENT = {
    'PATH': '/usr/bin:/bin',
    'LANG': 'C',
    'LC_ALL': 'C',
    'TZ': 'UTC',
}


def sha256(path: Path) -> str:
    """Return the complete regular file digest."""
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path: Path, value: object) -> None:
    """Write a new readable evidence record without replacing earlier data."""
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def verify_inputs(files: dict[str, str]) -> None:
    """Reject fixture changes rather than accepting a different oracle."""
    for relative, expected in files.items():
        if sha256(ROOT / relative) != expected:
            raise ValueError(f'Frozen fixture input changed: {relative}')


def run_attempt(
    node: Path,
    source: Path,
    destination: Path,
    oracle: dict,
) -> dict:
    """Retain actual process evidence and compare complete output bytes."""
    destination.mkdir()
    command = [str(node), str(source)]
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=ENVIRONMENT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        stdout, stderr = process.communicate()
    (destination / 'stdout.bin').write_bytes(stdout)
    (destination / 'stderr.bin').write_bytes(stderr)
    record = {
        'pid': process.pid,
        'argv': command,
        'cwd': str(ROOT),
        'environment': ENVIRONMENT,
        'exit_code': process.returncode,
        'timed_out': timed_out,
        'elapsed_seconds': time.monotonic() - started,
        'stdout_sha256': hashlib.sha256(stdout).hexdigest(),
        'stderr_sha256': hashlib.sha256(stderr).hexdigest(),
        'stdout_matches': stdout == oracle['expected_stdout'].encode('utf-8'),
        'stderr_matches': stderr == oracle['expected_stderr'].encode('utf-8'),
        'exit_matches': process.returncode == oracle['expected_exit'],
    }
    record['passed'] = (
        not timed_out
        and record['stdout_matches']
        and record['stderr_matches']
        and record['exit_matches']
    )
    write_json(destination / 'process.json', record)
    return record


def main() -> int:
    """Run only plain applications and retain every successful or failed run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    manifest = json.loads((ROOT / 'manifest.json').read_text())
    frozen_files = manifest['files_sha256']
    verify_inputs(frozen_files)
    oracle = json.loads((ROOT / 'oracle.json').read_text())
    output = args.output.resolve()
    output.mkdir(exist_ok=False)
    runs = output / 'runs'
    runs.mkdir()
    results = []
    runtimes = []
    for selected_node, expected_version in NODE_VERSIONS:
        node = selected_node.resolve(strict=True)
        node_hash = sha256(node)
        version = subprocess.run(
            [str(node), '--version'],
            env=ENVIRONMENT,
            check=True,
            capture_output=True,
            timeout=5,
        )
        if version.stdout != (expected_version + '\n').encode() or version.stderr:
            raise ValueError(f'Unexpected Node identity: {node}')
        runtime = {
            'requested_executable': str(selected_node),
            'actual_executable': str(node),
            'version': expected_version,
            'sha256': node_hash,
            'version_probes': 1,
        }
        runtimes.append(runtime)
        for repeat in range(REPEATS):
            verify_inputs(frozen_files)
            name = f'{expected_version}-repeat-{repeat:02d}'
            record = run_attempt(
                node, ROOT / oracle['source'], runs / name, oracle,
            )
            verify_inputs(frozen_files)
            record.update({'runtime': expected_version, 'repeat': repeat})
            results.append(record)
        if sha256(node) != node_hash:
            raise ValueError(f'Node executable changed during qualification: {node}')
        runtime['unchanged_after_execution'] = True
    verify_inputs(frozen_files)
    passed = all(record['passed'] for record in results)
    receipt = {
        'schema_version': 1,
        'status': 'plain fixture qualification only',
        'finished_utc': datetime.now(timezone.utc).isoformat(),
        'host': platform.platform(),
        'machine': platform.machine(),
        'python': sys.version,
        'manifest_sha256': sha256(ROOT / 'manifest.json'),
        'inputs_unchanged': True,
        'expected_oracle': oracle,
        'runtimes': runtimes,
        'repeats_per_runtime': REPEATS,
        'application_launches': len(results),
        'sdk_provider_consumed': False,
        'all_passed': passed,
        'results': results,
    }
    write_json(output / 'qualification.json', receipt)
    print(json.dumps({
        'application_launches': len(results),
        'all_passed': passed,
        'evidence': str(output / 'qualification.json'),
    }))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
