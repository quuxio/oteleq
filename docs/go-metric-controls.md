# Go live metric schedules

Status: implemented for explicit `source-v1` call-only receiver workers; actual-provider and retained-workflow qualification is in progress. Component tests do not establish complete Go support. The [prepared-provider guide](go-prepared-provider.md) names the accepted SDK protocols and remaining build limits.

The separate candidate `source-scope-v1` backend uses the same schedule contract with private-bootstrap-v1 and build6/7/prepared-tools2. Its generated, live and retained execution requires separate qualification; older source-v1 records do not cover it.

## Declare a schedule

Use an existing same-package factory and put an explicit metric state on every call. At least one call must enable both collection and emission. The first call's state also supplies the initial SDK policy, before the factory runs.

```toml
schema_version = 1
languages = ["go"]

[adapters.go]
backend = "source-v1"
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

Missing checkpoints, an early acknowledgement, changed file facts, a different process, a missing positive call, lost traces, disabled-window metrics or missing restored measurements prevent qualification. A passing component test cannot supply missing runtime evidence.

## Scope

This profile supports declared synchronous receiver calls and its fixed compiler/build recipe. It does not establish general invocation attribution, goroutine scheduling, resource actions, arbitrary Go objects, cgo/workspaces, shipping artefacts or other SDK helper recipes. Tagged builds and retained/replayed/reduced/promoted workflows need evidence against their exact implementation revisions. The [completion checklist](completion.md) remains open.

The result is **equivalence over these tests and observations**.
