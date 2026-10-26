"""Apply the strengthened maintained checker without relaunching applications."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / 'maintained-checkers'), str(ROOT / 'consumer/tests'),
               str(ROOT / 'consumer/examples'), str(ROOT / 'consumer/adapters/generation')]
import qualify_cpp_receivers as qualification


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


reports = attempts = 0
for path in sorted((ROOT / 'actual').rglob('report.json')):
    parts = path.relative_to(ROOT / 'actual').parts
    if any(part.startswith('refusal-') for part in parts):
        continue
    cases = json.loads(path.read_text())['cases']
    attempts += (qualification.check_bindings(path, len(cases)) if parts[0] in ('bindings', 'crlf')
                 else qualification.check_report(path, len(cases))[0])
    reports += 1
assert reports == 50 and attempts == 328
result = {'reports': reports, 'retained_attempts': attempts, 'application_relaunches': 0,
          'complete_expected_state_values_and_empty_application_output': True,
          'maintained_qualifier_sha256': digest(Path(qualification.__file__)),
          'verification_script_sha256': digest(Path(__file__)),
          'raw_manifest_sha256': digest(ROOT / 'raw-manifest.json'),
          'scope': 'Supplemental maintained checker; original runtime/source archive remains unchanged.'}
(ROOT / 'maintained-checker-verification.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result), flush=True)
