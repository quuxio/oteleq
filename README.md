<p align="center">
  <img src="docs/assets/quux-mark.png" width="160" alt="quux">
</p>

# oteleq

**Behavioural equivalence evidence for instrumented applications. A [quux](https://quux.io) project.**

[![CI](https://github.com/quuxio/oteleq/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/quuxio/oteleq/actions/workflows/ci.yml)
[![Status](https://img.shields.io/badge/status-scalar%20test%20generation-blue)](docs/roadmap.md)
[![License](https://img.shields.io/badge/license-AGPL--3.0-blue)](LICENSE)

---

[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=quuxio_oteleq&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=quuxio_oteleq)
[![Bugs](https://sonarcloud.io/api/project_badges/measure?project=quuxio_oteleq&metric=bugs)](https://sonarcloud.io/summary/new_code?id=quuxio_oteleq)
[![Code Smells](https://sonarcloud.io/api/project_badges/measure?project=quuxio_oteleq&metric=code_smells)](https://sonarcloud.io/summary/new_code?id=quuxio_oteleq)
[![Coverage](https://img.shields.io/badge/coverage-not%20reported-lightgrey)](docs/quality.md)
[![Duplicated Lines (%)](https://sonarcloud.io/api/project_badges/measure?project=quuxio_oteleq&metric=duplicated_lines_density)](https://sonarcloud.io/summary/new_code?id=quuxio_oteleq)
[![Lines of Code](https://sonarcloud.io/api/project_badges/measure?project=quuxio_oteleq&metric=ncloc)](https://sonarcloud.io/summary/new_code?id=quuxio_oteleq)
[![Reliability Rating](https://sonarcloud.io/api/project_badges/measure?project=quuxio_oteleq&metric=reliability_rating)](https://sonarcloud.io/summary/new_code?id=quuxio_oteleq)
[![Security Rating](https://sonarcloud.io/api/project_badges/measure?project=quuxio_oteleq&metric=security_rating)](https://sonarcloud.io/summary/new_code?id=quuxio_oteleq)
[![Technical Debt](https://sonarcloud.io/api/project_badges/measure?project=quuxio_oteleq&metric=sqale_index)](https://sonarcloud.io/summary/new_code?id=quuxio_oteleq)
[![Maintainability Rating](https://sonarcloud.io/api/project_badges/measure?project=quuxio_oteleq&metric=sqale_rating)](https://sonarcloud.io/summary/new_code?id=quuxio_oteleq)
[![Vulnerabilities](https://sonarcloud.io/api/project_badges/measure?project=quuxio_oteleq&metric=vulnerabilities)](https://sonarcloud.io/summary/new_code?id=quuxio_oteleq)
[![Repo Traffic](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fquuxio%2Foteleq%2Ftraffic-badges%2F.badges%2Ftraffic.json&cacheSeconds=3600)](https://github.com/quuxio/oteleq)

---

oteleq generates diagnostic tests that compare application behaviour with and without [otelc](https://github.com/quuxio/otelc) instrumentation across C, C++, Rust, Python, Java, JavaScript, TypeScript and Go. It compares results, errors, stdout/stderr and supported global/object state, while accounting for emitted OpenTelemetry telemetry separately.

Fixed diagnostic corpora also qualify [Python and Java executor context](docs/eight-language-capture.md) and the [optional native TypeScript emitter](docs/eight-language-capture.md#optional-native-typescript-workload) against the actual otelc adapters.

The result is **equivalence over these tests and observations**. It is not a blanket proof that every function is identical.

Generated tests live in a new private directory outside the application repository. Users can retain or explicitly export them, using Python's standard `unittest` suite independently of the application's existing framework.

**Status: automatic scalar test generation, AST inventory and repeated actual otelc execution are implemented for all eight languages.** Supported functions receive frozen concrete inputs; unsupported callables and state remain visible blockers. Python and Node capture supported object graphs; other adapters capture scalar results and accessible scalar globals. Generated access/entrypoint helpers produce diagnostic evidence. Shipping-artefact qualification and application-specific fixtures remain future work.

Start with [automatic generation](docs/automatic-generation.md), [fixed eight-language workloads](docs/eight-language-capture.md) or [workload comparison](docs/workload-comparison.md). See [usefulness and limits](docs/adoption.md), the [design](docs/design.md) and [roadmap](docs/roadmap.md).

## Usage

### Build

With Git and Rust 1.98.1 or newer installed:

```sh
git clone https://github.com/quuxio/oteleq.git
cd oteleq
cargo build --locked
./target/debug/quux-oteleq --help
```

`cargo install --path . --locked` installs `quux-oteleq` locally. The CLI embeds its generation workers. Generation and capture additionally require Python 3.12+, otelc's locked OTLP decoder environment and the qualified tools/adapters for the selected languages; see [setup and capabilities](docs/automatic-generation.md). Contributor tooling and CI coverage instructions are in [repository quality](docs/quality.md).

### Generate and run tests

Build otelc's qualified adapters first. Use its locked Python environment, then create an external plan and use the workspace path printed by `plan`:

```sh
export OTELEQ_PYTHON=/absolute/path/to/otelc/.venv/bin/python
OTELEQ_CLI=/absolute/path/to/oteleq/target/debug/quux-oteleq
"$OTELEQ_CLI" plan --source /absolute/path/to/application \
  --otelc-root /absolute/path/to/otelc --workspace-parent /tmp

OTELEQ_WORKSPACE=/tmp/oteleq-run-actual-id
"$OTELEQ_CLI" generate --workspace "$OTELEQ_WORKSPACE"
"$OTELEQ_CLI" run --workspace "$OTELEQ_WORKSPACE" \
  --report-dir /absolute/path/to/new-report
"$OTELEQ_PYTHON" "$OTELEQ_WORKSPACE/tests/test_equivalence.py"
```

The default generates up to three distinct scalar cases per function and compares two plain with two instrumented runs per case. Missing instrumentation, changed source, unstable observations, failed builds and selected blockers fail the gate. The report records tested inputs, state coverage, telemetry and gaps. Syntax discovery and scalar samples do not establish business preconditions.

Use repeated `--language ID`, `--exclude 'qualified.pattern'` and `--cases 1` through `--cases 16` on `plan` to select a supported scope. [The CLI reference](docs/cli-and-configuration.md#implemented-commands) lists every public command and flag.

### Replay, retain or incorporate

```sh
"$OTELEQ_CLI" replay --workspace "$OTELEQ_WORKSPACE" --case case-id-from-corpus

"$OTELEQ_CLI" export-tests --workspace "$OTELEQ_WORKSPACE" \
  --destination /absolute/path/to/new-tests
"$OTELEQ_CLI" export-tests --workspace "$OTELEQ_WORKSPACE" \
  --destination /absolute/path/to/new-tests --apply

"$OTELEQ_CLI" clean --workspace "$OTELEQ_WORKSPACE"
```

Export includes a frozen application snapshot and runnable suite. It refuses existing destinations and may be placed in the application only by that explicit choice. Generated boilerplate is MIT licensed; application code retains its licence. Retained suites test their frozen snapshot; create a new plan for changed application code. See [capabilities, limits and complete usage](docs/automatic-generation.md). The broader [configuration/adapter protocol](docs/cli-and-configuration.md) and [example policy](examples/equivalence.toml) remain proposed interfaces.

### Compare an existing workload bundle

```sh
./target/debug/quux-oteleq compare-workload /path/to/bundle.json > /path/to/comparison.json
```

This command consumes repeated captured observations from a qualified observer. The [fixed eight-language integration](docs/eight-language-capture.md) creates such bundles using actual otelc workloads. See [the evidence schema and exit codes](docs/workload-comparison.md).
