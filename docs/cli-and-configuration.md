# Proposed CLI, configuration and adapter protocol

## Status

The broader commands and contracts on this page remain design interfaces. The implemented `quux-oteleq compare-workload BUNDLE.json` command uses a separate byte-channel schema documented in [workload comparison](workload-comparison.md). The proposed executable is `quux-oteleq`. Configuration has its own version-1 schema and references otelc's schema-2 policy; it does not duplicate otelc selection/export rules.

## Workflow

```sh
# Inspect build/language capabilities without generating or executing tests.
quux-oteleq doctor --source /path/to/application \
  --config /path/to/equivalence.toml

# Create an external workspace, inventory and reviewable generation plan.
quux-oteleq plan --source /path/to/application \
  --config /path/to/equivalence.toml \
  --workspace-parent /path/to/temporary-runs

# Each plan prints its unique workspace path. Use that path below.
quux-oteleq generate --workspace /path/to/temporary-runs/oteleq-run-<id>

# Export durable reports before successful transient cleanup.
quux-oteleq run --workspace /path/to/temporary-runs/oteleq-run-<id> \
  --report-dir /path/to/reports/run-<id> --keep-workspace

# Reproduce a retained difference without generating new inputs.
quux-oteleq replay --bundle /path/to/reports/run-<id>/replay --case case-0042

# Review which generated files and dependencies would be incorporated.
quux-oteleq promote --workspace /path/to/temporary-runs/oteleq-run-<id> \
  --destination /path/to/application/tests/oteleq --dry-run

# Explicitly apply the copy plan; conflicting files remain an error.
quux-oteleq promote --workspace /path/to/temporary-runs/oteleq-run-<id> \
  --destination /path/to/application/tests/oteleq --apply

# Remove a retained owned workspace.
quux-oteleq clean --workspace /path/to/temporary-runs/oteleq-run-<id>
```

The angle-bracket path token denotes the workspace ID printed by `plan`; replace the full placeholder before running a command. `--workspace-parent` is optional and defaults to the operating-system temporary directory. All generation/build paths resolve outside the application repository. `--report-dir` is required for a transient run and must be durable and outside the owned workspace; copying tests into the source tree only occurs through explicit promotion.

`plan` validates configuration and build/discovery capabilities; it does not execute target functions. Semantic discovery can still require compiler/build tooling. `generate` creates runner projects, dependency locks, fixture requests and a corpus. It may execute configured fixture/discovery workers only in the declared execution environment. `run` validates the unchanged plan/source identities before building and executing.

Reports are JSON plus a standalone HTML view and JUnit XML for CI. The HTML view presents selected/excluded functions, tests actually executed, required lanes, observation scope, differences, gaps and source/build identity. JUnit maps incomplete/blocked selected work to a failing strict gate; it cannot represent them as passing tests. There is no application report renderer yet.

## Configuration

The [example policy](../examples/equivalence.toml) expresses all eight languages and the default strict evidence requirement. `/path/...` values are placeholders. This repository validates TOML syntax, not application-schema execution.

| Section | Contract |
| --- | --- |
| `schema_version`, `languages` | Explicit schema and enabled language IDs; unknown/duplicate IDs fail |
| `sources`, `functions` | Original-path/name include/exclude policy; exclusions win and remain inventoried |
| `workspace` | New external run directory and failure retention; source-tree writes are prohibited |
| `instrumentation` | Provider, executable, external otelc policy and explicitly requested lanes |
| `generation` | Seed, per-function budgets, edge cases and stateful-sequence bounds |
| `state` | Receiver/argument roots, discovered observable globals and requested capture mode |
| `effects` | Application output and declared filesystem/fixture channels |
| `limits` | Bounded process, graph, capture and shutdown resources |
| `ci` | Required completeness, nonzero execution and instrumentation witness |
| `adapters.<language>` | Runner, toolchain/build recipe and language-specific fixture/observation capabilities |

Keep build recipes and fixture factories in external per-language plan inputs. A recipe is an executable plus an argument vector, working directory and declared environment delta; never a shell-interpolated command string. Relative paths resolve against the configuration's directory except source selectors, which resolve against the supplied application root. Unknown keys and unsupported requested capabilities fail validation.

Original application dependencies and toolchains are pinned according to their build recipes. Runner/fuzzer dependencies live in a workspace environment. An existing application test runner is an optional additional recipe and does not dictate the generated runner.

OTLP credentials remain external to resolved plans, command logs and replay bundles. Functional policy hashes cover non-secret settings and record credential references, not credential material. Optional float/path/ordering rules require field-scoped entries and are shown in reports; the example leaves them exact.

## Adapter protocol

Use bounded UTF-8 JSON Lines over dedicated worker channels. Every message includes `protocol_version = 1`, `request_id`, `run_id` and a method/event discriminator. Validate message size and schema before deserialisation; reject mismatched versions, duplicate case completion and undeclared outputs. Application stdout/stderr are captured on separate pipes and cannot be interpreted as control messages.

| Method | Request | Response |
| --- | --- | --- |
| `capabilities` | Language, toolchain, platform, otelc plan and requested observations | Supported build/call/control/state/effect capabilities and explicit reasons for gaps |
| `discover` | Immutable source snapshot, build recipe and selectors | Callable inventory with stable IDs, types, visibility, build inclusion and otelc identity mapping |
| `generate` | Inventory entry, fixture contracts and generation policy | Harness files, dependency plan, concrete cases, fixture requests and generation status |
| `prepare` | Workspace, lane, recipe and immutable corpus identity | Artefact identity, compilation delta, launch vector and instrumentation plan |
| `execute` | Artefact, concrete case/sequence and limits | Typed observations, per-channel completeness, termination and actual instrumentation evidence |
| `cleanup` | Owned worker resources | Completion or explicitly retained-resource failure |

The Rust core materialises and schedules cases. A framework generator supplies concrete candidate values to the core through an adapter; both variants consume each candidate. No language worker decides the final cross-lane verdict independently.

### Inventory entry

Each entry records original language/path/source range, qualified name and signature, overload/instantiation identity, build variant, body/source digest, visibility and access route. Its stable ID derives from those declared fields, not a generated-file offset. Record relationships between definitions, concrete instances and scenario-covered internal functions.

Separate fields capture `generation_status`, `execution_status`, `observation_status` and `instrumentation_status`. Gap records include a reason code, affected scope and a concrete resolution such as "provide a factory for DatabaseHandle". Source parse failures are inventory gaps, not permission to omit that file.

### Observation record

A record includes `protocol_version`, `case_id`, `function_id`, `lane`, `artefact_class`, typed initial/final graph snapshots, outcome, declared effect events and capture metadata. See [the observation contract](observations.md) and [illustrative JSON](../examples/observations/baseline.json).

Graph snapshots contain named roots and typed nodes. Cross-lane node IDs are local; the comparator matches graph structure and aliases. A channel's omission is not an empty value. Its completeness, capture mode and reasons for absence must be explicit. Instrumentation witness and OTLP receipt records belong to separate telemetry evidence linked by run/case scope.

### Comparison record

The comparator checks equal case/corpus/fixture contracts, stable initial state and compatible artefact classes before comparing. A record contains the verdict, compared dimensions, required/completed lanes, precise differences, gap reasons, explicit normalisation rules and pointers to raw observations. Missing required evidence cannot derive `equivalent_observed`.

Differences include typed values and graph paths. The comparator must handle alias/cycle changes, oversized integers, float bit patterns and opaque/truncated data safely. Comparison and capture limits are part of the report's scope.

## Proposed exit codes

| Code | Meaning |
| --- | --- |
| `0` | Required comparisons completed with observed equivalence and completeness policy satisfied |
| `1` | At least one reproducible application difference |
| `2` | Invalid configuration, plan, input or requested capability |
| `3` | Incomplete/inconclusive/blocked comparison under the selected gate |
| `4` | Tool, build, harness or protocol error |
| `130` | Interrupted run with best-effort retained evidence |

Mixed-result precedence is tool error, invalid plan, difference, incompleteness, then success. Reports retain every outcome regardless of exit precedence. Inventory/plan success is separate from execution success, and zero executed cases cannot produce a successful comparison.
