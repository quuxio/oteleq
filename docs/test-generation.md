# Test generation and retention

## Implemented slice

[Automatic generation](automatic-generation.md) now creates deterministic scalar cases, diagnostic callers and a retained independent `unittest` suite for all eight languages. It implements explicit inventory gaps, two plain/two instrumented repetitions, supported state observations, replay and portable export. Factories, domain preconditions, property frameworks, action sequences and shrinking described below remain future work.

## Broader design

## Generation contract

Plan a test entry for every discovered function in the selected source/build context. A runnable test requires a valid caller, valid input strategy, independent fixture initialisation and an observation contract. Where any of these is missing, generate a visible inventory/gap entry and an actionable fixture request. Never manufacture a passing empty assertion or count a generated file as executed coverage.

Types are useful for generating primitive values, but they do not establish business preconditions. A string might represent an account identifier; an integer might be a port or a buffer length. The generator needs explicit contracts or factories for those meanings. Invalid baseline executions remain recorded and do not count as equivalence evidence.

## Input sources

| Source | Use |
| --- | --- |
| Compiler/runtime types and signatures | Primitive domains, enum cases, valid container shapes and nullable contracts |
| Constants and branch conditions | Candidate boundary values such as empty, minimum/maximum and adjacent values |
| Existing examples, fixtures or recorded inputs | Optional domain-valid seed cases with provenance |
| User factories and preconditions | Opaque types, receivers, resource handles, dependent interfaces and semantic constraints |
| Property generators and fuzzing | Bounded exploration and repeatable shrinking within a declared valid domain |
| Action-sequence models | Constructors/method calls, caches, stateful updates, close/drop and async progression |

Generate edge cases deterministically before seeded exploration. Prefer local deterministic generation. AI-assisted fixture proposals can be an optional later feature, but they require compilation, baseline validity and review like any other generated case; they cannot establish expected results or a proof.

## One corpus for all lanes

Materialise generated inputs and action sequences once, including concrete generic instantiations and fixture specifications. Every lane consumes the same case IDs and values. Do not run independent random property loops against each build and compare their aggregate pass counts.

The framework can ask the paired executor to evaluate a candidate case. Corpus discovery and shrinking must respect adapter protocol limits and independent process state. Record generator/framework versions, settings and seed, but retain concrete values because a seed alone may stop reproducing after a dependency upgrade.

A property asserts that baseline and required instrumented observations match. It does not ask an AI to guess the correct return value. Separate domain invariants can validate a fixture or baseline, but equivalence still permits a bug shared by both variants and says nothing about general business correctness.

Build dependencies through fixture factories, then reconstruct the same specification independently for each worker. A fixture can supply a fake database or clock when configured; the report states that dependency was simulated and does not imply real-service equivalence.

## Generated workspace

Create a new private directory outside the target source tree. The default is a unique operating-system temporary directory with owner-only access. If the user supplies a directory, create a new owned run subdirectory; refuse an existing non-owned workspace and resolve symlinks before deciding that paths are outside the source tree.

```text
oteleq-run-<id>/
  owner.json
  plan.json
  inventory.json
  source-snapshot/
  generated/
    c/ cpp/ rust/ python/ java/ javascript/ typescript/ go/
  fixtures/
  corpus/
  dependencies/
  builds/
    baseline/ instrumented-off/ instrumented-on/
  observations/
  telemetry/
  reports/
  replay/
```

`owner.json` identifies the run and workspace format. Cleanup is limited to that owned workspace and never follows arbitrary symlinks or deletes a parent/source directory. Tests, dependency caches, coverage output and compiler writes stay there. The snapshot records selected original contents and build-relevant assets; no hard-linked writable source copies.

Some build systems require generated helper files inside a package/module. Put those files into a private copy under `source-snapshot/` or into an explicitly qualified overlay, never the original checkout. The report records any helper/access/manifest delta. Run builds against the snapshot to avoid mutation by build scripts; original source hashes are still verified at completion.

## Retention choices

| User choice | Result |
| --- | --- |
| Default transient run | Export a durable evidence report to the requested report directory, then remove successful-run workspaces |
| Failure/incomplete run | Preserve workspace and replay artefacts by default and print their path |
| `--keep-workspace` | Preserve generated tests and all configured replay/build evidence even after success |
| Explicit promotion | Copy the chosen tests, fixtures, corpus and runner instructions into a destination selected by the user |

Transient cleanup happens only after the durable report/export succeeds. Source/build identities and concrete test cases needed to interpret the report remain in that bundle according to its stated retention scope. `clean` is an explicit operation for retained workspaces.

## Optional incorporation into a repository

`promote` first creates a copy plan listing destination paths, runner/dependency requirements, fixture changes and any unresolved private-access requirements. The user applies that plan explicitly. Refuse conflicting destination files by default; do not overwrite existing tests or edit the application's manifests/lockfiles automatically.

Promoted files include a self-contained README, pinned dependency declarations for their test environment, seed corpus, fixture contracts, generated test provenance and replay instructions. Standalone equivalence tests require the oteleq executor and both build recipes. An optional exported baseline regression form stores typed expected observations and clearly identifies its source/build origin; it cannot compare instrumentation on its own.

A private generated helper may not be directly portable into an existing repository's test directory. Promotion must say so and provide the external/private-build instructions, rather than insert an uncompilable test or silently change visibility. Users can retain an independent test project beside their existing framework.

## Difference reduction

When a stable difference is found, shrink values and action sequences while preserving preconditions, fixture independence and the same required lanes. Confirm each reduced case with the stability controls. If reduction changes the build/observation contract, it is a different experiment and does not replace the original evidence.

Keep original and reduced inputs, case IDs, expected/observed paths, raw observations and exact build identities. A replay command must reproduce the difference from the retained bundle without needing a particular random search outcome.
