"""Compare the documented public CLI with normal installed startup behaviour."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import venv

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'source'


def main():
    with tempfile.TemporaryDirectory(prefix='public-cli-hook-', dir=ROOT) as temporary:
        root = Path(temporary)
        private = root / 'interpreter'
        venv.EnvBuilder(with_pip=False, symlinks=True).create(private)
        python = private / 'bin/python'
        site = private / f'lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages'
        site.mkdir(parents=True, exist_ok=True)
        (site / 'application-startup.pth').write_text('import builtins;print("installed application hook")\n')
        app = root / 'app';app.mkdir()
        entry = app / 'entry.py';entry.write_text('print("original")\n')
        policy = root / 'otelc.toml';policy.write_text('schema_version=3\nlanguages=["python"]\n')
        environment = {**os.environ, 'PYTHONPATH': str(SOURCE), 'PYTHONDONTWRITEBYTECODE': '1'}
        plain = subprocess.run([str(python), str(entry)], cwd=app, env=environment,
            capture_output=True, timeout=20)
        argv = [str(python), '-m', 'otelc', '--config', str(policy), 'python',
            '--root', str(app), '--entry', str(entry), '--runtime', str(root / 'plain-runtime'), '--plain']
        actual = subprocess.run(argv, cwd=app, env=environment, capture_output=True, timeout=40)
        prepared = subprocess.run([*argv[:-2], str(root / 'prepared-runtime'), '--plain', '--prepare-only'],
            cwd=app, env=environment, capture_output=True, timeout=40)
        try:
            json.loads(prepared.stdout)
            json_valid = True
        except ValueError:
            json_valid = False
        result = {'head': 'eb853cea77c2c5c713587b951dbbc58c124dba54',
            'python': sys.version, 'native_exit': plain.returncode,
            'native_stdout': plain.stdout.decode(), 'native_stderr': plain.stderr.decode(),
            'public_cli_exit': actual.returncode, 'public_cli_stdout': actual.stdout.decode(),
            'public_cli_stderr': actual.stderr.decode(),
            'stdout_matches_native': actual.stdout == plain.stdout,
            'prepare_only_exit': prepared.returncode, 'prepare_only_stdout_is_JSON': json_valid,
            'prepare_only_stdout_prefix': prepared.stdout[:100].decode(),
            'prepare_only_stderr': prepared.stderr.decode(),
            'scope': 'Actual documented normal Python -m otelc plain/prepare-only CLI with one installed .pth hook; no SDK starts.'}
        index = json.loads((ROOT / 'source.json').read_text())
        assert all(hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == expected
                   for name, expected in index['files'].items())
        result['source_files_preserved'] = len(index['files'])
        (ROOT / 'public-cli-hook.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result))


if __name__ == '__main__':
    main()
