# Language adapter plan

## Required language set

All eight current otelc targets are required and have implemented scalar adapters: `c`, `cpp`, `rust`, `python`, `java`, `javascript`, `typescript`, `go`. The published [language documentation](https://github.com/quuxio/otelc/blob/3d5b2d7c9167d9cc6fb1be876a05f83a9d6c6e5a/docs/languages.md) is the original design baseline. The [current discovery/execution matrix](automatic-generation.md#discovery-and-build-boundary) and [qualification record](quality.md#published-qualification) describe the implemented scope as of 9 October 2026.

The [implemented scalar generator](automatic-generation.md) supports bounded syntax inventory, private harnesses and actual paired otelc execution for all eight IDs. The rows below describe the broader proposed adapters, frameworks and build-aware capabilities beyond that slice. Toolchain/runtime versions and executable capabilities are pinned when each adapter is qualified against otelc. Objective-C, Swift, Fortran, Zig and .NET appear as later or exploratory otelc routes; they are outside its current eight-language set and are not silently advertised as supported here.

## Proposed framework and integration choices

The implemented suite uses Python's standard `unittest` for every language. The language-native runners and property frameworks below are proposed extensions; no current command installs or selects them.

| Language ID | Semantic discovery | Generated tests and input generation | otelc execution route |
| --- | --- | --- | --- |
| `c` | Clang AST using original compile commands and preprocessor definitions | cmocka runner; typed edge cases and bounded corpus; optional qualified libFuzzer discovery | Matched Clang/LLVM build wrapper |
| `cpp` | Clang AST with overload, template-instantiation and class-layout context | Catch2 runner; generators and explicit factories; optional qualified libFuzzer discovery | Matched Clang/LLVM build wrapper with exceptional exits |
| `rust` | Rust syntax plus Cargo/rustc build context and compiler-resolved callable types where available | libtest and proptest in an external harness or generated private tree | otelc's private generated-source/Cargo compiler wrapper |
| `python` | Python AST plus qualified import/runtime inspection in isolated discovery workers | pytest and Hypothesis in a workspace virtual environment | otelc's CPython monitoring launcher |
| `java` | Build/classpath-aware source model and compiled class descriptors/bytecode | JUnit Platform with Jupiter examples and jqwik properties in a private test module | otelc's Java bytecode agent |
| `javascript` | Node-compatible parser and module/export analysis | `node:test` and fast-check in a workspace package | otelc's Node in-memory loader transform |
| `typescript` | TypeScript compiler API, type checker and original source maps | `node:test` and fast-check with qualified TypeScript emission | otelc's TypeScript compiler/Node route |
| `go` | `go/packages`, AST and `go/types` for the actual build tags/modules | `testing`, built-in fuzzing and typed fixture constructors in a private package copy | otelc's compiler overlays |

The generated framework is independent of the target's current test framework. Reuse existing fixtures or run existing tests only when configured; no target dependency manifest or lockfile changes are required. Workspace dependencies are pinned and included in evidence. The runner is separate from the comparator: it emits application observations, while the Rust core decides paired equivalence.

Coverage-guided fuzzing may use extra diagnostic build flags. Its resulting inputs are replayed against ordinary comparison artefacts. Sanitised/fuzz builds are labelled diagnostic and do not certify shipping binaries. Native fuzz engines execute worker processes through a qualified bridge; they do not load both application variants into the core process.

## C

Discover functions and addressable globals under the real compilation database, including internal linkage. Preserve include paths, macros, standards, ABI and original application function bodies. Separate configured preprocessor/build variants remain separate inventory identities.

Public/linkable functions use external harnesses linked against application objects. Internal static functions may be reached through public scenarios or a generated helper in a private translation unit, with changed build context declared. Including an implementation file into a synthetic translation unit is not automatically equivalent to the original build.

Pointers require explicit length/ownership/lifetime contracts. Generate valid allocation-backed buffers and null cases only where the contract allows them. Native snapshots inspect declared initialised typed fields and byte buffers, never arbitrary memory pages or structure padding. Opaque pointers, callbacks, variadic functions and OS resources require fixtures. Longjmp, signal handlers and unsupported otelc backend combinations are explicit gaps.

## C++

Inventory overloads, constructors, destructors, methods, operators and instantiated templates with stable original identities. Provide typed factories for receivers, dependent services and callback objects; test copy/move operations as declared action sequences.

Private methods and fields require a legal qualified access route or generated diagnostic helper. Do not apply `#define private public`, alter class layout or pretend altered access is shipping evidence. Templates need concrete, build-relevant type instantiations; uninstantiated templates remain in inventory as a generation gap.

Observe typed fields, aliasing, exception type/payload, construction success/failure and declared destructor/resource events. Do not compare raw object memory, vtables or addresses. Coroutine/ABI/backend capabilities must be supported by both the harness and pinned otelc adapter; exception-enabled cases require otelc's qualified exception-aware backend.

## Rust

Use Cargo metadata and the actual feature/target set to resolve crates and callable instances. Syntax discovery alone cannot determine every generic, trait dispatch or macro expansion. Enumerate unresolved definitions and flag the missing semantic information.

Public callables use an external Cargo harness. Private callables can be tested through a generated child test module in a private tree because Rust permits that visibility. Record the `cfg(test)`/feature/profile changes and classify the result as harness evidence. Adding tests to original module files is not required.

Factories specify concrete generic types, ownership, borrowing and construction of nontrivial values. Observe only legally accessible typed values and declared static roots. No blanket `unsafe` memory dump or fabricated references. Move/drop order, panic/unwind and async completion/cancellation require independent fixtures; aborting panics cannot be caught as normal return observations. Foreign code, macro-generated constructs and otelc support gaps remain visible.

## Python

Discover module functions, methods, constructors and supported nested callables without importing the application in the main process. Runtime introspection/imports execute only in a workspace worker because imports can produce side effects. Combine type hints, signatures, constants and explicit factories; annotations are useful hints rather than proof of valid inputs.

Use separate interpreter processes for each lane/case so module globals, decorators, import caches and descriptors are reset. Observe receiver/input graphs and declared module globals without invoking getters or arbitrary custom serialisation. Slots, descriptors, extension objects and opaque resources require qualified observers.

Drive async functions, generators and cancellation through the same declared scheduler/iteration sequence on each lane. Compare yields, terminal values, exceptions and state at selected boundaries. Unsupported schedulers or C-extension internals remain gaps; matching an immediate coroutine object is not a completion test.

## Java

Resolve source/build inclusion, overloads and erased/instantiated generic types from the actual Maven/Gradle/classpath recipe. Create a workspace test module with pinned JUnit/jqwik dependencies and the same application artefacts. Preserve module configuration and class-loader behaviour where possible.

Each lane uses a fresh JVM initially. Private/module-encapsulated members require an explicit legal reflection/open-module or diagnostic helper plan; such flags are recorded and may disqualify exact production evidence. Factories construct valid receivers, interfaces and service dependencies.

Observe declared instance/static fields, object aliasing, exception type/message/payload and constructor effects. JVM object identity uses graph relationships rather than address/hash values. CompletionStage/Future and executor scenarios explicitly wait for declared completion; otelc's method-body timing does not by itself establish asynchronous completion instrumentation.

## JavaScript

Resolve ESM/CommonJS modules in their real package context. Include exported functions, reachable callbacks, methods and constructors; closures and unexported functions need a supported public scenario or diagnostic access helper. Do not change original modules to add exports.

Run each lane in a separate Node process. Preserve package scope, loaders, module initialisation and source locations. Workspace framework dependencies live separately from application dependencies.

Observe own data properties and supported built-in containers without calling getters, proxies or custom `toJSON` code. Preserve sparse arrays, undefined, symbols, bigint, Map/Set ordering and graph aliasing through typed codecs. Promise, generator, async-generator and cancellation scenarios declare their completion boundaries; unsupported otelc tracing constructs remain blocked for the requested trace lane.

## TypeScript

Share the JavaScript worker and observation backend but use TypeScript's type checker to plan inputs and preserve compiler options, project references, declaration resolution, runtime decorators and source maps. Type-only interfaces do not supply runtime factories automatically.

Record both original source identities and emitted module hashes. Generics require concrete runtime-relevant cases. Validate values after generation because structural type compatibility does not guarantee business preconditions. Hidden/private fields and unsupported loader/emission combinations remain declared observation/build gaps.

## Go

Resolve modules, build tags, generated sources and package types through official Go tooling. Work in a private package/module copy for generated same-package `_test.go` files and unexported access. Do not assume otelc's source overlays alone can insert tests into every build-system layout.

Set private build/module caches, preserve `go.mod`/`go.sum` in the original tree, and use independently launched test workers. Go's built-in fuzzing accepts a defined primitive set; decode that corpus through typed factories for richer values. Run fixtures and globals from a clean process for each sequence.

Observe declared package globals, struct fields, pointers/slices/maps with aliasing, errors and panic/recover behaviour. Channel/goroutine scenarios need bounded scheduling/termination fixtures. Stable map comparison differs from observable iteration order; never erase ordered output differences by sorting them. Requested cgo/workspace/backend cases require explicit otelc capability checks.

## Qualification contract shared by every adapter

An adapter must demonstrate unchanged source/manifests/locks; complete callable inventory for its qualified scope; stable paired corpus execution; independent initial state; declared observation coverage and limitations; return/error/mutation difference detection; a working instrumentation witness; correct unsupported-feature diagnostics; and runnable retained/promoted generated tests.

Private access, async boundaries and source/build variants are capabilities, not universal assumptions. Publish the exact tested compiler/runtime/platform matrix. All eight adapters must meet the shared core contract before the application advertises complete otelc language coverage.

## Primary references

Framework routes are design choices based on their documented capabilities. Pin compatible releases during implementation rather than assuming the newest versions always match otelc.

- [cmocka](https://cmocka.org/) and [Catch2](https://catch2-temp.readthedocs.io/en/latest/) provide native unit runners; [libFuzzer](https://llvm.org/docs/LibFuzzer.html) supplies a qualified corpus-discovery route.
- [Rust test organisation](https://doc.rust-lang.org/book/ch11-03-test-organization.html) explains public integration tests versus private child-module tests; [proptest](https://proptest-rs.github.io/proptest/intro.html) provides generated values and failure shrinking.
- [pytest](https://docs.pytest.org/en/stable/) and [Hypothesis](https://hypothesis.readthedocs.io/en/latest/) provide Python runner/property generation.
- [JUnit](https://junit.org/) and [jqwik](https://jqwik.net/docs/current/user-guide.html) provide Java runners and properties.
- [Node's test runner](https://nodejs.org/api/test.html) and [fast-check](https://fast-check.dev/docs/introduction/) provide JavaScript/TypeScript runners, generated values and shrinking.
- [Go fuzzing](https://go.dev/doc/security/fuzz/) documents primitive input types and state-reset requirements; [Go build flags](https://pkg.go.dev/cmd/go#hdr-Build_flags) describe build/overlay controls.

## Current workload comparator

The implemented [byte-channel comparator](workload-comparison.md) accepts all eight language IDs. [Fixed diagnostic captures](eight-language-capture.md) execute all eight ordinary function workloads, Python tasks, Python/Java worker context and optional native TypeScript emission. [Automatic scalar generation](automatic-generation.md) separately provides syntax inventories, diagnostic harnesses, supported state observers, replay and export for every language. The broader semantic/build-aware, receiver/factory and production requirements above remain outstanding.
