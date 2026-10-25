# Native prepared provider components

<!-- markdownlint-disable MD013 -->

Status: internal integration work. These readers and the execution controller implement the public otelc `native-owned-v1` build-2/preparation-1 contract for C and C++. Generated test commands do not select this provider yet. The existing native generator continues to use its documented provider. This work does not qualify C, C++, Rust, production artefacts or the whole project as complete.

## Inputs and private builds

The consumer freezes operator-selected LLVM 22 tools, six fixed metadata queries, the native SDK library/build record, original SDK sources, application units and independently supplied per-unit dependency sets. It reconstructs the plugin, pre-exec gate, bootstrap and both compiler/linker recipes without importing SDK renderers. The fixed standalone recipe is C11 or C++17; general compilation databases and build-system flags need separate integration.

Every accepted build retains its complete product and command-channel denominator, including both per-unit dependency manifests. Checks bind original bytes, inode, write times, permissions and link counts. A rewritten record or an identical-byte replacement cannot repair an earlier accepted identity. Caller-selected paths precede producer metadata; metadata never chooses an executable or a foreign dependency to inspect.

Function selectors in this SDK profile match demangled compiler names such as `workload(int)`. Source selection is separate. Emitted function identities add the relative source path, such as `main.cpp::workload(int)`. Generated inventory integration must translate and bind that relationship, then require positive downstream evidence for each requested target. An attached SDK with zero selected functions does not prove instrumentation.

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
```

This runs native reader/controller tests, including changed or rehashed records, per-unit dependency substitution, wrong PID/group/session, unsafe publication, nonzero exits, final health failures and child cleanup. The full `make check` also requires at least 80% statement coverage in each new component. These tests use literal independent records and narrow OS fakes. They do not start a real SDK application or replace actual provider qualification.

## Remaining integration

The generator still needs explicit provider selection, independent caller/dependency discovery, inventory-to-compiler target binding and integration of the native OTLP reader. Generated, replayed, framework, detached, reduced and promoted suites need exact-revision execution, source preservation and negative controls. Live collection/emission schedules, invocation attribution, automatic object lifetimes, task/HTTP context, broader build recipes and platform/shipping qualification remain open. The [project completion checklist](completion.md) remains the acceptance boundary.
