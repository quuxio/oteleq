# Apply oteleq to all eight otelc languages

The diagnostic capture integration runs C, C++, Rust, Python, Java, JavaScript, TypeScript and Go through the actual otelc launcher. Each language runs twice plain and twice instrumented in fresh processes and private source copies. The Rust comparator must return `equivalent_observed` for every requested language; missing instrumentation, incomplete export, unstable output or changed tools cannot pass.

## Run

Build otelc and its qualified toolchains/adapters first. Use its locked CPython 3.12 environment for the OTLP protobuf decoder. From the oteleq checkout:

```sh
make capture-otelc PYTHON=../otelc/.venv/bin/python \
  OTELC_ROOT=../otelc REPORT_DIR=/tmp/oteleq-all-language-evidence
```

The report directory must be new and outside both repositories. TMPDIR must also resolve outside both repositories; an unsafe location is rejected before creating reports. The default is all eight languages. To qualify one language, add `CAPTURE_ARGS="--language cpp"`; multiple `--language` arguments select a subset. Do not describe a subset run as an all-language pass.

If the default tools are unsuitable, set `OTELC_NODE`, `OTELC_JAVA`, `OTELC_GO` or `OTELC_RUSTC` to qualified executables before running. The Rust SDK must be built with the same compiler distribution as the selected `rustc`; matching the version number alone does not establish compatibility. The Node Promise observer must match the selected Node version and module ABI. C/C++ use otelc's matched LLVM metadata, not an unrelated compiler on PATH. The current native manifest is qualified on macOS ARM64/LLVM 22; it fingerprints the macOS pass library. It does not establish Linux or Windows qualification.

The [independent fixture manifest](../examples/otelc-workloads.json) declares exact function counts, trace roots and escaping-error spans. C++ includes constructor/destructor ABI bodies and exceptions; these are function spans, not complete object lifetimes. Rust/Python/Node fixtures cover their qualified async/error boundaries. Java includes a virtual thread and failed constructor. Go includes goroutines and panic/recover. Generated baseline/instrumented native builds use equivalent flags and retain exceptions.

## Evidence and failure behaviour

Each language directory retains `bundle.json`, `comparison.json`, concrete corpus, source/policy and adapter/tool content identities. Attempt directories retain exact stdout/stderr bytes, build logs where applicable, launch commands, runtime reports, received OTLP protobuf bytes and HTTP capture manifests, including failures. The decoder validates service/scope identity, nonzero unique IDs, parent presence, acyclic local trees, exact function/root/error counts and complete zero-loss runtime/export status. A child may finish after its parent; causality does not require timestamp containment.

All target source/configuration remains unchanged. Generated copies and reports are outside the target repository. Observer code, SDK/adapter inputs and selected tool executables are re-enumerated and hashed before and after each execution, including added or removed dependency code. Private build temporary directories sit outside the copied project to avoid recursively mirroring compiler scratch directories. Ambient telemetry headers, agents and compiler wrappers are not inherited.

Managed reports must declare the expected language and schema; native reports must confirm draining. Python pending contexts cannot be omitted. Fixture manifests also reject duplicate JSON keys and their contents join the observer identity manifest. Both examples reject unexpected baseline telemetry, retain HTTP evidence and application output before later qualification checks, and refuse source-contained temporary parents before probing them. Parent graphs are validated with one visit per node.

Any failed build, missing report, unexpected telemetry, timeout or changed artefact aborts capture and retains partial evidence. The failing language cannot acquire a complete bundle or successful comparison. Already completed language reports remain available; languages after the failure have not been qualified. Reuse a new report directory for the next attempt.

## Scope

The claim is **equivalence over these tests and observations**. This is fixed trusted diagnostic workload coverage for every language, not automatic test generation, semantic function discovery or a complete language adapter. It compares exact stdout/stderr and successful exits; selected fixtures also assert results, exception identity and existing cleanup in application code. It does not compare hidden receiver/global/argument state, filesystem/network side effects or typed alias graphs. Internal fixture success does not qualify an arbitrary application.

Build identity describes the diagnostic source, recipe, adapter/SDK inputs and tool drivers, not a shipping binary. Compiler sysroots, OS libraries, hostile-process containment and general output/memory limits are outside this qualification. TypeScript uses otelc's existing 6.0.3 compiler API and Node runtime; this integration does not establish TypeScript 7 or browser support. Exact telemetry IDs, timestamps and natural GC times are not compared across runs.

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

## Checks

```sh
make observer-check
make check
```

The new capture modules each enforce at least 80% line coverage independently of the Rust comparator's 80% gate. Regression tests cover corrupted IDs/parents, late children, wrong service/scope/function counts, missing/unfinished exports, losses, changed/added/missing adapter inputs, ambient configuration isolation, byte preservation, bounded/truncated OTLP requests, duplicate JSON keys, ambiguous HTTP framing and malformed runtime counters, source preservation and real private subprocess capture.
