# Native lifetime provider integration

<!-- markdownlint-disable MD013 -->

Status: independent negotiation and SDK source-binding components. Generated lifetime execution is not available through this work yet. The [qualified prepared project profile](native-prepared-provider.md) remains the function-only build3 route. Its 100-application result does not qualify object/resource lifetimes.

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

## Remaining integration and acceptance

1. Freeze caller-selected per-unit contexts and independently observed semantic type/construction/allocation sites before SDK compilation. Bind private VFS/neutral-driver assets without importing SDK renderers or trusting producer-selected paths.
2. Reconstruct complete build4/build5 commands, products and compiler channels. For C resources, retain matched symbol checks for every application and neutral-driver object in both lanes, and bind the complete emitted-site resolution denominator.
3. Independently reconstruct the selected inventory from actual frontend evidence, preserving unsupported cases and compiler input/search probes. Type names and aggregate counts alone do not establish construction or resource pairing.
4. Extend owned preparation, final health and direct OTLP receipt. Keep complete-constructor return, destructor entry, C free entry and garbage collection as distinct observations. Censored shutdown and lost/capacity-refused observations must remain visible.
5. Connect real nontrivial/allocated fixtures to generated and retained/replayed/reduced/promoted suites. Qualify all metric startup states and same-process live controls separately, including same-output state differences and altered-evidence refusals.
6. Complete source preservation, independent review, measured coverage, final-head CI and published exact-revision execution before admitting either profile. Shipping artefacts, performance/resource budgets and broader platforms retain separate acceptance evidence.

Run `make native-provider-check PYTHON=/absolute/path/to/python` for the negotiation, source-binding and existing function-provider regressions. These tests use literal records and fake tools; they do not replace genuine SDK product binding or actual application/telemetry qualification. The [completion checklist](completion.md) remains open for the unimplemented requirements above.
