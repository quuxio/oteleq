# Hosted native lifetime workflow checks

<!-- markdownlint-disable MD013 -->

Status: a maintained genuine-workflow development driver and hosted job. No passing hosted execution is claimed yet. The separate [public profiles](native-lifetime-generation.md) have literal component evidence; this job must build and execute their actual SDK/application path before it can add runtime evidence.

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

Eight ordinary fixtures cover the fixed boundaries below. Every selected call returns `42`, changes a declared scalar global by its input and exposes the application errno after its work. The C state control has a declared additional instrumented global change. The independent oracle checks the exact return value, initial/final global graphs, integer representation, errno, clean application channels and every repeat. Equal but invalid outcomes refuse.

| Fixtures | Input | Expected lifetime evidence |
| --- | --- | --- |
| C/C++ completed | 5 | One admitted and completed Item; C++ exception flag is false. |
| C same-return state control | 5 | One completed Item and the intended instrumented global difference. |
| C/C++ zero | 0 | An explicit empty lifetime declaration, one selected function span and zero admitted/completed/censored Items. The SDK remains attached and enabled. |
| C/C++ censored | 5 | One admitted Item deliberately left live; shutdown emits one incomplete lifetime after the selected call, with no invented completion or release path. |
| C++ caught unwind | 5 | One completed stack Item whose destructor runs during unwinding; its exception flag is true. The selected function catches the integer exception and returns normally. |

The zero fixtures guard acquisition with the scalar input. C censoring leaves an allocation unreleased; C++ censoring leaves a heap Item undeleted. These are bounded diagnostic sources, unchanged between baseline and instrumented lanes. The caught-unwind fixture does not qualify an exception escaping the selected function or arbitrary exception payloads.

Each fixture declares an explicit two-unit compilation-database target at `-O2`, with one shared type header and a separately compiled helper that receives the object pointer. This prevents the optimiser from removing the intended allocation while both lanes retain the same source and build recipe. The first hosted development run used an elidable single-unit C allocation: its original compiler resolution reported zero emitted `malloc`/`free` calls and final health reported zero admitted resources. The independently declared one-lifetime expectation correctly refused that run. Its failed evidence remains separate from qualification of the corrected fixture.

The driver exercises generated execution, the generated framework, replay and detached exported suites with input `[0]` for zero fixtures and `[5]` for the others. The intentional state difference also exercises scalar reduction, the preserved original report, every trial/confirmation and the reduced framework. Confirmation and reduced-framework runs require `[0]`; each trial report must match its recorded candidate within the declared integer domain 0 to 5. The original generated caller record must carry those same checked arguments. Boolean and floating-point values refuse in both the report and original caller record, including `false` in place of integer zero. A self-consistent report for an unintended input refuses. Copied reports join the original four-launch record; they are not counted as new launches. Original application launch identifiers, evidence bytes/file facts and SDK/source facts remain held through the final audit.

The driver also exercises current-source promotion for each fixture. It checks a dry-run plan before applying the external framework bundle, then runs the suite against the original source and a relocated changed checkout. The original function must now return `43`; a newly added `selected_extra` must return `44`. Both keep the declared input, state/errno effects and lifetime boundary. The two-unit compilation database is relocated explicitly. The oracle requires the complete declared callable inventory and four new original application launch records per case; copied earlier reports cannot satisfy this denominator. Original and changed fixture file facts must remain unchanged through their respective executions. The full driver requires 240 original launch records and 120 instrumented raw receipts; copied observations and altered-copy controls do not increase these counts.

`qualification.json` explicitly labels a successful result as genuine public workflow development. The consumer checks the SDK's complete lifetime/function receipt. A separate driver oracle checks raw signals, literal boundary expectations, the canonical function witness and closed final SDK units. Whole-corpus qualification of all eight fixtures and promotion remains pending. Escaping target errors, all startup/live states, production artefacts and the wider completion checklist remain open.

## Independent raw audit

The maintained corpus declares one normally returning selected call and zero or one Item per process. `native_lifetime_cases.py` supplies closed caller-owned expectations; report metadata cannot choose another boundary. `native_lifetime_otlp.py` decodes every captured trace/metric request independently of the consumer's verified summary. It checks resource/scope identity, the separate lifetime trace, exact creation link, completion/exception flags and admission number. Completion must occur inside the selected root; censoring must end after that root and have no release path or destructor exception flag. Explicit zero permits only the selected function span and no lifetime measurements. Function and lifetime counters, gauges and complete cumulative histograms retain every point. Completed and censored histograms must match their raw span durations; their counter/boundary labels stay distinct. The SDK converts integer ticks to binary64 before scaling, including values above `2**53`.

`native_lifetime_audit.py` reconstructs the fixed corpus policy and checks the caller-owned prebuild expectations. The driver independently supplies `selected` or the declared promoted `selected_extra`; report metadata cannot choose another function or rename its raw signals. The service and loopback endpoint remain bound to that policy. The full policy digest and the separate source/function/lifetime-selection digest must match final health. Exact closed SDK function/lifetime/span counters, control state, export API units, flush and shutdown must explain the complete raw receipt. API batches and actual HTTP requests remain separate: empty API batches need not send an HTTP request. Plain lanes require no telemetry or SDK health.

After the genuine routes, `native_lifetime_refusals.py` checks fourteen altered copies for each of seven language/boundary profiles: 98 controls. Normal/censored/unwind controls cover creation links and completion types. Zero controls instead introduce an unexpected lifetime span or alter the function attribute type. All profiles check missing/malformed spans, HTTP failures, final SDK units, summaries, witnesses and explicit prebuild expectations. No application is started. Original capture file facts are checked before and after; successfully refused copies are removed and their small refusal receipt is retained. Unexpected acceptance leaves its corrupt copy for diagnosis. Copied runner paths remain data and never become new SDK product identities.

The complete archived C and C++ captures supply unchanged policy, protobuf, server-response, expectation and final-health component fixtures under `tests/fixtures/native-lifetime-c-capture/` and `tests/fixtures/native-lifetime-cpp-capture/`, with byte-hash inventories. The C++ fixture also retains the complete original report/typed bundle from successful [run 40205833448](https://github.com/quuxio/oteleq/actions/runs/40205833448), consumer `123e0b2` and SDK `acb13d7`. Its original archive digest is `d4293a5d2601ef3230289eb6706b1e2dc0de2683bc377888ea3bbf04aacc6b81`. Zero/censored/unwind component controls explicitly adapt copied captured bytes through a test-input helper; they are not new runtime evidence. The common function-only oracle retains its existing receipt tests. Raw files have a combined 32 MiB budget checked before each read; these bounds do not establish CPU/memory isolation for arbitrary applications.

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
