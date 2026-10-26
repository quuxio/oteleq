"""Recheck both bounded all-language fixtures and recompute their comparisons."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'reviewed-source-03b9658/tests'))
import project_fixture_oracle as oracle


def read(path: Path):
    return json.loads(path.read_text())


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main() -> None:
    assert not sys.flags.optimize
    frozen = read(ROOT / 'freeze.json')
    cli = Path(frozen['cli'])
    assert digest(cli) == frozen['cli_sha256']
    seen, reports = set(), {}
    for name in ('added-smoke', 'added-after-promotion'):
        folder = ROOT / name
        assert (ROOT / (name + '.exit')).read_text().strip() == '0'
        records = [json.loads(line) for line in (folder / 'suite.stdout').read_text().splitlines()]
        assert len(records) == 9
        workspace = Path(records[0]['workspace'])
        plan = read(workspace / 'plan.json')
        assert plan['cli_sha256'] == frozen['cli_sha256']
        assert all(digest(Path(plan['source']) / path) == value for path, value in plan['source_manifest'].items())
        actual, cases = set(), set()
        for record in records[1:]:
            path = Path(record['report'])
            case, attempts = oracle.check_report(path, 'added')
            assert actual.isdisjoint(attempts) and case not in cases
            actual.update(attempts)
            cases.add(case)
            data = read(path)['cases'][0]
            bundle = path.parent / case / 'typed-bundle.json'
            result = subprocess.run([str(cli), 'compare-observations', str(bundle)], capture_output=True, check=False, timeout=30)
            assert result.returncode == 0 and not result.stderr and json.loads(result.stdout) == data['comparison']
            reports[str(path)] = digest(path)
        assert len(actual) == 32 and actual == set(read(folder / 'qualification.json')['attempts'])
        assert seen.isdisjoint(actual)
        seen.update(actual)
        physical = set()
        for parent, directories, files in os.walk(folder):
            directories[:] = [entry for entry in directories if entry != 'go-cache']
            if 'typed-observation.json' in files:
                physical.add(str(Path(parent).resolve()))
        assert physical == actual
    empty = ROOT / 'added-after-promotion'
    assert (empty / 'empty-before.exit').read_text().strip() == '1'
    initial = Path((empty / 'plan.stdout').read_text().strip())
    assert read(initial / 'tests/corpus.json') == []
    assert not any(entry['status'] in ('ready', 'blocked') for entry in read(initial / 'plan.json')['inventory'])
    assert len(seen) == 64 and len(reports) == 16
    result = {'status': 'verified', 'scope': 'Zero-argument callers/relocation, then genuine post-promotion discovery and empty-before refusal',
        'distinct_launches_verified': len(seen), 'typed_comparisons_recomputed': len(reports), 'reports': reports,
        'attempts': sorted(seen), 'original_preflight_failure_retained': True, 'full_project_qualification_complete': False}
    (ROOT / 'added-smokes-independent-review.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: value for key, value in result.items() if key not in ('reports', 'attempts')}, indent=2))


if __name__ == '__main__':
    main()
