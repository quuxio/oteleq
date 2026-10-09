# Apply oteleq to all eight otelc languages

The diagnostic capture integration runs C, C++, Rust, Python, Java, JavaScript, TypeScript and Go through the actual otelc launcher. Each language runs twice plain and twice instrumented in fresh processes and private source copies. The Rust comparator must return `equivalent_observed` for every requested language; missing instrumentation, incomplete export, unstable output or changed tools cannot pass.

## Run

Build otelc and its qualified toolchains/adapters first. Use its locked CPython 3.12 environment for the OTLP protobuf decoder. From the oteleq checkout:

```sh
make capture-otelc PYTHON=../otelc/.venv/bin/python \
  OTELC_ROOT=../otelc REPORT_DIR=/tmp/oteleq-all-language-evidence
```

The report directory must be new and outside both repositories. TMPDIR must also resolve outside both repositories; an unsafe location is rejected before creating reports. The default is all eight languages. To qualify one language, add `CAPTURE_ARGS="--language cpp"`; multiple `--language` arguments select a subset. Do not describe a subset run as an all-language pass.

If the default tools are unsuitable, set `OTELC_NODE`, `OTELC_JAVA`, `OTELC_GO` or `OTELC_RUSTC` to qualified executables before running. C/C++ select LLVM 22 from `/opt/homebrew/opt/llvm@22/bin` on macOS or `/usr/lib/llvm-22/bin` elsewhere; override with `OTELC_CLANG` and `OTELC_CLANGXX`. The selected compiler directory must match otelc's metadata. Metadata cannot redirect the executable. The Rust SDK must be built with the same compiler distribution as the selected `rustc`; matching the version number alone does not establish compatibility. The Node Promise observer must match the selected Node version and module ABI. The current native manifest is qualified on macOS ARM64/LLVM 22; it fingerprints the macOS pass library. It does not establish Linux or Windows qualification.

The [independent fixture manifest](../examples/otelc-workloads.json) declares exact function counts, trace roots and escaping-error spans. C++ includes constructor/destructor ABI bodies and exceptions; these are function spans, not complete object lifetimes. Rust/Python/Node fixtures cover their qualified async/error boundaries. Java includes a virtual thread and failed constructor. Go includes goroutines and panic/recover. Generated baseline/instrumented native builds use equivalent flags and retain exceptions. Both Java lanes use `-Xshare:off` to align class-data-sharing behaviour when the task bridge is installed.

## Evidence and failure behaviour

Each language directory retains `bundle.json`, `comparison.json`, concrete corpus, source/policy and adapter/tool content identities. Attempt directories retain exact stdout/stderr bytes, build logs where applicable, launch commands, runtime reports, received OTLP protobuf bytes and HTTP capture manifests, including failures. The decoder validates service/scope identity, nonzero unique IDs, parent presence, acyclic local trees, exact function/root/error counts and complete zero-loss runtime/export status. A child may finish after its parent; causality does not require timestamp containment.

All target source/configuration remains unchanged. Generated copies and reports are outside the target repository. Observer code, SDK/adapter inputs and selected tool executables are re-enumerated and hashed before and after each execution, including added or removed dependency code. Private build temporary directories sit outside the copied project to avoid recursively mirroring compiler scratch directories. Ambient telemetry headers, agents and compiler wrappers are not inherited.

Managed reports must declare the expected language and schema; native reports must confirm draining. Python pending contexts cannot be omitted. Fixture manifests also reject duplicate JSON keys and their contents join the observer identity manifest. Both examples reject unexpected baseline telemetry, retain HTTP evidence and application output before later qualification checks, and refuse source-contained temporary parents before probing them. Parent graphs are validated with one visit per node.

Any failed build, missing report, unexpected telemetry, timeout or changed artefact aborts capture and retains partial evidence. The failing language cannot acquire a complete bundle or successful comparison. Already completed language reports remain available; languages after the failure have not been qualified. Reuse a new report directory for the next attempt.

## Scope

The claim is **equivalence over these tests and observations**. This is fixed trusted diagnostic workload coverage for every language, not automatic test generation, semantic function discovery or a complete language adapter. It compares exact stdout/stderr and successful exits; selected fixtures also assert results, exception identity and existing cleanup in application code. It does not compare hidden receiver/global/argument state, filesystem/network side effects or typed alias graphs. Internal fixture success does not qualify an arbitrary application.

Build identity describes the diagnostic source, recipe, adapter/SDK inputs and tool drivers, not a shipping binary. Compiler sysroots, OS libraries, hostile-process containment and general output/memory limits are outside this qualification. The default TypeScript workload uses otelc's 6.0.3 compiler API and Node runtime; the separate native workload below selects its pinned executable compiler. Neither establishes browser support. Exact telemetry IDs, timestamps and natural GC times are not compared across runs.

The separate [Python task example](workload-comparison.md#use-it-with-otelc-now) qualifies the implemented asyncio propagation fixture. Future task/service/lifetime milestones must add their own independently declared corpus, state/effect channels and expected telemetry. Passing the current function fixtures is insufficient evidence for those features.

## Python worker workload

The executor-context workload uses the same strict observer with an [independent corpus](../examples/otelc-worker-workloads.json):

```sh
make capture-otelc PYTHON=../otelc/.venv/bin/python \
  OTELC_ROOT=../otelc REPORT_DIR=/tmp/oteleq-python-workers \
  CAPTURE_ARGS="--workload python-workers"
```

This requires otelc's `examples/apps/python_workers_app.py` and `examples/python-worker-context.toml`, introduced in [otelc PR #45](https://github.com/quuxio/otelc/pull/45). The candidate qualified here is commit `750b0cb1ee71051b012df95c2a35155809f787ab`; an older checkout without those fixtures cannot run this workload. Build the launcher and Python adapter from the selected candidate before capturing it.

Two plain and two instrumented attempts compare the standard `ThreadPoolExecutor` and `asyncio.to_thread` fixture. Each instrumented attempt must provide ten spans, five causal trees, one escaping worker error and zero reported losses or pending contexts. All attempts must produce identical stdout/stderr and successful exits; the fixture checks results `11,21,31,41` and original exception identity. The case has its own ID, distinct from the ordinary Python function example. Selecting another language with this workload fails before creating reports.

This qualifies those concrete observations. Direct thread creation, arbitrary executors, other languages' propagation and hidden global/instance state remain outside this corpus. Both fixture manifests join the observer identity, so either changing during capture prevents qualification.

## Java worker workload

The Java platform executor corpus uses the same independent observer:

```sh
make capture-otelc PYTHON=../otelc/.venv/bin/python \
  OTELC_ROOT=../otelc REPORT_DIR=/tmp/oteleq-java-workers \
  CAPTURE_ARGS="--workload java-workers"
```

This requires `JavaWorkerApp.java` and `java-worker-context.toml` from [otelc PR #46](https://github.com/quuxio/otelc/pull/46). The exact qualified otelc head is `6bfbb1441cfa3f2b1b861d665ef6a04fb49c4f45`. Two baseline and two instrumented JVMs use matching `-Xshare:off`; original source/policy/CLI/agent identities must remain unchanged. Each instrumented attempt independently requires five `JavaWorkerApp.root(java.util.concurrent.ThreadPoolExecutor,int)` spans, three `JavaWorkerApp.child(int)` spans, five complete roots and two escaping errors, with no losses or pending contexts.

All four attempts must produce exactly `results=11,21; original-error=true; cancelled=true; future-identity=true; rejection-identity=true` plus newline and empty stderr. The fixture checks original FutureTask, worker exception and rejection identity, results and queued cancellation. Running cancellation and shutdown edge cases have separate otelc tests; this corpus does not claim to exercise every executor or schedule. Choosing `python-workers` still selects Python only, and choosing `java-workers` selects Java only; unavailable language requests fail before capture.

## Optional native TypeScript workload

The default function workload continues to use the source TypeScript compiler. To qualify otelc's optional native executable emitter separately:

```sh
make capture-otelc PYTHON=../otelc/.venv/bin/python \
  OTELC_ROOT=../otelc REPORT_DIR=/tmp/oteleq-typescript-native \
  CAPTURE_ARGS="--workload typescript-native"
```

This requires `examples/typescript-native-traces.toml` and the installed host executable from the pinned TypeScript 7.0.2 platform package. The identity parser remains TypeScript 6.0.3. The independently declared [native corpus](../examples/otelc-typescript-native-workloads.json) requires eleven spans, five roots and one escaping error from the original trace fixture. The case has its own identity; selecting another language fails before capture.

Both lanes explicitly set `OTELC_TYPESCRIPT_BACKEND=native`. The observer checks that the common instrumented policy selects the same backend, and records the selection beside each launch vector. It rejects a backend mismatch or missing host compiler. Both attempts use independent copies with the same source-relative path and default private project settings; this fixture does not qualify arbitrary application tsconfig/build graphs.

Content identity includes installed `@typescript/typescript-*/lib/tsc` and `tsc.exe` executables, in addition to the lockfile, parser and adapter files. Replacement at the same path, addition or deletion prevents qualification. Including an exposed Windows executable in that inventory does not qualify Windows execution. Automatic scalar generation currently uses the classic compiler; this opt-in workload supplies separate native diagnostic evidence.

The macOS ARM64 provider qualified here is otelc `cb45e8cbcbd9893a4048b0039864c754b9a8f075`, using Node 24.21.0. Two baseline and two native-instrumented runs matched exact stdout/stderr and successful exits; each on run contained the independently expected eleven spans, five roots and one error with complete zero-loss export. CLI, native compiler, adapter, source and policy hashes matched the frozen provider manifest before and after capture. This qualifies that fixture and private project context.

## Checks

```sh
make observer-check
make check
```

The new capture modules each enforce at least 80% line coverage independently of the Rust comparator's 80% gate. Regression tests cover corrupted IDs/parents, late children, wrong service/scope/function counts, missing/unfinished exports, losses, changed/added/missing adapter inputs, ambient configuration isolation, byte preservation, bounded/truncated OTLP requests, duplicate JSON keys, ambiguous HTTP framing and malformed runtime counters, source preservation and real private subprocess capture.
