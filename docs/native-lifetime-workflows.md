# Hosted native lifetime workflow checks

<!-- markdownlint-disable MD013 -->

Status: the [exact-revision diagnostic qualification](qualification/native-lifetime-workflows-2026-10-25.json) covers 100 original application launches, 50 instrumented receipts and 26 reports, including nine current-source promotion reports, from [run 40211685995](https://github.com/quuxio/oteleq/actions/runs/40211685995). A separate retained-byte audit checks complete raw signals and original source/product hashes; 28 altered-capture controls refuse. This qualifies the three named completed-lifetime fixtures and routes below. Broader profiles remain open.

## Run in one original environment

The `Native lifetime workflow qualification` GitHub Actions workflow uses Ubuntu 24.04, LLVM 22, Python 3.12 and Rust 1.98.1. It checks out the exact consumer revision and reviewed otelc source `acb13d7735526448209df37b7e6b98e5717befdb`, which includes the object/ABI errno correction and both native lifetime ABIs. It builds a new noncoverage shared SDK and the consumer in the same job. Existing build manifests are neither copied nor rebound to another path or filesystem identity.

The workflow starts for changes to its own definition or driver and supports manual dispatch after it is available on main. It uses read-only repository permission, disables persisted checkout credentials and passes no account secrets to SDK or application processes. LLVM installation reuses the pinned SDK's verified-key installation script, with matching Clang frontend tools. SDK and application commands retain their original output and failures. Qualification commands require the configured 8 GiB free-space floor before starting.

To run the driver in a suitable original Linux environment:

```sh
python tests/qualify_native_lifetimes.py \
  --otelc-root /absolute/reviewed-otelc-checkout \
  --sdk-build /absolute/new-native-sdk \
  --report-dir /absolute/new-lifetime-evidence \
  --cli /absolute/quux-oteleq
```

Both output directories must be new and outside application/tool source inputs, including physical case aliases. The driver rejects dirty consumer or SDK checkouts and verifies the pinned SDK commit before writing the initial source snapshot or starting its build. It then snapshots tracked source facts, builds the shared library without coverage and freezes both SDK products. The generated tests remain in external transient workspaces.

## Corpus and acceptance boundary

Three ordinary fixtures cover C resource completion, C++ object completion and a C same-return/global-state difference. Each call creates and releases one `Item`, changes a declared scalar global and exposes the application errno after the lifetime operation. The independent application oracle checks the exact return value, initial/final global graphs, integer representation, errno, clean application channels and every repeat. Equal but invalid outcomes refuse.

Each fixture declares an explicit two-unit compilation-database target at `-O2`, with one shared type header and a separately compiled helper that receives the object pointer. This prevents the optimiser from removing the intended allocation while both lanes retain the same source and build recipe. The first hosted development run used an elidable single-unit C allocation: its original compiler resolution reported zero emitted `malloc`/`free` calls and final health reported zero admitted resources. The independently declared one-lifetime expectation correctly refused that run. Its failed evidence remains separate from qualification of the corrected fixture.

The driver exercises generated execution, the generated framework, replay and detached exported suites with the independently declared input `[5]`. The intentional state difference also exercises scalar reduction, the preserved original report, every trial/confirmation and the reduced framework. Confirmation and reduced-framework runs require `[0]`; each trial report must match its recorded candidate within the declared integer domain 0 to 5. The original generated caller record must carry those same checked arguments. Boolean and floating-point values refuse in both the report and original caller record, including `false` in place of integer zero. A self-consistent report for an unintended input refuses. Copied reports join the original four-launch record; they are not counted as new launches. Original application launch identifiers, evidence bytes/file facts and SDK/source facts remain held through the final audit.

The driver also exercises current-source promotion for each fixture. It checks a dry-run plan before applying the external framework bundle, then runs the suite against the original source and a relocated changed checkout. The original function must now return `43`; a newly added `selected_extra` must return `44`. Both keep the declared state/errno effects and one completed `Item` per call. The two-unit compilation database is relocated explicitly. The oracle requires the complete declared callable inventory and four new original application launch records per case; copied earlier reports cannot satisfy this denominator. Original and changed fixture file facts must remain unchanged through their respective executions.

The original `qualification.json` labels its successful execution as genuine public workflow development. The separate published record adds the completed retained-byte audit and actual altered-capture refusals for that exact execution; it does not change the original record or executor identity. The consumer checks the SDK's complete lifetime/function receipt. A separate driver oracle checks raw signals, literal completed-instance expectations, the canonical function witness and closed final SDK units. The audit covers 100 distinct launch identifiers and 104 observations, including four copied shrink observations that add no launches. All 1,048 selected original evidence files remain unchanged. Zero/censored/exception profiles, all startup/live states, production artefacts and the wider completion checklist remain open.

## Independent raw audit

The maintained corpus declares one normal selected call and one completed `Item` per process. `native_lifetime_otlp.py` decodes every captured trace/metric request independently of the consumer's verified summary. It checks resource/scope identity, the separate lifetime trace, exact creation link, creation/release times inside the selected root, completion/exception flags and admission number. Function and lifetime counters, gauges and complete cumulative histograms retain every point; the completed histogram must match the duration measured by the raw lifetime span. The SDK converts integer ticks to binary64 before scaling, including values above `2**53`.

`native_lifetime_audit.py` reconstructs the fixed corpus policy and checks the caller-owned prebuild expectations. The driver independently supplies `selected` or the declared promoted `selected_extra`; report metadata cannot choose another function or rename its raw signals. The service and loopback endpoint remain bound to that policy. The full policy digest and the separate source/function/lifetime-selection digest must match final health. Exact closed SDK function/lifetime/span counters, control state, export API units, flush and shutdown must explain the complete raw receipt. API batches and actual HTTP requests remain separate: empty API batches need not send an HTTP request. Plain lanes require no telemetry or SDK health.

After the genuine routes, `native_lifetime_refusals.py` checks fourteen altered copies from an actual successful capture for each language. Controls cover creation links, missing or malformed spans, wire types, HTTP failures, final SDK units, summaries, witnesses and prebuild expectations. No application is started. Original capture file facts are checked before and after; successfully refused copies are removed and their small refusal receipt is retained. Unexpected acceptance leaves its corrupt copy for diagnosis. Copied runner paths remain data and never become new SDK product identities.

The complete archived C capture supplies unchanged policy, protobuf, server-response, expectation and final-health component fixtures under `tests/fixtures/native-lifetime-c-capture/`, with a byte-hash inventory. C++ component controls use an explicitly adapted wire schema and are not C++ runtime qualification. The common function-only oracle retains its existing receipt tests. Raw files have a combined 32 MiB budget checked before each read; these bounds do not establish CPU/memory isolation for arbitrary applications.

The driver prints concise starting/completed stage events and elapsed time separately from command output. Application stdout/stderr stay in their own captured channels. `qualification.json` is the final success record; a stage with no completion event or an absent summary remains incomplete evidence.

## Evidence and component tests

The workflow retains original evidence, SDK build logs/products and exact source archives for seven days, including failed runs. Artifact names include both run and attempt IDs. A missing success summary or failed job remains incomplete evidence. Downloaded archives do not acquire the original job's filesystem identities and cannot silently recertify its products.

The driver reads the public run envelope: top-level exit/source-preservation/blocker fields, the single ready inventory entry, and the case's nested comparator verdict. It binds the selected function and case identifier before checking observations. A later development run completed the corrected C comparison, then exposed the driver's earlier incorrect report-shape assumption. That failed driver run does not establish completion of the full corpus; its retained report supplies the regression shape.

The complete unchanged C report and typed bundle from [run 40204568942](https://github.com/quuxio/oteleq/actions/runs/40204568942), consumer revision `aa19bd27414e0099424111804a5c073b5e406f7f`, are retained in `tests/fixtures/native-lifetime-workflow-c-report.json` and `tests/fixtures/native-lifetime-workflow-c-typed-bundle.json`. Their regression checks fixed byte hashes, the actual report envelope and all four captured observation repeats. Original filesystem/ownership auditing is mocked in that component regression; historical runner paths remain data and are not used as new input locations or product identities. The original downloaded archive has SHA-256 `b9b382f95fb9351be22af2700f4b010f4a2c046cab09af7f9e77846511cc11ba`.

Graph, outcome, termination and literal receipt comparisons use the independent oracle's strict JSON comparison. Python equality does not distinguish `true` from `1` or `32` from `32.0`; those wire-type substitutions must refuse. Actual-bundle controls alter all 28 signedness or bit-width fields and check rejection. Lifetime completion/path, function/span/pending/loss counters and retained health comparisons preserve the same distinctions.

```sh
make native-lifetime-workflow-check PYTHON=/absolute/path/to/python
```

These component tests use unchanged archived records, explicit literal schemas and mocked orchestration, enforce separate 80% statement floors for the driver and every oracle module, and start no SDK/compiler/application workload. Required documentation CI includes this gate. Changes to raw oracle modules also trigger the original-environment hosted workflow. Workflow syntax controls separately pin the reviewed source, read-only permission, original-job build and failure retention.
