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

Declared [numeric argument preconditions](docs/numeric-preconditions.md), such as `start < end`, constrain automatic domain generation and scalar reduction. They remain frozen through generated suites and replay/export, and apply to every supported ordered method call. Their [912-launch qualification](docs/qualification/numeric-preconditions-2026-10-22.json) covers all eight scalar profiles, Java/Node ordered calls, all four retained routes, replay, reduction and 24 prelaunch refusals.

[Node caller context](docs/node-source-context.md) preserves actual CommonJS/ES-module formats across original sources, private snapshots and generated callers, including `.js`/`.ts` package interpretation. Its [245-launch qualification](docs/qualification/node-projects-2026-10-22.json) covers eleven module contexts, declared receivers, detached suites, replay, reduction and refusal controls; the existing receiver corpus separately passes 186 launches on that same CLI. General Node dependency/build integration remains open.

Python [source-package imports](docs/python-package-context.md) retain their context through declared receiver construction. Namespace packages, ambiguous roots and shadowed modules remain visible blockers, including in generated and exported suites.

Generated tests live in a new private directory outside the application repository. Selection, scalar domain fixtures, [declared return values](docs/expected-returns.md), seeded inputs and execution budgets use a [validated project policy](docs/automatic-generation.md#project-policy-and-concrete-fixtures). Users can retain or explicitly export them, using Python's standard `unittest` suite independently of the application's existing framework.

**Status: automatic scalar test generation, AST inventory and repeated actual otelc execution are implemented for all eight languages.** Supported functions receive frozen concrete inputs; unsupported callables and state remain visible blockers. Python and Node capture supported object graphs; declared [Java receiver fixtures](docs/java-receivers.md) add source-field graphs and permitted private access. Declared [Go receivers](docs/go-receivers.md) add source-bound private struct/array storage and pointer aliases, with [168-launch qualification](docs/qualification/go-receivers-2026-10-20.json). Declared [C++ receiver fixtures](docs/cpp-receivers.md) add private source-field graphs, pointer/reference aliases and fixed constructor/factory inputs, with [331-launch diagnostic qualification](docs/qualification/cpp-receivers-2026-10-20.json). C and Rust capture scalar results and accessible scalar globals. Native scalar types are checked by the compiler; C++ scalar aliases additionally use Clang's resolved declarations. Generated access/entrypoint helpers produce diagnostic evidence. Shipping-artefact qualification and application-specific fixtures remain future work.

**Provider compatibility:** the default generated workflows use qualified pre-rebuild otelc APIs, such as the frozen [`d6d03b7` provider](docs/qualification/integrated-provider-2026-10-20.json). Java can explicitly select the replacement SDK's [prepared provider](docs/java-prepared-provider.md) with `[adapters.java] backend = "prepared"`. It verifies the public launch recipe, compiler bindings, loaded class origins, actual JVM PID and direct health/OTLP receipt. Node has the explicit source profile below. Other replacement-SDK adapters require their own consumer integration and qualification. Prepare the matching tools from the recorded provider revision.

The explicit rebuilt-SDK [Node `source-v1` profile](docs/node-source-context.md#rebuilt-sdk-source-profile) has [1,800-launch qualification](docs/qualification/node-source-provider-2026-10-22.json) covering Node 24/26, both TypeScript compilers, declared receivers, bounded collection, binary application output, filesystem/HTTP effects and retained/promoted suites. It checks actual application/SDK processes, source/emission/body-entry evidence and direct health/OTLP. [Live Node metric schedules](docs/node-metric-controls.md) have separate [696-launch positive-first evidence](docs/qualification/node-metric-controls-2026-10-23.json) and [2,784-launch startup qualification](docs/qualification/node-startup-metric-controls-2026-10-23.json) across all four initial states. Action attribution and general dependency/build integration remain open.

The [prepared Java qualification](docs/qualification/java-prepared-2026-10-21.json) completes 151 receiver JVM launches through generated/exported suites, replay, shrinking and refusal controls, plus four packaged recursive and eight legacy-compatibility launches. It verifies complete independent state/outcome oracles, actual PID/health/OTLP accounting and removal of owned short runtimes.

Prepared Java keeps the original `stock-methods-v1` launch profile and accepts an explicit `safe-methods-v1` recipe for the corrected SDK. The safe recipe binds exception-safe advice and a pinned bootstrap parser patch. See [profile selection](docs/java-prepared-provider.md#select-the-fixed-launch-profile) and exact-revision qualification before choosing a provider.

The [corrected-profile qualification](docs/qualification/java-safe-profile-2026-10-21.json) completes 164 actual JVM launches against immutable SDK `e4aaafa`, including a matching exception-cause getter regression, all four live metric states and ordinary legacy compatibility. The original frozen provider's genuine getter-mutation difference remains recorded separately.

Prepared Java receiver sequences can also request [live metric collection and emission controls](docs/java-metric-controls.md). One unchanged JVM executes the declared states; direct metric receipt distinguishes recording suppression from transport silence while traces remain active. The scope is selected synchronous method trees. The [164-launch qualification](docs/qualification/java-metric-controls-2026-10-21.json) covers generated/replayed/exported/reduced routes, actual off-state receipts and ordinary prepared/legacy compatibility. It also retains a real getter-mutation difference in the frozen SDK.

Generated Java builds retain [compiler-owned source/class bindings](docs/java-build-bundles.md), actual class products and the selected JDK module-image identity. They require a complete JDK 21 and use a fixed UTF-8 profile with annotation processing disabled. The prepared manifest supports ongoing SDK integration; general Java classpath/module builds remain open.

Declared [ordered receiver calls and Node calls/release](docs/ordered-sequences.md) retain intermediate state. The [Java call-only corpus](docs/qualification/java-sequences-2026-10-21.json) qualifies 240 actual JVMs across prepared/legacy providers, including a state difference restored before the final boundary. The earlier [148-launch qualification](docs/qualification/ordered-sequences-2026-10-20.json) covers Node calls/release and bounded JavaScript collection. Missing collection stays inconclusive.

Opt-in [native project context](docs/native-project-context.md) preserves explicit C/C++ compilation-database targets, generated inputs, matched per-unit recipes and target-wide scalar state through generated suites, replay, export and scalar reduction. Its [64-launch qualification](docs/qualification/native-projects-2026-10-21.json) uses one frozen SDK candidate; compatibility with the replacement SDK, richer project-mode receivers and general build-system integration remain open.

Declared [Java source roots and dependencies](docs/java-project-context.md) add complete target-unit compilation and ordered private JAR/class/resource inputs. Compiler reads, dependency bytes and loaded class origins remain checked through replay and detached export. The [168-launch qualification](docs/qualification/java-projects-2026-10-21.json) covers prepared and legacy providers, private receivers, resources and scalar reduction. The explicit prepared [runtime archive profile](docs/java-runtime-archives.md) adds multi-release selection and independently verified helper relocation, with [260-launch qualification](docs/qualification/java-archives-2026-10-22.json) across eleven variants, private receivers, live metric states, detached suites and reduction. Maven/Gradle execution and modules remain open.

Declared [C++ receiver call sequences](docs/cpp-receivers.md#ordered-calls) now retain intermediate graphs, errors and aliases on one constructed receiver. Their [149-launch qualification](docs/qualification/cpp-sequences-2026-10-23.json) covers private factories, intermediate errors, recursion, replay/export, scalar reduction, a restored state difference and one/32-call bounds. The earlier C++ record keeps its single-call scope.

Start with [automatic generation](docs/automatic-generation.md), [fixed eight-language workloads](docs/eight-language-capture.md) or [workload comparison](docs/workload-comparison.md). See [usefulness and limits](docs/adoption.md), the [design](docs/design.md) and [roadmap](docs/roadmap.md).

Observers refuse unsupported application formatters and exception accessors. Such capture failures remain incomplete evidence; see the [qualified codec limits](docs/automatic-generation.md#selection-and-inputs).

The explicit [Node live metric schedule](docs/node-metric-controls.md) has [2,784-launch startup qualification](docs/qualification/node-startup-metric-controls-2026-10-23.json) on Node 24/26 for JavaScript `.cjs`, native TypeScript `.cts` and API TypeScript `.mts`. It starts with either metric flag disabled independently or together, preserves one application/SDK pair through all four states and requires a both-on call somewhere in the schedule. The complete corpus catches a restored intermediate mutation, refuses 336 altered-evidence controls and independently recomputes 720 comparisons. [Prepared Java startup schedules](docs/java-metric-controls.md#qualify-startup-schedules) have separate [2,256-JVM qualification](docs/qualification/java-startup-metric-controls-2026-10-23.json) across all four initial states in three recorded provider profiles, with 168 refusals and 576 recomputed comparisons. Earlier positive-first and source-provider records retain their own scope.

Declared [Python ordered calls](docs/ordered-sequences.md#python-call-sequences) retain every intermediate receiver/global/static graph on one reconstructed instance. Their [150-launch diagnostic record](docs/qualification/python-sequences-2026-10-23.json) covers retained suites, replay, reduction and refusal controls, with separate single-call compatibility. Async, release and collection remain outside this call-only profile; explicit prepared live metric schedules have separate qualification below.

## Usage

Rebuilt Python [prepared execution](docs/python-prepared-provider.md) has an explicit generated worker route when `adapters.python.backend = "prepared"` and `profile = "python-native-origins-v2"` are both selected. It checks target/declared source creation origins in both lanes, actual process identities, direct health and decoded telemetry. Its [424-launch diagnostic qualification](docs/qualification/python-generated-origins-2026-10-24.json) covers Python 3.12/3.14 receivers, generated domains, filesystem/HTTP effects and retained/promoted workflows. The original input-only prepared profile stays blocked, and the default legacy provider is unchanged.

The explicit [Python cached-loader profile](docs/python-cache-context.md) preserves existing cache bytes and source timestamps through private and retained execution. Its separate [488-launch diagnostic qualification](docs/qualification/python-generated-caches-2026-10-24.json) covers ordinary cache/fallback decisions, receivers, effects and retained/promoted workflows on Python 3.12/3.14. A cache binding does not prove compilation of current source; the source-only record remains separate.

Python [live metric schedules](docs/python-metric-controls.md) have [3,008-launch diagnostic qualification](docs/qualification/python-metric-controls-2026-10-24.json) across Python 3.12.15/3.14.8, both explicit prepared origin/cache profiles and all four initial states. One unchanged application/SDK pair executes each schedule, including independent collection/emission controls and restored retained measurements. The corpus checks complete intermediate graphs, retained/promoted routes, 768 recomputed comparisons and 224 altered-evidence refusals. Broader actions, invocation attribution and shipping workloads remain open.

The explicit [Java private-handle action profile](docs/java-action-witness.md#generated-private-handle-profile) connects generated callers, offline bindings, public preparation, host control, typed outcomes, decoded traces, function metrics and final SDK health. Its [160-JVM diagnostic qualification](docs/qualification/java-generated-actions-2026-10-24.json) covers the recorded safe/archive provider, retained workflows and four metric startup states. Broader Java build, object, asynchronous and shipping scope remains open. Default generated Java profiles retain their documented witness limits.

### Build

With Git and Rust 1.98.1 or newer installed:

```sh
git clone https://github.com/quuxio/oteleq.git
cd oteleq
cargo build --locked
./target/debug/quux-oteleq --help
```

`cargo install --path . --locked` installs `quux-oteleq` locally. The CLI embeds its generation workers. Generation and capture additionally require Python 3.12+, otelc's locked OTLP decoder environment and the qualified tools/adapters for the selected languages; see [setup and capabilities](docs/automatic-generation.md). Contributor tooling and CI coverage instructions are in [repository quality](docs/quality.md).

Maintainers can use the checkout's [cold receipt archive/restore commands](docs/qualification-retention.md) to reduce completed qualification storage. Archived raw paths must be restored before existing retained verifiers run.

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
"$OTELEQ_PYTHON" -I -B "$OTELEQ_WORKSPACE/tests/test_equivalence.py"
```

Render a retained run as [standalone HTML and JUnit XML](docs/reporting.md):

```sh
"$OTELEQ_CLI" render-report /absolute/path/to/new-report/report.json \
  --output-dir /absolute/path/to/new-presentation
```

Rust requires the [standalone build/run provider API](docs/rust-build-bundles.md); combined compile-and-launch providers are unsupported. The default `compiler` backend and opt-in `llvm` profile use separate matched flag and provenance contracts. The original-source compiler schema3 validator additionally binds its fixed profile, MIR driver, request and emitted inventory; the [original-source compiler corpus](docs/qualification/rust-compiler-2026-10-20.json) records its actual provider qualification. LLVM accepts the original profile1/inventory2 pair or the compiler frontend profile2/inventory3 pair, with its fixed frontend asset and emitted-symbol checks. The [frontend record](docs/qualification/rust-frontend-2026-10-20.json) names exact qualified revisions and gaps; format support alone does not qualify a new provider.

The default generates up to three distinct scalar cases per function and compares two plain with two instrumented runs per case. Missing instrumentation, changed source, unstable observations, failed builds and selected blockers fail the gate. The report records tested inputs, state coverage, telemetry and gaps. Syntax discovery and scalar samples do not establish business preconditions.

[Declared independent domains](docs/domain-generation.md) can supply concrete inputs automatically. Omit the fixture's literal case list when each parameter has a reviewed scalar domain; planning freezes the resulting requests for both builds, replay and retained suites.

The [domain-generation qualification](docs/qualification/domain-generation-2026-10-22.json) checks 30 functions and 82 initial cases across all eight languages through direct, generated and detached/exported routes. Its 1,384 actual launches include two deliberate differences per full route, frozen-policy replay, scalar reduction and seeded inputs. Fourteen invalid domain contracts fail before application execution. General relational/factory/object generation remains open.

Go requires the [retained build/run provider API](docs/go-build-bundles.md). Each attempt retains its matched baseline/instrumented executables, compiler channels and loaded source/dependency identities; both launches replay without compilation. Explicit [Go module roots](docs/go-package-context.md) add real package/type discovery, sibling state, imported named scalar types and frozen build tags, using private callers for libraries and `main` packages. Provider module/checksum/runtime/policy changes invalidate the plan. Private compiler/module caches are reused; cgo/workspaces, broader build recipes and SDK dependency isolation remain open. The [standalone Go build qualification](docs/qualification/go-builds-2026-10-20.json) records 78 actual launches, matched byte/status/signal controls and strict prelaunch refusals. The [Go package corpus](docs/qualification/go-packages-2026-10-20.json) adds six cases and 112 actual launches across library, nested-module and tagged builds, including the mutation control and shrinking/replay.

For ordinary Go instance methods, declare `receiver = { factory = "New", arguments = [10] }` with explicit module roots. [Go receiver fixtures](docs/go-receivers.md) cover private source fields, arrays, primitive panics and pointer aliases, including converted pointer views. Their [nine-case/168-launch corpus](docs/qualification/go-receivers-2026-10-20.json) also checks executable packages and returned struct copies.

The rebuilt [Go prepared provider](docs/go-prepared-provider.md) has independent protocol, input/build, 21-file context reconstruction, call-only helper/rule, prepared-recipe, owned-execution and health components. A private worker gate binds actual native ownership before calls. The current development path uses explicit build4/config2/health4 and keeps HTTP completion separate from resource release and GC. Public generator admission and complete actual-provider workflow qualification remain in progress. Earlier build-3 and retained-provider records remain tied to their frozen APIs.

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

Cleanup can remove an unchanged owned workspace after its original sources or toolchain have been removed. [Retention and cleanup](docs/test-generation.md#retention-and-cleanup) explains the preservation checks.

Export includes a frozen application snapshot and runnable suite. It refuses existing destinations and may be placed in the application only by that explicit choice. Generated boilerplate is MIT licensed; application code retains its licence. Retained suites test their frozen snapshot; create a new plan for changed application code. See [capabilities, limits and complete usage](docs/automatic-generation.md). Pass the executable [example policy](examples/equivalence.toml) with `plan --config PATH` for selection, scalar fixtures and budgets. Broader build/factory and generated graph-adapter integration remain on the [completion checklist](docs/completion.md).

[Planning after an in-source export](docs/retained-source-selection.md) verifies and excludes retained oteleq bundles from application discovery and snapshots. Invalid or edited bundles stop planning; plans and reports disclose the exclusions.

For future application changes, [promote a current-source suite](docs/current-source-tests.md). `promote --workspace "$OTELEQ_WORKSPACE" --source /absolute/path/to/application --destination /absolute/path/to/application/equivalence-tests` prints its file plan; add `--apply` to create it. Run `python3 -I -B` on its `test_equivalence.py` to generate and execute fresh per-case tests from the current checkout in external private workspaces. Tool/provider context and policy remain frozen, and selected gaps remain failures. The [exact-revision qualification](docs/qualification/current-source-tests-2026-10-22.json) checks the supported eight-language profiles through changed bodies, checkout relocation and newly added functions.

[Input inspection](docs/input-inspection.md) refuses unreadable or vanished directories instead of silently omitting their contents from plans or byte identities. On qualified POSIX hosts, shared hashing also rejects named pipes without waiting for a writer.

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

## Development

See [repository quality](docs/quality.md) for contributor tools and full checks. `make dependency-audit` runs the [locked dependency audit](docs/dependency-audit.md); required CI and a separate weekly workflow retain its current advisory evidence.
