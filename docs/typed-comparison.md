# Typed observation comparison

`compare-observations` compares retained, versioned boundary graphs together with the workload comparator's exact byte channels, source identities, process completion and decoded telemetry witness. It does not execute application code. Generated scalar workers emit this format for all eight language IDs. They retain raw observations separately and compare semantic graphs with exact application stdout/stderr.

```sh
./target/debug/quux-oteleq compare-observations examples/typed-observations.json > /tmp/typed-comparison.json
# Exit 1: the example deliberately changes receiver.calls from 4 to 5.
```

The example is hand-authored acceptance data. Its placeholder hashes and witness are labelled illustrative. It is not evidence from a target execution. A valid bundle proves consistency of the supplied evidence, not its authenticity or the correctness of an unqualified capture codec. Actual producers must retain raw captures and bind the function, fixture, build and telemetry witness to each invocation.

## Bundle and fixture contract

The version-1 bundle has `typed_schema_version`, the existing workload `scope`, and one or more `cases`. Each case declares a `contract`, corpus hash, expected function/span counts, and independent `baseline` and `instrumented_on` attempts. An attempt has `execution` (the existing workload attempt) and `observation`.

The contract fixes `observation_schema_version: 1`, case/function identities, fixture hash, exact `required_roots` and `expected_baseline`. A returning baseline is the default explicit expectation, `{ "kind": "return" }`. An intentional error requires `{ "kind": "error", "category": "exception", "type": "qualified.Error" }`, or category `panic`. Matching unexpected baseline errors are blocked. An instrumented exception introduced with a valid returning baseline is a difference.

Every observation echoes those identities and carries fixture status, phase-specific capture gaps, a `before` graph, an `outcome`, and an `after` graph. A ready fixture has status `ready`; a failed factory records status `invalid` with a reason and outcome `not_run` with a reason. Invalid construction cannot pass. A missing requested root or opaque value is incomplete evidence. Unequal fully captured initial fixtures are blocked before comparing function outcomes.

Return/error outcome graphs contain all required state roots plus `result` or `error`; this retains aliases between the output and captured state. `result` and `error` are reserved contract root names. Before/after graphs contain exactly the required roots. Optional scope exclusions stay visible in `scope.gaps`; they cannot replace missing required roots. Snapshot IDs are local: identity across separate capture boundaries needs a separately qualified producer contract.

## Graph representation

A graph has `roots`, a map of root names to typed values, and `nodes`, a list of `{ "id", "type", "fields" }` records. Fields are maps to typed values. Root and field map keys must be unique. All nodes must be reachable; references cannot dangle. Cross-lane matching uses a bijection of reachable nodes, preserving aliases and cycles independently of local IDs or node storage order.

| Value kind | Payload |
| --- | --- |
| `null`, `undefined`, `unbound` | Separate absence tags |
| `unit` | Qualified `type` |
| `boolean` | Boolean `value`; optional qualified `type` (generated application values retain it; logical codec flags may omit it) |
| `integer` | Qualified `type`, canonical decimal string `value`, optional `bits` (8/16/32/64/128), `signed` |
| `float` | Qualified `type`, exact lowercase hexadecimal `bits` (16/32/64/128 bits) |
| `string` | Qualified `type`, `encoding`, lowercase hexadecimal `value` |
| `bytes` | Qualified `type`, lowercase hexadecimal `hex` |
| `reference` | `node_id` |
| `opaque` | Qualified `type`, nonblank `reason`; never counted as equal |

String encodings are `utf8`, `utf16_be`, `codepoints32_be` and `raw_bytes`. UTF-16 preserves unpaired surrogate code units; code points preserve Python surrogate values. Invalid UTF-8 is rejected for a declared UTF-8 string. Exact float bits preserve negative zero and NaN payloads. Integer strings avoid JSON numeric narrowing. Fixed-width values are range checked.

Container codecs must explicitly encode observable ordering, key types, sparse holes, descriptors and shared backing storage as typed fields/references. This comparator does not infer those language semantics from a type label. Native uninitialised padding and arbitrary serialisation callbacks are not qualified codecs. Enumeration, view/backing-store and project-specific codecs remain adapter work.

## Verdicts and limits

At least two independent attempts per lane are required; up to 100 are accepted. Every attempt must retain complete declared byte channels and a successful process exit. An instrumented attempt needs its expected decoded function/span witness, zero loss and pending counts, and the selected typed function in the witness expectation. These checks validate producer-supplied evidence; phase attribution and capture authenticity remain producer responsibilities.

Typed graphs are compared across lanes and within each lane. Repeat instability is inconclusive even if one pair matches. A consistently introduced instrumented exception remains a difference. Changed source or invalid fixtures take precedence, then incomplete/unstable evidence, then observed differences. Exit codes are 0 for observed equivalence, 1 for differences, 2 for invalid contracts or blocked fixtures/source changes, 3 for incomplete evidence, and 4 for file/JSON/output errors.

Differences use escaped JSON Pointer paths such as `/after/receiver/calls`; initial differences are retained separately under `/before`. A graph allows 512 nodes, depth 32, 8192 total fields/roots and 256 KiB of payload. At most 128 differences are retained per graph comparison. Opaque gap details are capped at 128 per lane, with a 256 KiB diagnostic payload budget per lane; differences have their own 256 KiB diagnostic payload budget. A limit marker records omitted diagnostics, which cannot produce an equivalence result. Iterative gap traversal retains one path per active graph level rather than copying long paths for every queued child. These are payload budgets, not limits on JSON escaping overhead. Input files are capped at 16 MiB. Unknown schema fields, duplicate map keys, invalid values and malformed references are rejected.

The protocol accepts all eight language IDs. That is shared comparator coverage, not evidence that each adapter has emitted or qualified every graph kind. Retained unittest/replay/export consume the typed comparator. Richer receivers/factories, additional language codecs, project build context and shipping qualification remain on the [completion checklist](completion.md).
