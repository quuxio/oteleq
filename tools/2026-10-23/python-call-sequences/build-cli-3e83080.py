"""Build and retain the exact frozen corpus candidate using the pinned toolchain."""

import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).parent
SOURCE = ROOT / 'source-3e83080'


def main() -> None:
    seal = json.loads((ROOT / 'source-3e83080.json').read_text())
    environment = dict(os.environ,
        PATH='/Users/sclarke/.rustup/toolchains/1.98.1-aarch64-apple-darwin/bin:/opt/homebrew/bin:/usr/bin:/bin',
        CARGO_TARGET_DIR=str(ROOT / 'target-cli-4593e82'), CARGO_NET_OFFLINE='true')
    command = ['cargo', 'build', '--locked']
    record = {'commit': seal['commit'], 'argv': command,
              'started_at': datetime.datetime.now(datetime.UTC).isoformat()}
    with (ROOT / 'build-cli-3e83080.log').open('w') as output:
        result = subprocess.run(command, cwd=SOURCE, env=environment,
                                stdout=output, stderr=subprocess.STDOUT)
    record['exit_code'] = result.returncode
    if result.returncode == 0:
        binary = ROOT / 'quux-oteleq-3e83080'
        shutil.copy2(ROOT / 'target-cli-4593e82/debug/quux-oteleq', binary)
        record['cli_sha256'] = hashlib.sha256(binary.read_bytes()).hexdigest()
    assert all(hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == expected
               for name, expected in seal['files'].items())
    record.update(source_files_preserved=len(seal['files']),
                  finished_at=datetime.datetime.now(datetime.UTC).isoformat())
    (ROOT / 'build-cli-3e83080.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record))
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
