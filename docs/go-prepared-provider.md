# Rebuilt Go provider integration

Status: the explicit `source-v1` generator route has [80-launch diagnostic qualification](qualification/go-source-provider-2026-10-24.json) for the recorded untagged build-4/prepared-tools-1 SDK candidate on macOS ARM64. It connects public negotiation/build preparation, independent caller/context checks, owned execution and decoded Go OTLP/health through scalar, receiver, replay, framework, detached, reduction and current-source promotion experiments. The corpus detects same-return instance/global/alias differences and preserves source/tool inputs. Other builds, live controls, actions and platforms remain open. The default [legacy retained Go profile](go-build-bundles.md) keeps its separate qualification.

## Explicit protocol boundary

The reader accepts the explicit `go-source-v1` descriptor: untagged build 4; configuration 2; request, plan, prepared, command and execution 1; health 4; embedded SDK; `source_complete = false`. The candidate tagged route below separately requires build 5 and inspection 2. Build metadata must bind `runtime_protocols = {config: 2, health: 4}`. Missing or additional fields, another profile, substituted versions and numeric/boolean coercions are refused. Earlier build-2/build-3 evidence belongs to its separately frozen source; the active reader does not reinterpret it. Metadata cannot select an older combined compiler/launcher or qualify source closure.

The application and SDK share one native Go PID. The prepared supervisor has a separate PID. The complete consumer must bind both to its actual owned process group and fixed build/launch recipe before accepting runtime evidence. Receiving a valid descriptor alone cannot establish that relation.

## Development generator route

Select the rebuilt provider explicitly in the application policy:

```toml
[adapters.go]
backend = "source-v1"
module_roots = ["."]
```

Pass that file with `plan --config /absolute/path/to/equivalence.toml`, then use the ordinary `generate` and `run` commands. The default backend remains `legacy`. The development source route requires an explicit module root. The linked qualification covers untagged single-call workflows; tagged builds and [call-only receiver sequences](ordered-sequences.md#candidate-go-call-sequences) are separate candidates with pending workflow qualification. Live metric schedules and other actions remain visible blockers. Unsupported provider formats cannot fall back to the legacy provider.

Planning freezes the public SDK entrypoint, Go runtime/inspector sources, host Python installation and executable bytecode caches, selected native compiler, fixed installed weaver, pinned upstream bundle and complete common-policy/protocol replies. `go-protocols --prepared-tools` must advertise the closed build-4 descriptor with `prepared_tools = 1`. Each attempt uses fixed `go-build --prepared-tools` and `go --prepare-only` recipes. Build and preparation replies supply checked data, never executable commands. Prepared-tool reuse must preserve the installation independently of the application's private module/build caches; the consumer refuses changed tool identities.

The independent Go OTLP reader checks exact service/SDK resources and scopes, selected call trees and factory ordering, cumulative function/error metrics and duration histograms. Disabled lifetime hooks permit only their two explicit zero live gauges. Actual final SDK health, owned native PID and downstream receipt remain separate evidence in `go-verified-telemetry.json`; the comparator receives only its six supported witness fields. Missing signals, unknown data, changed inputs or failed lifecycle checks cannot qualify a case. The linked qualification names the exact SDK, consumer, platform, observations and remaining limits; these checks do not qualify another profile by themselves.

### Candidate tagged builds

An explicit nonempty `adapters.go.build_tags` list selects build 5 and inspection 2. For example, add `build_tags = ["feature", "tools", "\u03c0"]` to the policy above. The source backend freezes sorted, distinct literal names, with at most 128 names and 256 UTF-8 bytes per name. The pinned Go inspector validates Unicode tag grammar; Python character categories do not define it. The legacy backend keeps its ASCII tag interface.

Planning requires the separate `go-protocols --prepared-tools --build-tags` descriptor. Independent caller discovery binds the requested tags and the complete active package/source/embed denominator before SDK compilation. The fixed public build command passes each name as a separate `--build-tag` argument. Both reconstructed compiler recipes require the same single literal `-tags=...` flag; the untagged build-4 recipe cannot accept a tagged receipt.

The reader additionally binds build-5 `command_evidence` to every retained compiler log. It reconstructs the tooling import guard as the negation of the first requested tag, so an explicit `tools` tag cannot turn that private tooling package into application code. Retained tag, inventory, command, log and helper substitutions refuse independently. Component tests and compiler-only discovery are implemented; public generated/retained qualification of this candidate is still pending. The existing 80-launch record remains untagged evidence.

## Independent inputs and build recipes

`go_files` snapshots canonical original inputs without executing application code. Reads refuse links, special files, incomplete directory walks, changed parent directories, altered bytes/file facts and reached file/tree budgets. Each tree is bounded to 4,096 files and 256 MiB; JSON metadata is bounded to 32 MiB. Original device/inode, mode, ownership, size and timestamps remain distinct from content identity.

Canonical data seals also bind each stored input catalogue and its file facts. Editing a frozen object's dictionaries, including numeric/boolean substitutions or rewriting them to match changed files, cannot turn it into a newly accepted snapshot. Build caller data is sealed before provider records are read; accepted receipt/inventory/evidence values remain bound on every recheck.

`go_build.Intent` supplies the original source snapshot, SDK and independently prepared context snapshot, selected declarations, canonical tags, actual tool identities and original module/settings records. The reader checks the complete explicitly selected build-4 or build-5 receipt against these caller-owned facts. It reconstructs all 15 compiler commands for the initial synchronous call profile, with no context task/HTTP hooks or lifetime selections. Returned argv is compared as data and never executed. Both binaries, the complete compiler channels, compiler inventory, selected source locations and private input catalogues are retained and rechecked after acceptance. Existing module resolutions and original module/language/toolchain/GODEBUG settings remain bound to the independent inputs.

Before invoking the producer, the caller uses `go_context.prepare(bundle, output)` to create the expected context in a new external directory. The consumer checks the pinned official `go.opentelemetry.io/otelc@v1.0.1` bundle digest, reads exactly thirteen fixed ordinary members and applies the reviewed no-task recipe. It preserves nine upstream files, patches four and adds eight, including the exact manifest and attribution. The expected telemetry/baggage extensions and rules are fixed consumer literals; no SDK renderer or producer output supplies the expected bytes. The context snapshot retains file facts and refuses later changes. Task inheritance, HTTP-enabled builds and other recipes require explicit extensions and separate qualification.

The caller's compiler-only `discover.go` frontend is copied into each attempt's new mode-0700 `go-frontend` directory before execution. Its mode-0600 source, original compiler/export-data identities and file facts remain in the caller read catalogue after CLI cleanup. An existing frontend directory, application overlap or changed retained source refuses reuse. Earlier records can name the CLI's temporary extracted frontend, which is removed when that CLI exits; those records establish its checked execution-window identity but do not retain that original file for later physical reinspection. New retention does not repair or broaden the older evidence.

Private SDK/context bytes must match the caller's frozen profiles; original program files must retain their bytes in the private copy. `go_hooks` independently reconstructs every generated helper, rule and tooling import for the call-only profile, including the build-4 implicit telemetry callback. It checks the exact private file denominator, selection guard, selected function indices, receiver bindings and main shutdown hook. Reserved-path/identifier collisions, extra private code and rehashed altered helpers refuse. Only closed compiler-profile error predicates can enter the generated rule. The reader never imports an SDK renderer to establish expected bytes. Broader compiler/context/action profiles require separate consumer integration and qualification.

## Independent preparation

`go_prepared.Intent` binds a checked build to its separate runtime directory, frozen producer modules, selected supervisor interpreter, complete common policy, literal arguments and baseline/instrumented lane. The reader reconstructs the request, binary/cwd plan, full configuration2, prepared manifest and fixed supervisor invocation. All retained private records and the whole public response must agree, including their different policy, selection and prepared-metadata digest encodings. A new launch refuses an already used runtime. An explicit retained-only metadata check starts no process.

Rehashed request, configuration, producer or binary substitutions cannot change the caller's intent. Private records remain bounded owned mode-0600 files in a canonical mode-0700 runtime. Their bytes and file facts are checked again after decoding and before sealing. Plain lanes cannot introduce SDK configuration. This verifies preparation metadata; it does not establish that the intended application subsequently ran.

The caller intent and whole response are sealed before the prepared launch records are read. Subsequent rechecks also refuse in-memory changes to policy destinations, command arguments, interpreter identities and retained evidence dictionaries. A late caller change cannot become the new expectation after the recipe comparison. The independent checks still use caller-owned fixed commands.

## Owned process and generated call boundary

`go_launch.Session` uses the shared process monitor and its original time/output budgets and group cleanup. The generated private Go helper publishes readiness, then waits for a host release. The barrier precedes receiver construction, state observations and calls. Application stdout/stderr carry no rendezvous messages. The helper validates private ownership/modes, canonical paths, nonce and release bytes and has its own bounded wait. Both links to a published marker remain retained, preserving its inode and file facts through host inspection and final audit. The helper is compiled in the reserved `oteleq_generated_control` package, outside application lexical scope: an application function named `len` or another shadowed builtin cannot run through the readiness code. Its complete source/package inputs enter independent caller discovery. A pre-existing file, directory or symlink at the reserved path refuses discovery. This package change requires its own generated-workflow qualification; older records retain their original helper recipe.

The host queries only the known supervisor and candidate application with fixed `/bin/ps` arguments, without a shell or SDK-selected command. Both native parent and process group must match the actual consumer-owned supervisor. The consumer host may be PID 1; supervisor, application and group identities must remain greater than 1. Component tests simulate that parent boundary; they do not qualify execution in a PID-1 container. A stale release, different command, malformed readiness, changed marker or early completion cannot supply a successful binding. This POSIX path has separate actual-provider qualification requirements for each published platform.

`go_execution.bind` independently checks both closed start records and complete prepared digests before the host releases the call. `finish` joins the same native PID to a successful diagnostic exit, unchanged start records and inputs, exact embedded SDK identity and the directly read final health report. It refuses SDK failures, interruption, incomplete input checks and failed final lifecycle. Accepted mutable dictionaries have canonical seals. SDK execution readers never establish the consumer's expected result.

This establishes ownership and final report consistency. Independent decoded OTLP accounting still uses `go_health.qualify`; a successful SDK drain does not prove receipt. The development build-4 pair checks a complete literal scalar/global observation, actual pre-call native ownership, one function span and direct metric batches. All 21 expected context files are independently reconstructed before its build. Earlier build-3 pairs used a separately caller-pinned context and retain that limitation. The separate 80-launch record qualifies its listed public scalar/receiver and retained routes; live controls and broader workloads remain open.

## Independent materialised caller discovery

`go_caller.discover` independently uses the selected Go compiler, `go list` and the consumer's own `go/types` inventory after diagnostic caller generation and before an SDK build. It binds the generated main separately from its source package, re-resolves target/factory locations after helper insertion and freezes all active module compiler inputs, including embedded files. Main, importing-library and declared receiver callers retain distinct package and receiver identities. Compiler, inventory-tool and selected export-data bytes/file facts are sealed and rechecked; application initialisers are not executed. `Caller.build_intent` supplies these expected active-input/package denominators and canonical tags to the build reader, which refuses omissions or substitutions even when individual returned file hashes are valid. The original component-only intent remains separate and does not assert this independent discovery. Tagged execution requires the candidate build-5 route above. The separate public qualification covers the recorded untagged workflows; it does not admit tagged execution or another callable/build profile.

## Independent health reader

`go_health.read(runtime)` reads a completed `health.json` only from an owned canonical mode-0700 directory. The report must be an owned mode-0600 bounded regular file with one link. Links, FIFOs, replaced files, changed bytes/file facts, oversized reports and duplicate JSON keys are refused. The reader does not import the provider or execute retained code.

`validate` binds the closed schema-4 report to caller-owned application PID, policy digest and compiler selection digest. The reader retains the complete raw controls, lifecycle, probe, HTTP, exporter and unavailable-delivery fields. A running snapshot is not assumed to be atomic or quiescent.

`qualify` separately requires a final successful flush/shutdown, closed clean probes, exact independently counted function/auxiliary completions, no active or lost observations and matching decoded trace/metric batch receipt. Trace span totals and queue loss/pending counts are checked separately. Metric point totals are not available from the SDK exporter record: the reader retains independent received points and leaves the SDK point total explicitly unavailable.

HTTP recording observations follow the trace SDK: either exact start/end/active/closed counters or the single field `observed = false`. Final qualification requires closed HTTP accounting, zero active operations and complete independently decoded HTTP spans in the diagnostic full-sampling profile. An unread response body cannot disappear behind a successful SDK flush. HTTP EOF/close-attempt boundaries are separate from successful resource release or GC. The general raw validator does not infer complete delivery from sampled or unobserved traces.

Observed GC, successful resource release, pending objects and unreleased resources remain distinct counters. A clean SDK drain does not invent a GC or release boundary for a censored object. An unobserved trace exporter supplies no fabricated zero queue counters. The SDK's downstream and partial-rejection fields remain unavailable; actual receipt belongs to the independent receiver.

## Component checks and remaining work

The independent `go_control` component reads the existing private TCP endpoint, checks closed status replies, sets collection and emission independently and binds running health to the actual native PID, policy and compiled selection. Paused call-only health requires complete selected probes, no losses and live exporters; asynchronous exporter counters remain separate snapshots. The completed emission-off reply supplies the SDK's export barrier. The explicit [live schedule](go-metric-controls.md) now connects private call checkpoints, the original owned process monitor, retained schedule readers and collection-dependent metric oracles. Its actual-provider and retained-workflow qualification remains in progress.

```sh
PYTHONPATH=tests python -m unittest -v \
  test_generation_go_files test_generation_go_caller test_generation_go_context test_generation_go_source_build \
  test_generation_go_hooks test_generation_go_prepared test_generation_go_health \
  test_generation_go_execution test_generation_go_launch test_generation_go_rendezvous test_generation_go_control \
  test_generation_go_live test_generation_go_control_receipt \
  test_generation_go_source test_generation_go_source_run test_generation_go_telemetry
```

The maintained literal fixtures cover protocol substitutions, wrong process/policy/selection, compiler/source/module changes, rehashed private copies/helpers and launch recipes, extra/missing private code, invalid rule bindings, missing/unknown fields, exact unsigned counters, pre-call ownership/release, live/final separation, unclosed HTTP operations, censored lifetimes, unavailable trace observation, failed exports/drains, receiver disagreements and private-file races. Context tests check the complete 21-file hash denominator, selected archive members, exact patches, pinned attribution, source races and fresh private output. The compact archive unit fixture stubs the file-hash boundary; actual full-release reconstruction has separate development execution evidence. The provider/generator modules and attribution file are embedded/retained with the generator, with independent 80% line-coverage floors. The actual compiled Go readiness/checkpoint package has separate race checks, invalid-binding/release cases and an 80% statement floor. Frozen literal helper/context fixtures are independent of the consumer renderers and need explicit review when a recipe changes.

Run the maintained receiver/framework/export/reduction corpus with a compatible SDK checkout and prepared Go tooling:

```sh
make generation-go-source-otelc \
  PYTHON=/absolute/path/to/qualified/python \
  OTELC_ROOT=/absolute/path/to/prepared/otelc \
  REPORT_DIR=/absolute/path/to/new-evidence
```

The command keeps the existing receiver corpus's complete literal field/alias/panic oracles and adds native ownership, exact selected target/factory receipt and copied-probe refusal checks. It creates fresh evidence and does not retry failed operations. Its separate execution must pass before being cited as a new qualification. The original 80-launch record also checks scalar/global outcomes and changed-source promotion with added library discovery.

For the candidate tagged workflow, invoke `tests/qualify_go_receivers.py` with the same `--otelc-root`, `--report-dir` and `--cli` values, `--backend source-v1` and repeated `--build-tag NAME` arguments. The fixtures retain the complete field/result oracles and add an excluded alternative factory with a different value. Each tagged attempt also checks both compiler flags, the active source choice, the tooling import guard and every retained compiler channel identity. A completed run is required before claiming tagged receiver or retained-suite qualification.

Live metric schedules require their pending actual-provider and retained-workflow qualification. Additional build/context recipes and richer source/dependency graphs require new integration and evidence. Broader Go builds, cgo/workspaces, asynchronous/resource actions, shipping artefacts and the [full completion checklist](completion.md) remain open.

The intended result remains **equivalence over these tests and observations**.
