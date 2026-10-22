# Shrink and retain a scalar counterexample

`shrink` reduces one generated case while preserving its qualified failure signature. It reruns the original case, evaluates deterministic smaller candidates through the ordinary paired executor, and reconfirms the final input before retaining a sealed `unittest` workspace. Every trial keeps its observations, compiler/loader evidence, plan and comparison. The application and original generated corpus remain unchanged; replay adds a retained run under the original workspace.

The result remains **equivalence over these tests and observations**. A reduced counterexample demonstrates a difference within the declared experiment. It does not establish the application's business correctness or a globally smallest failing input.

## Declare the valid input domain

Add explicit independent parameter domains to the matching fixture before creating a new plan:

```toml
schema_version = 1
languages = ["python"]

[[fixtures]]
function = "api.calculate"
cases = [[100]]
domains = [{kind = "integer", minimum = 0, maximum = 100}]
```

The domain array follows parameter order. Each original concrete case and its actual target representation must satisfy these constraints. Domains are optional for ordinary generation; shrinking refuses a case without them. Type and domain checks precede every candidate execution. The existing expected baseline return/error contract remains mandatory.

| Kind | Required fields | Constraints and candidate rules |
| --- | --- | --- |
| `integer` | `minimum`, `maximum` | Ordered integer endpoints, at most 4096 bits. Values must be integral, including integral Node `Number` representations; the language's scalar type limits still apply. Try the value closest to zero, then progressively smaller binary deltas and a unit step. |
| `float` | `minimum`, `maximum` | Ordered finite numeric endpoints. Try the domain value closest to zero, binary deltas and a neighbour in the actual 32/64-bit representation. Positive zero is simpler than negative zero. |
| `boolean` | No additional fields | Try `false` before `true`. |
| `string` | `minimum_length`, `maximum_length`, `alphabet` | Lengths count Unicode scalar characters, from 0 to 4096; they do not count UTF-8 bytes or UTF-16 code units. Use an ordered alphabet of 1 to 256 distinct Unicode scalars. Try a minimum-length string, chunk deletion and character simplification. |

All fields are explicit; unknown fields and unsupported domain kinds are rejected. Integer/boolean/string parameter types remain strict. The `float` domain accepts finite numeric requests; the language adapter controls their actual representation. Bounds apply after coercion too: a decimal endpoint may exclude its rounded float32 representation. Supported strings follow the adapter's existing codec. A domain cannot enable a blocked argument type, receiver or build context.

These domains constrain each parameter independently. Optional [numeric argument preconditions](numeric-preconditions.md) retain explicit ordering/equality rules between finite numeric arguments while shrinking. Application predicates, arithmetic expressions, factories, objects, buffers and action sequences require further contracts. Do not declare an interval or alphabet as valid when additional conditions are necessary. Baseline failures and incomplete fixtures remain visible trials.

## Run the shrinker

Generate the configured workspace, then use the case ID from `tests/corpus.json`:

```sh
"$OTELEQ_CLI" shrink --workspace "$OTELEQ_WORKSPACE" \
  --case case-id-from-corpus \
  --report-dir /absolute/path/to/new-shrink-report \
  --trials 64
```

The report directory must be new and outside the application, provider and original workspace. `--trials` bounds candidate experiments from 1 to 1024, default 64. The original confirmation and final confirmation are additional experiments. Every experiment keeps the configured repeats, independent processes, launch/output limits, source/tool identities, initial-state checks and decoded instrumentation witness. Trials can involve compilation and produce substantial retained evidence; the trial budget does not bound total wall time or disk usage.

The original must reproduce a stable, fully qualified difference. A matching, blocked, unstable, incomplete or failed original cannot seed shrinking. Acceptance preserves the observed byte-channel names, typed difference paths/reasons/representation, outcome kind and qualified error class. Changed scalar content is permitted. A different failure, unexpected baseline error or missing witness cannot replace the original counterexample. Requested observation gaps also prevent acceptance. Spans retain the existing name-based qualification limits.

Search visits parameters and candidates in a deterministic order. After an accepted reduction it restarts from the reduced input. Already tested concrete inputs are not repeated during search; final confirmation always executes again. This avoids consuming compilation time on duplicate candidates while retaining a fresh final check.

## Read and replay the result

`shrink.json` records the original/reduced arguments, failure signature, every trial, source preservation and retained workspace. `parent-plan.json` and `original/` retain the original experiment; each `trial-NNNN/` keeps its exact trial plan and full ordinary report. `confirmation/report.json` is a normal generation report and can be rendered as HTML/JUnit. The top-level shrink summary is a separate schema and is not a renderer input.

The search status is one of:

- `candidate_rule_minimal`: the deterministic candidate rules found no further qualified reduction. This is local to those rules and the tested failure signature.
- `budget_limited`: the candidate budget ended before those rules were exhausted.
- `incomplete_candidates`: candidate execution or comparison contracts were blocked/incomplete, so minimality is unproven.

A retained counterexample exits `1`, including budget-limited results. Argument errors exit `2`; refusal, identity, build or final-confirmation failures exit `4` with partial evidence retained. A failed final confirmation does not produce a successful `shrink.json`.

The printed workspace has a frozen one-case corpus and explicit exclusions for the other inventoried callables. Use its case ID for `replay`, run its generated `tests/test_equivalence.py`, or use `export-tests` with a new destination and explicit `--apply`. Its normal comparison continues to fail while the instrumentation difference exists. Keep the whole shrink report if the search history is required; exporting the final suite retains that concrete replay experiment. `clean` accepts the owned final workspace after its normal preservation checks.

Qualification of actual producers and platforms is recorded separately. Unit tests with controlled comparison results prove the search/ownership contracts; they do not establish an otelc runtime result.

The [20 October diagnostic qualification](qualification/shrinking-2026-10-20.json) records 11 cases and 472 actual launches across all eight language IDs, with independent value checks, fresh confirmations, generated unittest execution, replay/export and altered-witness refusal controls. It names the exact consumer, provider and retained corpus. Its Python float case is intentionally budget-limited; no minimum is claimed for it.

Contributors can reproduce that maintained diagnostic workflow with a compatible qualified provider and the selected language tools:

```sh
make generation-shrink-otelc PYTHON="$OTELEQ_PYTHON" \
  OTELC_ROOT=/absolute/path/to/qualified/provider \
  REPORT_DIR=/absolute/path/to/new-qualification
```

The fixtures deliberately inspect instrumentation/runtime presence, including SDK symbols in the Rust diagnostic binary. They are controlled differences for testing the process. A provider or build which changes those conditions needs fresh fixture qualification.
