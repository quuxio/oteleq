# Ordered receiver and collection observations

Declared receiver fixtures can execute an ordered sequence of calls to the selected method, followed by release and optional collection. Each case reconstructs its receiver independently in each process. The typed contract records every requested action and its required roots; missing, reordered or unobserved actions cannot become passing skips.

```toml
schema_version = 1
languages = ["javascript"]

[functions]
include = ["sample.Counter.add"]

[[fixtures]]
function = "sample.Counter.add"
cases = [[7]]
receiver = { factory = "Counter", arguments = [10] }
sequence = [
  { action = "call", arguments = "case" },
  { action = "call", arguments = [2] },
  { action = "release" },
  { action = "collect", gc_rounds = 64, settle_turns = 4 },
]
```

At least one call uses the concrete case arguments. Other calls can have independently declared finite scalar inputs. Calls to the selected ordinary async method are awaited. Every call retains before/outcome/after graphs; a temporary mutation can be a difference even when the last result and final state agree. A later action's changed starting state is an observed sequence difference, rather than a mismatched initial fixture. Initial construction still requires matching starting fixtures.

Call steps can declare `expected_baseline` using the existing return/error contract. Otherwise a case-argument call inherits the fixture expectation and a fixed-argument call expects a return. Unexpected intermediate baseline errors block the case even if a later call succeeds. The case's outer outcome is its last call outcome. Scalar shrinking preserves the declared construction and action schedule while reducing every use of the case arguments; it does not shrink action order or fixed inputs.

## Release and collection

`release` clears the harness's strong receiver reference. Returned-receiver graphs contain encoded values, so a captured alias does not intentionally keep that receiver alive. Application globals, class data, caches or closures can still retain the object; the harness does not change them.

`collect` is an explicit test control. The worker uses the selected Node runtime with `NODE_OPTIONS=--expose-gc`, a native weak reference and bounded event-loop turns. It never calls an application replacement for `gc` or `WeakRef.deref`. `gc_rounds` is 1 through 256 and defaults to 64; `settle_turns` is 1 through 16 and defaults to four. These controls are frozen in the plan and retained per attempt. Production instrumentation does not force collection.

An observed collection is a boundary event. The actual retry count remains raw evidence and is excluded from typed equality; neither GC timing nor lifetime duration is required to match. If collection is not observed within the requested bound, the step has an explicit gap and the result is incomplete. This is not evidence of a leak. Incomplete or censored SDK lifetime observations also remain explicit nonzero witness losses.

For JavaScript/TypeScript, the provider selects the exact declared class for collection lifetimes. Source factories also become selected creation calls: the lifetime root must link to the actual factory span. Direct source constructors have no selected creation function and require an unlinked collection root. Method roots must match the declared calls, recursion remains inside those roots, and construction cannot invoke the selected method. Telemetry retains real span identities, class/instance attributes, counters and transport diagnostics; no source or telemetry is normalised.

## Current boundaries

The generator supports the existing ordinary JavaScript/TypeScript receiver profile. Call/release sequences use those supported source bindings and codecs. Collection additionally requires a separately qualified lifetime-capable provider. [TypeScript collection](typescript-collection.md) freezes the source/native emitter and requires the provider's explicit public capability response before application execution. Explicit CommonJS `.cjs`/`.cts` receiver callers use the real module wrapper and require an unshadowed `require` binding. General Node package/build contexts remain open.

The bounded sequence has 1 through 32 steps: calls first, at most one release, then at most one final collection. Other method targets, scheduler/yield/iteration actions, resource-close actions, arbitrary object arguments, inherited/private/native receiver state and the other language runners require further adapter work. The common ordered typed protocol is shared across all language IDs; unavailable requested generators remain named blockers.

Generated and exported suites retain the concrete schedule and all intermediate observations. Raw collection telemetry is checked separately from application state and exact stdout/stderr. This remains **equivalence over these tests and observations**, with diagnostic callers rather than shipping artefact proof. Actual provider/toolchain qualification is separate from unit and plain-worker coverage.

Run the maintained actual corpus with `make generation-sequence-otelc OTELC_ROOT=/absolute/path/to/qualified/otelc REPORT_DIR=/private/tmp/new-sequence-qualification`. It exercises both Node language IDs, JavaScript ESM/CommonJS collection and creation links, intermediate mutation restored before the final boundary, declared errors, user finalizers, retained-object incompleteness, generated/exported suites and scalar replay. Exact revisions and actual results must be recorded separately from the implementation checks.

## Published qualification

The [20 October record](qualification/ordered-sequences-2026-10-20.json) names runtime `2cf56e1` and the frozen `c65a35c` provider on macOS ARM64/Node24.21. The maintained eight-case corpus completed 148 actual launches: six cases matched, the transient-state control differed, and the application-retained receiver remained inconclusive. Generated/exported suites, scalar shrinking and replay retained those outcomes. Six altered-evidence controls and one changed-source refusal passed. Source inputs were preserved. All 332 local regressions and exact-runtime remote checks passed; Rust product line coverage was 97.29%.

This qualification covers JavaScript ESM/CommonJS collection, source factories, ordinary async methods, encoded returned aliases and an application finalizer, plus TypeScript source-emitter calls/release. This earlier record does not qualify the separately gated [TypeScript collection emitters](typescript-collection.md#published-qualification) or other language sequences.
