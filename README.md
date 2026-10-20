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

oteleq generates diagnostic tests that compare application behaviour with and without [otelc](https://github.com/quuxio/otelc) instrumentation across C, C++, Rust, Python, Java, JavaScript, TypeScript and Go. It compares results, errors, stdout/stderr, supported global/object state and declared [filesystem boundaries](docs/filesystem-effects.md) and [HTTP fixtures](docs/http-fixtures.md), while accounting for emitted OpenTelemetry telemetry separately.

The [HTTP qualification](docs/qualification/http-fixtures-2026-10-20.json) covers 18 cases and 544 actual launches across all eight languages, including same-return request differences, incomplete capture and scalar shrinking/replay.

A separate [integrated-provider qualification](docs/qualification/integrated-provider-2026-10-20.json) checks the standard fixed and scalar workflows against frozen otelc `d6d03b7`: 533 actual launches, including matching cases, deliberate state differences and refused fixtures. Earlier capability records retain their own provider identities.

Fixed diagnostic corpora also qualify [Python and Java executor context](docs/eight-language-capture.md), [Python collection lifetimes](docs/eight-language-capture.md#python-collection-lifetime-workload), [fixed Python resource closes](docs/eight-language-capture.md#python-resource-close-workload) and the [optional native TypeScript emitter](docs/eight-language-capture.md#optional-native-typescript-workload) against the actual otelc adapters.

The [original-source Rust compiler corpus](docs/rust-build-bundles.md) qualifies four generated scalar cases through generated/exported suites and fixed completion/cancellation/unwind and aliased-module diagnostics: 108 candidate-provider launches, 24 legacy compatibility launches and 14 altered build-record refusals. General Cargo, generated async and receiver support remain open.

The result is **equivalence over these tests and observations**. It is not a blanket proof that every function is identical.

Generated tests live in a new private directory outside the application repository. Selection, scalar domain fixtures, seeded inputs and execution budgets use a [validated project policy](docs/automatic-generation.md#project-policy-and-concrete-fixtures). Users can retain or explicitly export them, using Python's standard `unittest` suite independently of the application's existing framework.

**Status: automatic scalar test generation, AST inventory and repeated actual otelc execution are implemented for all eight languages.** Supported functions receive frozen concrete inputs; unsupported callables and state remain visible blockers. Python and Node capture supported object graphs; declared [Java receiver fixtures](docs/java-receivers.md) add source-field graphs and permitted private access. Declared [Go receivers](docs/go-receivers.md) add source-bound private struct/array storage and pointer aliases, with [168-launch qualification](docs/qualification/go-receivers-2026-10-20.json). Declared [C++ receiver fixtures](docs/cpp-receivers.md) add private source-field graphs, pointer/reference aliases and fixed constructor/factory inputs, with [171-launch diagnostic qualification](docs/qualification/cpp-receivers-2026-10-20.json). C and Rust capture scalar results and accessible scalar globals. Native scalar types are checked by the compiler; C++ scalar aliases additionally use Clang's resolved declarations. Generated access/entrypoint helpers produce diagnostic evidence. Shipping-artefact qualification and application-specific fixtures remain future work.

Declared [ordered Node receiver calls/release](docs/ordered-sequences.md) retain intermediate state, with bounded JavaScript collection observations and [148-launch qualification](docs/qualification/ordered-sequences-2026-10-20.json). Missing collection stays inconclusive.

Start with [automatic generation](docs/automatic-generation.md), [fixed eight-language workloads](docs/eight-language-capture.md) or [workload comparison](docs/workload-comparison.md). See [usefulness and limits](docs/adoption.md), the [design](docs/design.md) and [roadmap](docs/roadmap.md).

Observers refuse unsupported application formatters and exception accessors. Such capture failures remain incomplete evidence; see the [qualified codec limits](docs/automatic-generation.md#selection-and-inputs).

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

Render a retained run as [standalone HTML and JUnit XML](docs/reporting.md):

```sh
"$OTELEQ_CLI" render-report /absolute/path/to/new-report/report.json \
  --output-dir /absolute/path/to/new-presentation
```

Rust requires the [standalone build/run provider API](docs/rust-build-bundles.md); combined compile-and-launch providers are unsupported. The default `compiler` backend and opt-in `llvm` profile use separate matched flag and provenance contracts. The original-source compiler schema3 validator additionally binds its fixed profile, MIR driver, request and emitted inventory; the [original-source compiler corpus](docs/qualification/rust-compiler-2026-10-20.json) records its actual provider qualification. LLVM accepts the original profile1/inventory2 pair or the compiler frontend profile2/inventory3 pair, with its fixed frontend asset and emitted-symbol checks. The [frontend record](docs/qualification/rust-frontend-2026-10-20.json) names exact qualified revisions and gaps; format support alone does not qualify a new provider.

The default generates up to three distinct scalar cases per function and compares two plain with two instrumented runs per case. Missing instrumentation, changed source, unstable observations, failed builds and selected blockers fail the gate. The report records tested inputs, state coverage, telemetry and gaps. Syntax discovery and scalar samples do not establish business preconditions.

Go requires the [retained build/run provider API](docs/go-build-bundles.md). Each attempt retains its matched baseline/instrumented executables, compiler channels and loaded source/dependency identities; both launches replay without compilation. Explicit [Go module roots](docs/go-package-context.md) add real package/type discovery, sibling state, imported named scalar types and frozen build tags, using private callers for libraries and `main` packages. Provider module/checksum/runtime/policy changes invalidate the plan. Private compiler/module caches are reused; cgo/workspaces, broader build recipes and SDK dependency isolation remain open. The [standalone Go build qualification](docs/qualification/go-builds-2026-10-20.json) records 78 actual launches, matched byte/status/signal controls and strict prelaunch refusals. The [Go package corpus](docs/qualification/go-packages-2026-10-20.json) adds six cases and 112 actual launches across library, nested-module and tagged builds, including the mutation control and shrinking/replay.

For ordinary Go instance methods, declare `receiver = { factory = "New", arguments = [10] }` with explicit module roots. [Go receiver fixtures](docs/go-receivers.md) cover private source fields, arrays, primitive panics and pointer aliases, including converted pointer views. Their [nine-case/168-launch corpus](docs/qualification/go-receivers-2026-10-20.json) also checks executable packages and returned struct copies.

Python can use explicit [source package import roots](docs/python-package-context.md), including regular packages and `src` layouts. Relative imports and package initialisers use their real module context; unsupported package contexts remain blockers.

[Declared receiver fixtures](docs/receiver-fixtures.md) test ordinary Python, Java, JavaScript and TypeScript instance methods using existing constructors or same-module factories. They capture supported instance graphs and declared class statics, with independently reconstructed state for every attempt. Node methods can await declared async completion. Java has a separate declared private-access profile; inherited/native storage and arbitrary action targets remain unsupported. The [Node receiver qualification](docs/qualification/node-receivers-2026-10-20.json) records both language IDs, 186 actual launches and detected same-return instance/static mutation controls.

The [Java receiver qualification](docs/qualification/java-receivers-2026-10-20.json) records eight cases and 151 actual launches, including private constructor/factory/method access, arrays and aliases, expected exceptions, same-return instance/static differences, scalar shrinking and refusal controls. Its [observation contract](docs/java-receivers.md) covers own source fields and class/message exception payloads; broader Java project/module integration remains open.

Node receivers can opt into [ordered call/release sequences](docs/ordered-sequences.md), with intermediate typed observations and optional bounded JavaScript collection checks. Missing actions or unobserved collection remain incomplete; GC timing is excluded from equality. [TypeScript collection](docs/typescript-collection.md) requires explicit source/native selection and a successful public provider capability gate, with [264-launch qualification](docs/qualification/typescript-collection-2026-10-20.json).

Use repeated `--language ID`, `--exclude 'qualified.pattern'` and `--cases 1` through `--cases 1024` on `plan` to select a supported scope. [The CLI reference](docs/cli-and-configuration.md#implemented-commands) lists every public command and flag.

### Replay, retain or incorporate

For a reproducible difference, [counterexample shrinking](docs/counterexample-shrinking.md) reduces scalar inputs within explicit fixture domains and retains a sealed replay suite plus all trial evidence. It preserves the qualified failure and reports budget/incomplete-search limits.

```sh
"$OTELEQ_CLI" replay --workspace "$OTELEQ_WORKSPACE" --case case-id-from-corpus

"$OTELEQ_CLI" export-tests --workspace "$OTELEQ_WORKSPACE" \
  --destination /absolute/path/to/new-tests
"$OTELEQ_CLI" export-tests --workspace "$OTELEQ_WORKSPACE" \
  --destination /absolute/path/to/new-tests --apply

"$OTELEQ_CLI" clean --workspace "$OTELEQ_WORKSPACE"
```

Export includes a frozen application snapshot and runnable suite. It refuses existing destinations and may be placed in the application only by that explicit choice. Generated boilerplate is MIT licensed; application code retains its licence. Retained suites test their frozen snapshot; create a new plan for changed application code. See [capabilities, limits and complete usage](docs/automatic-generation.md). Pass the executable [example policy](examples/equivalence.toml) with `plan --config PATH` for selection, scalar fixtures and budgets. Broader build/factory and generated graph-adapter integration remain on the [completion checklist](docs/completion.md).

### Compare an existing workload bundle

```sh
./target/debug/quux-oteleq compare-workload /path/to/bundle.json > /path/to/comparison.json
```

This command consumes repeated captured observations from a qualified observer. The [fixed eight-language integration](docs/eight-language-capture.md) creates such bundles using actual otelc workloads. See [the evidence schema and exit codes](docs/workload-comparison.md).

### Compare typed boundary graphs

```sh
./target/debug/quux-oteleq compare-observations /path/to/typed-bundle.json > /path/to/typed-comparison.json
```

The [typed comparator](docs/typed-comparison.md) reports field paths, alias/cycle changes, invalid initial fixtures and incomplete captures while retaining repeated execution and telemetry checks. Its shared format accepts all eight language IDs. Generated scalar workers emit that format in `typed-bundle.json`, retaining raw capture separately. They validate declared initial roots and baseline outcome expectations. Richer receivers/factories and additional graph codecs remain incomplete.
