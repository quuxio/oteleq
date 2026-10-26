"""Plan or COW-compact inactive native outputs after a terminal qualification receipt."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess

HELPER = Path(__file__).parent / '2026-10-23/clone-retained-cpp-products.py'
HELPER_SHA256 = '5f51189d6b2683916620116a57c380a2d6af018efe3c365c15179eae674a3c09'


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-root', type=Path, required=True)
    parser.add_argument('--terminal-receipt', type=Path, required=True)
    parser.add_argument('--record', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    report = args.report_root.resolve(strict=True)
    receipt = args.terminal_receipt.resolve(strict=True)
    record_path = args.record.resolve()
    if record_path.exists() or record_path.is_relative_to(report):
        parser.error('record must be new and outside the retained report root')
    terminal = json.loads(receipt.read_text())
    if type(terminal.get('exit_code')) is not int or terminal['exit_code'] not in (0, 1) or not terminal.get('finished_at'):
        parser.error('require the completed outer qualification controller receipt')
    terminal_sha = sha(receipt)
    if sha(HELPER) != HELPER_SHA256:
        parser.error('native COW helper identity changed')
    helper = runpy.run_path(str(HELPER))
    rows = []
    for directory, subdirs, names in os.walk(report):
        folder = Path(directory)
        if folder.name in ('node_modules', '.git', 'go-cache', '.venv', 'target'):
            subdirs[:] = []
            continue
        if folder.name != 'scratch' or not folder.parent.name.startswith(('baseline-', 'instrumented_on-')):
            continue
        identity = folder.parent / 'build-identities.json'
        if not identity.is_file() or not (folder.parent / 'command.json').is_file():
            continue
        binding = json.loads(identity.read_text()).get('application')
        if not isinstance(binding, str) or len(binding) != 64:
            continue
        for name in ('application', 'application.otelc.json'):
            path = folder / name
            if not path.is_file() or path.is_symlink() or path.stat().st_size < 1048576:
                continue
            value = sha(path)
            if name == 'application' and value != binding:
                raise ValueError('retained application differs from its build identity')
            rows.append({'path': str(path), 'sha256': value, 'bytes': path.stat().st_size})
    opened = subprocess.run(['lsof', '-nP', '-Fpn'], capture_output=True, text=True, check=True)
    active = {line[1:] for line in opened.stdout.splitlines() if line.startswith('n')}
    if any(row['path'] in active for row in rows):
        raise ValueError('a retained product is still open; compaction refused')
    record = {'started_at': datetime.datetime.now(datetime.UTC).isoformat(),
              'report_root': str(report), 'terminal_receipt': str(receipt),
              'terminal_receipt_sha256': terminal_sha, 'apply': args.apply,
              'helper_sha256': HELPER_SHA256, 'products': rows, 'clones': []}
    record_path.parent.mkdir(parents=True, exist_ok=True)
    canonical = {}
    try:
        for row in rows:
            path = Path(row['path'])
            before = helper['metadata'](path)
            attrs = helper['xattrs'](path)
            if sha(path) != row['sha256'] or sha(receipt) != terminal_sha:
                raise ValueError('retained input or terminal receipt changed')
            key = (path.name, row['sha256'], before['mode'], before['uid'], before['gid'], attrs)
            if key not in canonical:
                canonical[key] = path
                continue
            donor = canonical[key]
            if not args.apply:
                record['clones'].append({'path': str(path), 'canonical': str(donor), 'bytes': row['bytes']})
                continue
            temporary = path.with_name('.' + path.name + '.cow-' + str(os.getpid()))
            if temporary.exists():
                raise FileExistsError(temporary)
            record['pending'] = {'path': str(path), 'sha256': row['sha256'], 'before': before}
            record_path.write_text(json.dumps(record, indent=2) + '\n')
            try:
                if helper['lib'].clonefile(os.fsencode(donor), os.fsencode(temporary), 1) != 0:
                    raise OSError('native clonefile failed')
                os.utime(temporary, ns=(before['atime_ns'], before['mtime_ns']))
                after = helper['metadata'](temporary)
                if (not helper['preserved'](before, after) or helper['xattrs'](temporary) != attrs
                        or sha(temporary) != row['sha256'] or after['inode'] == donor.stat().st_ino):
                    raise ValueError('clone bytes or metadata differ')
                current = helper['metadata'](path)
                if any(current[key] != before[key] for key in ('inode', 'bytes', 'mtime_ns', 'mode', 'uid', 'gid')):
                    raise ValueError('original product changed before replacement')
                os.replace(temporary, path)
                if sha(path) != row['sha256']:
                    raise ValueError('post-replacement content differs')
                record['clones'].append({'path': str(path), 'canonical': str(donor), 'bytes': row['bytes'],
                                         'sha256': row['sha256'], 'original_metadata': before,
                                         'clone_metadata': helper['metadata'](path)})
                record.pop('pending')
                record_path.write_text(json.dumps(record, indent=2) + '\n')
            finally:
                if temporary.exists():
                    temporary.unlink()
        if sha(receipt) != terminal_sha or any(sha(Path(row['path'])) != row['sha256'] for row in rows):
            raise ValueError('final retained evidence check failed')
        record.update(exit_code=0, finished_at=datetime.datetime.now(datetime.UTC).isoformat(),
                      candidate_files=len(rows), duplicate_files=len(record['clones']),
                      duplicate_bytes=sum(row['bytes'] for row in record['clones']))
    except BaseException as error:
        record.update(exit_code=1, error_type=type(error).__name__)
        raise
    finally:
        record_path.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({key: value for key, value in record.items() if key not in ('products', 'clones')}))


if __name__ == '__main__':
    main()
