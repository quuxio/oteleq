# Java action witness components

## Status

The independent `java-sync-action-v2` control/final and decoded-trace readers, offline binding bridge and ordinary JDK private harness channel are implemented components. An explicitly selected `java-sync-private-handle-v1` control/final reader also checks the schema-3 route identity and verification flag. Generated prepared-Java action scopes are not yet available: generated caller wiring, actual SDK control integration and complete qualification with a real frozen producer remain required. Existing generated workers retain their documented name-only witness. These components do not establish equivalence of a shipping artefact.

The [shared witness design](action-witness.md) remains the acceptance boundary. A producer acknowledgement cannot replace actual receiver evidence, and successful framing cannot qualify invocation attribution.

## Independent context binding

`OteleqRendezvous.java` uses standard JDK 21 APIs and a private Unix socket. It imports no instrumentation API. The same helper bytes run in both lanes. Application stdout, stderr and stdin carry no harness control messages.

The parent freezes a case ID, attempt ID and ordered distinct action IDs. Each readiness frame contains those identities, a fresh private token, the actual JVM PID and `Thread.currentThread().threadId()`. The parent checks the PID against the launched process. It releases only the connection which supplied that validated readiness. Partial, duplicate, oversized, reordered and foreign-process frames refuse. The executor retains responsibility for application output, time/resource budgets and process cleanup.

The selected producer context must match that independently reported Java thread ID before arming. The consumer also binds its opaque cookie and freshness sequence to the runtime instance and frozen compiler/build/probe identities. Another envelope becoming ready first cannot be treated as the intended action. A concurrent action can cause refusal under the initial one-active-action profile; it must not cause false attribution. Virtual threads and asynchronous migration require separate support and remain unavailable.

## Offline compiler bindings

`java_action_bindings.py` freezes four distinct caller-declared envelope, rendezvous, wrapper and target methods. It calls the public offline SDK compiler from a fixed isolated Python process, pins the selected JDK, and rechecks the application sources, compiler records, class products, SDK inputs and declarations after success, failure or cancellation. Cancellation keeps its original exception; a failed input audit remains an attached diagnostic. Application classes are read without initialising them.

The independent reader defaults to the explicit v2 schema/profile. It requires closed fields, exact owner/name/descriptor declarations, matching compiler-owned class bytes and recomputed role probe IDs. Method-code digests and harness shape are checked by the frozen offline SDK compiler; they still need actual runtime capture and receipt before invocation admission. Neither metadata acceptance nor the presence of this module enables a generated worker. The v2 direct-call restriction remains in force: reflected wrappers and undeclared handle profiles cannot silently use it. Explicit private-handle compilation is described below; its route is never inferred from a document.

Bindings and final JSON use one stable private-file reader: canonical owned mode-0700 parent, one owned mode-0600 regular file link, no-follow/nonblocking open, bounded read and descriptor/path identity checks. Binding declarations/output each have a 1 MiB budget. SDK stdout must agree with the retained bindings. The output hash comes from the same opened snapshot as the verified data, and a final snapshot must match its bytes and file identity before publication. Compiler channels, fixed argv and input/output hashes remain available for review.

With the matching prebuilt SDK and a selected full JDK, qualify the offline API in a new directory outside both repositories:

```sh
make generation-java-bindings-otelc OTELC_ROOT=/path/to/otelc REPORT_DIR=/path/to/new-report
```

The retained qualification compiles a source fixture whose class initialiser leaves a sentinel if executed. It accepts the direct private target, refuses a wrong target descriptor and a reflected wrapper, and requires that sentinel to remain absent. No application is launched. This contributor command qualifies offline metadata only; generated invocation execution and shipping qualification remain open.

## Explicit versioned reader

`java_witness.py` accepts wire/schema version 2 and the explicit `java-sync-action-v2` profile. It has a closed command vocabulary: status, arm, end and cancel. Arm includes the independently expected Java thread ID. Replies require unique JSON fields, the correlated request ID, actual JVM PID, exact bounded decimal counters, bounded distinct span-ID sets and the declared build/selection/policy/tooling and compiler probe identities. Version 1 cannot silently satisfy version 2.

An incomplete or refused scope remains data. A producer completion claim requires all declared exits, a successful checkpoint, matching started/ended/exported sets, no pending exports and no known queue loss. Prior flush failures remain visible even when a later checkpoint succeeds. Actual scoped OTLP receipt and final process/pipeline health still need independent qualification.

Final reports must be bounded owned mode-0600 regular files inside the canonical owned mode-0700 runtime. The reader uses nonblocking, no-follow opens, a bounded read and opened/path identity checks. The caller's actual JVM PID, frozen producer identity, outer report and producer header must all identify the same JVM. It also checks the frozen runtime/build/probe identity. Duplicate or reordered contexts refuse. Unavailable queue evidence remains unavailable.

## Explicit private-handle reader

The `java-sync-private-handle-v1` reader requires explicit selection through `profile=java_witness.HANDLE_PROFILE`. It accepts only schema/wire version 3. The caller freezes the additional `route_binding_sha256` alongside the original build and compiler probe hashes before binding an `Identity`. Every subsequent acknowledgement and final producer header must match that route and profile. An arm command appends the route digest after the independently expected logical thread ID.

Each schema-3 scope has an exact boolean `route_verified`. An incomplete scope may retain `false`; a producer completion claim requires `true` as well as all the existing exits, span sets, queue and checkpoint evidence. Default reader calls still accept only v2. Neither version can select the other from its fields, and unknown profiles refuse before socket I/O.

Decoded receipt validation uses the frozen identity's explicit profile. The handle route does not relax the complete tree, compiler probe, context, interval, loss or application-outcome checks below. Generated runner activation and complete consumer qualification remain open.

## Typed private JDK callers and bindings

`java_handle_callers.members` emits ordinary JDK members and independently requested envelope/rendezvous/wrapper/target declarations. Source and binary owner names are explicit separate inputs. A private static-final `MethodHandle` is created through an ordinary private lookup. The static wrapper loads only that field and its typed arguments, calls `invokeExact` and returns the exact result. It does not adapt or bind arguments. Constructors, factories, argument construction, state observations and error handling belong outside the envelope and wrapper. The source imports no instrumentation API and is the same in both lanes.

The private rendezvous uses `OteleqRendezvous` and the harness-owned ordered `OTELEQ_ACTION_IDS` plan. Package relocation changes only that fixed helper's package declaration. Maintained real-JDK tests check private static and instance calls, primitive payloads including NaN and signed zero, UTF-16 strings, arrays, mutable state, aliases, original exception identity, binary output and a packaged Unicode owner. The emitted signatures and current qualifier cases are explicit; this component does not construct arbitrary object fixtures.

`java_action_bindings.compile(..., profile=java_witness.HANDLE_PROFILE, route=HandleRoute(...))` calls the public offline schema-3 compiler. The caller supplies the expected field name and static/virtual reference kind before compilation. The consumer recomputes all role probes and the route digest, checks the exact invocation descriptor and JVM slot bound, and refuses different fields, changed dispatch or incorrectly typed route members even if a producer rehashes them. The fixed isolated compiler command records its explicit profile; v2 retains its original default SDK API and cannot accept a handle route. Existing source, class, tool, cancellation and output-snapshot guards apply to both profiles.

With a matching prebuilt SDK, run the separate offline contributor qualification in a new directory:

```sh
make generation-java-handles-otelc OTELC_ROOT=/path/to/otelc REPORT_DIR=/path/to/new-report
```

The fifteen-case corpus compiles generated private callers for all eight primitive types, String, void, instance arrays and wide instance arguments. It refuses a different expected handle field, a wrong target descriptor and a handle wrapper offered to v2. An application-initialisation sentinel must stay absent. Compiler helper processes run; target applications do not. These checks qualify emitted bytecode and offline metadata. The generated execution pipeline still needs binding/launch integration, host control and complete actual-provider qualification before these components can admit invocation-scoped generated results.

## Independent decoded action trees

`java_action_receipt.py` compares actual decoded trace records with separately retained harness/arm identities captured before release and independently captured application outcome kinds. Final producer fields cannot supply those expectations. Every declared action must match its actual PID/runtime, case/attempt, logical thread, context cookie, sequence and scope ID. Final supported drain and zero observed queue loss are required. Resource and instrumentation-scope attributes also require zero drops and unique typed entries.

The synchronous diagnostic contract selects one source-bound method and its recursion. Each action needs its own fresh trace, one wrapper root and the exact target probe directly beneath that root. Every target or recursive-target probe needs its selected-method child, with the declared namespace/method and pinned instrumentation scope. The complete decoded span-ID set must equal the producer's started, ended and exported sets. Parent edges, intervals, exception status, compiler probe IDs and all nine action/build identity attributes are checked independently. Synchronous recursive siblings must not overlap, regardless of arrival order; equal end/start boundaries are permitted. Missing methods cannot be hidden by reducing both the producer count and the decoded receipt. Unattributed spans inside an action trace, duplicate spans, unknown scopes, unsupported links and dropped observations refuse.

Serial action root intervals must also follow the declared action order without overlap; equal end/start boundaries are permitted. Background spans remain retained outside the action counts. Metric bodies also remain retained; this component does not decode or qualify them. Final global SDK pipeline health, metric accounting, source/build binding, typed application observations and independent repeats remain separate requirements before generated admission. The decoder accepts at most 4,096 bodies, 32 MiB of raw data and 65,536 decoded spans; exceeding a budget refuses. Its retained receipt digest includes route and body lengths, preserving batch order and boundaries.

## Component checks

Run the maintained contributor gates with the documented toolchain:

```sh
make generation-check
```

Python readers and the private harness session each have an independent 80% line floor. Synthetic protobuf controls cover action trees, recursion/errors, cross-batch ordering, every identity attribute, missing/duplicate spans, altered producer counts, malformed graphs and explicit decode budgets. They do not count as real producer qualification. Real JDK regression workers check private method calls, serial readiness/release, actual Java thread IDs, binary application channels, virtual-thread refusal and wrong-release refusal. The compiled helper has a separate 80% JaCoCo line floor. JaCoCo applies only to these regression probes; it is not part of application or SDK qualification.

These checks leave the full [completion checklist](completion.md) open. The result remains **equivalence over these tests and observations**.
