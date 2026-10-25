# Go live metric schedules

Status: bounded diagnostic qualification for explicit `source-scope-v1` call-only receiver workers. The [320-launch qualification](qualification/go-scope-metric-controls-2026-10-25.json) covers all four startup states and generated/retained routes against its frozen runtime/provider. The separate `source-v1` implementation and earlier records retain their own scope. This does not establish complete Go support. The [prepared-provider guide](go-prepared-provider.md) names the accepted SDK protocols and remaining build limits.

The qualified `source-scope-v1` record uses private-bootstrap-v1, untagged build6/inspection1 and prepared-tools2. Tagged build7 and other helper/build profiles need separate execution and qualification; neither older source-v1 records nor this untagged corpus cover them.

## Declare a schedule

Use an existing same-package factory and put an explicit metric state on every call. At least one call must enable both collection and emission. The first call's state also supplies the initial SDK policy, before the factory runs.

```toml
schema_version = 1
languages = ["go"]

[adapters.go]
backend = "source-scope-v1"
module_roots = ["."]

[limits]
case_timeout_ms = 60000

[[fixtures]]
function = "*.Counter.Step"
cases = [[3]]
receiver = { factory = "New", arguments = [10] }
sequence = [
  { action = "call", arguments = "case", metrics = { collection = false, emission = true } },
  { action = "call", arguments = [2], metrics = { collection = true, emission = true } },
  { action = "call", arguments = [4], metrics = { collection = false, emission = false } },
  { action = "call", arguments = [1], metrics = { collection = true, emission = false } },
]
```

The same external `plan`, `generate`, `run`, `replay` and `export-tests` commands consume this policy. The target repository and its existing test framework need no changes. Compilation has its separate build timeout. Set the case timeout to cover calls, control exchanges and at least one second for each disabled interval; the shared process deadline remains in force. The maximum sequence length is 32 calls. The controlled profile permits at most 4,096 telemetry requests while retaining the shared 32 MiB body budget; repeated flushes cannot silently truncate receipt.

## Execution and observations

The native worker first publishes its owned readiness record. A private package then pauses it before the factory, before each subsequent call, after every call and after the complete observation file is closed. Checkpoints use the original private directory and nonce. The host binds the actual supervisor/application parent and process group before it releases application calls.

The host sends separate collection and emission commands to the SDK's private TCP endpoint. A completed emission command supplies the export barrier. Flushes and paused health snapshots surround each call; disabled states include a bounded quiet interval. The final checkpoint restores both settings and flushes retained measurements before normal SDK shutdown. The executable and application PID stay unchanged throughout the schedule.

The plain worker follows the same checkpoints and observations. It supplies no fabricated SDK status, health or telemetry.

Typed observations retain every call's before/after graph and outcome, including a supported primitive panic. Trace qualification counts all selected factory and method trees. Metric qualification counts only trees executed while collection was enabled. A factory is included only when the initial state enables collection. Emission-off measurements must appear after restoration; calls made with collection disabled must remain absent. Traces remain enabled in every state.

## Retained evidence and refusal rules

Each attempt retains `go-controls.json`, all checkpoint/acknowledgement links, the original native ownership records, final SDK health and raw downstream OTLP. The independent reader checks closed fields, declared call/state order, actual PID/policy/selection, receipt cursors, disabled intervals, separate setters and cumulative measurements. The detailed `go-verified-telemetry.json` adds the control-record digest and collected function counts. The comparator's six-field witness stays unchanged.

Running metric export counters are independent atomic reads. A periodic export can begin after a host flush returns, so a running snapshot need not show equal attempts and successes. The audit retains both counters, requires each to remain monotonic through restoration and final shutdown, and rejects any recorded export failure. The closed final report must show every attempt succeeded, with its export count equal to independently received OTLP requests. This does not relax the separate disabled-window or retained-measurement checks.

Missing checkpoints, an early acknowledgement, changed file facts, a different process, a missing positive call, lost traces, disabled-window metrics or missing restored measurements prevent qualification. A passing component test cannot supply missing runtime evidence.

## Scope

This profile supports declared synchronous receiver calls and its fixed compiler/build recipe. It does not establish general invocation attribution, goroutine scheduling, resource actions, arbitrary Go objects, cgo/workspaces, shipping artefacts or other SDK helper recipes. The recorded untagged retained/replayed/reduced/promoted workflows have the separate exact-revision evidence above. Tagged builds and changed profiles need their own qualification. The [completion checklist](completion.md) remains open.

The result is **equivalence over these tests and observations**.

## Qualify generated and retained suites

The maintained `source-scope-v1` corpus uses a private receiver, seven application declarations that shadow builtins, five ordered calls and a primitive panic. One method deliberately changes intermediate instance state only in the instrumented lane, then restores it. Complete literal graph expectations check every root, scalar, storage location, self cycle and call outcome in both repeats of both lanes. Matching return values and final state cannot hide that intermediate difference.

Run each initial state in a new external directory against the matching prepared SDK:

```sh
make generation-go-controls-otelc \
  OTELC_ROOT=/absolute/path/to/prepared-otelc \
  REPORT_DIR=/absolute/path/to/new-go-controls \
  AUDIT_DIR=/absolute/path/to/new-go-controls-audit \
  GO_CONTROL_STARTUP=both-on
```

Repeat serially with `collection-off`, `emission-off` and `both-off`. Every schedule includes all four flag pairs, an emitting positive control and a final collected panic while emission is disabled. Restoration must deliver the retained call, duration and error measurements. Raw decoded traces must retain the factory and all five selected calls throughout the schedule.

Fresh runs check an 8 GiB free-space floor before each qualification command. Set `GO_CONTROL_MIN_FREE_BYTES` for another measured budget, or use the script's `--min-free-bytes` option directly. The generated fixture also freezes this value as `[adapters.go] build_min_free_bytes`, so source-provider compiler-metadata, SDK build and preparation commands keep checking during framework, shrink and promoted-suite execution. A prelaunch qualification refusal retains a separate `*.storage-refusal.json` and starts no application for that operation. An interrupted build instead retains `go-tooling/<number>/storage-refusal.json`, the command PID and compiler channels, and cleans its owned process group. Both leave the attempt incomplete. This is a sampled check, not a disk quota or reservation. Keep one startup corpus active at a time and reclaim only unreferenced terminal caches. Retained-only audits start no applications and do not enforce this fresh-run floor.

Fresh qualification also declares one [bounded SDK compiler cache](go-build-bundles.md#bounded-sdk-compiler-cache) at `<report-dir>/compiler-cache`, shared by the generated, exported, reduced and promoted routes. Its default limit is 1 GiB between SDK builds. Set `GO_CONTROL_CACHE_MAX_BYTES`, or the script's `--cache-max-bytes`, to select another measured limit. Caller exports and module caches remain separate and retain their existing input checks. The free-space guard also measures the cache volume. A small passing component probe does not complete the startup or retained-route qualification matrix.

The command exercises direct generation, replay, external unittest, detached export, scalar shrinking and current-source promotion. Promotion changes existing return values and discovers a newly added method. The retained audit recomputes comparisons, checks every named operation and separates copied shrink observations from actual application launches. `GENERATION_ARGS=--retained-only` audits an existing complete run into a new `AUDIT_DIR`, without starting applications. Interrupted or failed operations retain their original output and must be inspected before recovery.

The shrink archive is a byte copy with new filesystem identities. Its four launch IDs must identify one unique original report in the complete retained registry. Every archived file, directory, mode and byte digest must match that original before the audit uses the original publication/link facts. Missing or ambiguous originals, modified archives and extra entries refuse qualification. The archive is not recertified as a new execution, and its observations remain separate from actual launches.

The [25 October record](qualification/go-scope-metric-controls-2026-10-25.json) binds runtime `cb08b82`, its CLI and SDK `eda9fcc` to 320 actual applications and 160 SDK processes. The four serial corpora produce 76 reports and 336 observations, including 16 copied originals, with 84 recomputed comparisons and 20 altered-evidence refusals. The final retained-only audit starts no applications, confirms 320 globally unique launch IDs and preserves all 401,894 original evidence files plus 587 consumer, 500 SDK, 485 pinned-weaver and six tooling inputs. The measured SDK cache bound is 512 MiB; every fresh command samples an 8 GiB storage floor. Earlier storage/interruption/oracle failures remain separate failed or incomplete records. Later native integration or documentation changes do not broaden the frozen Go runtime qualification.

These are maintained qualification tools. Successful focused tests or one startup state do not qualify the complete matrix; each new profile needs actual source, SDK, tooling and route evidence.
