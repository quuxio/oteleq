"""Check this repository's locked dependencies against current OSV advisories."""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
import tempfile
import tomllib
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VERSION = '2.7.0'
SHA256 = {
    ('Darwin', 'arm64'): 'd4926ef8da134332543be276dff157e4c170f99ad91fc48e89448a8816bdf70b',
    ('Darwin', 'x86_64'): 'e82c5df7ab0a42dff29a1cd0660711447b56b4c0483ff66ad8634df10fd81a45',
    ('Linux', 'x86_64'): '160c6253e2922e9e0a6a9771c5c4c40a4b3c6090b34a3cdd5e80c96cc2e4218b',
    ('Linux', 'aarch64'): '4061ef4c021ed3c47f203b818f337e351336cc5cd67c0274fc36bd1dfc728dd7',
}
LOCKS = ('Cargo.lock', 'ci/requirements.txt', 'ci/markdownlint/package-lock.json')
MAX_LOCK_BYTES = 8 * 1024 * 1024
MAX_REPORT_BYTES = 32 * 1024 * 1024
MAX_TOOL_BYTES = 128 * 1024 * 1024


def file_facts(path: Path, limit: int) -> dict:
    """Refuse links and oversized inputs before reading or executing them."""
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or path.resolve(strict=True) != path
            or info.st_size > limit):
        raise ValueError('expected a bounded ordinary file: ' + str(path))
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for data in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(data)
    after = path.stat()
    if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError('file changed while reading: ' + str(path))
    return {'sha256': digest.hexdigest(), 'size': info.st_size, 'device': info.st_dev,
            'inode': info.st_ino, 'mode': info.st_mode, 'mtime_ns': info.st_mtime_ns, 'ctime_ns': info.st_ctime_ns}


def scanner(cache: Path) -> tuple[Path, str]:
    """Acquire only a fixed release with a separately pinned platform digest."""
    system, machine = platform.system(), platform.machine()
    key = system, machine
    if key not in SHA256:
        raise ValueError('OSV scanner is not pinned for this operating system/architecture')
    architecture = 'arm64' if machine in ('arm64', 'aarch64') else 'amd64'
    name = 'osv-scanner_' + system.lower() + '_' + architecture
    path = cache / (VERSION + '-' + name)
    if path.exists() or path.is_symlink():
        if file_facts(path, MAX_TOOL_BYTES)['sha256'] != SHA256[key]:
            raise ValueError('cached OSV scanner digest differs; inspect the named cached file')
        return path, SHA256[key]
    cache.mkdir(parents=True, exist_ok=True)
    url = 'https://github.com/google/osv-scanner/releases/download/v' + VERSION + '/' + name
    request = urllib.request.Request(url, headers={'User-Agent': 'oteleq-dependency-audit'})
    descriptor, temporary = tempfile.mkstemp(prefix='.osv-download-', dir=cache)
    temporary = Path(temporary)
    try:
        digest, size = hashlib.sha256(), 0
        with os.fdopen(descriptor, 'wb') as target, urllib.request.urlopen(request, timeout=120) as response:
            while data := response.read(1024 * 1024):
                size += len(data)
                if size > MAX_TOOL_BYTES:
                    raise ValueError('OSV scanner download exceeds the pinned artifact size bound')
                target.write(data)
                digest.update(data)
        if digest.hexdigest() != SHA256[key]:
            raise ValueError('downloaded OSV scanner digest differs from the pinned release')
        temporary.chmod(0o700)
        # Hard-link publication refuses an existing cache entry rather than replacing it.
        os.link(temporary, path)
        return path, SHA256[key]
    finally:
        temporary.unlink(missing_ok=True)


def expected_packages(root: Path) -> dict[str, set[tuple[str, str, str]]]:
    """Derive all three inventories independently of scanner output."""
    result = {}
    cargo = tomllib.loads((root / LOCKS[0]).read_text())
    if any(row.get('source') and row['source'] != 'registry+https://github.com/rust-lang/crates.io-index'
           for row in cargo['package']):
        raise ValueError('Cargo audit requires the declared crates.io registry bindings')
    result[LOCKS[0]] = {('crates.io', row['name'], row['version']) for row in cargo['package']}
    requirements = set()
    for line in (root / LOCKS[1]).read_text().splitlines():
        line = line.strip().removesuffix('\\').strip()
        if not line or line.startswith('#'):
            continue
        if re.fullmatch(r'--hash=sha256:[0-9a-f]{64}', line):
            continue
        match = re.fullmatch(r'([A-Za-z0-9_.-]+)==([^\s;\\]+)', line)
        if match is None:
            raise ValueError('Python audit requires fully pinned requirements without includes or markers')
        requirements.add(('PyPI', re.sub(r'[-_.]+', '-', match[1]).lower(), match[2]))
    result[LOCKS[1]] = requirements
    npm = json.loads((root / LOCKS[2]).read_text())
    packages = set()
    for location, row in npm['packages'].items():
        if not location:
            continue
        if row.get('link') or 'node_modules/' not in location or not row.get('version'):
            raise ValueError('unsupported npm package binding in locked audit inputs')
        name = row.get('name', location.rsplit('node_modules/', 1)[1])
        packages.add(('npm', name, row['version']))
    result[LOCKS[2]] = packages
    if set(result) != set(LOCKS) or any(not values for values in result.values()):
        raise ValueError('missing or empty locked dependency inventory')
    return result


def check_report(data: object, root: Path, expected: dict, exit_code: int) -> dict:
    """Incomplete scans, skipped packages and tool failures cannot report success."""
    if (type(exit_code) is not int or exit_code not in (0, 1)
            or type(data) is not dict or type(data.get('results')) is not list
            or set(expected) != set(LOCKS) or any(not values for values in expected.values())):
        raise ValueError('dependency scan did not complete successfully')
    observed, advisories = {}, set()
    for source in data['results']:
        if type(source) is not dict or type(source.get('source')) is not dict:
            raise ValueError('invalid dependency source evidence')
        path = Path(source['source'].get('path', ''))
        if source['source'].get('type') != 'lockfile' or not path.is_relative_to(root):
            raise ValueError('dependency scan returned an unrequested input source')
        name = path.relative_to(root).as_posix()
        if name not in expected or name in observed or type(source.get('packages')) is not list:
            raise ValueError('missing, duplicate or unrequested dependency input')
        packages = set()
        for row in source['packages']:
            if type(row) is not dict:
                raise ValueError('invalid dependency package evidence')
            package = row.get('package', {})
            if type(package) is not dict:
                raise ValueError('invalid dependency package identity')
            identity = tuple(package.get(key) for key in ('ecosystem', 'name', 'version'))
            if any(type(value) is not str or not value for value in identity):
                raise ValueError('dependency package has incomplete identity')
            packages.add(identity)
            vulnerabilities = row.get('vulnerabilities', [])
            if type(vulnerabilities) is not list:
                raise ValueError('invalid dependency advisory list')
            for vulnerability in vulnerabilities:
                identifier = vulnerability.get('id') if type(vulnerability) is dict else None
                if type(identifier) is not str or not identifier:
                    raise ValueError('dependency advisory has no identity')
                advisories.add(identifier)
        observed[name] = packages
    if observed != expected:
        raise ValueError('dependency scan did not account for the complete locked package inventory')
    if bool(advisories) != bool(exit_code):
        raise ValueError('dependency scanner exit code disagrees with advisory evidence')
    return {'manifests': {name: len(values) for name, values in expected.items()},
            'package_versions': sum(map(len, expected.values())), 'advisories': sorted(advisories)}


def run(root: Path, output: Path, tool_cache: Path) -> tuple[dict, int]:
    """Retain one new scan and preserve all lock bytes and file identity facts."""
    root = root.resolve(strict=True)
    before = {name: file_facts(root / name, MAX_LOCK_BYTES) for name in LOCKS}
    expected = expected_packages(root)
    executable, digest = scanner(tool_cache)
    output.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix='scan-', dir=output))
    configuration = folder / 'empty-osv-scanner.toml'
    configuration.write_text('')
    report = folder / 'osv.json'
    argv = [str(executable), 'scan', 'source', '--no-ignore', '--no-resolve', '--all-packages',
            '--format=json', '--output-file=' + str(report), '--config=' + str(configuration),
            *['--lockfile=' + str(root / name) for name in LOCKS]]
    (folder / 'command.json').write_text(json.dumps(argv, indent=2) + '\n')
    (folder / 'identity.json').write_text(json.dumps({
        'scanner_version': VERSION, 'scanner_sha256': digest, 'inputs_before': before}, indent=2) + '\n')
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(('GH_', 'GITHUB_', 'SONAR_', 'AWS_'))}
    environment.update(XDG_CACHE_HOME=str(folder / 'cache'),
                       OSV_SCANNER_LOCAL_DB_CACHE_DIRECTORY=str(folder / 'cache'))
    with (folder / 'stdout').open('wb') as stdout, (folder / 'stderr').open('wb') as stderr:
        result = subprocess.run(argv, cwd=root, env=environment, stdout=stdout, stderr=stderr, timeout=180)
    (folder / 'exit').write_text(str(result.returncode) + '\n')
    if {name: file_facts(root / name, MAX_LOCK_BYTES) for name in LOCKS} != before:
        raise ValueError('dependency scanner changed original locked input files')
    file_facts(report, MAX_REPORT_BYTES)
    checked = check_report(json.loads(report.read_text()), root, expected, result.returncode)
    summary = {'scanner_version': VERSION, 'scanner_sha256': digest, 'inputs': before,
               **checked, 'checked_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'report_directory': str(folder),
               'scope': 'Current OSV advisories for these three locked repository inventories. '
                        'Target applications, external SDK/toolchains and unknown vulnerabilities are outside this scan.'}
    (folder / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return summary, result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/dependency-audit')
    parser.add_argument('--tool-cache', type=Path, default=ROOT / 'build/tools/osv-scanner')
    args = parser.parse_args()
    try:
        summary, code = run(ROOT, args.output.resolve(), args.tool_cache.resolve())
        print(json.dumps(summary))
        return code
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        print('dependency audit: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
