# Native project context

## Status

An opt-in scalar project profile now consumes explicit C/C++ compilation-database targets through `plan`, `generate`, `run`, `replay`, `export-tests`, `shrink` and `clean`. It preserves actual per-unit flags and working directories, project-header callables and target-wide scalar state. The [exact-revision corpus](qualification/native-projects-2026-10-21.json) passes 64 real application launches across generated/detached suites, fixed replay and scalar reduction, including a same-return global-state difference and four refusal controls.

This work contributes to the [completion checklist](completion.md). It does not qualify arbitrary CMake, Meson or other native projects, and it is not shipping-artefact evidence.

## Usage

Use an otelc build with the validated native object transformation interface (`object rename-main --help` must succeed), its matched compiler and the matching Clang development headers/libraries, `llvm-config`, `clang-scan-deps` and `llvm-objcopy`. The tested provider is the frozen otelc `58abcf5` candidate on macOS ARM64 with LLVM 22. This is compatibility evidence for that provider, not a claim about the SDK's replacement implementation, current main or a released product. Interface availability alone does not qualify another provider or platform.

Create a policy outside the application repository:

```toml
languages = ["c"]

[functions]
include = ["selected"]

[adapters.c]
compilation_database = "build/compile_commands.json"

[[adapters.c.targets]]
name = "application"
units = [{ source = "src/one.c" }, { source = "src/two.c" }]
link_flags = []
```

For C++, use `languages = ["cpp"]`, `[adapters.cpp]` and `[[adapters.cpp.targets]]`, with C++ unit paths and compiler-resolved function identities such as `selected(int)`. Headers are interpreted in each real translation unit's language, including C++ `.h` headers. `.C` source units are recognised. A unit selector can additionally specify `output = "build/one.o"` when the database contains multiple variants of the same source.

Run the normal [plan/generate/run commands](automatic-generation.md#build-and-run), passing this policy with `plan --config /path/to/equivalence.toml`. Keep the workspace and report directories outside the application and SDK repositories. The source database and all consumed generated headers/resources must already exist. The database declares compilation commands; the policy must supply ordered target membership and supported link flags.

Without a compilation-database setting, the existing standalone native profiles remain unchanged. Project-mode receivers and richer storage are separate unsupported capabilities; selecting them produces visible blockers.

## Inputs and inventory

An explicit target recipe identifies ordered translation units and their compilation-database output variants. The database alone does not identify the linker recipe. The parser preserves the supported ordered defines, include paths, language mode and optimisation flags, and removes output/dependency bookkeeping. It refuses ambiguous variants, different compilers, response files, unsupported flags and paths outside the project. Long include-related options require separate path arguments; only `-I` additionally accepts a joined path, avoiding confusion with options such as `-include-pch`.

A helper built from maintained source against the selected Clang development headers and shared libraries reads project declarations without executing application initialisers. It retains project-header byte locations and compiler-canonical scalar types, including project declarations nested inside a namespace opened by an external header. Foreign declaration trees without project-owned descendants are filtered to bound ordinary standard-library metadata. Unsupported or oversized metadata remains a failure.

Preprocessor callbacks record ordinary inputs and positive/negative header existence probes. Supported Clang versions additionally record embedded-resource probes and inputs. Existence-only files remain inputs even when their contents are never included. The raw metadata is retained alongside file content hashes, logical-to-physical path bindings, compiler/helper identities and helper build dependencies.

Verification checks original commands, retained metadata, tools and input bytes, then repeats preprocessing. A newly appearing header, a changed search result or altered resource cannot silently reuse the frozen context. The public snapshot refuses source/dependency symlinks rather than flattening them. Compiler-required files under normally excluded build directories are explicitly retained, including compilation databases and generated headers. Verification records remain outside application source.

The regression suite exercises these checks with the actual selected compiler. It also checks project-header models, imported scalar aliases, standard-library inclusion, helper relocation/tampering and source preservation. C++ conversion operators remain visible callable gaps until an appropriate invocation fixture exists.

## Private target workers

The internal target inventory keeps each translation-unit variant and its header callables. Clang's declaration linkage identifies external project storage as one linked root and keeps internal storage distinct per unit, including C++ namespace constants without an explicit `static`. Out-of-line constructor bodies retain their physical source bindings. Private, thread-local, template and persistent local storage remain visible gaps rather than omitted roots. Direct references to storage declared outside the project also require an explicit observation fixture.

Private scalar workers append header-free C ABI accessors through a per-unit Clang virtual filesystem overlay. The immutable private source files retain their original bytes and logical filenames. Each application unit compiles with its retained flags and working directory; a separate neutral driver records the complete ordered scalar roots before and after the call, its return value or supported C++ exception. Exact compiler type checks guard root reads and C++ overload selection. An inline compiler copy intrinsic avoids calling an application-supplied `memcpy`.

Object symbol rewriting renames the original application `main` after compilation, preserving the compiler's special implicit-return semantics. The instrumented lane delegates this to the SDK's validated transformation, retaining its object markers and provenance. Marker sidecars are never copied or fabricated. These are recorded diagnostic helper deltas. The baseline compiler/linker regressions cover sibling-unit mutations, internal storage, macros, logical source names, constant and boolean scalars, void returns and C++ exceptions.

Fresh private roots can recheck their complete dependency and positive/negative preprocessor search bindings without rewriting discovery metadata or earlier attempt evidence. Only application paths move; external SDK/system inputs retain their separate identities. Detached-copy regressions include a removed original source root, newly appearing headers and altered inputs or metadata.

Every build retains commands, working directories, original/transformed objects, SDK markers, helper bytes and executable hashes. Neutral-driver input/header identities are recorded separately from application inputs. The generated suite keeps one immutable application snapshot, with per-case helper previews; it does not duplicate the whole source tree for every preview. Real attempts always materialise fresh helpers and application roots. Export and reduction copy the sealed native context, and cleanup refuses edited or unowned context files.

## Reproduce the qualification

Run with the recorded provider or a separately qualified compatible build, matching compiler tools and the provider's Python environment:

```sh
make generation-native-project-otelc PYTHON=/path/to/provider/.venv/bin/python \
  OTELC_ROOT=/absolute/path/to/provider REPORT_DIR=/tmp/new-native-project-qualification
```

The maintained qualifier uses two-unit C `-O0` and C++ `-O2` matches plus a C `-O2` same-return global mutation. All cases run through the public CLI, generated standard-library `unittest`, fixed replay and detached exported tests after removing the original fixture source. The mutation also reduces argument `5` to `0` and reruns the reduced suite. All 64 actual launches have independently expected complete typed/raw before/after scalar state, results, output and telemetry health. Four copied original-shrink records are retained separately from launch counts. Changed generated inputs, newly appearing existence-only headers, altered context and cleanup of edited context are refused before application execution.

Raw attempts and frozen products remain private; the published record binds their hashes and scope. Plain Linux/Clang 18 regressions are separate from this actual-provider macOS ARM64/LLVM 22 corpus. Separate-process comparisons do not qualify live collection/emission toggles.

## Limits and remaining work

- Targets use one declared native language and a closed supported flag/link recipe. General build-system execution, mixed-language linking, response files, modules/PCH, sanitised/LTO builds and cross-compilation need separate recipes and qualification.
- Scalar free functions and target-wide supported globals are the initial scope. Project-mode C++ receivers, mutable arguments, private/opaque storage, persistent locals, thread-local and template storage remain blockers. Selected files outside declared target contexts are explicit inventory gaps.
- Source filters select callables; they do not remove required sibling-unit state. Third-party/library state outside the declared observations, full sysroot contents, loaded OS libraries, concurrency and arbitrary resource effects are not fully observed.
- Private build paths, access helpers, neutral drivers and renamed entrypoints produce diagnostic artefacts. Path/address-sensitive behaviour and application interposition of runtime/library calls require reviewed fixtures; a same-return state difference remains a failed equivalence result.
- Extend actual-provider qualification to further types, fixtures, SDK revisions, operating systems and architectures before making broader claims. Plain Linux/Clang 18 compiler regressions are distinct from actual macOS/LLVM 22 SDK execution.

The result remains **equivalence over these tests and observations**.
