# Keep numeric arguments in a declared relationship

A fixture can declare numeric `preconditions` alongside concrete `cases` or independent scalar `domains`. These are reviewed input rules supplied by the user. Planning does not infer them from application branches or execute application predicates.

```toml
schema_version = 1
[generation]
cases_per_function = 3

[[fixtures]]
language = "go"
function = "*distance*"
domains = [
  {kind = "integer", minimum = 7, maximum = 9},
  {kind = "integer", minimum = 7, maximum = 9}
]
preconditions = [{left = 0, operator = "<", right = 1}]
```

For a supported two-integer function this freezes `[7, 9]`, `[7, 8]` and `[8, 9]`. The same requests and actual target values are used by both execution lanes, repeats, generated suites, replay and export.

## Accepted rules

`left` and `right` are zero-based argument indices. Operators are `<`, `<=`, `==`, `!=`, `>=` and `>`. Every listed rule must hold. The policy accepts at most 32 distinct rules and indices from 0 through 1023; a rule must also fit the selected callable's actual parameter count.

Referenced values must be finite primitive numbers. Booleans, strings, objects and comparison callbacks are refused. Integer comparison does not first narrow values to floating point. Rules are checked on both the requested inputs and their actual target representations. For example, two distinct requested Java float values which round to the same float32 cannot satisfy a declared strict ordering.

These are relations over frozen numeric values. They do not reproduce every language's implicit casts or establish that the application accepts an input.

Rules apply to selected method arguments. Receiver construction inputs remain fixed and have their existing separate contract. For supported ordered receiver sequences, every fixed call and every generated call must satisfy the method's rules, before and after target conversion.

## Generation and limits

Domain generation retains its deterministic edges, seeded parameter pools and existing payload limits. It filters bounded combinations against the rules. The requested case count is an upper bound; exhausting a finite sampled pool can yield fewer valid cases. Producing no valid cases blocks the callable.

The search examines at most 65,536 candidate combinations per function, including repeated diagonal candidates. Reaching that limit before completing the requested corpus blocks the function, including when some valid inputs were found. A search refusal does not prove that the declared mathematical domain has no solution. Use reviewed explicit cases for valid combinations which are difficult to reach with bounded independent sampling.

Explicit case lists retain their values and order. Every case must satisfy the rules; the tool does not discard invalid declared cases to create a passing subset. Rules require either concrete cases or declared domains. Unsupported callable/build contexts remain blockers.

## Reduction and retention

Scalar shrinking filters each candidate through the original domains and numeric rules. Derived workspaces retain those rules in both the frozen policy and callable inventory. Fixed sequence calls remain unchanged. The original qualified difference, trial observations and final confirmation remain separate evidence.

These rules do not add arbitrary predicates, arithmetic expressions, string-length rules, dependent factories, complex arguments or joint object/action-sequence shrinking. A locally minimal result still refers to the documented scalar candidate rules. Numeric preconditions do not establish application correctness or exhaustive branch coverage.

## Qualification status

The maintained actual-provider workflow is:

```sh
make generation-preconditions-otelc \
  PYTHON=/absolute/path/to/otelc/.venv/bin/python \
  OTELC_ROOT=/absolute/path/to/qualified/provider \
  REPORT_DIR=/absolute/path/to/new-precondition-evidence
```

Its fixed corpus declares 20 selected functions and 54 cases: integer and floating argument pairs in all eight languages, a deliberate Python instrumentation-sensitive probe and Java/JavaScript/TypeScript receiver sequences with fixed and generated float calls. Guarded integer encodings and exact float-pair classifiers bind both supplied arguments independently of lane equality. The workflow checks all four retained routes, frozen replay, relation-preserving reduction and prelaunch refusals.

Resume is limited to initial routes before later controls start. Completed route receipts are rechecked; an incomplete generated suite or preflight is refused. Confirm the old process is terminal before recovery. The workflow must not silently repeat partial application execution.

Component regressions cover the closed operators, all eight scalar profiles, target rounding, malformed rules, search limits, fixed and generated sequence calls, planning without application execution and retained reduction contracts. The precondition module has 100% line coverage in that focused run. Actual-provider qualification of this new capability remains pending. Results remain **equivalence over these tests and observations**.
