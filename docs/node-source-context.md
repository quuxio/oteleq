# Node callable module context

Generated JavaScript and TypeScript callers retain the actual CommonJS or ES-module format selected for the original source, its private snapshot and each materialised caller. This covers `.js`, `.mjs`, `.cjs`, `.ts`, `.mts` and `.cts` inputs supported by the selected provider. It does not complete Node dependency or general build integration.

## Use the project root

Pass the application directory containing its package and compiler configuration to `plan`:

```sh
quux-oteleq plan --source /absolute/path/to/application \
  --otelc-root /absolute/path/to/qualified/otelc \
  --language javascript --language typescript --workspace-parent /tmp
```

The normal [generation, run, replay and export commands](automatic-generation.md#build-and-run) then apply. No module-format override is needed. Select the TypeScript emitter through the existing `[adapters.typescript] backend` setting.

## Rebuilt SDK profile in qualification

The explicit `source-v1` Node profile uses the rebuilt SDK's public schema-3 policy and source-launch APIs. Select it in the project policy:

```toml
[adapters.node]
backend = "source-v1"
typescript_compiler = "native"
```

`typescript_compiler` accepts `native` or `api`. These identify the SDK's Microsoft native TypeScript compiler and TypeScript API compiler respectively. Keep the legacy `[adapters.typescript] backend` at its default `source`; a conflicting legacy emitter is refused. Use `OTELEQ_PYTHON` to select the SDK's matching Python environment and `OTELC_NODE` to select its prepared Node runtime. The provider must contain its locked dependencies and matching prebuilt observer; planning does not install or build SDK products.

Planning requires the public source5/execution1 protocol descriptor, probes it once per workspace and retains the complete public capability response, including candidate declarations. It freezes installed SDK/dependency/tool identities. A candidate declaration permits this explicit profile to be tested; it does not qualify an adapter automatically. An older or mismatched protocol is refused before application launch. TypeScript inspection uses the selected SDK compiler with plain emission, then replaces the selected application module before evaluation. Raw compiler inputs, options, outputs, maps and actual configuration reads are retained separately from application-launch evidence.

Each attempt uses a fixed consumer supervisor. It retains the actual Node PID, process group and exit, waits for the independent SDK's actual exit, and checks the original request, generated recipe, startup journal, versioned input-verification receipt, final health and decoded OTLP. It independently rechecks the raw source journal, retained source/compiler/emission bytes, fixed compiler recipes and original input identities. After verified SDK shutdown, it removes the inactive event FIFO and records that cleanup; retained evidence can then be copied during reduction. Plain JavaScript has no fabricated SDK report or loader journal. The OTLP receiver accepts bounded chunked requests only for this explicit profile. Function metrics and traces are checked separately from application stdout/stderr and state.

The supervisor takes no command-line request override. Its request, policy and runtime have fixed names in the owned run directory; the selected application must be a regular input in the prepared private project. Runtime output must also remain outside the actual loaded SDK, including when a provider path uses an alias. Post-run evidence paths are derived again from original consumer intent, after comparing the retained request.

Source5 keeps returned code separate from observed module-body entry. The consumer independently checks the closed execution1 witness against the actual application PID, original source, load identity, returned emission digest and pinned observation helper. It recomputes every module outcome from the raw journal. A deferred earlier attempt requires a complete same-URL reentry chain ending in a later witnessed entry; its execution format remains unobserved. Compiler phases must remain complete and ordered. Actual selected entries must match the independently inspected module context. Plain TypeScript includes a metadata-only body-entry helper; its raw compiler output is retained separately. These witnesses identify module entry, not individual function invocation or module completion.

Function metric verification retains every cumulative sample and its start/end timestamps. It checks samples in observation-time order before using their final totals. A changed start, decreasing count, histogram bucket or duration sum, or contradictory snapshots at one timestamp cannot be hidden by an earlier maximum. Identical repeated snapshots and valid out-of-order delivery remain permitted.

The `node-source-provider` directory seals planning/compiler evidence and travels with exported and reduced suites. Changed evidence prevents replay and cleanup. Current-source promotion retains the provider settings and makes fresh context receipts for each new snapshot.

This profile remains in qualification. Initial source4 development evidence covers scalar public CLI runs on Node 24 and 26, both TypeScript compilers, retained Node 24 suites, receiver diagnostics, collection and reduction. Broader context checks found unresolved or retried format evidence in default JavaScript/TypeScript contexts. Those failed runs remain separate; they are not adapter admission. The first delivered profile requires corrected source5/execution1 evidence and a new immutable SDK handoff. Complete runtime/context/control qualification, final review and protected CI delivery remain pending. Live Node metric controls and invocation-scoped action attribution remain unimplemented.

Include every `package.json` and `tsconfig.json` required by this source context within the selected tree. Selecting only a `src` subdirectory can omit a parent package which changes `.js` or `.ts` interpretation. An ambient package outside the selected root is a visible blocker. The private workspace must also have no undeclared parent package.

## What is checked

Planning uses the selected Node executable and, for TypeScript, the provider's compiler-only loader. A fixed inspection hook obtains the real loader result and replaces the selected module with empty source before evaluation. Application initialisers, constructors and function bodies do not execute during this inspection.

The original source and private snapshot must agree on:

- The actual CommonJS or ES-module format.
- The nearest package's relative path and complete content hash, or its absence.
- The selected Node version. The plan separately retains the tool's content identity.

The source hash is checked around inspection. A malformed package, unavailable compiler context, changed input or unsupported loader format remains an inventory blocker with the discovered callable names. Supplying a receiver fixture cannot clear that blocker.

CommonJS callers load the fixed observer synchronously through the ordinary unshadowed `require` binding and invoke asynchronous observer work inside a private async caller. ES-module callers retain their module bootstrap. Free-function and class bindings are still captured before application statements or static initialisers can replace them. A shadowed CommonJS `require` needs a separate access fixture and remains blocked.

Before each application launch, a second inspection checks the generated caller's actual format against its planned context. Each attempt retains `node-context.json` with original and caller receipts, plus the bounded `node-context-probe` process output. These inspections execute tooling only and are separate from application launch counts.

Generated suites, replay and exported bundles retain the same context. Package or source edits invalidate the frozen plan; create a new plan for changed application code.

## Observation and build limits

This is diagnostic caller evidence. It preserves the existing [scalar and object observation scope](observations.md) and [declared receiver contract](receiver-fixtures.md). State reachable only through CommonJS wrapper/module.exports caches or undeclared imported modules remains unobserved and is recorded as a scope gap.

The normal snapshot still excludes `node_modules`. Dependency installation, workspace links, package-manager hooks, custom loaders, semantic TypeScript project/type graphs and general bundler/build recipes remain incomplete. Relative imports and package mappings must resolve using the available private inputs and the qualified provider. A matching module-format receipt does not prove that all imports resolve or that a shipping artefact is equivalent.

## Reproduce the qualification

Use the qualified provider's locked Python environment and the matching Node tool:

```sh
make generation-node-project-otelc \
  PYTHON=/absolute/path/to/otelc/.venv/bin/python \
  OTELC_ROOT=/absolute/path/to/qualified/otelc \
  REPORT_DIR=/private/tmp/new-node-context-qualification
```

This creates fresh fixtures and tests them through public run/replay commands, the generated `unittest` suite and an exported suite with its original application directory detached. It also reduces a same-return global-state difference from argument `7` to `0` and retains every trial and confirmation. The report directory must be new and outside both repositories.

To qualify the explicit rebuilt SDK profile, add `GENERATION_ARGS='--node-backend source-v1 --typescript-compiler native'` to that command and use its immutable source5/execution1 provider. Repeat with `api` for the other TypeScript compiler and a fresh report directory. This selects a separate contract: default Preserve `.ts` executes as a module under these Microsoft compiler profiles, while the legacy default remains unchanged. The maintained oracle checks complete fixed application graphs, actual module context, direct final SDK status and independently decoded raw function signals. The command does not admit the profile merely because its metadata handshake succeeds.

## Qualified scope

Maintainer regressions cover actual loader formats, CommonJS free/receiver callers, exact scalar state and return values, source preservation, binding/intrinsic refusal, named context blockers and detached export. They use a limited compiler fixture for JS-compatible TypeScript unit cases.

The [22 October record](qualification/node-projects-2026-10-22.json) binds runtime/verifier `6e723ca`, frozen provider `d6d03b7` and Node `24.21.0` on macOS ARM64. Its 245 unique application launches cover:

- Eleven free-function contexts: `.cjs`, `.mjs`, default/module/commonjs `.js`, syntax-detected `.js`, `.cts`, `.mts` and default/module/commonjs `.ts`.
- Plain JavaScript and TypeScript CommonJS receivers with independently expected state and self-aliases.
- Complete initial/final/outcome graphs, exact scalar argument/result bits, descriptors, property order, stdout/stderr and original/private/caller context receipts in every repeat and lane.
- Independently decoded raw OTLP span identity, application PID/service/scope, counters, histogram buckets/extrema and zero reported loss.
- Four refusals before application launch: shadowed `require`, changed source, a rehashed forged format and an ambient parent package. Startup rebinding is separately refused after one plain launch.

Every module-context fixture ends in a line comment without a final newline. Generated CommonJS callers insert an explicit newline and statement separator before their async wrapper. The existing JavaScript/TypeScript receiver corpus separately passes 186 application launches on the same frozen CLI. Copied shrink reports do not count as new launches. All 9,744 sealed evidence files and the provider's recorded source, products, dependency inputs and tools were rechecked.

These are diagnostic caller results for the recorded provider/platform, with the observation and build limits above. The acceptance claim remains **equivalence over these tests and observations**.
