# Go receiver fixtures

Declare an existing same-package factory for an ordinary method on a named source struct. Each attempt constructs independently and captures the receiver, scalar arguments, package globals and result or primitive panic. Tests, the access bridge and an observer package live in the external private copy. The application repository and its module files stay unchanged.

```go
package counter

type Counter struct { value int64; self *Counter }
var total int64
func New(start int64) *Counter {
    value := &Counter{value: start}
    value.self = value
    return value
}
func (value *Counter) Add(amount int64) *Counter {
    value.value += amount
    total += amount
    return value
}
```

```toml
schema_version = 1
languages = ["go"]

[adapters.go]
module_roots = ["."]

[functions]
include = ["*.Counter.Add"]

[[fixtures]]
function = "*.Counter.Add"
cases = [[3]]
receiver = { factory = "New", arguments = [10] }
domains = [{ kind = "integer", minimum = 0, maximum = 3 }]
```

Use the normal `plan --config`, `generate`, `run`, `replay`, `export-tests` and `shrink` commands. The factory takes concrete scalar inputs and must return exactly `*Counter`; it can be private or declared in an active sibling source file. The selected method can have a pointer or value receiver. Pointer receivers can be nil when the existing factory returns nil. A nil receiver cannot call a value-receiver method. Factory inputs remain fixed during scalar method-argument shrinking.

## Observation contract

Real `go/types` discovery freezes nominal type identities, widths, array lengths, ordered source fields, embedding, field packages and tags. Reflection checks those declarations before constructing the fixture. The observer reads supported private storage directly, without calling application getters, formatting, JSON methods, equality or hashing. Its separate private package prevents application declarations from replacing observer builtins.

For executable packages, observed nominal types use Go's runtime `main.Type` identity. Discovery binds that mapping through the checked source package owner; the full module import path, source files and callable identity remain recorded separately.

Supported storage is booleans, integers, strings, floats, pointers, bounded arrays and named same-package source structs. Graphs retain pointer cycles, returned-receiver aliases and interior aliases to fields, array elements and package variables. Globals are observed through their addressable slots so pointer rebindings remain visible. Struct fields and array elements retain slot references; value receivers and composite returns preserve Go value-copy semantics. The observer never serialises its internal addresses. Identity is local to each boundary; allocation replacements that preserve the same graph can remain unobserved.

Private observer schema 2 keeps shared location references separately from typed pointer views. Converting a pointer between nominal types therefore preserves its storage alias; rebinding that pointer to equal-valued independent storage remains observable. Location nodes contain no raw address or application-formatted value.

Location references describe equal starting addresses. Arbitrarily overlapping regions created through unsafe address arithmetic need a separate observation profile.

Strings retain arbitrary bytes, including invalid UTF-8. Integer widths/signs and float64 bits remain exact. Float32 finite values, infinities and signed zero are supported; float32 NaNs refuse capture because this reflection path can quiet signalling payloads. No unsafe memory reads are used. Primitive panic payloads retain their actual type and value without `Error` or `String`; complex payloads and `panic(nil)` need another codec. Construction failures are incomplete fixture evidence, never matching target panics.

Required roots are `receiver`, `argument:N` for each scalar argument and `global:NAME` for every active declared package variable. All three boundaries contain them; outcome graphs additionally contain `result` or `error`. Unknown/missing fields, roots or types, unreachable nodes and unsupported storage refuse capture. Bounds are 512 types/nodes, 256 fields per struct, 32 reference levels, 4,096 array elements, 8,192 graph fields, 64 KiB per string and 256 KiB encoded per graph. String bytes are also budgeted before hex/JSON allocation.

## Scope and validation

This profile requires explicit [Go module/package context](go-package-context.md) and the [retained build/run provider](go-build-bundles.md). Maps, slices, interfaces, channels, functions, unsafe pointers, foreign/anonymous structs, blank fields and generic storage remain visible blockers. Broader mutable arguments, constructor/action targets, goroutine schedules, cgo, workspaces and general build recipes remain open. The private `oteleq_generated_observer` path is reserved; a collision refuses discovery.

`make go-observer-check` compiles the actual observer, runs its regression probes and `go vet`, and enforces 80% statement coverage. `make generation-check` additionally enforces independent 80% floors for the Python binding, graph validator and coverage gate. CI selects Go 1.27.2. Unit/plain-worker results are separate from actual otelc qualification. The [exact-revision corpus](qualification/go-receivers-2026-10-20.json) completes nine cases and 168 actual launches: six matches, three same-return state/alias differences, all generated/exported routes, scalar shrinking/replay and thirteen refusal controls. No shipping artefact is qualified by this diagnostic helper.

The result is **equivalence over these tests and observations**. The existing name-bound instrumentation witness remains unchanged; the [invocation-scoped witness](action-witness.md) is still a proposal.
