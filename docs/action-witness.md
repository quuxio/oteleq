# Proposed invocation-scoped telemetry witness

## Status

This is a producer/consumer design proposal. The current generated workers use a decoded, name-only invocation tree with source/binding guards. They do not implement this protocol, expose compiler probe IDs or prove that arbitrary concurrent activity belongs to a test action. Existing qualification must retain that limitation.

The proposed capability binds telemetry to one generated action using a compiler-identified wrapper, a live runtime context and a fresh scope ID. A process-wide nonce or a static wrapper ID alone cannot identify an invocation: another call can occur between arming and the intended action.

## Generated worker shape

The diagnostic artefact contains ordinary generated rendezvous and invocation functions. Both lanes use the same harness bytes and schedule. Application sources and dependencies stay unchanged; generated access helpers remain explicit diagnostic deltas.

1. Decode arguments and construct the independent fixture.
2. Capture the declared initial state.
3. Enter a reserved rendezvous function and wait for release on a private harness channel.
4. Call an ordinary wrapper whose body invokes only the selected target. Errors escape the wrapper and are caught by the surrounding harness.
5. Capture the return/error and final state outside the wrapper.
6. Finish the harness and collect the producer's completed scope and decoded telemetry.

Only declared asynchronous functions are awaited. Observers, argument conversion, fixture factories and error formatting cannot satisfy the target witness. Later sequence support needs separately declared action scopes and completion rules.

The baseline performs the same ordinary rendezvous and wrapper call without SDK imports or API calls. It expects no producer events or telemetry. The instrumented lane uses producer control probes; a missing producer event cannot be replaced by baseline behaviour or a name-only witness.

## Rendezvous and context binding

The producer instruments the reserved rendezvous as a control probe. At its actual entry, it reports a runtime-instance ID, compiler probe ID, opaque live-context cookie and freshness sequence. The harness reports its case/attempt readiness separately. The parent associates both events with the launched process and frozen rendezvous declaration before arming the wrapper.

The consumer does not infer logical context identity from an OS thread alone. An ordinary Go harness has no supported public goroutine-ID API, and a Node worker can host multiple concurrent asynchronous contexts. A producer-issued cookie avoids adding application SDK imports or guessing runtime IDs.

| Language | Context which the producer must qualify |
| --- | --- |
| C / C++ | Actual execution thread; propagation to other threads needs a separate supported contract |
| Rust | Actual Rust execution context; synchronous thread support does not qualify futures, migration or detached work |
| Python | Native execution thread and, when applicable, the active asynchronous task |
| Java | Actual logical thread, including separately qualified virtual-thread behaviour |
| JavaScript / TypeScript | Node runtime/worker plus the active logical asynchronous context |
| Go | Actual goroutine context across supported scheduling/migration |

Context must remain live through rendezvous release and wrapper entry. Waiting must allow the producer control service to progress. A blocked Node event loop cannot depend on that same event loop to acknowledge arming. Unsupported context capture or propagation is a visible capability gap and prevents scoped qualification.

Where a qualified asynchronous backend needs a distinct invocation owner, the worker may use a reserved ordinary per-case envelope around decode, rendezvous, invoke-wrapper and encode. A producer control probe can establish that envelope's logical context without treating its decoding/encoding as action spans. Both lanes retain the same envelope. The context cookie identifies the exact logical invocation, not just an inherited nonce or worker ID. A backend which cannot prove continuity and reject context mismatch refuses the scoped capability.

## Proposed control exchange

Harness control and producer control are separate from application stdout/stderr, values and OTLP. Each record has a version, request identity, bounded size and case/attempt association. Fields below define required semantics; they are not an implemented SDK API or a final wire schema.

| Event/command | Required identity and checks |
| --- | --- |
| Harness ready | Frozen case/attempt and rendezvous identity; independent fixture ready; private channel belongs to the launched process |
| Producer ready | Runtime instance, actual rendezvous probe, opaque context cookie and freshness sequence |
| Arm | Fresh unpredictable scope ID, exact wrapper probe, expected runtime/context/sequence; one active scope initially |
| Armed acknowledgement | Echo the request and all bound identities; reject stale, overlapping or mismatched requests |
| Harness release | Release only after a valid armed acknowledgement; one release for that readiness record |
| Consumed | Exactly one entry into that wrapper on that live context consumes the arm; unrelated calls cannot consume it |
| Root exit / end | Matching scope and wrapper invocation; declared completion, inflight, loss and pending counts |
| Cancel | Retire an unconsumed or failed scope after a bounded timeout; retain its failure and any late activity |

The control service must not provide arbitrary process commands or accept executable paths from messages. IDs and cookies are bounded opaque data. The frozen source/build/selection manifest binds rendezvous, wrapper and target compiler probe IDs to the actual transformed artefact. A function name alone is insufficient.

Target descendants inherit the scope through qualified SDK context propagation. Recursive calls inherit it without rearming. Late or detached descendants, cancellation, crashes and unsupported context migration require explicit incomplete results until their completion semantics are qualified. A successful wrapper exit alone cannot establish quiescence or completed export.

## Required decoded evidence

A scoped result requires the actual decoded OTLP spans, not just control acknowledgements. The consumer checks:

- One wrapper root with the exact compiler probe ID and fresh scope ID.
- The expected target probe invocation and parent relationship within that root.
- Consistent runtime, case/attempt, build and selection identities.
- Complete supported descendant relationships, valid IDs and no unexpected scoped roots.
- Matching end status, completed export and zero inflight, loss and pending counts.
- The existing independent repeat, source preservation, process completion, fixture and typed observation requirements.

Startup, fixture, codec and background telemetry remains retained evidence and cannot satisfy the action count. The supported profile must declare how such activity is separated. Missing fields, unsupported scope capability, malformed acknowledgement sequences and incomplete transport cannot derive observed equivalence. No fallback silently weakens a requested scoped mode.

## Qualification controls

Positive qualification needs actual generated workers and decoded telemetry for each supported language/context profile. Baseline and instrumented application observations must still match over the declared tests.

Negative controls include another concurrent call between arm and consume, another asynchronous task in the same Node worker, Go scheduling/migration, a stale or reused cookie, cross-runtime IDs, duplicate consumption, mismatched end, overlapping scopes, missing wrapper/target spans, a missing end/export, dropped spans, recursion, exceptions, cancellation and detached work. Argument/observer callbacks which invoke the target must not satisfy its scoped witness. Unsupported cases remain explicit gaps.

The result remains **equivalence over these tests and observations**. This protocol improves invocation attribution; it does not establish complete object observation, exhaustive inputs/schedules, hostile-code containment or equivalence of a different shipping artefact.
