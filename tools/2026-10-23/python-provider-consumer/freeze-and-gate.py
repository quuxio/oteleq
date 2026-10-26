import datetime, hashlib, json, os, pathlib, subprocess, tarfile
base = pathlib.Path(__file__).resolve().parent
repo = pathlib.Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-python-prepared-provider')
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
source = base / ('source-' + head[:7])
archive = base / ('source-' + head[:7] + '.tar')
subprocess.run(['git', 'archive', '--format=tar', '-o', str(archive), head], cwd=repo, check=True)
source.mkdir()
with tarfile.open(archive) as stream:
    names = [item.name for item in stream.getmembers() if item.isfile()]
    stream.extractall(source, filter='data')
hashes = lambda: {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in names}
before = hashes()
(base / ('source-' + head[:7] + '-manifest.json')).write_text(json.dumps(before, indent=2, sort_keys=True) + '\n')
old = pathlib.Path('/Users/sclarke/github/oteleq-qualification/2026-10-23/qualification-retention/source-2b0f9f1/ci')
subprocess.run(['/bin/cp', '-cR', str(old / 'markdownlint/node_modules'), str(source / 'ci/markdownlint')], check=True)
subprocess.run(['/bin/cp', '-cR', str(old / 'java-coverage'), str(source / 'ci')], check=True)
bindir = base / ('bin-' + head[:7])
bindir.mkdir()
cli = bindir / 'quux-oteleq'
subprocess.run(['/bin/cp', '-c', '/Users/sclarke/github/oteleq-qualification/2026-10-23/python-call-sequences/target-runtime-4593e82/debug/quux-oteleq', str(cli)], check=True)
cli.chmod(0o500)
previous = json.loads(pathlib.Path('/Users/sclarke/github/oteleq-qualification/2026-10-23/qualification-retention/gate-2b0f9f1.json').read_text())
command = previous['command']
environment = {**os.environ, **previous['environment']}
record = {'head': head, 'source': str(source), 'source_files_before': len(before), 'command': command, 'environment': previous['environment'], 'immutable_cli': str(cli), 'cli_sha256': hashlib.sha256(cli.read_bytes()).hexdigest(), 'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
receipt = base / ('gate-' + head[:7] + '.json')
receipt.write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({'head': head, 'source': str(source), 'gate': str(receipt), 'immutable_cli': str(cli)}), flush=True)
with (base / ('gate-' + head[:7] + '.log')).open('wb') as output:
    result = subprocess.run(command, cwd=source, env=environment, stdout=output, stderr=subprocess.STDOUT)
record.update(exit_code=result.returncode, source_files_after=len(hashes()), source_preserved=hashes() == before, finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
receipt.write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record), flush=True)
raise SystemExit(result.returncode)
