# Native lifetime provider integration

<!-- markdownlint-disable MD013 -->

Status: independent negotiation, SDK source binding, build/inventory readers, owned preparation/final health and a separate [raw lifetime receipt](native-lifetime-receipt.md) component. Experimental [public lifetime profiles](native-lifetime-generation.md) connect these components to generated scalar callers and explicit fixture expectations. Their separate [100-launch lifetime qualification](qualification/native-lifetime-workflows-2026-10-25.json) covers three completed-lifetime fixtures and generated/retained/promoted routes; broader profiles remain open. The [qualified prepared project profile](native-prepared-provider.md) remains the function-only build3 route and retains its separate evidence.

## Explicit contracts

The consumer checks each complete descriptor independently. A build4 descriptor must declare unit-recipe1, object-inventory2 and `otelc.object.v1`. Build5 must instead declare unit-recipe1, resource-inventory1, resource-resolution1 and `otelc.resource.v1`. Missing, added, combined, downgraded or incorrectly typed fields refuse. The default remains build2; build3 retains its existing separate contract.

SDK source catalogues are a separate caller choice, not inferred from the producer's source manifest:

| Caller source profile | Required LLVM ABI headers after the native runtime source catalogue |
| --- | --- |
| `function-v2` (default) | `function_abi.h` |
| `object-v1` | `function_abi.h`, `object_abi.h` |
| `resource-v1` | `function_abi.h`, `object_abi.h`, `resource_abi.h` |

The component `native_sdk.capture(..., source_profile=...)` binds the complete selected catalogue, matching built library, original build record, fixed CMake/Ninja recipe and LLVM tool queries. A newer SDK with all three headers needs the explicit `resource-v1` catalogue even when a future caller selects C++ object instrumentation. Catalogue names describe held SDK inputs, not application language support. Metadata cannot introduce another header path, select a different profile or repair an already accepted source identity. Missing/aliased headers, record substitutions and identical-byte replacements refuse.

These interfaces support the experimental [public lifetime profiles](native-lifetime-generation.md). Accepted build4/build5 components enter the owned preparation/session path with independently declared test expectations. Component acceptance does not qualify the generated observation/telemetry workflow.

## Caller-bound builds and inventories

`native_lifetime_build.freeze/read` checks build4 C++ object and build5 C resource products separately from the function-only reader. The shared context freezer binds source, per-unit flags/directories, dependencies, header aliases, VFS assets and a neutral driver; the existing build3 reader continues to refuse enabled lifetime policies. The caller must provide complete independently obtained frontend facts and semantic-tool dependencies before SDK compilation. A producer response cannot select new input paths or replace that earlier intent.

The lifetime readers reconstruct both pass-object compilations and the linked LLVM plugin, complete application/driver/main-rename/link commands, semantic-helper/library recipes, per-unit compiler input channels and selected inventories. Source/type globs are evaluated independently. Raw retained semantics must match the caller's complete frontend catalogues, including duplicate rows; catalogue order is not an execution schedule. Repeated compiler includes bind each frozen canonical input once while the original dependency channel remains unchanged. Changed source, restored bytes with different file facts, missing or foreign outputs, altered selection and rehashed command records refuse.

C resource builds additionally bind matched `llvm-nm` checks for every application and neutral-driver object in both lanes. Custom allocator/free definitions refuse. Each selected source allocation/release retains its emitted-site resolution, including a valid zero-emission result; missing sites and forged callees/counts refuse.

On macOS the semantic-helper compiler also produces three fixed dSYM files. These are independently retained by the consumer even though the current SDK's artifact list omits them. The caller supplies the selected compiler's host target before building; the reader fixes the ARM64/x86-64 debug paths and matches the helper and DWARF Mach-O UUIDs. Unknown files/directories, substitutions or changed debug bytes cannot pass the complete consumer product check. Linux does not acquire a fabricated debug bundle.

The recorded development probe uses real LLVM 22.1.8 and genuine SDK `b425d1f` products on macOS ARM64. Independent caller frontend queries precede both SDK builds; the C++ object reader accepts 55 products and the C allocation reader accepts 60. All 624 consumer and 487 provider source files plus both original SDK products remain unchanged in that window. It starts no applications. Earlier refusals for the unhandled dSYM bundle and repeated compiler includes remain separate failed evidence. This is an uncommitted development snapshot, not exact-revision generated/runtime qualification.

Run `make native-lifetime-check PYTHON=/absolute/path/to/python` for the literal build/inventory, compiler-channel, symbol, output, preparation, final-health and substitution controls. The new readers and shared preparation/execution/health modules have individual 80% statement-coverage gates in this target. The full `make check` retains its component floors. The modules are embedded in the Rust distribution and included in generator identity. Genuine provider builds and later application/telemetry qualification remain separate checks.

## Owned preparation and final health

The existing owned supervisor/session accepts only the separately checked function, unit or lifetime `Build` types. Lifetime context stays explicit: runtime selection includes the compiled lifetime filters, and its complete lifetime policy, including the live-instance capacity, must match caller intent. A runtime record cannot disable the profile, substitute the other language's accounting or downgrade its selection digest to function-only. Both plain and SDK lanes retain the same original build and producer file facts.

Final health requires the selected `object_accounting` or `resource_accounting` record and rejects it for a function-only profile. All counters retain their exact unsigned-decimal wire types. Shutdown must be closed, with no pending, lost, duplicate or invalid observations. `admitted = completed + censored` is checked independently. Censored observations remain visible; they are not relabelled as completed destruction or free operations. Empty type catalogues cannot claim admitted instances.

A separate uncommitted development snapshot exercises genuine SDK `b425d1f` through four owned applications: plain/on C++ construction/destruction and plain/on C allocation/free. Both SDK lanes report one admitted/completed instance, no censored/lost observations and one selected function call. Each raw OTLP capture decodes two spans and twelve metric points, matching its final SDK unit counters. All 625 consumer and 487 provider source facts plus both SDK products remain unchanged. This checks the preparation/session/health connection and retains raw transport bytes; it is not exact-revision generated-suite or lifetime-specific semantic receipt qualification. The function-only downstream reader retains its separate scope and refuses lifetime profiles. The new [lifetime receipt component](native-lifetime-receipt.md) has its own later four-application development evidence against SDK `6475be4`, with caller records published before release and complete raw span/metric joins.

## Remaining integration and acceptance

The [maintainer caller pipeline](native-lifetime-callers.md) materialises compiler-bound scalar callers, obtains complete lifetime semantic facts before SDK compilation and repeats compiler input/search and semantic checks. Its earlier two-profile metadata probe starts no SDK builds or applications. The experimental public route connects explicit planning/runtime configuration and independent prebuild expectations; the separate qualified completed-lifetime corpus adds actual generated, retained and promoted execution. Metadata probes alone do not qualify execution.

1. Qualify caller-selected per-unit contexts and independently observed semantic type/construction/allocation sites through the connected public route, including private VFS/neutral-driver assets and producer-selected path refusals.
2. Exercise the connected build4/build5 readers through genuine generated callers and public planning/runtime, retaining complete commands, products, semantic expectations and compiler channels.
3. Qualify independent frontend/tool discovery and unsupported cases through compiler input/search probes before and after actual builds/execution. Type names and aggregate counts alone do not establish construction or resource pairing.
4. Verify the integrated caller expectation and direct OTLP components against actual public generated observations. Keep complete-constructor return, destructor entry, C free entry and garbage collection distinct. Censored shutdown and lost/capacity-refused observations must remain visible.
5. Connect real nontrivial/allocated fixtures to generated and retained/replayed/reduced/promoted suites. Qualify all metric startup states and same-process live controls separately, including same-output state differences and altered-evidence refusals.
6. Complete source preservation, independent review, measured coverage, final-head CI and published exact-revision execution before admitting either profile. Shipping artefacts, performance/resource budgets and broader platforms retain separate acceptance evidence.

Run `make native-provider-check PYTHON=/absolute/path/to/python` for the negotiation, source-binding and existing function-provider regressions. These tests use literal records and fake tools; they do not replace genuine SDK product binding or actual application/telemetry qualification. The [completion checklist](completion.md) remains open for the unimplemented requirements above.
