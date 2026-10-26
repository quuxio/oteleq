"""Publish only completed final-head checks while leaving unfinished routes open."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent
text = (ROOT / 'pr-body-e765f0d.md').read_text()
before = '- Exact-commit local `make check`, tagged and untagged retained receiver corpora, the committed live workflow and hosted required checks are running. Do not interpret these as passing until their terminal results are recorded.'
after = '''- Exact-commit `make check` passes in 1,116.139 seconds, including 1,400 generation tests and 97.38% Rust product line coverage. All 572 source files and original file facts remain unchanged.
- The exact committed CLI passes the separate live builtin-shadow workload: 16 applications/eight SDK processes, all four startup states, 80 intermediate observations and 48 spans. The retained-only literal graph/tool audit checks every attempt plus eight altered-graph refusals. Source, SDK, application, tool, private weaver and CLI facts remain held. No extra applications are started by that audit.
- The focused 84-test group also passes on Python 3.14 against the committed frozen source.
- All three required hosted checks pass on e765f0d, Actions run `40140861832`.
- Tagged and untagged retained receiver corpora are still running. Full retained/live/promotion breadth and the corrected SDK full gate remain pending; do not interpret them as passing.'''
assert before in text
text = text.replace(before, after)
with (ROOT / 'pr-body-e765f0d-verified.md').open('x') as output:
    output.write(text)
