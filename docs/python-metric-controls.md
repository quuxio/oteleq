# Python live metric schedules

Status: implementation candidate; complete workflow qualification and protected delivery are pending. The first Python 3.12 origin-v2 smoke run completed two baseline and two instrumented applications. Its complete literal state/alias graphs, native origins, controls, SDK health, OTLP and comparison were rechecked without new target launches. This is initial diagnostic evidence, not admission of every profile or workload.

Explicit [prepared origin-v2](python-prepared-provider.md) and [cached-loader profile3](python-cache-context.md) receiver call sequences can declare independent metric collection and emission states. One unchanged native application and SDK pair execute the whole instrumented schedule. Target sources require no imports, decorators or control calls. A generated private helper pauses each diagnostic call while the external host changes the real SDK controls.

## Declare the schedule

Use the existing project policy and a supported plain receiver fixture. For an `app.Counter.add` method, the following schedule supplies one generated argument and four fixed calls:

```toml
schema_version = 1
languages = ["python"]

[adapters.python]
backend = "prepared"
profile = "python-native-origins-v2"

[functions]
include = ["app.Counter.add"]

[[fixtures]]
function = "app.Counter.add"
cases = [[1]]
receiver = { factory = "Counter", arguments = [10] }
sequence = [
  { action = "call", arguments = "case", metrics = { collection = true, emission = true } },
  { action = "call", arguments = [2], metrics = { collection = false, emission = true } },
  { action = "call", arguments = [3], metrics = { collection = true, emission = false } },
  { action = "call", arguments = [4], metrics = { collection = false, emission = false } },
  { action = "call", arguments = [5], metrics = { collection = true, emission = true } },
]
```

Use the normal [plan, generate and run commands](automatic-generation.md#build-and-run). The selected provider, native tools and installed SDK dependencies must match the chosen Python environment before planning. Preparation must not introduce new products into an already frozen catalogue.

Every call must declare both flags, and at least one call must have collection and emission enabled. The first call fixes the actual startup state; it may request any of the four states. Broader startup/profile qualification remains pending. Legacy and input-only prepared profiles refuse live schedules. A source constructor or factory can finish before the first checkpoint: its trace and its measurements follow the initial state and are counted separately.

Add [typed return expectations](expected-returns.md) where the intended values are known. Repeated equality alone cannot establish that both lanes returned the intended result.

## What is checked

The host binds the actual supervisor, application and SDK process identities, process group, launch ID and policy. It reads the private authenticated control endpoint and retains command replies plus independently reconstructed live health reports. Missing or changed checkpoints, wrong initial flags, active calls at a boundary, failed exports and incomplete final health cannot pass.

The host changes collection and emission separately. A drained emission-off acknowledgement precedes the corresponding call. Disabled windows are held for a full configured export interval and checked against literal downstream metric receipt. Traces remain required for every complete selected call tree. Live queue counts remain explicitly unavailable; final SDK accounting and direct decoded receipt establish the final drain.

Only collection-enabled call trees contribute function metrics. Measurement counts, exception counts and optional exemplars must refer to that collected span set. Measurements collected while emission is off must appear after emission is restored. The host restores both flags before the application exits, then verifies the final SDK report, native execution and both OTLP signals. The baseline uses the same private checkpoints without inventing SDK replies or emitting telemetry.

`python-controls.json` retains the requested states, process bindings, command/health replies, receipt positions and held intervals. `python-verified-controls.json` records the checked code counts and collected span denominator. Endpoint authentication keys are excluded from these records. Original private SDK runtime files still require private retention.

## Scope and remaining qualification

### Run the maintained workflow qualification

Use an owned SDK copy whose native tools are already built for the selected locked Python environment. The output and audit directories must be new, separate and outside both source trees:

```sh
make generation-python-controls-otelc \
  PYTHON=/path/to/locked/python \
  OTELC_ROOT=/path/to/owned/otelc \
  REPORT_DIR=/path/to/new/evidence \
  AUDIT_DIR=/path/to/new/audit \
  PYTHON_CONTROL_PROFILE=python-native-origins-v2 \
  PYTHON_CONTROL_STARTUP=both-off
```

The supported startup choices are `both-on`, `collection-off`, `emission-off` and `both-off`. Repeat with `PYTHON_CONTROL_PROFILE=python-native-cache-origins-v3` for ordinary caches and with each qualified Python environment. Each invocation retains six literal receiver methods, constructor/factory setup, recursion, exceptions and an intentional intermediate difference. It exercises generated tests, replay, unittest, detached exports, scalar reduction and promotion against original and changed current sources.

For a retained-only audit, keep the same evidence directory, profile, startup state, interpreter and SDK, select a new `AUDIT_DIR`, and add `GENERATION_ARGS=--retained-only`. Comparisons are recomputed in that separate directory. Original receipt bytes and file identity/timestamp facts must remain unchanged, and no target applications are started. A started or partial execution is never automatically restarted. Inspect its terminal command receipts before recovery.

This candidate covers declared synchronous Python receiver calls under explicit prepared origin/cache profiles. It keeps the existing source/installed-input guards and ordinary typed observations. It does not add asynchronous schedules, lifetime controls, arbitrary observation roots or invocation cookies. Serial trace grouping remains distinct from the [action witness](action-witness.md).

All startup states, both selected Python runtimes/profiles, constructor/factory and recursive/error cases, generated/replayed/framework/detached/reduced/promoted routes, altered-evidence controls and source preservation still require the maintained complete qualification corpus. Independent review, the full final gate, rendered guidance, protected checks and merge remain required. The [full project checklist](completion.md) stays open.

The result remains **equivalence over these tests and observations**.
