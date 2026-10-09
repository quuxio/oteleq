# Workload comparison: implemented first slice

## Behaviour and scope

`quux-oteleq compare-workload BUNDLE.json` compares captured observations supplied by an external observer. It does not launch arbitrary applications, generate tests or implement the broader version-1 adapter protocol. Its separate `workload_schema_version = 1` describes repeated workload evidence for all eight language IDs.

The claim is **equivalence over these tests and observations**. Only successful exits and exact declared byte channels are compared. Channels can hold stdout, stderr or externally captured fixture events; the comparator does not infer hidden state from output or interpret arbitrary object graphs. Scope gaps remain in the JSON report. A scoped success is not a complete-inventory or production release qualification.

Acceptance requires at least two independent attempts per lane, identical concrete corpus and source identities, complete declared channels, stable controls, and an expected decoded telemetry witness on every instrumented attempt. Missing evidence, nonzero exits, signals, timeouts, losses or pending telemetry cannot pass. Loss diagnostics must contain at least one named counter; an empty map cannot establish loss-free capture. Source-identity disagreement blocks comparison. Unknown schema fields/languages and duplicate JSON keys fail, including keys inside channel/count/loss maps. Zero cases cannot pass. Input bundles are limited to 16 MiB, 10,000 cases and 100 attempts per lane.

## Build and compare

```sh
cargo build --locked
./target/debug/quux-oteleq --help
./target/debug/quux-oteleq compare-workload /path/to/bundle.json > /path/to/comparison.json
```

The JSON report retains scope, attempt counts, all case verdicts, reasons and precise differing byte channels. No timestamps, `otel` fields or application diagnostics are filtered out.

| Exit | Meaning |
| --- | --- |
| 0 | Equivalent observations within the declared scope |
| 1 | Stable, complete observations differ |
| 2 | Invalid contract or changed source identity |
| 3 | Incomplete, invalid-target or unstable evidence |
| 4 | IO, codec or input-size failure |

In a mixed report, blocked or incomplete evidence takes precedence over differences, and every case result remains visible. Matching crashes do not establish equivalence. This initial command qualifies successful workloads only; expected nonzero application outcomes need a future typed outcome contract.

## Use it with otelc now

The [eight-language capture integration](eight-language-capture.md) applies this comparator to actual C, C++, Rust, Python, Java, JavaScript, TypeScript and Go trace examples. It independently checks function counts, causal graphs, zero losses and complete export. The Python task-specific example below supplements those function fixtures with asyncio propagation evidence.

The [task-workload capture example](../examples/capture_otelc_tasks.py) runs the ordinary Python task example twice without instrumentation and twice with the actual otelc launcher. It uses fresh processes, independent private source copies and a local OTLP receiver. Original source and policy are checked for modification. Original repositories receive no generated tests, dependencies or source edits. The Python observer uses otelc's existing locked environment for its OTLP protobuf decoder.

From an oteleq checkout, with the Python task-context milestone built in the sibling otelc checkout:

```sh
cargo build --locked
../otelc/.venv/bin/python examples/capture_otelc_tasks.py \
  --otelc-root ../otelc --report-dir /tmp/oteleq-task-evidence
./target/debug/quux-oteleq compare-workload \
  /tmp/oteleq-task-evidence/bundle.json > /tmp/oteleq-task-evidence/comparison.json
```

The report directory must be new and outside both repositories. The operating-system temporary parent (including `TMPDIR`) must also resolve outside both repositories, or capture refuses to start. Reports retain concrete corpus, artefact hashes, raw stdout/stderr, runtime reports, HTTP capture manifests and received OTLP protobuf bytes. Every instrumented attempt must contain eight distinct spans: two `group`, one `detached` and five `leaf` observations, with no runtime/export losses, active/queued trace trees or pending contexts. The observer validates span IDs, non-empty names and timestamp ordering against the [OTLP span contract](https://github.com/open-telemetry/opentelemetry-proto/blob/main/opentelemetry/proto/trace/v1/trace.proto). Duplicate deliveries cannot inflate the witness count. Telemetry timing and IDs are retained separately; they are not expected to match across executions. Parent graphs, resource attributes and full telemetry semantics are not qualified. This is a **diagnostic example workload**, not a shipping application qualification or complete Python adapter.

The observer records adapter/interpreter/launcher/observer content identities and verifies them before and after every execution. A concurrent rebuild, changed adapter/lock/interpreter/observer or missing artefact aborts capture; observations from different recorded tool builds cannot share a complete bundle. Installed dependency and standard-library contents are not fingerprinted, and this gap is retained in the report. File identities use streaming SHA-256 rather than loading executables into memory on every check.

The fixed trusted example uses a 30-second subprocess timeout and accepts at most 16 OTLP requests of at most 1 MiB each. The receiver accepts complete, uncompressed, length-delimited requests on `/v1/traces` and `/v1/metrics`; body reads have a two-second deadline. Rejected, truncated, malformed or timed-out HTTP capture aborts bundle creation, even if other spans were received. Runtime JSON rejects duplicate fields and requires typed loss/pending diagnostics; trace and runtime loss names have distinct prefixes so one cannot overwrite another. General process-tree, memory/output limits, sandboxed execution, typed state observers and hostile targets are outside this example's qualification. Failed capture raises an error and leaves its partial report directory; it does not emit a successful complete bundle.

## Evidence contract

Read [the Rust structs](../src/protocol.rs) for the strict initial schema. `scope` declares language, artefact class, source/build/policy SHA-256 identities, observer, exact channel names and unobserved gaps. Each concrete case declares its corpus digest, expected function counts and expected span count. Attempts carry before/after source digests, termination, byte arrays, capture completeness and optional telemetry witness. Instrumented witnesses include decoder identity, raw OTLP digest, decoded function counts, span total, losses and pending count.

The comparator validates **provider-supplied evidence**; it cannot authenticate a fabricated JSON bundle or establish that an observer really launched the declared artefact. Capture observers need their own tests and qualification, including which loss counters cover their signal path; a non-empty map alone does not establish that every possible loss is observed. It does not independently decode OTLP; the diagnostic observers do. Raw evidence remains available for review. Full selected-function inventory, state graph/alias comparison, off controls, automatic test generation and shipping artefact validation remain [roadmap requirements](roadmap.md).

## Apply it to context and lifetime milestones

Use this comparator for each otelc context-propagation and **automatic object / resource lifetime spans** milestone across C, C++, Rust, Python, Java, JavaScript, TypeScript and Go. Each integration supplies its own independently captured fixture channels and decoded signal witness; accepting a language ID here is not evidence that such an integration exists.

Context fixtures should expose task results, cancellation/error outcomes and scheduler side effects as stable byte channels, while checking causal span graphs separately. Lifetime fixtures should expose existing acquisition/close/drop events, object retention and finaliser behaviour through qualified external observers. Do not compare exact GC completion times or span IDs between runs. Before making a state-equivalence claim, implement typed receiver/global/argument observers and alias/cycle comparison from the broader design; stdout alone cannot establish unchanged retention, layout or object state.

Keep the ordinary control, instrumented-off where supported and instrumented-on lanes distinct. The current comparator implements baseline/on only. Extend its schema with fail-closed capability checks before adding off/fault lanes or non-successful application outcomes. Each otelc PR must retain its corpus, complete observation scope and gaps, actual telemetry evidence and source/build identities, alongside focused semantic tests and existing coverage gates.

## Checks

```sh
make setup
make check
```

The meaningful Rust regression cases include non-Unicode bytes, changed effects despite unchanged outcomes, unstable controls, missing/extra/truncated channels, matching crashes, altered source, mismatched/lost telemetry and mixed incomplete reports. The coverage gate excludes integration-test code and enforces at least 80% over the Rust product code. CI also checks the documentation and illustrative policy syntax; syntax validation does not execute the future configuration schema.
