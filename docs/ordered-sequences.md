# Ordered receiver and collection observations

Declared Python, C++, Java, JavaScript and TypeScript receiver fixtures can execute an ordered sequence of calls to the selected method. Node receivers additionally support release and optional collection. Each case reconstructs its receiver independently in each process. The typed contract records every requested action and its required roots; missing, reordered or unobserved actions cannot become passing skips.

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

The explicit Node source provider also implements [live metric schedules](node-metric-controls.md), with separate [696-launch qualification](qualification/node-metric-controls-2026-10-23.json) for positive-first calls. These schedules contain only calls, with an explicit collection/emission state for every call. They cannot combine release/collection actions with metric controls.

## C++ call sequences

The [C++ source receiver profile](cpp-receivers.md#ordered-calls) accepts call-only schedules on one independently constructed receiver. Its version-two native envelope retains every intermediate source-bound graph and requires consistent outer boundaries. The worker streams steps within the shared capture budget. Actual decoded telemetry must retain the declared number of serial selected root trees, including complete recursive descendants. The [149-launch recorded corpus](qualification/cpp-sequences-2026-10-23.json) qualifies this diagnostic profile on the pinned provider/toolchain. Release, collection, metric controls and broader resource/concurrent actions remain unavailable.

## Java call sequences

Use the existing [Java receiver profile](java-receivers.md), including permitted private constructor/factory/method access. Add a call-only schedule to its fixture:

```toml
sequence = [
  { action = "call", arguments = "case" },
  { action = "call", arguments = [2] },
]
```

One JVM and one constructed receiver execute the complete schedule per repeat. Each call retains every declared receiver, scalar argument and own-static root before and after execution, plus its result/error graph. Returned aliases, source arrays and cycles use the same closed Java codecs. The outer `before` is the first call's starting graph; its `outcome` and `after` come from the last call. The version-two receiver envelope must contain every declared step in order and agree with those outer boundaries. Missing state, reordered actions and unsupported codecs cannot qualify.

Both `legacy` and explicit `prepared` providers require one independent selected root tree per declared call. Recursion may add spans within each tree. Prepared mode additionally requires cumulative call/duration metrics to finish at the total decoded selected-span count, and final health to match actual PID and exports. This is still a named-tree witness; it does not attribute an individual span to a particular action using the [proposed invocation API](action-witness.md). Construction/startup calls and other side effects need their own qualified witness scope.

Prepared Java calls can declare [live metric collection/emission states](java-metric-controls.md), using private host checkpoints and direct receipt. This does not add release or object collection. Java release, collection, asynchronous schedules, other method targets and resource actions remain named blockers. Identity is local to each graph; the profile does not establish allocation identity across calls. Filesystem/HTTP observations cover the whole worker rather than each intermediate call. All steps share the existing case time/output budgets.

Run `make generation-java-sequence-otelc JAVA_BACKEND=prepared OTELC_ROOT=/absolute/frozen/sdk REPORT_DIR=/new/external/evidence` for the maintained actual-provider corpus. Select `JAVA_BACKEND=legacy` with the matching earlier provider for compatibility qualification. The corpus checks complete independently expected intermediate graphs, private factories, expected intermediate errors, recursive trees and a state difference restored before the final boundary. It exercises generated/detached-exported suites, per-case replay, scalar shrinking and altered-evidence refusals. Implementation tests alone do not qualify another provider or platform.

## Python call sequences

Declared plain Python receivers can generate 1 through 32 call-only steps on one independently constructed instance. Each step retains its own concrete scalar arguments, before/outcome/after graphs, receiver aliases, declared module globals and own-static roots. An explicitly expected supported exception does not prevent the later calls from running. The whole-case boundaries must equal the first step's before and the final step's outcome/after; missing, reordered or substituted steps fail capture.

The caller pins the original reconstructed class and rechecks it and the method before and after each call without application attribute lookup. Replacing both the module's class binding and the instance's class together still refuses capture, even when names and method code are copied. Rebound method bodies, instance method shadows and unsupported storage also refuse capture. Single-call callers keep their existing execution recipe. Serial telemetry must retain the declared independent root trees, complete drain and zero loss; bounded queue/request headroom does not waive the existing byte/time budgets.

The [150-launch diagnostic corpus](qualification/python-sequences-2026-10-23.json) qualifies this profile on the recorded CPython/provider. It checks complete independently expected raw and typed graphs through direct/framework, per-case replay, detached/exported and reduced routes. Five methods match; an intentional intermediate mutation differs even though its final return and state match. The separate 81-launch single-call compatibility corpus checks every declared value and alias. Release/collection, asynchronous Python actions, arbitrary targets and mutable object arguments remain unavailable through this sequence generator.

Explicit prepared origin/cache profiles additionally support [live metric schedules](python-metric-controls.md), with a collection/emission state on every call and a positive both-on call in the schedule. The [3,008-launch diagnostic matrix](qualification/python-metric-controls-2026-10-24.json) covers Python 3.12.15/3.14.8, both profiles and all four initial states, including source constructors/factories, recursion/errors and generated/retained/promoted workflows. This separate evidence does not change the earlier legacy provider's control limits.

`make generation-python-sequence-otelc OTELC_ROOT=/absolute/frozen/provider REPORT_DIR=/new/external/evidence` runs the maintained six-method package corpus. Its separate literal oracles specify every raw and typed field, argument, static/global root, alias and expected exception. The corpus requires direct/framework and detached/exported routes, per-case replay, scalar reduction, one/32-call positives, oversized-observation and coordinated class-rebinding refusals, and altered-evidence/source controls. `tests/qualify_python_sequences.py --recheck` verifies retained evidence without launching applications. The publication records the executed runtime and the later shared verifier separately; its retained-only recheck starts no new applications.

## Release and collection

`release` clears the harness's strong receiver reference. Returned-receiver graphs contain encoded values, so a captured alias does not intentionally keep that receiver alive. Application globals, class data, caches or closures can still retain the object; the harness does not change them.

`collect` is an explicit test control. The worker uses the selected Node runtime with `NODE_OPTIONS=--expose-gc`, a native weak reference and bounded event-loop turns. It never calls an application replacement for `gc` or `WeakRef.deref`. `gc_rounds` is 1 through 256 and defaults to 64; `settle_turns` is 1 through 16 and defaults to four. These controls are frozen in the plan and retained per attempt. Production instrumentation does not force collection.

An observed collection is a boundary event. The actual retry count remains raw evidence and is excluded from typed equality; neither GC timing nor lifetime duration is required to match. If collection is not observed within the requested bound, the step has an explicit gap and the result is incomplete. This is not evidence of a leak. Incomplete or censored SDK lifetime observations also remain explicit nonzero witness losses.

For JavaScript/TypeScript, the provider selects the exact declared class for collection lifetimes. Source factories also become selected creation calls: the lifetime root must link to the actual factory span. Direct source constructors have no selected creation function and require an unlinked collection root. Method roots must match the declared calls, recursion remains inside those roots, and construction cannot invoke the selected method. Telemetry retains real span identities, class/instance attributes, counters and transport diagnostics; no source or telemetry is normalised.

## Current boundaries

Python, C++ and Java support their call-only profiles above. Node call/release sequences use the existing ordinary JavaScript/TypeScript receiver bindings and codecs. Collection additionally requires a separately qualified lifetime-capable provider. [TypeScript collection](typescript-collection.md) freezes the source/native emitter and requires the provider's explicit public capability response before application execution. Explicit CommonJS `.cjs`/`.cts` receiver callers use the real module wrapper and require an unshadowed `require` binding. General Node package/build contexts remain open.

The bounded sequence has 1 through 32 steps: calls first, then Node-only release and optional final collection. Other method targets, scheduler/yield/iteration actions, resource-close actions, arbitrary object arguments, unsupported inherited/private/native receiver state and the remaining language runners require further adapter work. The common ordered typed protocol is shared across all language IDs; unavailable requested generators remain named blockers.

Generated and exported suites retain the concrete schedule and all intermediate observations. Raw collection telemetry is checked separately from application state and exact stdout/stderr. This remains **equivalence over these tests and observations**, with diagnostic callers rather than shipping artefact proof. Actual provider/toolchain qualification is separate from unit and plain-worker coverage.

Run the maintained actual corpus with `make generation-sequence-otelc OTELC_ROOT=/absolute/path/to/qualified/otelc REPORT_DIR=/private/tmp/new-sequence-qualification`. It exercises both Node language IDs, JavaScript ESM/CommonJS collection and creation links, intermediate mutation restored before the final boundary, declared errors, user finalizers, retained-object incompleteness, generated/exported suites and scalar replay. Exact revisions and actual results must be recorded separately from the implementation checks.

## Published qualification

The [23 October Python record](qualification/python-sequences-2026-10-23.json) names runtime `18f70b9` and frozen provider `d6d03b7`: 150 distinct applications, 30 reports, 152 typed observations, 38 independently recomputed comparisons and 34 required route commands. Four copied shrink attempts remain in the 154 raw attempt folders without inflating launches. The one/32-call positives, rich-graph budget refusal, coordinated class-replacement refusal, five altered-evidence controls and changed-source refusal all retain their expected outcomes. A separate 81-launch compatibility corpus checks the original five single-call methods. The initial runtime attempt stopped on a real metric export loss; its cause remains unresolved and its failed evidence is preserved. The separately labelled complete quiet-host corpus passed with the same frozen inputs and unchanged loss checks. These records qualify the stated diagnostic profile, with no broader transport-reliability or shipping claim.

The [21 October Java record](qualification/java-sequences-2026-10-21.json) qualifies runtime `dc8fa3d` with prepared SDK `f3279fd` and legacy provider `d6d03b7`: 120 actual JVMs per provider, five cases each, private factories, complete intermediate source graphs, expected intermediate exceptions and recursive trees. Four cases match; the deliberate intermediate-state difference is detected although the final state and return match. Generated suites, detached exported run/suites, per-case replay and shrinking seven to zero retain those outcomes. Each provider passes five altered-evidence controls and one prelaunch source refusal.

The verifier at `8d08d65` rechecks all 46 reports, 248 retained observations/compiler manifests and 744 class bindings without new JVMs. Prepared mode also checks 124 retained runtimes, 120 actual PID/argv identities and 62 instrumented receipts against decoded telemetry and final health. Four copied original shrink attempts per provider are retained once in the actual launch denominator. The initial script completed the execution routes but subtracted those four launches twice during its final audit; the correction has focused regression checks. Both frozen prepared SDK source copies and Java products are unchanged, and original short runtimes are removed. These remain diagnostic builds with the limits above.

The [20 October record](qualification/ordered-sequences-2026-10-20.json) names runtime `2cf56e1` and the frozen `c65a35c` provider on macOS ARM64/Node24.21. The maintained eight-case corpus completed 148 actual launches: six cases matched, the transient-state control differed, and the application-retained receiver remained inconclusive. Generated/exported suites, scalar shrinking and replay retained those outcomes. Six altered-evidence controls and one changed-source refusal passed. Source inputs were preserved. All 332 local regressions and exact-runtime remote checks passed; Rust product line coverage was 97.29%.

This qualification covers JavaScript ESM/CommonJS collection, source factories, ordinary async methods, encoded returned aliases and an application finalizer, plus TypeScript source-emitter calls/release. This earlier record does not qualify the separately gated [TypeScript collection emitters](typescript-collection.md#published-qualification) or other language sequences.
