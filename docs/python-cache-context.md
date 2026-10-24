# Python cache context integration

<!-- markdownlint-disable MD013 -->

Status: the explicit prepared cache route is implemented; actual generated-workflow qualification is in progress. The independent reader, private input catalogue, prepared transport and selected-input checks use journal 3. The separately qualified source-only route retains its existing contract. A cache binding does not establish that cached code came from the current source file.

```toml
[adapters.python]
backend = "prepared"
profile = "python-native-cache-origins-v3"
```

Use a matching pinned SDK candidate and complete interpreter environment. Missing protocols, changed inputs, unknown cache roots and incomplete execution evidence refuse the run. This candidate has no completed generated cache-workflow qualification record yet.

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

## Qualification still required

Use actual ordinary, checked-hash and unchecked-hash caches on both recorded Python runtimes. Cover unchanged cache use, invalid/stale cache source fallback, receivers/factories, exceptions, recursion, file/HTTP effects and retained/promoted/reduced routes. Include changed cache/source/file facts and equal-but-unrelated cache bytes as refusal controls. Preserve original failures and count actual applications separately from copied or re-audited observations.

This work advances the full [completion checklist](completion.md). It remains **equivalence over these tests and observations**, with shipping artefacts and broader language/build acceptance separate.
