# Delivery roadmap

## Current status

Updated 20 October 2026. The [Rust byte-channel comparator](workload-comparison.md) is implemented with repeated-lane, source-identity, incomplete-evidence and telemetry-witness checks. [Fixed diagnostic captures](eight-language-capture.md) execute real otelc function workloads for all eight languages, Python tasks, Python/Java executor context, the fixed Python collection lifetime corpus and optional native TypeScript emission. The [scalar generator](automatic-generation.md) implements syntax inventories, frozen scalar corpora, independent bounded execution, supported state observers, strict blockers, a retained `unittest` suite, replay, export and explicit cleanup across all eight languages. [Scalar shrinking](counterexample-shrinking.md) adds declared-domain candidate reduction with retained replay evidence; richer relational/object/sequence contracts remain open. Explicit [Python source-package roots](python-package-context.md) support regular and `src` layouts with retained source/function binding; installed-project/build metadata and imported-root observation remain open. Declared [plain Python/JavaScript/TypeScript receivers](receiver-fixtures.md) support independent constructors/functions, instance state and own class data roots, including awaited Node method completion; [Ordered Node receiver calls/release](ordered-sequences.md) add intermediate graphs and bounded Node collection observations, including the explicit [TypeScript emitter/provider gate](typescript-collection.md); broader factories, other actions and cross-language sequences remain open. [Published qualification](quality.md#published-qualification) records actual execution, mutation detection, coverage and final provider identities.

[Declared filesystem fixtures](filesystem-effects.md) now supply independent seeded roots and bounded bytes/kinds/permissions for the generated runners; transient events, network protocols and broader resource effects remain open.

The [completion checklist](completion.md) tracks the full-project goal and remaining acceptance evidence. The stages below are the broader delivery plan, not a claim that generation or state observation is still wholly unimplemented. They remain incomplete where they require semantic/build-aware discovery, arbitrary receiver/factory fixtures, language-native property frameworks, richer generated object/factory codecs or production qualification. Current export and [standalone HTML/JUnit presentation](reporting.md) are delivered; richer fixture/build integration during promotion remains proposed. See [adoption priorities](adoption.md) for the next practical increments.

The application targets equivalence over tested inputs and recorded observations. Each stage is complete only when its concrete acceptance evidence is published against the exact implementation revision. An early slice does not imply complete language coverage.

## Stage 1: Rust contracts and paired executor

Implement configuration/plan validation, external workspace ownership, typed corpus and observation contracts, bounded subprocess execution, comparison and JSON reporting. Use small controlled fixtures to qualify the core before adopting arbitrary repositories.

Acceptance requires:

- Matching returns/state/effects derive a scoped equivalence verdict; identical returns with differing receiver/global mutations derive a difference.
- Graph cycles/aliasing, big integers, signed-zero/NaN encoding, initial-state mismatch, transient-write limits, opaque roots and truncation are handled correctly.
- Both variants consume the same concrete inputs and independent fixture state; failing control repeats derive inconclusive results.
- Crashes, timeouts, harness errors, missing messages, zero cases and missing instrumentation witness cannot pass.
- Workspace creation/cleanup cannot overwrite source or unrelated paths, including symlink and ownership cases; cleanup occurs only after durable export.
- A retained replay bundle reproduces a known difference without random search.
- Rust formatting, Clippy, focused regression tests and measured core coverage pass; coverage is published with an explicit scope.

## Stage 2: Python and actual otelc execution

Deliver the first complete slice using Rust orchestration, Python semantic discovery, pytest/Hypothesis generation, independent CPython workers and a pinned real otelc launcher. Implement receiver/module-state observers, controlled async/generator fixtures, a bounded OTLP decoder and instrumentation witness.

Acceptance includes plain and telemetry-on execution, declared off controls, same-output/different-mutation detection, generated domain-invalid input handling, private workspace preservation and runnable retained tests. Record unsupported object/scheduler cases. Add at least one exact production-workload comparison alongside the unit harness evidence.

## Stage 3: JavaScript and TypeScript

Implement separate language capabilities with shared Node execution/graph codecs, `node:test`/fast-check, ESM/CommonJS package-context handling and TypeScript compiler/type/source-map integration. Preserve undefined, bigint, sparse arrays, reference aliases, promises and declared yield/completion boundaries.

Acceptance includes loader selection/witness, constructors and mutable receivers, valid async fixtures, TypeScript emission provenance, unsupported construct reporting and an independent transient framework project. Both language IDs must pass the common qualification suite.

## Stage 4: C and C++

Deliver Clang/build-aware discovery, cmocka/Catch2 harnesses, valid native fixtures and typed observers, matched otelc LLVM wrapping and build inspection. Qualify optional native fuzz corpus discovery separately.

Acceptance includes typed buffers/aliasing, observable globals, internal-linkage access limits, exceptions, constructor/resource sequences, distinct C++ overload/template instances and no padding/uninitialised-memory comparison. Validate production artefact identity separately from helper/fuzz/sanitised builds. Publish exact ABI, compiler and platform qualification.

## Stage 5: Java

Deliver classpath/module-aware inventory, private JUnit/jqwik test project, receiver/static graph codecs, independent JVM workers and pinned otelc bytecode-agent integration.

Acceptance includes factories/interfaces, constructor/exception identity, module encapsulation diagnostics, executor/completion fixtures and loaded-class/agent provenance. Extra reflection/open-module flags remain visible harness/diagnostic deltas.

## Stage 6: Go and Rust

Explicit [Go module roots](go-package-context.md) now provide active package/type discovery, private library/main callers, sibling scalar state and fixed build tags. Broader Go fixtures, fuzz bridges, cgo/workspace recipes and receiver codecs remain open.

Deliver Go package/type discovery, private same-package tests and fuzz-to-typed-corpus bridges, plus Rust Cargo/type-aware discovery, external/private harnesses and proptest integration. Their ownership, panic, package/global state and build-variant contracts have independent qualifications.

Acceptance includes unchanged module/manifests/locks, unexported/private access limits, explicit generic instances, panic/defer/recover or unwind/drop scenarios, supported goroutine/async fixtures and witnessed otelc overlay/compiler-wrapper execution. No unsafe fabricated fixtures or unsupported backend substitutions.

## Stage 7: Full-language release qualification

All eight adapters pass the same shared qualification suite. Standalone HTML/JUnit presentation of generated-run evidence is implemented. Typed generated scalar/graph results retain contracts and field differences. Complete richer codecs, redaction, promotion plans and apply operations, production-workload replay and qualified optional telemetry-failure/live-toggle scenarios. Validate installation and a usable multi-language repository demonstration.

Release requires:

- Every current otelc language ID has implemented discovery, generated execution, scoped observations, witness and replay with declared limits.
- The supported compiler/runtime/platform matrix is explicit and tested; publish native macOS ARM64 and Linux x86-64/ARM64 results only where they actually run.
- Mixed-language repositories use one run plan with per-component build graphs and declared service fixtures; unsupported build edges remain visible.
- Promoted/retained tests run from their documented location without requiring original source changes or the target's existing framework.
- The complete selected inventory and observation coverage are shown beside all passing cases; default strict CI fails on gaps.
- Functional and performance/resource evidence have separate gates. Shipping-artefact evidence names the actual files and hashes tested.
- Dependencies are pinned/scanned; credentials remain external; CI and real code-analysis badges reference the final implementation commit.
- README, help, examples, design/status records and release assets agree with implemented behaviour.

## Continuing support

Requalify an adapter when otelc, a compiler/runtime, a test framework or a value codec changes its relevant semantics. Keep concrete failing cases as regressions and rerun the paired corpus on both build variants. A new otelc language requires a design/capability update and qualified adapter before complete compatibility is claimed.
