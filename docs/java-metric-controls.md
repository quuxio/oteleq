# Live Java metric controls

Declared Java receiver sequences can change metric collection and emission independently while one instrumented JVM and build remain in place. The plain lane executes the same calls and private checkpoints in its own process. Application and dependency sources remain unchanged; no application SDK calls are required.

This profile uses the [prepared Java provider](java-prepared-provider.md), its existing private control socket and the ordinary [Java receiver codecs](java-receivers.md). It supports **equivalence over these tests and observations**, including each call's result, supported state and exact stdout/stderr. Its metric proof applies to the selected synchronous method trees. General SDK instruments, arbitrary callbacks, concurrent schedules and shipping artefacts require separate qualification.

## Declare a sequence

Select `profile = "safe-methods-v1"` under `[adapters.java]` for the corrected SDK recipe, or keep the default `stock-methods-v1` for the original frozen provider. Profile selection and getter expectations are independent: neither configuration nor a summary can turn an observed difference into equivalence.

For the existing `Counter.add(int)` receiver example, use:

```toml
schema_version = 1
languages = ["java"]

[adapters.java]
backend = "prepared"

[functions]
include = ["Counter.add(int)"]

[limits]
case_timeout_ms = 20000

[[fixtures]]
function = "Counter.add(int)"
cases = [[7]]
receiver = { factory = "Counter", arguments = [10] }
domains = [{ kind = "integer", minimum = 0, maximum = 7 }]
sequence = [
  { action = "call", arguments = "case", metrics = { collection = true, emission = true } },
  { action = "call", arguments = [2], metrics = { collection = false, emission = true } },
  { action = "call", arguments = [3], metrics = { collection = true, emission = false } },
  { action = "call", arguments = [4], metrics = { collection = false, emission = false } },
]
```

Use the normal `plan --config`, `generate`, `run`, `replay`, `shrink` and `export-tests` commands. A call in the schedule must provide a collection-on/emission-on positive control. Every call in a live schedule must declare both booleans. The first call's flags set the SDK's actual startup state in both the common policy and independently checked launch properties. The first status must already match those flags; later setters cannot repair an incorrect initial state. Fixed arguments, construction inputs, required roots and states remain frozen through generated suites, export and scalar shrinking. Other provider/language profiles remain explicit blockers.

The earlier qualifications below cover positive-first schedules. The separate [2,256-JVM startup qualification](qualification/java-startup-metric-controls-2026-10-23.json) covers all four initial states in the recorded stock, safe and archive prepared profiles. Each application retains its original PID and build while the flags change independently and together.

Positive and restored checkpoints keep the application paused until the collector receives both cumulative function series with the required service, method and completed-call totals. A flush acknowledgement alone cannot close those windows. New bodies are decoded once; waiting does not repeat setters or control commands. Existing process, output, time and capture budgets remain enforced. Missing or partial series cannot become a successful checkpoint. Actual qualification of this receipt barrier is pending; earlier records retain their own runtime identities.

| Requested state | Selected function measurements | Metric export | Tracing |
| --- | --- | --- | --- |
| Collection on, emission on | Recorded | Exported | Remains active |
| Collection off, emission on | No new recordings | May export earlier aggregates | Remains active |
| Collection on, emission off | Recorded and retained | No metric requests in the measured off window | Remains active |
| Collection off, emission off | No new recordings | No metric requests in the measured off window | Remains active |

The host restores both controls and flushes before the JVM exits. The final direct function counter and duration count must include calls made while collection was enabled, including retained emission-off measurements, and exclude calls made while collection was disabled. Traces must still cover every declared call tree, including recursive invocations and declared errors. A no-op exporter or missing telemetry cannot substitute for these checks.

## What is checked

The generated caller uses private file checkpoints before and after each call. A separate host client sends the public socket commands. Both lanes use the same caller code; the plain lane records no fabricated SDK responses. Each process keeps its PID, executable, source/classes, policy and loaded origins throughout the schedule.

Control replies have a closed schema, actual PID, explicit flags and available counters. Unknown counters, losses, changed processes and contradictory acknowledgements fail the gate. Each setter must preserve the other control. Emission-off waits for zero in-flight exports and the effective-off acknowledgement before releasing the next call. Each off window includes a forced flush and at least one complete 1,000 ms export interval. The host continues to enforce the shared case time/output budgets; increase the explicit timeout for longer functions or schedules.

Direct OTLP receipt independently checks each selected trace, complete root/parent graphs, scope, method identity and cumulative metric series. Synchronous root trees must have an unambiguous serial order, with children contained in their root interval. Their sizes determine the expected recorded-call denominator for each declared collection state. Positive and restoration flushes must supply both actual function metric series. Final SDK health remains separate and must match the actual PID, policy/selection and all received export batches/units without pending or lost evidence.

This remains a named-tree witness. It does not add the [proposed invocation cookies](action-witness.md) or qualify hidden concurrent activity. Application snapshots remain call boundaries; broader asynchronous or resource actions need their own observations.

## Retained evidence

Each attempt adds `java-controls.json`, containing actual control histories, receiver positions, measured off windows and restoration. `verified-controls.json` binds its digest, actual PID, all selected spans and collected spans. The existing compiler products, launch/PID records, raw OTLP and final health are retained. Original short SDK runtimes are archived and removed normally. Missing checkpoints, unsafe files and incomplete control schedules cannot pass.

The client accepts at most 4 KiB per reply, 256 status records per transition and 512 in total. The full control record is capped at 256 KiB. These are additional observer budgets; the existing application and telemetry budgets still apply. This is trusted local execution, not a hostile-code sandbox.

## Maintainer qualification

```sh
make generation-java-controls-otelc \
  PYTHON=/absolute/path/to/qualified/python \
  OTELC_ROOT=/absolute/path/to/frozen/prepared-sdk \
  LEGACY_OTELC_ROOT=/absolute/path/to/frozen/legacy-sdk \
  REPORT_DIR=/absolute/path/to/new-qualification
```

The primary corpus covers six methods, complete intermediate graphs, private factories, nonempty application stdout/stderr, recursive trees, a declared error while collection is off, and state differences during both off modes. It exercises direct/generated/detached-exported routes, per-case replay and scalar shrinking. Ordinary prepared/legacy calls are checked separately so live controls remain opt-in. Contributor gates enforce 80% line coverage separately for the client, checkpoint host and receipt validator; actual-provider qualification is a separate requirement.

The cause-getter regression uses an exact supported outer `RuntimeException("outer", cause)`. Its custom cause mutates a private receiver field when the SDK formats the exception. Frozen SDK `f3279fd` causes one extra mutation per call; the comparison correctly reports a difference. The cause internals remain outside the observation codec. This is a known producer defect and is delegated to the otelc owner. `GETTER_EXPECTATION=different` records that known result; select `equivalent` only when qualifying a corrected immutable SDK. A summary cannot reclassify retained failing observations as equivalent.

The qualifier's `--recheck` validates completed retained reports, compiler products, checkpoint pairs and raw receipt/health without new JVM launches. Keep failed or partial evidence separate; it does not restart incomplete routes.

Set `JAVA_PROFILE=safe-methods-v1 GETTER_EXPECTATION=equivalent` when qualifying a corrected SDK. The defaults retain the original stock recipe and known getter difference. The qualifier exposes the same choices as `--java-profile` and `--getter-expectation`; use the same values for `--recheck`.

## Qualify startup schedules

The maintained startup corpus uses the complete six-method receiver fixture, including private access, aliases/cycles, recursion, an intermediate exception and two declared state differences. It exercises direct/generated and detached/exported suites, replay, scalar reduction and current-source promotion before and after a real console-body change. The [recorded twelve-corpus qualification](qualification/java-startup-metric-controls-2026-10-23.json) checks 2,256 distinct JVM launches, 168 copied actual-evidence refusals and 576 freshly recomputed comparisons. The altered copies and 48 retained shrink duplicates do not count as new JVM launches.

```sh
make generation-java-startup-otelc \
  PYTHON=/absolute/path/to/qualified/python \
  OTELC_ROOT=/absolute/path/to/frozen/provider \
  REPORT_DIR=/absolute/path/to/new-startup-evidence \
  JAVA_CONTROL_STARTUP=both-off \
  JAVA_STARTUP_PROFILE=safe-methods-v1
```

`JAVA_CONTROL_STARTUP` also accepts `both-on` (the default), `collection-off` and `emission-off`. Each run rotates the complete four-state schedule. `JAVA_STARTUP_PROFILE` defaults to `safe-methods-v1`; `stock-methods-v1` and `archive-methods-v1` require their own matching frozen provider. The script accepts the same values through `--startup-state` and `--java-profile`. Startup corpus cases explicitly allow 60 seconds per attempt; earlier positive-first corpus budgets remain unchanged.

The script's explicit `--recheck` option audits a complete retained corpus without launching an application. It checks the original profile, all 19 required route commands and their contract-known exit codes, retained command output, all observations, standalone or archive-context compiler bindings, actual receipts and alteration controls. It writes fresh comparisons and a new qualification result under `offline-recheck-*`, preserving the original controller result and any failure. Missing or unfinished routes, whole-record omissions and substituted commands are refused. Optional historical comparison records do not supply route-completion evidence.

## Published qualification

The [23 October startup record](qualification/java-startup-metric-controls-2026-10-23.json) identifies executed runtime `bb1fb96` and offline verifier `d0282c4` separately. All twelve completed corpora pass the corrected verifier, including 228 independently required route commands. The original four archive controllers failed their final build audit because it assumed standalone compiler argv positions. Their failures remain unchanged; the corrected archive-context audit uses the actual retained products and selected JDK without relaunching applications. The record also keeps a first offline attempt's ambient-JDK refusal separate. Final cleanup/cancellation production code `6571c7c` has its own component and sixteen-JVM compatibility evidence; it did not execute the twelve-corpus matrix. An actual stock both-off HTML/JUnit report retains four matching methods, two deliberate state differences and four excluded callables.

The [21 October record](qualification/java-metric-controls-2026-10-21.json) qualifies runtime `0288559` with frozen prepared SDK `f3279fd` and legacy provider `d6d03b7`: 164 actual JVM launches, including 140 through the six-method live corpus, eight getter-regression launches and eight ordinary calls per backend. The main corpus has four matching methods and two deliberately different methods. Complete intermediate receiver/static/error graphs, private factories, recursion, stdout/stderr and all four live states are checked through generated suites, replay, detached export and scalar shrinking from seven to zero. Four copied original shrink attempts remain retained once in the 168 observations and do not inflate actual launches.

Seven altered actual control/metric receipts and three incompatible schedule requests are refused; the latter launch no application. Changed-source replay is also refused before launch. Both 62-file frozen SDK source copies and the two prepared Java products remain unchanged. The 661-regression repository gate passes, with 97.32% Rust product line coverage and 97% to 100% coverage in the three new control modules. The rendered guide and actual six-case HTML report were inspected.

The getter case remains a genuine difference on this frozen SDK: exception-cause formatting adds one private receiver-field mutation per call. Its exact failing graphs, raw telemetry and final health remain retained. Corrected providers require their own qualification; this record does not claim that the frozen defect is fixed.

### Corrected SDK profile

The [safe-profile record](qualification/java-safe-profile-2026-10-21.json) separately qualifies runtime `b4f2024` with immutable SDK `e4aaafa`, whose tree matches merged producer main `9956bd9`. All 164 actual JVM routes pass their independent expectations. The getter case now matches with no extra receiver-field mutation, while both artificial state differences remain detected. Four live states, recursive traces, collection counters, retained emission-off measurements and final health remain checked in each instrumented process. Seven altered actual receipts are refused.

All 78 SDK source files, the extension and bootstrap parser patch remain unchanged. The 665-regression gate passes, with 97.32% Rust product line coverage and 100% coverage of the explicit recipe validator. The original provider's failing getter evidence remains preserved in its separate record. This does not qualify broader dependency/type-metadata contexts or subsequent SDK revisions.
