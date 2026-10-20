# Retained Go builds and replay

Go capture and generated scalar tests require otelc's separate build-only/baseline/on replay API. The former combined `go SOURCE.go` compiler/launcher is not a qualified substitute. The API is developed in [otelc PR91](https://github.com/quuxio/otelc/pull/91); a frozen candidate is independent qualification evidence, not a claim that it has merged or shipped.

## What happens in an attempt

1. Read the environment/version of the explicitly selected `OTELC_GO` compiler and hash that driver plus its compile/asm/link tools.
2. Build both actual executables with `go --build SOURCE.go --output-dir NEW_DIRECTORY`. Application `init`/`main` must not run during this stage.
3. Verify the schema-1 `build.json`, listed regular files and their hashes, compiler recipe, original source/SDK inputs, resolved policy and nonempty module graphs.
4. Launch the requested lane with `go --run-baseline BUNDLE` or `go --run BUNDLE`. The adapter validates the retained bundle and copies its selected executable privately; neither lane invokes the compiler.
5. Capture exact application bytes, typed state/outcome and the selected on-lane instrumentation/transport witness. Compiler diagnostics stay in build evidence.

The current generated caller is standalone and appends a diagnostic helper in a private source copy. It does not add arbitrary package/class access, build tags, cgo or workspace support. Original application/dependency files, manifests and locks remain unchanged. Tests and captures stay outside the target repository.

## Retained evidence

Each attempt's `go-bundle/` contains both `baseline` and `application`, `build.json`, resolved `plan.json`, `recipe.json`, original/resolved module snapshots, private module/overlay/generated inputs and baseline/instrumented compiler stdout/stderr/status. `go-build-identities.json` binds the real binary hashes, bundle/recipe/plan hashes, selected compiler and input denominator. Generated reports also retain these under `build-identities.json`.

Metadata records actual source, SDK and compiler paths as provenance. It cannot choose the consumer's executable or flags. The consumer obtains its compiler identity from the selected tool, checks the recipe against the supported fixed flags and hashes loaded inputs while its private source still exists. The replay adapter additionally validates embedded binary build information and module preservation. Empty/missing main-module graphs cannot establish preservation.

The compiler and module caches live under the owned external workspace's `go-cache/build` and `go-cache/modules`; attempts reuse them. Fixed diagnostic capture similarly owns a private cache beside its attempt directories. Loaded input hashes, not cache presence, provide build evidence. Exported and reduced workspaces create independent caches. This changes neither application dependencies nor the original module cache.

Cache roots cannot redirect through symlinks or point into source/provider trees. Each case also freezes a compiler/dependency input fingerprint across its attempts; a new internally consistent build using changed external bytes still refuses the experiment. Different per-attempt private source paths are excluded from that fingerprint and retain their separate source/harness identities.

Bundle JSON/metadata are limited to 4 MiB per file, executable/loaded input files to 256 MiB and inventories to 65,536 entries. Paths must name regular listed files; altered/missing/unlisted bundle data and unsafe names refuse launch. Both compiler builds must have succeeded. Unknown schema/backend, selected compiler changes, source/SDK/hash mismatch and changed build policy cannot produce an equivalence result.

## Build settings and runtime controls

Source/function selectors, annotations and `traces.enabled` are build settings. Both replay policies must preserve them, including baseline replay. Trace-disabled compilation is a different build, not a runtime no-op exporter. Explicit target/compiler-setting changes also require rebuilding. Supported runtime resource/export/sampling settings can be changed for replay within the provider's contract.

The SDK's module resolution must preserve existing dependency, language/toolchain and runtime-default identities. Incompatible older module graphs refuse before application execution. SDK dependency isolation remains open; an unchanged original `go.mod` alone cannot prove unchanged language semantics. Recipe hashes detect inconsistent evidence; these diagnostic bundles are not signed attestations against an actor replacing all artefacts and recomputing their metadata.

Detached replay of a qualified self-contained fixture needs the matching launcher/adapter and host target, with its runtime assets. It does not require the original configured Go compiler, SDK/source installation or module cache. This is not a general portable release package. Forced exit or signals preserve application termination but cannot promise final telemetry flush.

## Run actual qualification

```sh
make generation-go-build-otelc \
  OTELC_ROOT=/absolute/path/to/qualified/otelc \
  REPORT_DIR=/private/tmp/new-go-build-qualification
```

The maintained corpus covers integer state, exact negative zero, an expected panic, a deliberate same-return state difference, generated/exported suites and shrinking/replay. A separate fixture checks no build-time execution, detached runtime-only installation, raw arguments/bytes, exit status and signals, plus altered policy/binary/module/recipe/target refusals. Keep original and incomplete attempts separately; only exact-revision, actual runs qualify the stated scope. General project integration, recording-off/fault lanes, overhead budgets and shipping artefacts remain on the [completion checklist](completion.md).

The [exact-revision macOS ARM64 record](qualification/go-builds-2026-10-20.json) completes 78 actual launches against frozen producer `5ea90fa`: 68 generated, two normal detached, four termination controls and four existing-workload attempts. Six direct tamper/policy/target controls refuse before execution; the old-module language guard and missing-state codec control pass. The first 74-launch run remains incomplete because its read-only binary tamper fixture could not be modified; the repaired fixture has a permanent regression.
