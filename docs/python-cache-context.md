# Python cache context integration

<!-- markdownlint-disable MD013 -->

Status: the explicit prepared cache route has [488-launch exact-revision diagnostic qualification](qualification/python-generated-caches-2026-10-24.json) on Python 3.12/3.14. The independent reader, private input catalogue, prepared transport and selected-input checks use journal 3. The separately qualified source-only route retains its existing contract. A cache binding does not establish that cached code came from the current source file.

```toml
[adapters.python]
backend = "prepared"
profile = "python-native-cache-origins-v3"
```

Use the matching pinned SDK and complete interpreter environment identified in the record. Missing protocols, changed inputs, unknown cache roots and incomplete execution evidence refuse the run. The actual SDK is frozen `ce4cf74`; a separate static bridge verifies identical consumed Python/native/builder input bytes and modes at candidate `e8e5861`. That bridge starts no applications and does not claim new binary execution.

## Preserved contracts

The default reader stays on journal 2. A caller must request version 3; mixed records and format substitution refuse. Cache route 3 binds an earlier loader `.pyc` read to its separate executing `.py` filename. Its flags are zero and optimisation 3 means unknown, not a source compiler invocation. Source routes 1/2 retain their compiler flags and optimisation checks. Graph, first-execution and SDK-join checks remain bounded and data-only.

The source-only selector refuses journal 3. Cache selection requires explicit profile-3 intent and a caller-owned cache catalogue, including an explicitly empty catalogue for source fallback. Public profile negotiation and the fixed native `--origin-loader-caches-root` recipe must agree. Provider metadata cannot enable it implicitly.

## Implemented build and selection boundary

The route checks:

- Freeze existing ordinary source-loader cache bytes and file facts in a bounded caller-owned catalogue before launch. Retain the source filename separately; never infer that a cache was compiled from its current bytes.
- Preserve source timestamps needed by ordinary timestamp-cache validation in private snapshots and attempts. Do not delete caches, force recompilation or change application/dependency files.
- Preserve the cache catalogue through generated execution, replay, detached export, shrinking and current-source promotion. Promotion must discover the current source/cache inputs afresh.
- Bind every selected cache-return execution to the independently frozen consumed cache read, declared callable identity and actual SDK code joins in both lanes. A source fallback requires the existing independent source/compiler relation.
- Check actual loader decisions, cache/source preservation, process ownership, raw journals, observations, both OTLP signals and final health separately. Report cache-bound and source-compiler-bound selection distinctly.
- Keep unsupported loaders, sourceless inputs, dependency closure, async/resource actions and per-action attribution visible.

The plan seals source-associated cache bytes and original file facts outside the application snapshot. Source timestamps and modes survive private snapshots so ordinary timestamp-cache validation can make its original decision. Cache files are materialised beside the private sources and frozen again before launch. Replay, export and reduction retain the sealed context; promotion plans the current source/cache pair afresh. After execution, original inputs, private bytes/file facts and every observed cache root are rechecked. Every selected match reports `source-compiler` or `cache-read`; an unchecked-hash cache can legitimately contain older code, and the route does not label that a compilation of the current source.

The generated observer freezes the expected target and source factory bodies through the ordinary `SourceFileLoader.get_code` decision before executing their module. This operation is confined to the owned private copy and requires bytecode writes disabled. It can use an accepted cache or fall back to source without replacing cache files. The selected qualified name, declaration line and bound code must still match. Native input-to-code evidence independently checks the actual executing body and consumed bytes; the helper's expected code is not a substitute for that evidence. Source-only profiles retain direct source compilation for their expected body.

## Recorded qualification and reproduction

Maintainers can reproduce the complete diagnostic workflow corpus with the portable driver. It creates its own application fixtures and uses a matching owned SDK copy. The default `all` component covers the ordinary-loader matrix, package receivers/factories, recursion, exceptions, filesystem/HTTP effects, replay, unittest, detached suites, reduction and fresh current-source promotion:

```sh
make generation-python-cache-workflows-otelc \
  PYTHON=/path/to/complete/python/environment/bin/python \
  OTELC_ROOT=/path/to/owned/otelc-copy \
  REPORT_DIR=/new/external/cache-workflow-evidence
```

Use `GENERATION_ARGS='--component receivers'` or `GENERATION_ARGS='--component effects'` for a new individual corpus. Retained-only audits require a separate new output directory, preserve the original operation/process records and do not repeat target applications or deliberate input mutations:

```sh
/path/to/complete/python/environment/bin/python -B \
  tests/qualify_python_cached_workflows.py \
  --otelc-root /path/to/owned/otelc-copy \
  --cli /path/to/original/quux-oteleq \
  --report-dir /path/to/original/cache-workflow-evidence \
  --recheck --audit-dir /new/external/cache-workflow-audit
```

Pass the same `--component` when auditing an individual corpus. Source/cache facts, historical source bodies, full raw/typed graphs, exact command receipts, consumed-input/code joins, ownership, health, decoded OTLP and every comparison are checked separately. Copied shrink originals remain observations of earlier launches and are not counted as new applications.

The maintained ordinary-loader corpus uses an independent scalar return and complete raw/typed graph oracle in every repeat and lane. It captures literal source/cache facts before planning, retains native/SDK/health/OTLP evidence and recomputes each comparison. It covers timestamp, checked-hash and unchecked-hash caches, an accepted older unchecked body, missing/stale caches and invalid-magic fallback. Use a matching owned SDK copy and a new external output directory:

```sh
make generation-python-caches-otelc \
  PYTHON=/path/to/complete/python/environment/bin/python \
  OTELC_ROOT=/path/to/owned/otelc-copy \
  REPORT_DIR=/new/external/cache-loader-evidence
```

Re-audit retained evidence without starting new applications by invoking `tests/qualify_python_caches.py` with the same `--otelc-root`, `--report-dir`, `--cli` and `--recheck`. This corpus alone does not qualify receivers, effects, retained suites or promotion.

The record contains 244 actual applications and 122 SDK processes per runtime, with 48 reports and 62 recomputed comparisons. Its 496 retained observations across both runtimes include 8 copied shrink originals; these add no launches. Twelve deliberate input changes were refused before another application started. Ten altered comparison controls check incomplete or differing evidence. Raw journals, final health and decoded OTLP are checked separately from outcomes. Coverage measured the qualifier host; application, native and SDK launch commands had no coverage startup.

The original timestamp preservation and older cache body failures remain recorded with their fixes. The failed audit and recipe count checks also remain in the record. Other loaders, dependency closure, async/resources, live controls, invocation attribution and shipping workloads require new qualification. Missing or unobserved dimensions cannot be treated as equality.

This work advances the full [completion checklist](completion.md). It remains **equivalence over these tests and observations**, with shipping artefacts and broader language/build acceptance separate.
