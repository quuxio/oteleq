# Native prepared provider

<!-- markdownlint-disable MD013 -->

Status: candidate public integration. Explicit C/C++ `backend = "prepared"` selects `native-owned-v1` build3/unit-recipe1 and preparation1 through the ordinary planning, generation and execution commands. The separate older fixed-source build2 readers remain available to component maintainers. Generated/retained workflow qualification is in progress. The default native provider is unchanged; this work does not qualify whole-language, production artefact or project completion.

## Select the candidate

Use the matching built SDK and LLVM 22 installation. Select each native language present in the source tree explicitly:

```toml
schema_version = 1
languages = ["cpp"]

[adapters.cpp]
backend = "prepared"
sdk_build = "/absolute/otelc/build/context-sdk"
build_timeout_ms = 180000
```

`sdk_build` is optional and defaults to `build/prepared-sdk` under the selected otelc root. It must identify the existing matching SDK library and build record. The provider negotiates the complete build3 descriptor and independently checks the selected toolchain and SDK recipe. An unavailable or incompatible provider refuses; there is no legacy fallback. Build timeouts accept 1000 to 900000 milliseconds and remain separate from the application's case timeout.

Without a compilation database, each C11 or C++17 source unit is a separate standalone target with fixed `-O2`, exception and pthread settings. Linked application targets use the existing explicit compilation-database policy. Add these fields to the selected adapter table and declare its ordered targets:

```toml
[adapters.cpp]
backend = "prepared"
sdk_build = "/absolute/otelc/build/context-sdk"
compilation_database = "build/compile_commands.json"

[[adapters.cpp.targets]]
name = "application"
units = [{source = "src/main.cpp"}, {source = "src/state.cpp"}]
link_flags = ["-pthread"]
```

Per-unit working directories, qualified semantic flags, actual dependencies and existence/search probes are frozen before SDK builds. The compilation database does not supply an inferred link recipe. See [native project context](native-project-context.md) for supported flags and target selection.

```sh
quux-oteleq plan --source /absolute/application --otelc-root /absolute/otelc \
  --config generation.toml --workspace-parent /absolute/transient
quux-oteleq generate --workspace /absolute/transient/oteleq-run-EXAMPLE
quux-oteleq run --workspace /absolute/transient/oteleq-run-EXAMPLE \
  --report-dir /absolute/transient/native-report
```

The candidate currently follows the scalar project-worker contract, including supported target-wide globals/statics and declared standard C++ exception observations. Unknown exception types, receivers, action sequences and live metric switches need separate integration. The generator retains these limits as blockers or incomplete execution; it does not silently discard them. Tests, copied source, access helpers, compiler products and runtime records remain in the external workspace. No application or dependency annotation is required.

The native exception graph uses names such as `cpp.std::runtime_error`. Declare an expected native error with `expected_baseline = { kind = "error", category = "exception", type = "cpp.std::runtime_error" }` in its fixture. This differs from the byte-based exception label used by the separate legacy C++ receiver codec. A wrong expectation blocks comparison even when both captured results match.

## Inputs and private builds

The consumer freezes operator-selected LLVM 22 tools, six fixed metadata queries, the native SDK library/build record, original SDK sources, application units and independently supplied per-unit dependency sets. It reconstructs the plugin, pre-exec gate, bootstrap and both compiler/linker recipes without importing SDK renderers. The fixed standalone recipe is C11 or C++17; explicit compilation-database targets use build3 per-unit recipes. Broader build-system flags still need separate integration.

Every accepted build retains its complete product and command-channel denominator, including both per-unit dependency manifests. Checks bind original bytes, inode, write times, permissions and link counts. A rewritten record or an identical-byte replacement cannot repair an earlier accepted identity. Caller-selected paths precede producer metadata; metadata never chooses an executable or a foreign dependency to inspect.

Function selectors in this SDK profile match demangled compiler names such as `workload(int)`. Source selection is separate. Emitted function identities add the relative source path, such as `main.cpp::workload(int)`. Generated inventory integration must translate and bind that relationship, then require positive downstream evidence for each requested target. An attached SDK with zero selected functions does not prove instrumentation.

### Candidate per-unit recipe

`native_unit_build.freeze/read` independently binds the explicit build3/unit-recipe1 contract. Build2 negotiation and its fixed-source reader remain separate. The caller supplies the complete ordered application units, each unit's language, semantic flags, working directory and independently discovered compiler inputs before the SDK creates products. Mixed C/C++ units can retain different standards and defines. This reader does not infer a compilation database or discover dependencies from a producer's response.

An optional neutral driver is a separately held private asset outside application source. It is compiled without probes in both lanes. A private VFS file maps original source paths to separately held observation copies; original files stay unchanged. Optional main rename uses only the fixed matched `llvm-objcopy` operation. Compiler, rename and link operations have complete product/stdout/stderr denominators, with an independently reconstructed compilation database. The common preparation controller accepts the checked build3 products under the unchanged request/preparation1 contract.

Build3 requires full `-MD` dependency channels, including application headers supplied through `-isystem`. The original SDK candidate's `-MMD` recipe omitted those headers and accepted a changed application header in an independent real-compiler control. That failed control remains recorded; this consumer refuses the incomplete recipe. A development probe against corrected SDK `5476ce0` completes four actual C/C++ plain/woven launches, including a mixed-language target, private observation overlays, different per-unit flags/directories, main rename, exact results, a C++ exception and independent direct telemetry. Both the caller-held consumer and SDK verifier refuse changed system-classified application headers. This is component evidence from a dirty development snapshot; immutable exact-head and generated/retained workflow qualification remain separate acceptance steps. The older fixed-source build2 contract is unchanged.

### Compiler-bound generated callers

`native_unit_caller.freeze/prepare` connects the independently inventoried scalar project-worker profile to build3. It freezes the project/target, concrete arguments, common SDK policy and compiler context before callbacks. It generates private source accessors and a neutral driver, then has the actual frontend check the original physical definition, unchanged signature and the generated invocation's reference to the intended declaration. This binds C++ overload selection as well as C calls. Every generated application accessor must have Clang's `NoProfileFunctionAttr`; developers add no annotations or code.

The frontend gives its supplied file manager the same VFS overlays as the compiler. Passing an overlay flag without applying it to that file manager previously inspected the original source instead. The regression checks both actual declarations and overlay-only header inputs, while preserving original source bytes.

Compiler MD channels and preprocessor existence/search probes are retained separately. Caller-owned header aliases bind logical names to already frozen canonical inputs before SDK compilation. This covers macOS SDK directory aliases without allowing a producer dependency file to choose a new filesystem read. Missing alias declarations, foreign paths, substitutions and changed original file facts refuse.

The generated execution path calls `Caller.recheck` after the SDK build and after each application execution. It repeats compiler input/probe checks into a fresh external evidence directory. A newly present `__has_include` target can change compilation while all previously read source files remain unchanged; a byte-only recheck is insufficient. Original caller metadata, helper/tool inputs and compiler channels retain their own immutable file identities.

The development caller probe against held SDK `5476ce0` completes four actual C/C++ plain/woven applications with independently decoded telemetry. Generated callers preserve the selected overload, complete supported target-wide globals/statics, argument values, ordinary return and original C++ exception path. A first attempt refused an undeclared macOS SDK header alias before any application launch and remains failed. The corrected probe is scoped to its recorded development snapshot; public CLI selection and generated/retained workflow qualification remain open. This bridge currently follows the existing scalar project-worker contract; receiver, action, resource and broader build fixtures require their own integration.

## Preparation and owned execution

`native_prepared.freeze/read` binds the runtime policy, literal application arguments, fixed lane image, selected isolated Python interpreter and complete SDK producer source set before execution. Its three preparation files must be stable private records in a new external directory. The command is reconstructed as the fixed SDK supervisor; recorded argv is never executed.

`native_session.Session` runs through the ordinary executor's original wall-time, output and process cleanup limits. Before releasing the application, it checks the actual OS parent, process group and session for the supervisor and waiting child. Each has its own session; the native child does not share the supervisor's group. Both complete SDK start records must agree with those observations and the accepted image. Original application constructors are still blocked at that point.

The controller publishes one bound host acknowledgement, retains original start/release file identities and checks the final zero exit, unchanged inputs and literal SDK health. Pending two-link SDK publications are retried without accepting their bytes or temporary file facts. The final ordinary records require owned mode-0600 single-link files. Cleanup covers the child's separate process group as well as the supervisor group.

`native_health` validates the closed native schema directly. It requires matching application PID, language, policy and selection, completed SDK shutdown and zero known function/queue/export losses. Unavailable counters cannot become invented zeroes. The public execution field `exec_verified=false` and `source_complete=false` remain visible; host release by itself is not proof of every executed image or source instruction.

In a drained native final report, `effective_emission_off` is true when collection or emission is disabled. Preserve the native SDK's rule; other language providers can expose different status semantics. This field does not replace independent collection counts or downstream disabled-window checks.

SDK exporter API batches and downstream HTTP requests are different observations. The official metric exporter can complete an empty API batch without an HTTP request. Independent receipt must compare the actual decoded metric points and spans to the corresponding unit counters, while retaining the separate API batch counters. A clean health report alone is not downstream receipt.

`native_telemetry` supplies that independent reader for fixed startup states. It binds complete serial function roots and their recursive trees, exceptions, source-qualified names, native resource/scope labels and cumulative call/error/duration metrics. Final function/span/metric-point unit counters must match actual decoded receipt. The native SDK resource identifies the official C++ SDK even for C applications; this candidate binds version 1.30.0. Collection-off, emission-off and combined startup states require absent measurements while selected traces remain complete. Plain execution requires absent SDK telemetry. Live state changes and per-action attribution need separate integration and qualification.

The expected service name must match the frozen prepared policy before receipt is decoded. Duration histograms retain their complete cumulative state. Their sums must fit actual extrema and populated buckets, allowing bounded binary64 summation error. Later samples must retain earlier bucket counts and extrema; only newly added observations can change the sum. Python uses the same range arithmetic with its existing fixed boundaries.

## Maintainer checks

```sh
make native-provider-check PYTHON=/absolute/path/to/python
make native-caller-check PYTHON=/absolute/path/to/python
```

This runs native reader/controller tests, including changed or rehashed records, per-unit flags/directories, private overlays, neutral-driver selection, main rename, dependency substitution, wrong PID/group/session, unsafe publication, nonzero exits, final health failures and child cleanup. The full `make check` also requires at least 80% statement coverage in each new component. These tests use literal independent records and narrow OS fakes. They do not start a real SDK application or replace actual provider qualification.

The separate caller target uses matched Clang tools for real AST/VFS/input checks and ordinary generated worker execution. Its SDK recipe fixtures are literal data; that target does not build or run the official SDK. It checks unknown/missing helper declarations, changed signatures/references, absent profiling exclusions, changed and restored helper bytes, header alias substitution and positive/negative existence probes. Actual SDK execution and retained-route qualification remain separate checks.

### Qualify generated and retained suites

The maintained native project corpus can explicitly select the prepared provider:

```sh
make generation-native-project-otelc \
  PYTHON=/absolute/path/to/python \
  OTELC_ROOT=/absolute/otelc \
  NATIVE_BACKEND=prepared \
  NATIVE_SDK_BUILD=/absolute/otelc/build/context-sdk \
  REPORT_DIR=/absolute/new-native-qualification
```

The default `NATIVE_BACKEND=legacy` retains the older provider route and omits the prepared SDK argument. `NATIVE_MIN_FREE_BYTES` defaults to 8 GiB. The corpus checks available storage before each command, keeps started/exit/output records and refuses to overwrite an incomplete operation. Use a new external report directory for a fresh run; inspect any failure before deciding how to recover it.

The prepared corpus covers two-unit C `-O0`, C++ `-O2` and same-return C global mutation fixtures. It checks complete expected scalar globals/statics and results through direct execution, generated unittest, replay, detached export and scalar reduction. Current-source promotion also checks a copied checkout and a newly added selected function. Four changed-input/context controls must refuse before application execution.

A separate fixture oracle reads actual ownership/start/release/completion records, original file identities, final health, raw protobuf and HTTP response receipts. It compares copied shrink evidence to exactly one original four-launch report, checks the complete copy denominator and counts copies separately. Thirteen altered-evidence controls use separate values or capture copies; they start no applications and leave the original evidence unchanged. Every observed original evidence file is rechecked before the final summary. The receipt modules each require 80% coverage in `make effect-qualification-check`. This normal-call corpus does not establish recursive/exception, receiver, live-control or shipping qualification. Exact-revision execution remains pending until its qualification record is published.

## Remaining integration

The candidate now connects provider selection, compiler-bound callers, owned sessions and the native OTLP reader. Generated, replayed, framework, detached, reduced and promoted suites need exact-revision execution, source preservation and negative controls before admission. Live collection/emission schedules, invocation attribution, automatic object lifetimes, task/HTTP context, broader build recipes and platform/shipping qualification remain open. The [project completion checklist](completion.md) remains the acceptance boundary.
