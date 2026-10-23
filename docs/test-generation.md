# Test generation and retention

## Implemented slice

[Automatic generation](automatic-generation.md) creates deterministic scalar cases, diagnostic callers and a retained independent `unittest` suite for all eight languages. It implements explicit inventory gaps, configured repeated plain/instrumented execution (at least two each), supported state observations, replay and portable export. Explicit scalar domain cases and seeded budgets are configured through [the project policy](automatic-generation.md#project-policy-and-concrete-fixtures). [Scalar shrinking](counterexample-shrinking.md) uses declared independent domains and retains its original/trial/final evidence. Declared [plain Python/Java/JavaScript/TypeScript receiver fixtures](receiver-fixtures.md) retain fixed construction inputs through generated tests, export, replay and scalar method-argument shrinking. [Go receiver fixtures](go-receivers.md) likewise preserve same-package scalar construction inputs and private source graphs. General object factories, inferred or arbitrary application preconditions, property frameworks and broader action sequences remain future work.

[Ordered receiver calls and Node calls/release](ordered-sequences.md) retain intermediate typed state. C++ has a [call-only source receiver profile](cpp-receivers.md#ordered-calls), with [149-launch diagnostic qualification](qualification/cpp-sequences-2026-10-23.json). Java supports call-only sequences on one declared receiver, including explicit [live metric states](java-metric-controls.md) through the prepared provider. Release/object collection and asynchronous Java actions remain open. [Declared filesystem fixtures](filesystem-effects.md) add independent seeded data and required whole-worker boundary channels across all eight runners; generated/exported suites, replay and scalar shrinking preserve those declarations. [Scripted HTTP fixtures](http-fixtures.md) add bounded required request/response channels with independent response state and a matched per-case URL. Broader action sequences and general network/resource effects remain incomplete.

## Current workspace

The Python call-only sequence implementation retains intermediate receiver graphs and checks source bindings around each call. It is [under qualification](ordered-sequences.md#python-calls-under-qualification); existing published Python receiver evidence retains its single-call scope. Component checks alone do not qualify the new instrumentation/retained routes.

[Declared independent scalar domains](domain-generation.md) can generate concrete case values without a literal `cases` list. Planning freezes the requests in the inventory, and retained suites consume those values. Existing explicit case lists keep their values and order. Declared [numeric argument preconditions](numeric-preconditions.md) constrain generation and scalar shrinking, including fixed ordered calls. General application predicates and richer argument/factory generation remain open.

The [exact-revision domain corpus](qualification/domain-generation-2026-10-22.json) checks 30 functions and 82 initial cases through all four direct/framework/detached routes, then frozen replay, reduction and seeded inputs: 1,384 actual launches. Its two deliberate differences per full route remain failures in generated unittest and JUnit output. Fourteen refused domain contracts cannot become passing empty suites.

The separate [numeric-precondition corpus](qualification/numeric-preconditions-2026-10-22.json) checks 20 functions and 54 initial cases through 912 distinct launches, including Java/Node ordered calls, all four retained routes, frozen replay and relation-preserving reduction. Twenty-four invalid contracts refuse before application execution. Its three intentional differences remain failures; three excluded constructors are separately visible in HTML/JUnit.

[Declared scalar return values](expected-returns.md) optionally check an independently known result in every baseline repeat and declared sequence call. Equal results that violate the fixture expectation remain blocked. The same contract is retained by generated suites, replay, export and scalar shrinking.

`plan` creates a new private `oteleq-run-*` directory outside the application and otelc repositories. `--workspace-parent` selects its parent; the default uses a qualified operating-system temporary parent. Use the actual path printed by `plan`. The selected original source is copied, without writable hard links, into an immutable snapshot. Discovery, helpers and builds operate on private copies, and source identities are checked again.

```text
oteleq-run-<id>/
  .oteleq-owned.json
  plan.json                 # source/tool identities, resolved policy and full inventory
  snapshot/                 # selected immutable application contents
  generated-manifest.json   # generated suite/corpus content hashes
  README.txt
  tests/
    GENERATED-LICENSE.txt
    test_equivalence.py
    corpus.json
    harnesses/<case-id>/
  runs/replay-<id>/          # created by replay and the generated suite
  go-cache/build/           # private compiler cache when Go is used
  go-cache/modules/         # private module cache reused within this workspace
```

`generate` creates `tests/` once. Each runnable case receives frozen arguments and a diagnostic caller preview; every selected blocker becomes a failing generated test. Zero selected cases cannot yield a passing empty suite. `run` writes attempts and `report.json` into the requested new external report directory. `replay` and the generated suite retain attempts inside `runs/`; a replay result applies only to that named case, while the complete suite includes all selected blockers.

Builds use fresh per-attempt private project copies. Go retains both executables and their build/recipe/module evidence under each report attempt, separately from its reused workspace caches. Reports retain outputs, build logs, available native binary hashes, raw observations, runtime reports, OTLP captures and comparison bundles. The broader versioned graph protocol and per-language runner projects below are proposals; the current layout above is the implemented contract.

Explicit [Java source/dependency context](java-project-context.md) additionally retains generated source roots and ordered private JAR/class/resource copies through replay, export and shrinking. Prepared-provider capability probes are sealed and carried with the exported workspace; edited probes refuse replay or cleanup.

Java also retains [compiler-owned source/class bindings](java-build-bundles.md), the exact frontend, JDK module-image identity, class products and a prepared-application manifest. Its fixed UTF-8 classpath profile disables annotation processing; arbitrary project/module builds remain unsupported.

Node attempts also retain [original/private/caller module context](node-source-context.md), including actual loader formats, package hashes and bounded prelaunch inspection output. The selected application is replaced with empty source during each inspection; these tooling processes do not execute application code.

## Retention and cleanup

| User choice | Current result |
| --- | --- |
| Default successful or failed run | Workspace remains available; external reports remain at the selected path |
| `replay` or generated suite | A new retained case run under `runs/` |
| `export-tests` | Prints the copy plan without copying |
| `export-tests --apply` | Copies the frozen snapshot, suite, corpus, instructions and sealed plan into a new destination |
| `promote` | Prints the current-source suite's file plan without copying |
| `promote --apply` | Creates a sealed independent entrypoint which generates fresh current-source cases on each discovery |
| `clean` | Explicitly removes the owned workspace after preservation checks |

There is no automatic successful-run deletion or `--keep-workspace` flag. Keep reports or export the suite before `clean`. Private snapshot and generated-suite checks include every directory and file, including cache/build names that were excluded from the original source snapshot. Added files or symlinks in those private trees invalidate replay and refuse cleanup; they are not silently discarded as caches. If another runner imports the generated test module, disable Python bytecode writes to avoid adding a cache to the frozen suite. Use `-B` with isolated Python mode; `PYTHONDONTWRITEBYTECODE=1` also works in a non-isolated interpreter.

Cleanup requires `.oteleq-owned.json`, rejects unknown top-level files, unsealed plans/suites and edited snapshots/suites, and does not require the original application or toolchain still to exist. It removes the owned workspace, including its internal replay evidence; independently stored external reports remain available.

Java runtime-archive cleanup checks the sealed private context, dependency bytes and retained probe files. Execution and detached replay separately require the known selected JDK. Removing or upgrading that JDK therefore permits cleanup of an unchanged owned workspace while preventing replay with unavailable or changed tools. The [cleanup qualification](qualification/java-cleanup-2026-10-22.json) retains failing-before/passing-after CLI evidence, detached replay and preservation controls.

## Optional incorporation into a repository

Use `export-tests --workspace PATH --destination PATH` to inspect the copy plan, then add `--apply` to perform it. The destination must be new and independent of the workspace. Choosing a new subdirectory in the application's repository explicitly incorporates the copied bundle; it does not edit existing tests, dependencies, manifests or locks.

Later plans [verify and exclude owned retained bundles](retained-source-selection.md), including their copied sources and access helpers. Unknown, edited or unsealed contents remain visible errors. The plan and execution report retain the exclusion scope; ordinary application changes still require a new plan.

The exported plan points at its copied immutable application snapshot and retains the original source provenance. Retained tests therefore continue testing that snapshot. Create a new plan for changed application code. Replay still requires the same qualified oteleq CLI, otelc adapters, Python environment and language tools; changed content identities fail. It is portable evidence with external toolchain requirements, rather than a standalone test of future source edits.

Use [current-source promotion](current-source-tests.md) to keep a reusable suite for future source changes. `promote --workspace PATH --source PATH --destination PATH` prints its six-file plan; add `--apply` to create it. Each discovery makes a fresh private snapshot and per-case unittest suite with the frozen policy and tool/provider context. An in-repository suite locates its source relative to itself; an external suite requires `OTELEQ_SOURCE`. Verified bundles are excluded from later inventory, and changed/unowned content remains an error.

Generated boilerplate carries the MIT licence. Copied application source retains its licence; oteleq's maintained implementation is AGPL-3.0. See [repository quality](quality.md#implementation-quality). Richer fixture/dependency integration, native property frameworks and baseline-only regression promotion remain proposed.

## Broader generation design

The following contracts describe future capabilities beyond scalar generation. They do not provide current configuration keys or extra CLI flags.

### Generation contract

Plan a test entry for every discovered function in the selected source/build context. A runnable test requires a valid caller, valid input strategy, independent fixture initialisation and an observation contract. Where any of these is missing, generate a visible inventory/gap entry and an actionable fixture request. Never manufacture a passing empty assertion or count a generated file as executed coverage.

Types are useful for generating primitive values, but they do not establish business preconditions. A string might represent an account identifier; an integer might be a port or a buffer length. The generator needs explicit contracts or factories for those meanings. Invalid baseline executions remain recorded and do not count as equivalence evidence.

### Input sources

| Source | Use |
| --- | --- |
| Compiler/runtime types and signatures | Primitive domains, enum cases, valid container shapes and nullable contracts |
| Constants and branch conditions | Candidate boundary values such as empty, minimum/maximum and adjacent values |
| Existing examples, fixtures or recorded inputs | Optional domain-valid seed cases with provenance |
| User factories and preconditions | Opaque types, receivers, resource handles, dependent interfaces and semantic constraints |
| Property generators and fuzzing | Bounded exploration and repeatable shrinking within a declared valid domain |
| Action-sequence models | Constructors/method calls, caches, stateful updates, close/drop and async progression |

Generate edge cases deterministically before seeded exploration. Prefer local deterministic generation. AI-assisted fixture proposals can be an optional later feature, but they require compilation, baseline validity and review like any other generated case; they cannot establish expected results or a proof.

### One corpus for all lanes

Materialise generated inputs and action sequences once, including concrete generic instantiations and fixture specifications. Every lane consumes the same case IDs and values. Do not run independent random property loops against each build and compare their aggregate pass counts.

The framework can ask the paired executor to evaluate a candidate case. Corpus discovery and shrinking must respect adapter protocol limits and independent process state. Record generator/framework versions, settings and seed, but retain concrete values because a seed alone may stop reproducing after a dependency upgrade.

A property asserts that baseline and required instrumented observations match. It does not ask an AI to guess the correct return value. Separate domain invariants can validate a fixture or baseline, but equivalence still permits a bug shared by both variants and says nothing about general business correctness.

Build dependencies through fixture factories, then reconstruct the same specification independently for each worker. A fixture can supply a fake database or clock when configured; the report states that dependency was simulated and does not imply real-service equivalence.

### Difference reduction

When a stable difference is found, shrink values and action sequences while preserving preconditions, fixture independence and the same required lanes. Confirm each reduced case with the stability controls. If reduction changes the build/observation contract, it is a different experiment and does not replace the original evidence.

Keep original and reduced inputs, case IDs, expected/observed paths, raw observations and exact build identities. A replay command must reproduce the difference from the retained bundle without needing a particular random search outcome.
