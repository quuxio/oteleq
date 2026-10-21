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

## Qualification status

Maintainer regressions cover actual loader formats, CommonJS free/receiver callers, exact scalar state and return values, source preservation, binding/intrinsic refusal, named context blockers and detached export. They use a limited compiler fixture for JS-compatible TypeScript unit cases.

Actual-provider qualification of this increment is pending. These regressions do not extend the published provider/platform matrix. The acceptance claim remains **equivalence over these tests and observations**.
