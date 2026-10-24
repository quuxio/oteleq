# Rebuilt Go provider integration

Status: independent public-protocol, file/build, prepared-recipe and health readers are implemented. Generated integration, independent helper reproduction, owned launch integration and actual-provider workflow qualification remain in progress. These components do not admit the rebuilt provider through the scalar generator. The existing [retained Go build/replay profile](go-build-bundles.md) remains a separate recorded contract.

## Explicit protocol boundary

The reader accepts the explicit `go-source-v1` descriptor: build 3; configuration 2; request, plan, prepared, command and execution 1; health 4; embedded SDK; `source_complete = false`. Build metadata must bind `runtime_protocols = {config: 2, health: 4}`. Missing or additional fields, another profile, substituted versions and numeric/boolean coercions are refused. Earlier build2/config1/health3 evidence belongs to its separately frozen source; the active reader does not reinterpret it. Metadata cannot select an older combined compiler/launcher or qualify source closure.

The application and SDK share one native Go PID. The prepared supervisor has a separate PID. The complete consumer must bind both to its actual owned process group and fixed build/launch recipe before accepting runtime evidence. Receiving a valid descriptor alone cannot establish that relation.

## Independent inputs and build recipes

`go_files` snapshots canonical original inputs without executing application code. Reads refuse links, special files, incomplete directory walks, changed parent directories, altered bytes/file facts and reached file/tree budgets. Each tree is bounded to 4,096 files and 256 MiB; JSON metadata is bounded to 32 MiB. Original device/inode, mode, ownership, size and timestamps remain distinct from content identity.

`go_build.Intent` supplies the original source snapshot, SDK and separately pinned context snapshot, selected declarations, actual tool identities and original module/settings records. The reader checks the complete build3 receipt against these caller-owned facts. It reconstructs all 15 compiler commands for the initial synchronous call profile, with no context task/HTTP hooks or lifetime selections. Returned argv is compared as data and never executed. Both binaries, the complete compiler channels, compiler inventory, selected source locations and private input catalogues are retained and rechecked after acceptance. Existing module resolutions and original module/language/toolchain/GODEBUG settings remain bound to the independent inputs.

Private SDK/context bytes must match the caller's frozen profiles; original program files must retain their bytes in the private copy. Generated helpers and rules are recorded and sealed against later changes. Independent reproduction of those generated additions is still required before admitting generated execution. HTTP-enabled compiler recipes and broader context/action profiles need separate consumer implementation and qualification.

## Independent preparation

`go_prepared.Intent` binds a checked build to its separate runtime directory, frozen producer modules, selected supervisor interpreter, complete common policy, literal arguments and baseline/instrumented lane. The reader reconstructs the request, binary/cwd plan, full configuration2, prepared manifest and fixed supervisor invocation. All retained private records and the whole public response must agree, including their different policy, selection and prepared-metadata digest encodings. A new launch refuses an already used runtime. An explicit retained-only metadata check starts no process.

Rehashed request, configuration, producer or binary substitutions cannot change the caller's intent. Private records remain bounded owned mode-0600 files in a canonical mode-0700 runtime. Their bytes and file facts are checked again after decoding and before sealing. Plain lanes cannot introduce SDK configuration. This verifies preparation metadata; it does not establish that the intended application subsequently ran.

## Independent health reader

`go_health.read(runtime)` reads a completed `health.json` only from an owned canonical mode-0700 directory. The report must be an owned mode-0600 bounded regular file with one link. Links, FIFOs, replaced files, changed bytes/file facts, oversized reports and duplicate JSON keys are refused. The reader does not import the provider or execute retained code.

`validate` binds the closed schema-4 report to caller-owned application PID, policy digest and compiler selection digest. The reader retains the complete raw controls, lifecycle, probe, HTTP, exporter and unavailable-delivery fields. A running snapshot is not assumed to be atomic or quiescent.

`qualify` separately requires a final successful flush/shutdown, closed clean probes, exact independently counted function/auxiliary completions, no active or lost observations and matching decoded trace/metric batch receipt. Trace span totals and queue loss/pending counts are checked separately. Metric point totals are not available from the SDK exporter record: the reader retains independent received points and leaves the SDK point total explicitly unavailable.

HTTP recording observations follow the trace SDK: either exact start/end/active/closed counters or the single field `observed = false`. Final qualification requires closed HTTP accounting, zero active operations and complete independently decoded HTTP spans in the diagnostic full-sampling profile. An unread response body cannot disappear behind a successful SDK flush. HTTP EOF/close-attempt boundaries are separate from successful resource release or GC. The general raw validator does not infer complete delivery from sampled or unobserved traces.

Observed GC, successful resource release, pending objects and unreleased resources remain distinct counters. A clean SDK drain does not invent a GC or release boundary for a censored object. An unobserved trace exporter supplies no fabricated zero queue counters. The SDK's downstream and partial-rejection fields remain unavailable; actual receipt belongs to the independent receiver.

## Component checks and remaining work

```sh
PYTHONPATH=tests python -m unittest -v \
  test_generation_go_files test_generation_go_source_build \
  test_generation_go_prepared test_generation_go_health
```

The maintained literal fixtures cover protocol substitutions, wrong process/policy/selection, compiler/source/module changes, rehashed private copies and launch recipes, missing/unknown fields, exact unsigned counters, live/final separation, unclosed HTTP operations, censored lifetimes, unavailable trace observation, failed exports/drains, receiver disagreements and private-file races. All five modules are embedded with the generator and have independent 80% line-coverage floors.

Next connect the checked metadata, independent helper reproduction, owned execution and decoded OTLP to generated/replayed/framework/detached/reduced/promoted workflows. Existing receiver/package support, live metric schedules, source/dependency preservation and refusal controls require qualification against the new provider. Broader Go builds, cgo/workspaces, asynchronous/resource actions, shipping artefacts and the [full completion checklist](completion.md) remain open.

The intended result remains **equivalence over these tests and observations**.
