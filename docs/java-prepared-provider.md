# Prepared Java SDK provider

Java can explicitly use the replacement otelc SDK's public prepared-launch API. This is a separate provider contract from the default pre-rebuild Java adapter. It runs the existing generated scalar and declared receiver workers; it does not require application SDK calls or source edits.

The result is **equivalence over these tests and observations**. These are private diagnostic builds. Shipping artefacts, arbitrary Java projects and invocation-scoped telemetry attribution require separate work.

## Select the provider

Use a complete JDK 21 and a compatible SDK checkout with its Java extension and pinned OpenTelemetry agent already built. Select the actual JDK executables:

```sh
export OTELC_JAVA=/absolute/path/to/jdk/bin/java
export OTELC_JAVAC=/absolute/path/to/jdk/bin/javac
export OTELEQ_PYTHON=/absolute/path/to/qualified/python
```

Add the explicit backend to the project's equivalence policy:

```toml
schema_version = 1
languages = ["java"]

[adapters.java]
backend = "prepared"
```

Use the ordinary `plan`, `generate`, `run`, `replay`, `shrink` and `export-tests` commands with this policy. The [automatic generation guide](automatic-generation.md) describes those commands and fixtures. Exported suites retain their source snapshot and use the same frozen CLI, tools and provider identities.

`backend = "legacy"` remains the default. Selecting `prepared` never silently falls back to that launcher. The replacement SDK currently provides Java; this setting does not make its other language placeholders executable adapters.

The provider must contain:

- Its public `otelc` Python package, including prepared-launch, health and control APIs.
- `build/tools/opentelemetry-javaagent-2.32.0.jar`, with oteleq's pinned SHA-256.
- `adapters/java/target/java-extension-0.2.0-SNAPSHOT.jar` and its source/POM inputs.

oteleq does not build or install these SDK products during a plan. Changed SDK sources, products or selected tools require a new plan. Use the SDK's documented build procedure before creating one.

## What the runner verifies

Planning retains a public config-only SDK `plan` request and response for each selected supported method. It checks the entire resolved schema-3 policy and the published Java capability. Missing capability or a changed policy becomes an explicit blocker before application execution.

Each attempt then:

1. Reconstructs an independent private source tree and fixture.
2. Compiles through the [compiler-owned Java frontend](java-build-bundles.md), retaining exact source reads, class products and the JDK module-image identity.
3. Calls the public SDK with `java --manifest ... --runtime ... --prepare-only --diagnostic-profile`, adding `--plain` for the baseline. Preparation starts no application JVM.
4. Independently reconstructs the complete expected Java executable, flags, classpath, properties, method selection and input identities. SDK metadata can verify that recipe; it cannot choose another executable or add launch flags.
5. Launches that exact argv and records the actual process PID.
6. Rechecks source, compiler products, launch inputs and loaded application/driver class origins after execution.
7. Compares the existing typed outcomes, stdout/stderr, supported state and declared filesystem/HTTP effects across the configured repeats.

Both lanes disable CDS. The instrumented lane sends the official agent's own diagnostics to a separate retained file. Application stderr is captured unchanged; there is no filter that removes agent-looking lines from it.

The selected method's decoded spans must form one complete invocation tree per requested call, with the expected owner, method and instrumentation scope. For ordinary calls, cumulative call and duration metrics must finish at the decoded span count. [Live metric schedules](java-metric-controls.md) instead count only trees executed with collection enabled; tracing still covers every call. Recursive calls may produce several spans in each tree. [Ordered Java receiver calls](ordered-sequences.md#java-call-sequences) require the declared number of independent roots; an ordinary single-call case still requires exactly one. These checks bind names and loaded source classes; they do not implement the [proposed invocation-scoped witness](action-witness.md).

The final private health report must identify the actual launched JVM and the exact policy/selection hashes. Its supported processor/exporter accounting must agree with independently decoded OTLP batches, spans and metric points, with no active, pending, dropped or failed exports. Unavailable counters cannot become zero. Successful flush retries retain their failed-attempt history. SDK pipeline completion and local receiver acknowledgement do not establish downstream collector processing or partial-rejection handling.

## Budgets and retained files

The fixed policy exports metrics every 1,000 ms, with a 1,000 ms export timeout and 10,000 ms shutdown budget. The private receiver accepts at most 4,096 telemetry requests, 1 MiB per request and 32 MiB in total. A budget failure makes the attempt incomplete. The legacy receiver retains its default 32-request allowance.

The SDK requires a short Unix-domain socket path. Each attempt creates an owned private `oej-*/r` runtime below the operating-system temporary parent, outside the application. The control-socket path must fit in 100 bytes; if the configured parent is too long, select a shorter `TMPDIR` before planning. Before removal, oteleq copies the runtime's bounded regular files into the attempt's `sdk-runtime/` directory. `runtime-archive.json` records the original path and file identities; `prepared-launch.json`, `process.json`, `verified-origins.json` and instrumented `verified-health.json` retain the independent checks. Original short runtime directories are removed after the attempt, including failed attempts.

The runtime archive is limited to 64 entries and 32 MiB. Links and special files are refused. Final health reads require an owned canonical 0700 runtime, an owned regular 0600 report and a 4 KiB size limit. Descriptor-relative reads refuse symbolic links and do not wait on FIFOs.

This profile requires POSIX sockets and the qualified JDK/platform. It is trusted local execution. The fixed source-classpath compiler profile excludes external dependencies, annotation processing, modules, custom classloaders and arbitrary JVM flags. SDK method-name selection may reject ambiguous overloads. [Live metric controls](java-metric-controls.md) are explicit per-call settings for declared receiver sequences. They retain the actual process/build, acknowledgements, export-off windows and restored measurements. General project integration, broader SDK-instrument/control profiles, receivers and shipping-artefact qualification remain open.

## Reproduce the receiver qualification

The existing receiver qualifier accepts an explicit provider backend. With the prepared SDK tools available, run:

```sh
make generation-java-receiver-otelc JAVA_BACKEND=prepared \
  PYTHON=/absolute/path/to/qualified/python \
  OTELC_ROOT=/absolute/path/to/prepared-sdk \
  REPORT_DIR=/absolute/path/to/new-qualification
```

The default `JAVA_BACKEND=legacy` preserves the earlier qualification route. Both modes check complete independent receiver/static/return/error graphs for every repeat, generated/exported suites, replay, shrinking and source/refusal controls. Prepared mode additionally rechecks actual JVM identities, every retained runtime file and actual protobuf batch/unit accounting. These checks do not qualify a different provider revision or platform.

## Published qualification

The [21 October record](qualification/java-prepared-2026-10-21.json) qualifies runtime `fae3874` with frozen SDK `f3279fd` on macOS ARM64/JDK 21. The receiver corpus completes 151 actual JVM launches: six matching cases, two deliberate same-return state differences, generated suites, per-case replay, exported suites with the original source temporarily unavailable, scalar shrinking from seven to zero and seven refusal controls.

All 155 retained compiler manifests, 467 class bindings and 155 runtime archives are checked independently. Four copied original shrink attempts remain retained evidence and do not inflate the 151 actual JVMs. Both 62-file SDK source copies and both Java products remain unchanged; all original short runtime directories are removed.

Four additional JVMs qualify a packaged recursive method with exact nonempty application stdout/stderr, complete independently expected scalar state and two spans per instrumented repeat. Eight additional JVMs check matching and deliberately different receivers through the legacy provider. The focused Java suite passes 71 regressions. The repository gate covers 625 distinct regressions; the recorded Rust product line coverage is 97.32%, and the four new Python modules measure 99% to 100%. Final delivery checks are recorded with [PR #49](https://github.com/quuxio/oteleq/pull/49/checks). This evidence retains the profile limits above and leaves the full [completion checklist](completion.md) open.

The separately archived verifier `8f8e86b` rechecks all 160 retained successful receiver/legacy observations, including four copied original shrink attempts. It requires complete literal types, widths, UTF-16 values, roots, fields, nodes and aliases. Eight altered type/shape controls and two substituted fixture identities are refused. Local node labels remain opaque; their spelling does not establish object identity across captures.
