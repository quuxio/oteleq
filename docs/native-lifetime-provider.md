# Native lifetime provider integration

<!-- markdownlint-disable MD013 -->

Status: independent negotiation, SDK source binding and build/inventory reader components. Generated lifetime execution is not available through this work yet. The [qualified prepared project profile](native-prepared-provider.md) remains the function-only build3 route. Its 100-application result does not qualify object/resource lifetimes.

## Explicit contracts

The consumer checks each complete descriptor independently. A build4 descriptor must declare unit-recipe1, object-inventory2 and `otelc.object.v1`. Build5 must instead declare unit-recipe1, resource-inventory1, resource-resolution1 and `otelc.resource.v1`. Missing, added, combined, downgraded or incorrectly typed fields refuse. The default remains build2; build3 retains its existing separate contract.

SDK source catalogues are a separate caller choice, not inferred from the producer's source manifest:

| Caller source profile | Required LLVM ABI headers after the native runtime source catalogue |
| --- | --- |
| `function-v2` (default) | `function_abi.h` |
| `object-v1` | `function_abi.h`, `object_abi.h` |
| `resource-v1` | `function_abi.h`, `object_abi.h`, `resource_abi.h` |

The component `native_sdk.capture(..., source_profile=...)` binds the complete selected catalogue, matching built library, original build record, fixed CMake/Ninja recipe and LLVM tool queries. A newer SDK with all three headers needs the explicit `resource-v1` catalogue even when a future caller selects C++ object instrumentation. Catalogue names describe held SDK inputs, not application language support. Metadata cannot introduce another header path, select a different profile or repair an already accepted source identity. Missing/aliased headers, record substitutions and identical-byte replacements refuse.

These interfaces are for maintainers implementing the next provider; they do not enable a new user-facing configuration or accept a build4/build5 application for execution.

## Caller-bound builds and inventories

`native_lifetime_build.freeze/read` checks build4 C++ object and build5 C resource products separately from the function-only reader. The shared context freezer binds source, per-unit flags/directories, dependencies, header aliases, VFS assets and a neutral driver; the existing build3 reader continues to refuse enabled lifetime policies. The caller must provide complete independently obtained frontend facts and semantic-tool dependencies before SDK compilation. A producer response cannot select new input paths or replace that earlier intent.

The lifetime readers reconstruct both pass-object compilations and the linked LLVM plugin, complete application/driver/main-rename/link commands, semantic-helper/library recipes, per-unit compiler input channels and selected inventories. Source/type globs are evaluated independently. Raw retained semantics must match the caller's complete frontend catalogues, including duplicate rows; catalogue order is not an execution schedule. Repeated compiler includes bind each frozen canonical input once while the original dependency channel remains unchanged. Changed source, restored bytes with different file facts, missing or foreign outputs, altered selection and rehashed command records refuse.

C resource builds additionally bind matched `llvm-nm` checks for every application and neutral-driver object in both lanes. Custom allocator/free definitions refuse. Each selected source allocation/release retains its emitted-site resolution, including a valid zero-emission result; missing sites and forged callees/counts refuse.

On macOS the semantic-helper compiler also produces three fixed dSYM files. These are independently retained by the consumer even though the current SDK's artifact list omits them. The caller supplies the selected compiler's host target before building; the reader fixes the ARM64/x86-64 debug paths and matches the helper and DWARF Mach-O UUIDs. Unknown files/directories, substitutions or changed debug bytes cannot pass the complete consumer product check. Linux does not acquire a fabricated debug bundle.

The recorded development probe uses real LLVM 22.1.8 and genuine SDK `b425d1f` products on macOS ARM64. Independent caller frontend queries precede both SDK builds; the C++ object reader accepts 55 products and the C allocation reader accepts 60. All 624 consumer and 487 provider source files plus both original SDK products remain unchanged in that window. It starts no applications. Earlier refusals for the unhandled dSYM bundle and repeated compiler includes remain separate failed evidence. This is an uncommitted development snapshot, not exact-revision generated/runtime qualification.

Run `make native-lifetime-check PYTHON=/absolute/path/to/python` for the literal build/inventory, compiler-channel, symbol, output and substitution controls. Both new reader modules have individual 80% statement-coverage gates in this target and the full `make check`. The modules are embedded in the Rust distribution and included in generator identity. Genuine provider builds and later application/telemetry qualification remain separate checks.

## Remaining integration and acceptance

1. Freeze caller-selected per-unit contexts and independently observed semantic type/construction/allocation sites before SDK compilation. Bind private VFS/neutral-driver assets without importing SDK renderers or trusting producer-selected paths.
2. Connect the implemented build4/build5 readers to generated callers and the public planning/runtime path, retaining their complete commands, products, semantic expectations and compiler channels.
3. Supply independently obtained frontend/tool facts from the application pipeline, preserving unsupported cases and compiler input/search probes before and after builds/execution. Type names and aggregate counts alone do not establish construction or resource pairing.
4. Extend owned preparation, final health and direct OTLP receipt. Keep complete-constructor return, destructor entry, C free entry and garbage collection as distinct observations. Censored shutdown and lost/capacity-refused observations must remain visible.
5. Connect real nontrivial/allocated fixtures to generated and retained/replayed/reduced/promoted suites. Qualify all metric startup states and same-process live controls separately, including same-output state differences and altered-evidence refusals.
6. Complete source preservation, independent review, measured coverage, final-head CI and published exact-revision execution before admitting either profile. Shipping artefacts, performance/resource budgets and broader platforms retain separate acceptance evidence.

Run `make native-provider-check PYTHON=/absolute/path/to/python` for the negotiation, source-binding and existing function-provider regressions. These tests use literal records and fake tools; they do not replace genuine SDK product binding or actual application/telemetry qualification. The [completion checklist](completion.md) remains open for the unimplemented requirements above.
