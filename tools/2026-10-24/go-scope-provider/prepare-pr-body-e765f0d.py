"""Keep the existing draft PR's claims aligned with its new committed head."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent
text = (ROOT.parent / 'go-live-controls/pr-body-b2eebdb.md').read_text()
text = text.replace('## Evidence\n', '''The explicit `source-scope-v1` backend now adds private-bootstrap-v1 and separate build6/7/prepared-tools2. The consumer independently authenticates the complete official upstream module catalogue and exact single-file backport, retains native metadata queries before caller discovery, and reconstructs all private helpers and compiler evidence. The maintained receiver qualifier covers this explicit profile through generated/framework/export/replay/reduction routes. Older source-v1/build4/5 formats keep their original requirements.

## Current head: e765f0d

- Published as `quuxio`, commit author `quux.io`; worktree clean.
- Independent exact-head code review is clear, with 60 selected tests passing and all 572 indexed files held unchanged. Review record SHA256: `9e44a61f42468a7f7323f07fd88eb52b4a02bfcc0d1f4a1dd07369820e9f2481`.
- The latest focused group passes 84 tests. The earlier complete Go component run passes 225 tests; its source snapshot remains separately identified.
- A frozen uncommitted development experiment passes 16 applications/eight SDK processes, all four metric startup states, 80 intermediate observations and 48 trace spans, including seven legal builtin shadows. A separate literal graph/tooling audit checks every repeat/lane and rejects eight altered-graph controls. All source, SDK, weaver source, tool and CLI facts remain held. This is development evidence, not exact-commit qualification.
- Exact-commit local `make check`, tagged and untagged retained receiver corpora, the committed live workflow and hosted required checks are running. Do not interpret these as passing until their terminal results are recorded.
- SDK `eda9fcc` runtime/source wire inputs remain fixed. Its original full gate failed because a test combined resource-release and observed-GC spans. The test-only correction is SDK `2481cfe`; its corrected full gate remains pending.
- Published Go private-bootstrap and qualification instructions have been inspected in GitHub Preview at this exact head.

## Earlier evidence\n''', 1)
text = text.replace('- Current `b2eebdb`:', '- Previous `b2eebdb`:')
before = 'Independent final delta review and full generated/retained qualification for the changed recipes remain open. Required checks must stay green on the eventual delivery head. The new scope-safe SDK candidate requires separate versioned consumer integration and review; existing build-4/5 semantics are unchanged. The older candidate\'s application-builtin limitations remain attached to its evidence. This PR stays a draft. The full 21-area/eight-language completion boundary remains unchanged.'
after = 'The exact e765f0d code delta is independently reviewed. Full final-head generated/retained/tagged/live qualification and the corrected SDK full gate remain open. Required hosted checks must pass on the eventual delivery head. The older candidate\'s application-builtin and temporary-frontend limitations remain attached to its evidence. This PR stays a draft. The full 21-area/eight-language completion boundary remains unchanged.'
assert before in text
text = text.replace(before, after)
with (ROOT / 'pr-body-e765f0d.md').open('x') as output:
    output.write(text)
