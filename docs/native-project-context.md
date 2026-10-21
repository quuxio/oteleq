# Native project context

## Status

C/C++ project integration is under development. The compilation-database parser, matched Clang inventory helper, target-wide storage inventory, private scalar workers and input-binding checks are implemented and regression tested. The public `plan`, generated build, replay and export commands do not yet consume this project context. Existing native scalar and C++ receiver profiles retain their documented standalone limits.

This work contributes to the [completion checklist](completion.md). It does not qualify arbitrary CMake, Meson or other native projects, and it is not shipping-artefact evidence.

## Implemented foundations

An explicit target recipe identifies ordered translation units and their compilation-database output variants. The database alone does not identify the linker recipe. The parser preserves the supported ordered defines, include paths, language mode and optimisation flags, and removes output/dependency bookkeeping. It refuses ambiguous variants, different compilers, response files, unsupported flags and paths outside the project. Long include-related options require separate path arguments; only `-I` additionally accepts a joined path, avoiding confusion with options such as `-include-pch`.

A helper built from maintained source against the selected Clang development headers and shared libraries reads project declarations without executing application initialisers. It retains project-header byte locations and compiler-canonical scalar types, including project declarations nested inside a namespace opened by an external header. Foreign declaration trees without project-owned descendants are filtered to bound ordinary standard-library metadata. Unsupported or oversized metadata remains a failure.

Preprocessor callbacks record ordinary inputs and positive/negative header existence probes. Supported Clang versions additionally record embedded-resource probes and inputs. Existence-only files remain inputs even when their contents are never included. The raw metadata is retained alongside file content hashes, logical-to-physical path bindings, compiler/helper identities and helper build dependencies.

Verification checks original commands, retained metadata, tools and input bytes, then repeats preprocessing. A newly appearing header, a changed search result, a retargeted header path or altered resource cannot silently reuse the frozen context. Verification records remain outside application source.

The regression suite exercises these checks with the actual selected compiler. It also checks project-header models, imported scalar aliases, standard-library inclusion, helper relocation/tampering and source preservation. C++ conversion operators remain visible callable gaps until an appropriate invocation fixture exists.

## Private target workers

The internal target inventory keeps each translation-unit variant and its header callables. Clang's declaration linkage identifies external project storage as one linked root and keeps internal storage distinct per unit, including C++ namespace constants without an explicit `static`. Out-of-line constructor bodies retain their physical source bindings. Private, thread-local, template and persistent local storage remain visible gaps rather than omitted roots. Direct references to storage declared outside the project also require an explicit observation fixture.

Private scalar workers append header-free C ABI accessors through a per-unit Clang virtual filesystem overlay. The immutable private source files retain their original bytes and logical filenames. Each application unit compiles with its retained flags and working directory; a separate neutral driver records the complete ordered scalar roots before and after the call, its return value or supported C++ exception. Exact compiler type checks guard root reads and C++ overload selection. An inline compiler copy intrinsic avoids calling an application-supplied `memcpy`.

Object symbol rewriting renames the original application `main` after compilation, preserving the compiler's special implicit-return semantics. This is a recorded diagnostic helper delta. The baseline compiler/linker regressions cover sibling-unit mutations, internal storage, macros, logical source names, constant and boolean scalars, void returns and C++ exceptions.

Fresh private roots can recheck their complete dependency and positive/negative preprocessor search bindings without rewriting discovery metadata or earlier attempt evidence. Only application paths move; external SDK/system inputs retain their separate identities. Detached-copy regressions include a removed original source root, newly appearing headers and altered inputs or metadata.

The first actual otelc probe accepts the VFS compile steps but refuses linking the rewritten objects because their original SDK markers do not bind the new object paths. A supported SDK transformation/provenance operation is required before this route can qualify instrumented execution. Copying or fabricating marker sidecars is not supported. These internal helpers are not yet a public project-build capability.

## Remaining integration

- Consume the validated target recipes through public policy and the frozen plan, including generated inputs under otherwise excluded build directories.
- Consume target/unit/header inventories through the public plan, with explicit accounting for unselected and unsupported callables.
- Bind the object transformation through the SDK's validated provenance contract, then compile and link both private lanes with target-wide state observation.
- Preserve complete source, compiler, dependency and generated-helper bindings through retained suites, replay, export, shrinking and explicit cleanup.
- Qualify the complete workflow against actual otelc builds, with independent expected outputs/state, mutation controls, platform/toolchain identities and visible diagnostic deltas.

These requirements remain open until the public workflow and exact-revision execution evidence cover them. The result remains **equivalence over these tests and observations**.
