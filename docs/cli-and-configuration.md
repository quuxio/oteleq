# CLI reference and proposed adapter protocol

## Status

Updated 9 October 2026. `quux-oteleq` implements the commands below. The scalar workflow uses embedded workers and a frozen JSON workspace contract. The later configuration and adapter sections describe proposed interfaces; the implemented commands do not consume `equivalence.toml` or the illustrative graph records.

## Implemented commands

| Command | Required arguments | Optional arguments | Result |
| --- | --- | --- | --- |
| `plan` | `--source PATH --otelc-root PATH` | `--workspace-parent PATH`, repeated `--language ID`, repeated `--exclude PATTERN`, `--cases N` | New private workspace path on stdout; snapshot, tool identities and syntax inventory in `plan.json` |
| `generate` | `--workspace PATH` | None | Frozen concrete corpus, diagnostic harness previews and `tests/test_equivalence.py` |
| `run` | `--workspace PATH --report-dir PATH` | None | All generated cases, complete inventory and JSON report in a new external directory |
| `replay` | `--workspace PATH --case ID` | None | One frozen case in a new `runs/replay-*` directory inside the workspace |
| `export-tests` | `--workspace PATH --destination PATH` | `--apply` | Copy plan by default; with `--apply`, a new runnable frozen source/suite bundle |
| `clean` | `--workspace PATH` | None | Removes an owned workspace after checking its snapshot/suite and top-level contents |
| `compare-workload` | `BUNDLE.json` positional path | None | Byte-channel comparison JSON on stdout |

The generation commands accept `--help`. `quux-oteleq --help` lists both workflows and their exit contracts. Use full option names; abbreviations are rejected. Paths accept both `--source PATH` and `--source=PATH` forms. `--cases` accepts 1 through 16 and defaults to 3 distinct scalar cases per function. Language IDs are `c`, `cpp`, `rust`, `python`, `java`, `javascript`, `typescript`, `go`; repeated language selectors form a subset, and exclusions match qualified function identities.

Set `OTELEQ_PYTHON` to otelc's qualified Python 3.12+ environment with the OTLP protobuf decoder. The selected language tools and built otelc adapters must already exist. `plan` performs syntax discovery using those tools, without executing target functions. It does not establish arbitrary build graphs or valid business preconditions. `generate` creates the suite once; a changed source, corpus, CLI or tool identity requires a new plan. Dependencies are not installed into the application.

Use the actual path printed by `plan` for subsequent commands. Workspace and temporary parents resolve outside both application and otelc repositories. `run` requires a new report directory outside those repositories and the workspace. Workspaces remain available after success or failure until explicit `clean`. Export refuses existing destinations and rebinds the suite to its copied immutable application snapshot; it retains the original source provenance. See [complete runnable usage](automatic-generation.md) and [workspace retention](test-generation.md).

Generation execution exits are `0` complete, `1` observed difference, `2` argument error, `3` incomplete/blocked and `4` tool/build/protocol/identity failure. A run with no completed cases or any selected blocker cannot return success. Mixed case results give precedence to `4`, `2`, `1`, then `3`; the report retains each result. `replay` qualifies only the named case. The generated `unittest` suite includes failing tests for all selected blockers. `compare-workload` has its own [exit-code contract](workload-comparison.md#build-and-compare).

## Proposed extensions

The broader design adds a `doctor` capability command, policy-driven build/fixture configuration, richer promotion planning, stateful inputs, HTML/JUnit reports and a versioned graph/worker protocol. `doctor`, `promote`, `--config`, `--keep-workspace`, `--dry-run` and replay `--bundle` are proposal names, not available CLI options. Current retention uses `export-tests` and explicit `clean`.

## Proposed configuration

The [example policy](../examples/equivalence.toml) illustrates all eight languages and a proposed strict evidence requirement. `/path/...` values are placeholders. This repository validates TOML syntax, not application-schema execution. Its settings, including 100 cases and stateful sequences, do not change the current scalar CLI defaults.

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

## Proposed adapter protocol

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
