# Native project context

## Status

C/C++ project integration is under development. The compilation-database parser, matched Clang inventory helper and input-binding checks are implemented and regression tested. The public `plan`, generated build, replay and export commands do not yet consume this project context. Existing native scalar and C++ receiver profiles retain their documented standalone limits.

This work contributes to the [completion checklist](completion.md). It does not qualify arbitrary CMake, Meson or other native projects, and it is not shipping-artefact evidence.

## Implemented foundations

An explicit target recipe identifies ordered translation units and their compilation-database output variants. The database alone does not identify the linker recipe. The parser preserves the supported ordered defines, include paths, language mode and optimisation flags, and removes output/dependency bookkeeping. It refuses ambiguous variants, different compilers, response files, unsupported flags and paths outside the project. Long include-related options require separate path arguments; only `-I` additionally accepts a joined path, avoiding confusion with options such as `-include-pch`.

A helper built from maintained source against the selected Clang development headers and shared libraries reads project declarations without executing application initialisers. It retains project-header byte locations and compiler-canonical scalar types. Filtering foreign top-level declarations keeps ordinary standard-library includes within the bounded metadata budget. Unsupported or oversized metadata remains a failure.

Preprocessor callbacks record ordinary inputs and positive/negative header existence probes. Supported Clang versions additionally record embedded-resource probes and inputs. Existence-only files remain inputs even when their contents are never included. The raw metadata is retained alongside file content hashes, logical-to-physical path bindings, compiler/helper identities and helper build dependencies.

Verification checks original commands, retained metadata, tools and input bytes, then repeats preprocessing. A newly appearing header, a changed search result, a retargeted header path or altered resource cannot silently reuse the frozen context. Verification records remain outside application source.

The regression suite exercises these checks with the actual selected compiler. It also checks project-header models, imported scalar aliases, standard-library inclusion, helper relocation/tampering and source preservation. C++ conversion operators remain visible callable gaps until an appropriate invocation fixture exists.

## Remaining integration

- Consume the validated target recipes through public policy and the frozen plan, including generated inputs under otherwise excluded build directories.
- Inventory every selected target variant and its header callables, with explicit accounting for unselected and unsupported callables.
- Compile and link both private lanes with the retained per-unit recipes; observe target-wide state, including internal-linkage storage, without changing original application/dependency sources.
- Preserve complete source, compiler, dependency and generated-helper bindings through retained suites, replay, export, shrinking and explicit cleanup.
- Qualify the complete workflow against actual otelc builds, with independent expected outputs/state, mutation controls, platform/toolchain identities and visible diagnostic deltas.

These requirements remain open until the public workflow and exact-revision execution evidence cover them. The result remains **equivalence over these tests and observations**.
