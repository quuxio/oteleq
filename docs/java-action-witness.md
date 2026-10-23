# Java action witness components

## Status

The independent `java-sync-action-v2` control/final and decoded-trace readers and ordinary JDK private harness channel are implemented components. Generated prepared-Java action scopes are not yet available: public build/probe binding, actual SDK control integration and qualification with a real frozen v2 producer remain required. Existing generated workers retain their documented name-only witness. These components do not establish equivalence of a shipping artefact.

The [shared witness design](action-witness.md) remains the acceptance boundary. A producer acknowledgement cannot replace actual receiver evidence, and successful framing cannot qualify invocation attribution.

## Independent context binding

`OteleqRendezvous.java` uses standard JDK 21 APIs and a private Unix socket. It imports no instrumentation API. The same helper bytes run in both lanes. Application stdout, stderr and stdin carry no harness control messages.

The parent freezes a case ID, attempt ID and ordered distinct action IDs. Each readiness frame contains those identities, a fresh private token, the actual JVM PID and `Thread.currentThread().threadId()`. The parent checks the PID against the launched process. It releases only the connection which supplied that validated readiness. Partial, duplicate, oversized, reordered and foreign-process frames refuse. The executor retains responsibility for application output, time/resource budgets and process cleanup.

The selected producer context must match that independently reported Java thread ID before arming. The consumer also binds its opaque cookie and freshness sequence to the runtime instance and frozen compiler/build/probe identities. Another envelope becoming ready first cannot be treated as the intended action. A concurrent action can cause refusal under the initial one-active-action profile; it must not cause false attribution. Virtual threads and asynchronous migration require separate support and remain unavailable.

## Explicit versioned reader

`java_witness.py` accepts wire/schema version 2 and the explicit `java-sync-action-v2` profile. It has a closed command vocabulary: status, arm, end and cancel. Arm includes the independently expected Java thread ID. Replies require unique JSON fields, the correlated request ID, actual JVM PID, exact bounded decimal counters, bounded distinct span-ID sets and the declared build/selection/policy/tooling and compiler probe identities. Version 1 cannot silently satisfy version 2.

An incomplete or refused scope remains data. A producer completion claim requires all declared exits, a successful checkpoint, matching started/ended/exported sets, no pending exports and no known queue loss. Prior flush failures remain visible even when a later checkpoint succeeds. Actual scoped OTLP receipt and final process/pipeline health still need independent qualification.

Final reports must be bounded owned mode-0600 regular files inside the canonical owned mode-0700 runtime. The reader uses nonblocking, no-follow opens, a bounded read and opened/path identity checks. The caller's actual JVM PID, frozen producer identity, outer report and producer header must all identify the same JVM. It also checks the frozen runtime/build/probe identity. Duplicate or reordered contexts refuse. Unavailable queue evidence remains unavailable.

## Independent decoded action trees

`java_action_receipt.py` compares actual decoded trace records with separately retained harness/arm identities captured before release and independently captured application outcome kinds. Final producer fields cannot supply those expectations. Every declared action must match its actual PID/runtime, case/attempt, logical thread, context cookie, sequence and scope ID. Final supported drain and zero observed queue loss are required.

The synchronous diagnostic contract selects one source-bound method and its recursion. Each action needs its own fresh trace, one wrapper root and the exact target probe directly beneath that root. Every target or recursive-target probe needs its selected-method child, with the declared namespace/method and pinned instrumentation scope. The complete decoded span-ID set must equal the producer's started, ended and exported sets. Parent edges, intervals, exception status, compiler probe IDs and all nine action/build identity attributes are checked independently. Synchronous recursive siblings must not overlap, regardless of arrival order; equal end/start boundaries are permitted. Missing methods cannot be hidden by reducing both the producer count and the decoded receipt. Unattributed spans inside an action trace, duplicate spans, unknown scopes, unsupported links and dropped observations refuse.

Serial action root intervals must also follow the declared action order without overlap; equal end/start boundaries are permitted. Background spans remain retained outside the action counts. Metric bodies also remain retained; this component does not decode or qualify them. Final global SDK pipeline health, metric accounting, source/build binding, typed application observations and independent repeats remain separate requirements before generated admission. The decoder accepts at most 4,096 bodies, 32 MiB of raw data and 65,536 decoded spans; exceeding a budget refuses. Its retained receipt digest includes route and body lengths, preserving batch order and boundaries.

## Component checks

Run the maintained contributor gates with the documented toolchain:

```sh
make generation-check
```

Python readers and the private harness session each have an independent 80% line floor. Synthetic protobuf controls cover action trees, recursion/errors, cross-batch ordering, every identity attribute, missing/duplicate spans, altered producer counts, malformed graphs and explicit decode budgets. They do not count as real producer qualification. Real JDK regression workers check private method calls, serial readiness/release, actual Java thread IDs, binary application channels, virtual-thread refusal and wrong-release refusal. The compiled helper has a separate 80% JaCoCo line floor. JaCoCo applies only to these regression probes; it is not part of application or SDK qualification.

These checks leave the full [completion checklist](completion.md) open. The result remains **equivalence over these tests and observations**.
