"""Dependency audits require complete inventories, verified tools and intact inputs."""

import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ci import dependency_audit as audit


def fixture(root: Path) -> dict:
    """Make three fixed parser inputs without installing their declared packages."""
    (root / 'ci/markdownlint').mkdir(parents=True)
    (root / audit.LOCKS[0]).write_text('version=4\n[[package]]\nname="crate"\nversion="1.2.3"\n')
    (root / audit.LOCKS[1]).write_text('# pinned\nDemo_Pkg==2.3.4 \\\n --hash=sha256:' + 'a' * 64 + '\n')
    (root / audit.LOCKS[2]).write_text(json.dumps({'packages': {'': {},
        'node_modules/package': {'version': '3.4.5'},
        'node_modules/@scope/name': {'version': '4.5.6'}}}))
    return {audit.LOCKS[0]: {('crates.io', 'crate', '1.2.3')},
            audit.LOCKS[1]: {('PyPI', 'demo-pkg', '2.3.4')},
            audit.LOCKS[2]: {('npm', 'package', '3.4.5'), ('npm', '@scope/name', '4.5.6')}}


def report(root: Path, packages: dict) -> dict:
    """Encode OSV's per-lockfile schema from independently supplied identities."""
    return {'results': [
        {'source': {'path': str(root / name), 'type': 'lockfile'},
         'packages': [{'package': dict(zip(('ecosystem', 'name', 'version'), item))} for item in sorted(values)]}
        for name, values in packages.items()]}


class DependencyAuditTests(unittest.TestCase):
    def test_lock_inventories_are_independent_and_python_versions_are_pinned(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            expected = fixture(root)
            self.assertEqual(audit.expected_packages(root), expected)
            for value in ('-r other.txt', 'pkg>=1', 'pkg==1; python_version>"3"', '--index-url=https://example.invalid'):
                (root / audit.LOCKS[1]).write_text(value)
                with self.subTest(value=value), self.assertRaises(ValueError):
                    audit.expected_packages(root)
            (root / audit.LOCKS[1]).write_text('pkg==1\n')
            for row in ({'link': True, 'version': '1'}, {}):
                (root / audit.LOCKS[2]).write_text(json.dumps({'packages': {'node_modules/item': row}}))
                with self.assertRaises(ValueError):
                    audit.expected_packages(root)
            (root / audit.LOCKS[2]).write_text('{"packages":{}}')
            with self.assertRaises(ValueError):
                audit.expected_packages(root)

    def test_zero_advisories_requires_every_manifest_and_package(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); expected = fixture(root)
            original = report(root, expected)
            result = audit.check_report(original, root, expected, 0)
            self.assertEqual(result['package_versions'], 4)
            self.assertEqual(result['manifests'], {name: len(values) for name, values in expected.items()})
            self.assertEqual(result['advisories'], [])
            for value in (None, [], {}, {'results': []}, {'results': original['results'][:-1]}):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    audit.check_report(value, root, expected, 0)
            for mutation in ('duplicate-source', 'outside-source', 'wrong-type', 'missing-package', 'wrong-version'):
                changed = copy.deepcopy(original)
                if mutation == 'duplicate-source':
                    changed['results'].append(changed['results'][0])
                elif mutation == 'outside-source':
                    changed['results'][0]['source']['path'] = str(root.parent / 'Cargo.lock')
                elif mutation == 'wrong-type':
                    changed['results'][0]['source']['type'] = 'directory'
                elif mutation == 'missing-package':
                    changed['results'][0]['packages'].pop()
                else:
                    changed['results'][0]['packages'][0]['package']['version'] = '9.9.9'
                with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                    audit.check_report(changed, root, expected, 0)
            for code in (1, 2, -9):
                with self.assertRaises(ValueError):
                    audit.check_report(original, root, expected, code)

    def test_advisory_identity_and_exit_status_must_agree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); expected = fixture(root)
            changed = report(root, expected)
            package = changed['results'][0]['packages'][0]
            package['vulnerabilities'] = [{'id': 'RUSTSEC-2020-0071'}]
            self.assertEqual(audit.check_report(changed, root, expected, 1)['advisories'], ['RUSTSEC-2020-0071'])
            with self.assertRaises(ValueError):
                audit.check_report(changed, root, expected, 0)
            for value in (None, {}, [{}], [{'id': ''}], [{'id': 42}]):
                package['vulnerabilities'] = value
                with self.assertRaises(ValueError):
                    audit.check_report(changed, root, expected, 1)
            package.pop('vulnerabilities')
            package['package']['name'] = None
            with self.assertRaises(ValueError):
                audit.check_report(changed, root, expected, 0)

    def test_download_digest_and_cached_tool_are_verified_before_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); raw = b'verified test executable'
            digest = hashlib.sha256(raw).hexdigest()
            with patch.object(audit.platform, 'system', return_value='Darwin'), \
                 patch.object(audit.platform, 'machine', return_value='arm64'), \
                 patch.dict(audit.SHA256, {('Darwin', 'arm64'): digest}), \
                 patch.object(audit.urllib.request, 'urlopen', return_value=io.BytesIO(raw)) as network:
                path, observed = audit.scanner(root / 'tools')
                self.assertEqual(observed, digest)
                self.assertEqual(path.read_bytes(), raw)
                self.assertEqual(path.stat().st_mode & 0o777, 0o700)
                self.assertEqual(audit.scanner(root / 'tools'), (path, digest))
                self.assertEqual(network.call_count, 1)
                path.write_bytes(b'changed')
                with self.assertRaises(ValueError):
                    audit.scanner(root / 'tools')
            self.assertEqual(list((root / 'tools').glob('.osv-download-*')), [])

    def test_unsupported_platform_bad_digest_and_oversized_download_refuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            with patch.object(audit.platform, 'system', return_value='Windows'), self.assertRaises(ValueError):
                audit.scanner(root / 'unsupported')
            for limit in (2, 1000):
                with patch.object(audit.platform, 'system', return_value='Darwin'), \
                     patch.object(audit.platform, 'machine', return_value='arm64'), \
                     patch.object(audit, 'MAX_TOOL_BYTES', limit), \
                     patch.object(audit.urllib.request, 'urlopen', return_value=io.BytesIO(b'incorrect artifact')), \
                     self.assertRaises(ValueError):
                    audit.scanner(root / str(limit))
                self.assertEqual(list((root / str(limit)).glob('*')), [])

    def test_input_limits_and_links_refuse_before_scanning(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); path = root / 'data'; path.write_bytes(b'abc')
            facts = audit.file_facts(path, 3)
            self.assertEqual(facts['sha256'], hashlib.sha256(b'abc').hexdigest())
            with self.assertRaises(ValueError):
                audit.file_facts(path, 2)
            link = root / 'alias'; link.symlink_to(path)
            with self.assertRaises(ValueError):
                audit.file_facts(link, 100)

    def test_scan_publishes_complete_new_evidence_and_preserves_locks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); expected = fixture(root)
            before = {name: audit.file_facts(root / name, 10000) for name in audit.LOCKS}
            def execute(argv, **kwargs):
                output = Path(next(value.removeprefix('--output-file=') for value in argv if value.startswith('--output-file=')))
                output.write_text(json.dumps(report(root, expected)))
                kwargs['stderr'].write(b'completed scanner')
                return SimpleNamespace(returncode=0)
            with patch.object(audit, 'scanner', return_value=(Path('/verified/osv'), 'a' * 64)), \
                 patch.object(audit.subprocess, 'run', side_effect=execute) as process:
                summary, code = audit.run(root, root / 'outputs', root / 'tools')
                self.assertEqual(code, 0)
                self.assertEqual(summary['inputs'], before)
                self.assertEqual(summary['package_versions'], 4)
                self.assertEqual(summary['scanner_sha256'], 'a' * 64)
                self.assertIn('--no-resolve', process.call_args.args[0])
                self.assertIn('--all-packages', process.call_args.args[0])
                self.assertEqual(sum(value.startswith('--lockfile=') for value in process.call_args.args[0]), 3)
                self.assertTrue((Path(summary['report_directory']) / 'summary.json').is_file())
                identity = json.loads((Path(summary['report_directory']) / 'identity.json').read_text())
                self.assertEqual(identity['inputs_before'], before)
            self.assertEqual({name: audit.file_facts(root / name, 10000) for name in audit.LOCKS}, before)

    def test_changed_inputs_and_cli_errors_cannot_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); fixture(root)
            def mutate(argv, **kwargs):
                (root / audit.LOCKS[0]).write_text('changed')
                return SimpleNamespace(returncode=0)
            with patch.object(audit, 'scanner', return_value=(Path('/verified/osv'), 'a' * 64)), \
                 patch.object(audit.subprocess, 'run', side_effect=mutate), self.assertRaises(ValueError):
                audit.run(root, root / 'output', root / 'tools')
        with patch.object(sys, 'argv', ['dependency-audit']), patch.object(audit, 'run', side_effect=ValueError('incomplete')), \
             patch.object(sys, 'stderr', new_callable=io.StringIO) as output:
            self.assertEqual(audit.main(), 2)
            self.assertIn('incomplete', output.getvalue())
        with patch.object(sys, 'argv', ['dependency-audit']), patch.object(audit, 'run', return_value=({'complete': True}, 0)), \
             patch.object(sys, 'stdout', new_callable=io.StringIO) as output:
            self.assertEqual(audit.main(), 0)
            self.assertEqual(json.loads(output.getvalue()), {'complete': True})

    def test_timeout_and_empty_expected_inventory_remain_incomplete(self):
        with patch.object(sys, 'argv', ['dependency-audit']), \
             patch.object(audit, 'run', side_effect=subprocess.TimeoutExpired(['scanner'], 180)), \
             patch.object(sys, 'stderr', new_callable=io.StringIO):
            self.assertEqual(audit.main(), 2)
        with self.assertRaises(ValueError):
            audit.check_report({'results': []}, Path('/repository'), {}, 0)
