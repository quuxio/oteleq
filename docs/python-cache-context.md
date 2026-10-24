# Python cache context integration

<!-- markdownlint-disable MD013 -->

Status: implementation in progress. The independent data reader accepts explicit journal 3 and its cache-return route. The generated prepared provider still accepts only its qualified input/source profiles. Cache framing alone does not enable generated execution or establish that cached code came from the current source file.

## Preserved contracts

The default reader stays on journal 2. A caller must request version 3; mixed records and format substitution refuse. Cache route 3 binds an earlier loader `.pyc` read to its separate executing `.py` filename. Its flags are zero and optimisation 3 means unknown, not a source compiler invocation. Source routes 1/2 retain their compiler flags and optimisation checks. Graph, first-execution and SDK-join checks remain bounded and data-only.

The source-only selector refuses journal 3. Public profile negotiation, prepared recipes and generated workers must each opt into the new contract after cache input preservation and selected-code checks exist. Provider metadata cannot enable it implicitly.

## Required build and selection boundary

The complete integration must:

- Freeze existing ordinary source-loader cache bytes and file facts in a bounded caller-owned catalogue before launch. Retain the source filename separately; never infer that a cache was compiled from its current bytes.
- Preserve source timestamps needed by ordinary timestamp-cache validation in private snapshots and attempts. Do not delete caches, force recompilation or change application/dependency files.
- Preserve the cache catalogue through generated execution, replay, detached export, shrinking and current-source promotion. Promotion must discover the current source/cache inputs afresh.
- Bind every selected cache-return execution to the independently frozen consumed cache read, declared callable identity and actual SDK code joins in both lanes. A source fallback requires the existing independent source/compiler relation.
- Check actual loader decisions, cache/source preservation, process ownership, raw journals, observations, both OTLP signals and final health separately. Report cache-bound and source-compiler-bound selection distinctly.
- Keep unsupported loaders, sourceless inputs, dependency closure, async/resource actions and per-action attribution visible.

## Qualification still required

Use actual ordinary, checked-hash and unchecked-hash caches on both recorded Python runtimes. Cover unchanged cache use, invalid/stale cache source fallback, receivers/factories, exceptions, recursion, file/HTTP effects and retained/promoted/reduced routes. Include changed cache/source/file facts and equal-but-unrelated cache bytes as refusal controls. Preserve original failures and count actual applications separately from copied or re-audited observations.

This work advances the full [completion checklist](completion.md). It remains **equivalence over these tests and observations**, with shipping artefacts and broader language/build acceptance separate.
