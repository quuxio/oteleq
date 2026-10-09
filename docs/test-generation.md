# Test generation and retention

## Implemented slice

[Automatic generation](automatic-generation.md) creates deterministic scalar cases, diagnostic callers and a retained independent `unittest` suite for all eight languages. It implements explicit inventory gaps, two plain/two instrumented repetitions, supported state observations, replay and portable export. Factories, domain preconditions, property frameworks, action sequences and shrinking remain future work.

## Current workspace

`plan` creates a new private `oteleq-run-*` directory outside the application and otelc repositories. `--workspace-parent` selects its parent; the default uses a qualified operating-system temporary parent. Use the actual path printed by `plan`. The selected original source is copied, without writable hard links, into an immutable snapshot. Discovery, helpers and builds operate on private copies, and source identities are checked again.

```text
oteleq-run-<id>/
  .oteleq-owned.json
  plan.json                 # source/tool identities and full inventory
  snapshot/                 # selected immutable application contents
  generated-manifest.json   # generated suite/corpus content hashes
  README.txt
  tests/
    GENERATED-LICENSE.txt
    test_equivalence.py
    corpus.json
    harnesses/<case-id>/
  runs/replay-<id>/          # created by replay and the generated suite
  go-cache/                 # created when needed by the Go adapter
```

`generate` creates `tests/` once. Each runnable case receives frozen arguments and a diagnostic caller preview; every selected blocker becomes a failing generated test. Zero selected cases cannot yield a passing empty suite. `run` writes attempts and `report.json` into the requested new external report directory. `replay` and the generated suite retain attempts inside `runs/`; a replay result applies only to that named case, while the complete suite includes all selected blockers.

Builds use fresh per-attempt private project copies. Reports retain outputs, build logs, available native binary hashes, raw observations, runtime reports, OTLP captures and comparison bundles. The broader versioned graph protocol and per-language runner projects below are proposals; the current layout above is the implemented contract.

## Retention and cleanup

| User choice | Current result |
| --- | --- |
| Default successful or failed run | Workspace remains available; external reports remain at the selected path |
| `replay` or generated suite | A new retained case run under `runs/` |
| `export-tests` | Prints the copy plan without copying |
| `export-tests --apply` | Copies the frozen snapshot, suite, corpus, instructions and sealed plan into a new destination |
| `clean` | Explicitly removes the owned workspace after preservation checks |

There is no automatic successful-run deletion or `--keep-workspace` flag. Keep reports or export the suite before `clean`. Cleanup requires `.oteleq-owned.json`, rejects unknown top-level files and edited snapshots/suites, and does not require the original application or toolchain still to exist. It removes the owned workspace, including its internal replay evidence; independently stored external reports remain available.

## Optional incorporation into a repository

Use `export-tests --workspace PATH --destination PATH` to inspect the copy plan, then add `--apply` to perform it. The destination must be new and independent of the workspace. Choosing a new subdirectory in the application's repository explicitly incorporates the copied bundle; it does not edit existing tests, dependencies, manifests or locks.

The exported plan points at its copied immutable application snapshot and retains the original source provenance. Retained tests therefore continue testing that snapshot. Create a new plan for changed application code. Replay still requires the same qualified oteleq CLI, otelc adapters, Python environment and language tools; changed content identities fail. It is portable evidence with external toolchain requirements, rather than a standalone test of future source edits.

Generated boilerplate carries the MIT licence. Copied application source retains its licence; oteleq's maintained implementation is AGPL-3.0. See [repository quality](quality.md#implementation-quality). A richer promotion plan with fixture/dependency integration and baseline-only regression export remains proposed; `promote` is not implemented.

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
