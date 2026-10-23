# Node live metric controls

<!-- markdownlint-disable MD013 -->

The explicit `source-v1` JavaScript/TypeScript provider implements metric collection and emission schedules around declared receiver calls. **Exact-revision qualification is in progress.** The earlier [1,800-launch source-provider record](qualification/node-source-provider-2026-10-22.json) does not qualify this new capability.

## Declare a schedule

Use an existing source constructor or factory through the [receiver fixture](receiver-fixtures.md). Every step must call the selected method and declare both booleans. The first step enables both as a positive control.

```toml
schema_version = 1
languages = ["javascript"]

[functions]
include = ["app.Counter.add"]

[adapters.node]
backend = "source-v1"
typescript_compiler = "native"

[limits]
case_timeout_ms = 60000

[[fixtures]]
function = "app.Counter.add"
cases = [[7]]
receiver = { factory = "Counter", arguments = [10] }
sequence = [
  { action = "call", arguments = "case", metrics = { collection = true, emission = true } },
  { action = "call", arguments = [2], metrics = { collection = false, emission = true } },
  { action = "call", arguments = [3], metrics = { collection = true, emission = false } },
  { action = "call", arguments = [4], metrics = { collection = false, emission = false } },
]
```

Generate and run this policy with the ordinary [automatic-generation commands](automatic-generation.md). TypeScript can select its explicit `native` or `api` compiler. Legacy Node providers, mixed declared/undeclared states and release/collection actions in a live metric schedule remain blockers.

## What the runner verifies

One application process, its independent SDK process and the same prepared source/build remain in use throughout the schedule. Only generated private callers contain checkpoints; application and dependency sources need no coding changes. The caller yields its event loop while the external host changes the actual authenticated SDK endpoint.

The supervisor publishes complete private PID receipts atomically. A caller can reach its first checkpoint before the parent is scheduled; the host waits within the same case budget for completed publication and then verifies actual process-group ownership.

Each transition sets collection and emission separately, verifies that the other flag and completed-call count remain unchanged, and waits for already admitted metric exports to drain before an emission-off window starts. Disabled windows last at least the configured one-second export interval. The ordinary case deadline still applies, so longer schedules need a sufficient budget.

The runner retains actual replies and raw receiver positions in `node-controls.json`. It verifies serial complete trace trees for every call, including calls made with collection disabled. Function metric totals include only collection-enabled trees. Direct positive receipts and the final restoration distinguish suppressed recording from emission-only suppression: measurements recorded with emission off must appear when both switches return on. Plain attempts complete the same checkpoints and fabricate no SDK responses.

The pinned SDK's own processed-span and queue metrics remain separate from function measurements. Unknown metric scopes/names and loss-labelled SDK samples are refused. Final source/process/input checks and direct SDK health remain required.

## Qualification and limits

The maintained corpus contains synchronous, awaited asynchronous and expected-error calls, plus a same-return static mutation which is restored before the final boundary. Complete independent graphs include every intermediate field, descriptor and alias. Nonempty binary stdout/stderr, real control acknowledgements and decoded OTLP are checked through direct execution, generated suites, replay and detached export. It also exercises scalar reduction and its retained suite/replay, followed by current-source promotion before and after a real return-value change. Actual process identities prevent copied reduction evidence from inflating launch counts.

Ten alterations to copied actual control/OTLP evidence check process identities, flag independence, completion counts, disabled windows, restoration, missing traces and withheld retained metrics. The product verifier must refuse every alteration and still accept the preserved original. These checks add no application launches.

```sh
make generation-node-controls-otelc \
  PYTHON=/absolute/path/to/provider/.venv/bin/python \
  OTELC_ROOT=/absolute/path/to/frozen/provider \
  REPORT_DIR=/absolute/path/to/new-control-evidence
```

Select the Node executable with `OTELC_NODE` before invoking the recipe. Qualify each recorded runtime separately. Completed corpus records, source/tool preservation, negative controls, review and protected checks are required before this profile is admitted.

This is diagnostic **equivalence over these tests and observations**. Serial named trace trees do not establish invocation-cookie attribution. Startup-off profiles, arbitrary concurrent schedules, other action targets, general Node dependency/build integration, combined GC/resource schedules, exporter faults and shipping artefacts still require separate qualification. The maintained routes above remain under exact-runtime qualification until their completed records are published. Trace duration and observer waiting time are not equality dimensions.
