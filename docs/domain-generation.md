# Generate cases from declared scalar domains

A fixture can omit its literal `cases` list when it declares one independent scalar domain per parameter. Planning generates and freezes concrete requests before either execution lane runs. Explicit case lists keep their existing values and order.

```toml
schema_version = 1
[generation]
seed = 7
cases_per_function = 3

[[fixtures]]
language = "go"
function = "*calculate*"
domains = [{kind = "integer", minimum = 7, maximum = 9}]
```

For a supported integer parameter this produces `[7]`, `[9]`, `[8]`: the endpoint nearest zero, the other endpoint and the midpoint. The application still needs to accept these values. A declared interval does not establish business preconditions or the correct result.

## Supported domains

| Kind | Generated inputs and limits |
| --- | --- |
| `integer` | Qualified integer parameters, Python unannotated parameters and supported Node numeric parameters. Declared bounds must fit the target's integer range; Node numeric bounds stay within exact safe integers. Ordinary floating parameters require a float domain. |
| `float` | Qualified floating parameters and supported Python/Node unannotated parameters. Bounds are finite. Float32 endpoints move inward to representable values inside the original interval; an empty representable interval is a visible blocker. Signed zeros remain distinct. |
| `boolean` | Qualified boolean parameters and supported Python/Node unannotated parameters. A finite pool contains at most `false` and `true`. |
| `string` | Existing Python, Java, JavaScript, TypeScript and Go string codecs. Lengths count Unicode scalar characters; the declared ordered alphabet contains distinct Unicode scalars. Existing limits are 4,096 characters and 256 alphabet symbols. C/C++/Rust string arguments remain unsupported. |

Use the [scalar-domain fields](counterexample-shrinking.md#declare-the-valid-input-domain) already used by shrinking. A zero-argument function can declare `domains = []` and receives one empty argument case. A domain/parameter count mismatch, unsupported type, out-of-range endpoint or failed post-conversion membership check blocks that callable. No unsupported selected callable becomes a successful skipped test.

## Sampling and budgets

Each parameter starts with deterministic edges. Larger budgets add local seeded samples and bounded deterministic fallback values. Parameter pools are combined along a diagonal, then filled from their lazy Cartesian product until the case budget or available combinations end. This is bounded exploration; it does not promise every combination or branch.

The requested budget is an upper bound. Finite boolean/string/integer domains and target representations can yield fewer distinct cases. Requested values are converted using the selected language's existing scalar rules, checked against the original domains and de-duplicated by concrete representation. The process preserves numeric and signed-zero distinctions.

Sample pools and materialised request lists each have a 1 MiB canonical JSON payload budget per function. Exceeding either budget blocks the function; the tool does not silently truncate a passing corpus. The existing 1,024-case limits and worker observation/time/output budgets also apply.

## Retention and shrinking

The resolved policy retains the declared domains without adding a user-supplied `cases` field. The plan inventory stores the generated concrete requests as `input_cases`. `tests/corpus.json` retains both requested and actual target arguments. Generation, repeats, replay and exported suites consume those frozen values rather than sampling independently in each lane.

An explicit `cases` list continues to override automatic sampling, even when `domains` is present. Its cases must satisfy the domains before and after conversion. Reordering or removing explicit cases is not part of automatic generation.

[Scalar shrinking](counterexample-shrinking.md) consumes the same declared domains. Derived replay suites retain explicit reduced inputs and the original experiment's provenance. Automatic generation does not infer relational preconditions, create object factories, enable unsupported argument codecs or add action-sequence shrinking. Supply reviewed concrete cases when parameters have additional relationships.

## Qualification status

Component regressions cover all eight language IDs, deterministic/frozen values, scalar kinds, finite pools, float32 boundaries, signed zeros, type/range refusals and input budgets. Actual-provider qualification of this new generation path is still pending. It remains **equivalence over these tests and observations**.
