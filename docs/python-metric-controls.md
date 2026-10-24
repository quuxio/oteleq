# Python live metric schedules

Status: [recorded diagnostic qualification](qualification/python-metric-controls-2026-10-24.json) covers 3,008 actual applications across Python 3.12.15/3.14.8, both explicit origin/cache profiles and all four initial metric states on macOS ARM64. It checks declared synchronous receiver workflows against the recorded SDK and native inputs. Other providers, workloads and the full project remain separate acceptance work.

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

Every call must declare both flags, and at least one call must have collection and emission enabled. The first call fixes the actual startup state; it may request any of the four states. The recorded matrix checks each initial state in both profiles and runtimes. Legacy and input-only prepared profiles refuse live schedules. A source constructor or factory can finish before the first checkpoint: its trace and its measurements follow the initial state and are counted separately.

Add [typed return expectations](expected-returns.md) where the intended values are known. Repeated equality alone cannot establish that both lanes returned the intended result.

## What is checked

The host binds the actual supervisor, application and SDK process identities, process group, launch ID and policy. It reads the private authenticated control endpoint and retains command replies plus independently reconstructed live health reports. Missing or changed checkpoints, wrong initial flags, active calls at a boundary, failed exports and incomplete final health cannot pass.

The private worker publishes each complete checkpoint without replacing an existing boundary. Its temporary hard link remains until the host acknowledges the boundary, so removing that link cannot change the file metadata during the host's stable-file read. The worker then removes the temporary link. This ordering is covered by a deterministic regression; changed or incomplete checkpoint files still fail capture.

The host changes collection and emission separately. A drained emission-off acknowledgement precedes the corresponding call. Disabled windows are held for a full configured export interval and checked against literal downstream metric receipt. Traces remain required for every complete selected call tree. Live queue counts remain explicitly unavailable; final SDK accounting and direct decoded receipt establish the final drain.

Only collection-enabled call trees contribute function metrics. Measurement counts, exception counts and optional exemplars must refer to that collected span set. Measurements collected while emission is off must appear after emission is restored. The host restores both flags before the application exits, then verifies the final SDK report, native execution and both OTLP signals. The baseline uses the same private checkpoints without inventing SDK replies or emitting telemetry.

`python-controls.json` retains the requested states, process bindings, command/health replies, receipt positions and held intervals. `python-verified-controls.json` records the checked code counts and collected span denominator. Endpoint authentication keys are excluded from these records. Original private SDK runtime files still require private retention.

## Recorded scope and reproduction

The [24 October record](qualification/python-metric-controls-2026-10-24.json) binds runtime and retained-only verifier `7495d31`, CLI SHA-256 `e6973a648d05897900a378d6f14195803698d2f67818b8e142d429293a69c5f3` and frozen otelc `ce4cf74`. All 16 configurations pass: two Python runtimes, two profiles and four initial states. The record contains 3,008 actual applications, 1,504 SDK processes, 608 reports, 3,072 complete raw/typed observations, 768 independently recomputed comparisons, 80 altered-comparison refusals and 144 altered-live-evidence refusals. The observations include 64 copied shrink originals; those copies add no launches. Every final audit preserves original evidence bytes and file facts and starts no target applications.

Each locked runtime retains 1,519 provider catalogue entries, including 1,421 installed files and 11 native tool files. Both complete 389-file SDK source copies match the recorded source archive. Exact source/tool identities and the retained route denominators are in the record. This is the executed provider; a static compatibility bridge or newer SDK commit does not add new execution evidence.

Earlier smoke and failed matrix results remain separate. The old runtime failed a checkpoint stable-file read after 12 successful configurations; three configurations were not started. The failed configuration retains 185 actual application starts and 92 SDK starts outside the successful denominator. The corrected hard-link publication receives this fresh complete matrix. Its deterministic regression fails without the fix; strict checkpoint checks remain in place.

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

The audit also checks nine altered-evidence refusals: missing calls, wrong process/startup identities, a short disabled interval, a missing export barrier, a changed requested state, extra collected calls and a missing creation trace. Seven control-file byte records are substituted in memory, and two raw OTLP corpora are changed separately. The checked native execution and original files stay fixed. These are decoder refusal controls; they are not additional application executions.

The recorded profile covers declared synchronous Python receiver calls under explicit prepared origin/cache profiles. It keeps the existing source/installed-input guards and ordinary typed observations. It does not add asynchronous schedules, lifetime controls, arbitrary observation roots or invocation cookies. Serial trace grouping remains distinct from the [action witness](action-witness.md).

The complete matrix covers all initial states, both recorded runtimes/profiles, source constructors/factories, recursive/error cases, generated/replayed/framework/detached/reduced/promoted routes, altered-evidence controls and source preservation. A different callable/build/loader shape, runtime, provider or asynchronous/resource profile requires new qualification. The [full project checklist](completion.md) stays open.

The result remains **equivalence over these tests and observations**.
