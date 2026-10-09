<p align="center">
  <img src="docs/assets/quux-mark.png" width="160" alt="quux">
</p>

# oteleq

**Behavioural equivalence evidence for instrumented applications. A [quux](https://quux.io) project.**

[![CI](https://github.com/quuxio/oteleq/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/quuxio/oteleq/actions/workflows/ci.yml)
[![Status](https://img.shields.io/badge/status-initial%20comparator-blue)](docs/roadmap.md)
[![License](https://img.shields.io/badge/license-AGPL--3.0-blue)](LICENSE)

---

[![Quality Gate Status](https://img.shields.io/badge/quality%20gate-not%20analysed-lightgrey)](docs/quality.md)
[![Bugs](https://img.shields.io/badge/bugs-not%20analysed-lightgrey)](docs/quality.md)
[![Code Smells](https://img.shields.io/badge/code%20smells-not%20analysed-lightgrey)](docs/quality.md)
[![Coverage](https://img.shields.io/badge/coverage-not%20analysed-lightgrey)](docs/quality.md)
[![Duplicated Lines (%)](https://img.shields.io/badge/duplication-not%20analysed-lightgrey)](docs/quality.md)
[![Lines of Code](https://img.shields.io/badge/lines%20of%20code-not%20analysed-lightgrey)](docs/quality.md)
[![Reliability Rating](https://img.shields.io/badge/reliability-not%20analysed-lightgrey)](docs/quality.md)
[![Security Rating](https://img.shields.io/badge/security-not%20analysed-lightgrey)](docs/quality.md)
[![Technical Debt](https://img.shields.io/badge/technical%20debt-not%20analysed-lightgrey)](docs/quality.md)
[![Maintainability Rating](https://img.shields.io/badge/maintainability-not%20analysed-lightgrey)](docs/quality.md)
[![Vulnerabilities](https://img.shields.io/badge/vulnerabilities-not%20analysed-lightgrey)](docs/quality.md)
[![Repo Traffic](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fquuxio%2Foteleq%2Fmain%2F.badges%2Ftraffic.json&cacheSeconds=3600)](https://github.com/quuxio/oteleq)

---

oteleq aims to generate tests that compare application behaviour with and without [otelc](https://github.com/quuxio/otelc) instrumentation across C, C++, Rust, Python, Java, JavaScript, TypeScript and Go. It compares results, errors, observable global and instance state, and declared side effects, while accounting for emitted OpenTelemetry telemetry separately.

The result is **equivalence over these tests and observations**. It is not a blanket proof that every function is identical.

Tests are generated in a separate transient directory. Users can retain them or choose to incorporate them into their application repository, using a framework that may differ from the application's existing tests.

**Status: the Rust workload comparator and diagnostic otelc capture integrations for all eight languages are implemented; full language adapters and automatic test generation remain planned.** Start with [comparing all eight languages](docs/eight-language-capture.md) or [the comparator and Python task example](docs/workload-comparison.md). Read the [design](docs/design.md), [language plan](docs/languages.md) and [delivery roadmap](docs/roadmap.md), or start with the [documentation index](docs/README.md).

## Usage

### Build and use the workload comparator today

The repository provides an initial Rust comparator alongside the broader design and example policies. With Git, Make, Rust 1.98.1+, Python 3.12+, Node.js 24+ and npm installed:

```sh
git clone https://github.com/quuxio/oteleq.git
cd oteleq
make setup
cargo build --locked
./target/debug/quux-oteleq --help
./target/debug/quux-oteleq compare-workload /path/to/bundle.json > /path/to/comparison.json
python3 -m venv .venv
.venv/bin/python -m pip install coverage==7.16.2
make check PYTHON=.venv/bin/python
```

`make check` validates documents and example syntax, Rust formatting, Clippy, comparator/capture regressions and at least 80% product line coverage. Coverage needs Python `coverage` 7.16.2, pinned `cargo-llvm-cov` 0.8.7 and matching LLVM tools; see [repository quality](docs/quality.md). The comparator consumes repeated captured observations and does not generate arbitrary tests. The [eight-language capture integration](docs/eight-language-capture.md) executes fixed ordinary otelc workloads with its qualified adapters.

### Planned application workflow

**The commands below are proposed interfaces and are not available on the published `main` branch yet.** Installation instructions will accompany an implementation release.

Start with the [example equivalence policy](examples/equivalence.toml). Set the languages and observations you need, point it at your external otelc policy, and supply the application build recipes and fixtures described in the [configuration guide](docs/cli-and-configuration.md#configuration). Paths below are examples; replace them with your own.

Inspect capabilities, then create an inventory and generation plan in a new directory outside your application repository:

```sh
quux-oteleq doctor --source /path/to/application \
  --config /path/to/equivalence.toml

quux-oteleq plan --source /path/to/application \
  --config /path/to/equivalence.toml \
  --workspace-parent /path/to/temporary-runs
```

`plan` prints the unique workspace path. Use that actual path for `OTELEQ_WORKSPACE`; choose a durable report directory outside the workspace for `OTELEQ_REPORT_DIR`:

```sh
OTELEQ_WORKSPACE=/path/to/temporary-runs/oteleq-run-1234
OTELEQ_REPORT_DIR=/path/to/reports/run-1234

quux-oteleq generate --workspace "$OTELEQ_WORKSPACE"

quux-oteleq run --workspace "$OTELEQ_WORKSPACE" \
  --report-dir "$OTELEQ_REPORT_DIR" --keep-workspace
```

The planned run compares an uninstrumented baseline with the required instrumented lanes using the same concrete inputs and independently prepared initial state. Reports describe matching observations, differences, instrumentation evidence and any functions or state that could not be tested. Missing required evidence prevents a successful equivalence verdict.

`--keep-workspace` retains the generated tests and replay artefacts. Omit it to remove a successful run's transient workspace after durable report export; failed or incomplete runs are retained by default.

### Optionally incorporate generated tests

Review the proposed destination files and framework dependencies before explicitly copying tests into your application repository:

```sh
quux-oteleq promote --workspace "$OTELEQ_WORKSPACE" \
  --destination /path/to/application/tests/oteleq --dry-run

quux-oteleq promote --workspace "$OTELEQ_WORKSPACE" \
  --destination /path/to/application/tests/oteleq --apply
```

The generated framework may differ from your existing framework. Promotion refuses conflicting files and includes runner/dependency instructions; see [test retention and incorporation](docs/test-generation.md#optional-incorporation-into-a-repository).

### Replay a difference and clean up

Use a case ID from the report to replay a retained difference. When the retained workspace is no longer needed, remove it with the workspace cleanup command:

```sh
quux-oteleq replay --bundle "$OTELEQ_REPORT_DIR/replay" --case case-0042

quux-oteleq clean --workspace "$OTELEQ_WORKSPACE"
```

See the [full CLI contract](docs/cli-and-configuration.md) for planned reports, exit codes and capability checks.
