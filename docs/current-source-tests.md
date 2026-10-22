# Keep a suite for the current checkout

`promote` creates a small independent Python `unittest` entrypoint for an application. Each discovery inventories the current source, makes a fresh external snapshot and exposes the generated per-case tests and selected blockers to the framework. It uses the same supported eight-language adapters, observation contracts, private workers and strict comparisons as ordinary generation.

## Review and create the suite

Start with a generated workspace from the qualified CLI and provider you intend to keep using. Its resolved policy supplies selections, fixtures, expected outcomes, build context and budgets.

Use Python 3.12 or newer for the independent entrypoint. The target application keeps its existing framework and dependencies.

```sh
"$OTELEQ_CLI" promote --workspace "$OTELEQ_WORKSPACE" \
  --source /absolute/path/to/application \
  --destination /absolute/path/to/application/equivalence-tests
```

This prints the destination and proposed files without copying. Add `--apply` to create the new directory. Existing destinations are refused. The command does not edit application files, dependencies, manifests, lockfiles or the existing test framework.

```sh
"$OTELEQ_CLI" promote --workspace "$OTELEQ_WORKSPACE" \
  --source /absolute/path/to/application \
  --destination /absolute/path/to/application/equivalence-tests --apply
python3 -I -B /absolute/path/to/application/equivalence-tests/test_equivalence.py
```

An in-repository suite finds the application relative to its own directory, so the checkout can move. For a suite kept outside the application, identify the current source explicitly on each run:

```sh
OTELEQ_SOURCE=/absolute/path/to/current/application \
  python3 -I -B /absolute/path/to/external-tests/test_equivalence.py
```

Use `python3 -I -B -m unittest discover -s /absolute/path/to/equivalence-tests` for discovery. Isolated mode prevents ambient Python import roots from becoming tooling inputs; `-B` prevents Python caches inside the sealed bundle. Such a cache is an unexpected file and prevents planning. An existing test runner's own setup remains outside the captured application observations.

## What is kept

The six files are `.oteleq-owned.json`, `project.json`, `project-policy.toml`, `test_equivalence.py`, `README.txt` and `GENERATED-LICENSE.txt`. They contain boilerplate, the resolved policy, tool identities and original source provenance. Application source is copied into each new private run workspace.

The policy is frozen at promotion, including earlier CLI selection overrides. Each run applies it to the current checkout. Changed bodies and newly discovered supported functions are tested. New unsupported selected functions remain failing tests. A failed plan, a changed tool context or empty discovery becomes a failing preparation test.

Every run prints its new workspace path and retains preparation receipts, concrete inputs and actual observations. Successful runs also retain their data. Use the existing replay/report tools within their documented source/tool identity contract; original source changes can invalidate an earlier run's replay. Create a new current-source run to test the changed application.

## Frozen context and limits

The CLI, adapter-host identity, resolved policy and tool/provider artefact contents must match the promotion context. Tool paths remain provenance; their bytes are bound by the artefact records. `OTELEQ_CLI` can relocate identical CLI bytes; `OTELEQ_PYTHON` selects the matching adapter environment. A changed provider, selected tool content or language set requires a fresh plan and reviewed promotion. Application/build inputs receive new recorded identities on each plan. This is a new experiment rather than silent use of an incompatible retained suite.

`OTELEQ_WORKSPACE_PARENT` selects an existing external run parent. It cannot be inside the application or provider. Preparation uses the CLI's existing per-tool limits. Workers retain their normal wall-time/output limits and process cleanup. The same trusted local execution boundary applies; this is not a hostile-code sandbox.

Verified promoted bundles are excluded from later source inventory and snapshots. Ownership checks require all six files, exact known boilerplate, content hashes and the validated policy identity. Unknown, edited, missing or linked content remains a visible error. Explicit build inputs inside a bundle are refused. `clean --workspace PATH` removes an unchanged owned suite when explicitly requested; it does not edit the application.

General build systems, richer fixtures, additional graph codecs, native property frameworks and baseline-only regression promotion remain open. Promotion does not expand an adapter's language or observation capability. Its result remains **equivalence over these tests and observations**.

## Qualification status

The [22 October exact-revision qualification](qualification/current-source-tests-2026-10-22.json) completes 936 main application launches and a separate 20-launch preliminary preflight on frozen runtime `1f47c46` and legacy provider `d6d03b7`. Original and changed-body routes each test 20 functions/53 cases; checkout relocation and additions test 28 functions/61 cases; the external suite adds one deliberate Python instrumentation-sensitive function for 29 functions/62 cases. New zero-argument functions are discovered in every language. The final route has 61 matches and one expected stable return difference. Ten prelaunch controls refuse missing, changed, linked, foreign or empty inputs without application execution.

Independent review checks all 956 distinct launches, complete literal graphs, raw channels and server response records, then recomputes all 239 retained typed comparisons. All 7,360 provider input records, eleven links and eight external tool identities remain unchanged. The 30,430 accepted raw evidence records are sealed separately from rebuildable Go caches. Final HTML/JUnit are browser-reviewed: 62 executed cases, one deliberate failure, zero errors and four explicit exclusions. Local validation passes 884 distinct regressions and 97.38% Rust product line coverage. These results qualify the recorded diagnostic profiles, not broader providers, projects or platforms.

Component regressions also cover dry runs, apply, strict ownership, tool/provider identity, source-contained run parents, output errors and empty discovery. Both promotion modules have separate 80% line-coverage floors. Earlier development and incomplete experiments remain separately retained.

The maintained corpus is `make generation-project-tests-otelc OTELC_ROOT=/absolute/path/to/qualified/otelc REPORT_DIR=/absolute/path/to/new-evidence PYTHON=/absolute/path/to/qualified/python`. It first checks declared Java/Node sequences, a non-BMP Python argument and an escaped ASCII control character, then tests original and changed bodies, newly added functions, a moved checkout, standard unittest discovery and an external suite with a deliberate result difference. Its independent oracle checks complete literal graphs and every repeat. `GENERATION_ARGS=--preflight-only` runs only the small preflight; that result does not qualify the full matrix. Started operations and actual exit receipts are retained; incomplete stages must be inspected before any new execution.

The corpus checks [server response records](automatic-generation.md#reports-replay-and-retention) against every retained OTLP body. These timestamps and write results are diagnostic server evidence, separate from the required runtime/exporter health and decoded instrumentation witness. An earlier retained Python export failure remains incomplete; later successful experiments do not establish its original cause.

The maintained policy explicitly allows 600000 ms for each [Go prepare/build command](go-build-bundles.md#build-settings-and-runtime-controls), retaining the ordinary 60000 ms application launch limit. Independent review checks all 208 recorded prepare/build commands across 104 Go attempts. The default build budget remains 180000 ms. An earlier 180-second Go build timeout is retained as incomplete evidence before application launch. The new experiment does not silently retry that failed build or establish its underlying cause.
