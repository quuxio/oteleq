# C++ receiver fixtures

Declared C++ fixtures construct an existing source class independently in every attempt and call one exact instance method. The observer records private fields, namespace and class statics, scalar method inputs and the result at the declared boundaries. Returned references, pointer cycles and interior aliases retain their relationships without recording raw addresses.

This is a diagnostic access profile. Its private source copy gains friend declarations; generated access helpers and the driver are identical in both lanes. Original application/dependency files remain unchanged. A diagnostic match does not qualify a shipping artefact.

## Declare construction and a method

```cpp
namespace sample {
class Counter {
    int value_;
    inline static int total_ = 0;
public:
    explicit Counter(int start) : value_(start) {}
    int add(int amount) {
        value_ += amount;
        total_ += amount;
        return value_;
    }
};
}
```

```toml
schema_version = 1
languages = ["cpp"]

[functions]
include = ["sample::Counter::add(int)"]

[[fixtures]]
function = "sample::Counter::add(int)"
cases = [[3]]
receiver = { factory = "sample::Counter", arguments = [10] }
domains = [{ kind = "integer", minimum = 0, maximum = 3 }]
```

Use the normal `plan --config`, `generate`, `run`, `replay` and `export-tests` commands. The factory can be the source class, an existing ordinary free function or an existing same-class static function returning the exact source class by value. Private source fields, methods, constructors and same-class static factories use legal friend access. A constructor fixture currently requires one unique explicit constructor; source declarations and out-of-line definitions are joined by their actual compiler symbol. Factory inputs remain fixed while scalar method inputs are shrunk.

Constructor fixtures create the receiver at its final address inside the friend worker. An extra helper return can introduce ABI copies of small trivial classes and invalidate self pointers. Existing application factories retain their own return semantics and the declared live-storage precondition. Generated type names resolve to the global source declaration, including an application class named `Graph`.

The inventory and build share C++17, optimisation and threading flags. The selected LLVM compiler's sibling `llvm-cxxfilt` supplies the actual instrumentation identity. For example, a `short` alias resolves to `sample::Counter::add(short)`, and a const method retains its `const` qualifier. Mach-O linkage prefixes are removed before resolution so C-linkage names preserve the application's own underscores. Exact typed member pointers bind overloaded methods; inventory accounts for declarations and excluded functions separately.

## Storage and capture limits

The closed registry supports native booleans and integers up to 64 bits, IEEE float/double storage, named physical source classes/structs, fixed arrays, const storage, pointers and lvalue references. Every field has a typed slot. Separate location nodes preserve equal starting addresses across typed views, including an interior pointer and a reference returned to the receiver. Scalar bytes preserve signed zero and NaN payloads; structure padding is never compared. Graphs are rebuilt at each boundary and do not establish allocation identity across destruction or address reuse.

The observer uses a fixed arena without C++ dynamic allocation. It does not call overloaded address operators, getters, stream formatters or object serialisers. Exception capture is limited to exact supported standard exception classes and their standard `what()` payload; derived/custom exception accessors and other thrown values refuse capture. A thrown exception can still expose the method's preceding state mutation.

The registry is bounded to 512 types, 256 fields per source record and 4,096 elements per array dimension. Each boundary permits 512 nodes, depth 32, 8,192 fields and 256 KiB of encoded graph data. Exception messages are bounded to 64 KiB. Exceeding a bound is incomplete evidence.

Clang's complete AST JSON currently has a 64 MiB discovery budget. Large standard-library instantiations can exceed it and produce an inventory gap before fixtures are bound. A build-aware source inventory which avoids dumping all included declarations remains required for broader repository adoption.

Factories and targets must leave observed storage and pointer pointees live, correctly typed and initialised at every boundary. Explicit constructor field initialisers are checked, but that check does not prove arbitrary C++ memory validity, ownership, absence of races or future pointer lifetime. Arbitrary overlapping memory is outside this profile; location nodes describe equal starting addresses.

Inheritance, virtual storage, unions, bitfields, volatile/atomic storage, foreign/opaque objects, header-defined classes, template classes, mutable object arguments, unbounded buffers and arbitrary resource/concurrent sequences need further adapters. Function-local statics and macro-expanded storage are visible blockers because this profile cannot observe them through its source access helper. Macro-generated C/C++ callables remain in the inventory with a build-aware fixture gap. General compilation databases and dependency/build variants remain open.

## Validation

`make cpp-observer-check` compiles the maintained observer with the selected Clang compiler and enforces an independent 80% LLVM line coverage floor. Matching `llvm-cov` and `llvm-profdata` must be beside the real compiler. Coverage instrumentation is confined to regression probes and is absent from generated equivalence workers.

`make generation-cpp-receiver-otelc OTELC_ROOT=/absolute/path/to/otelc REPORT_DIR=/private/tmp/new-cpp-receiver-qualification` runs the maintained actual-provider corpus. It checks private state, aliases, exact float storage, standard exceptions, all generated/exported routes and scalar shrinking/replay. Its deliberate same-return instance/static/alias controls must be reported as differences.

The [exact-revision macOS ARM64 record](qualification/cpp-receivers-2026-10-20.json) covers 17 cases and 299 unique application launches: 14 matches, three deliberate differences, fixed construction through scalar shrinking/replay and eleven refusal controls. Separate binding and CRLF groups exercise a global application class named `Graph`, small self-referential construction and C-linkage names with application underscores. It records 303 attempt folders because four original shrink attempts are copied. The frozen driver exits successfully; retained verification checks every report, original/copy relationship, binary, source and complete value oracle without relaunching applications. Macro-expanded storage is refused before application launch. This qualifies the recorded diagnostic runtime/provider profile; other platforms and shipping builds remain open.

The claim remains **equivalence over these tests and observations**.
