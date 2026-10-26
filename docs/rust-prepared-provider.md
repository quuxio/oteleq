# Rebuilt Rust provider integration

<!-- markdownlint-disable MD013 -->

This work connects the rebuilt Rust SDK to oteleq. The current SDK has retained standalone stock/woven builds and direct launches. The SDK owner has reserved an owned preparation contract; its execution remains under implementation. The existing qualified Rust compiler/LLVM profiles remain separate; this document does not admit a new generated runtime profile.

## Consumer components

`rust_tools.py` independently reads the existing `otelc.rust.compiler-tools` version-one record. The caller supplies its selected compiler, sysroot, host and actual version query before the record is read. Fixed compiler/bridge product paths and the complete SDK Rust source/manifest/lock denominator are reconstructed independently. Original bytes and file facts remain held. The reader imports no SDK implementation and executes no compiler or application.

`rust_protocol.py` validates the reserved `otelc.rust.protocols` version-one descriptor for the explicit `rust1981-owned-standalone-v1` profile. Source build1 selects sync-v1, native plan2 and health1; source build2 selects drop-v2, native plan3 and health5. All other prepared record versions remain1. Missing or extra fields, mixed profiles and boolean/float version substitutes refuse. Descriptor acceptance alone does not establish that an SDK implements execution.

Run `make rust-provider-check` for the bounded metadata tests and separate 80% coverage floors. Both readers are embedded in the Rust distribution and bound to the generator identity. Required CI also runs these tests through `generation-check`.

These file/metadata components do not establish compiler execution, whole dependency/sysroot closure, application instrumentation or downstream receipt. Those require their own observed build/launch records and genuine qualification.

## Required SDK preparation boundary

The reserved `otelc.prepared_rust` interface preserves the current direct-build contracts: `rust1981-standalone-sync-v1`/build1 and `rust1981-standalone-drop-v2`/build2. Its separate `rust-owned-build.json` version-one envelope binds the caller-selected original `rust-source-build.json` and the fixed `gate/gate.json`; its profile is `rust1981-owned-standalone-v1`. The original application build remains external and is not copied or rewritten. SDK implementation and independent consumer build/prepared/launch readers remain required.

Preparation must be compiler-free, create a new single-use private runtime and bind a closed request/plan/prepared record to the caller's policy, original build, fixed image, literal arguments, bounded wait and fresh launch ID. Both baseline and instrumented lanes need the same host release boundary. The baseline has no linked SDK, SDK plan or health. The instrumented lane supplies its existing native plan2/3 and health1/5 explicitly.

The host must observe the real supervisor/application parent, group and session before release. SDK metadata must retain unavailable image/ownership dimensions accurately; the consumer makes its own kernel observations. Final execution rechecks original source, compiler/bridge/SDK products and policy/selection, and retains actual exit, health, loss and drain results. Metadata cannot choose executables, compiler flags, modules or extra filesystem reads.

The consumer then joins independently declared values/state, raw function/drop telemetry and closed health. Live collection and emission change independently in one unchanged process/build while tracing remains independent. Generated callers, replay, detached/framework suites, reduction and current-source promotion each need actual execution and refusal controls.

## Full Rust requirements

Standalone preparation is one integration step. Cargo targets/features, dependency and build-script inputs, complete compiler/sysroot closure, receivers and mutable values, generic instances, async/cancellation and richer ownership remain required by the [completion plan](completion.md). Unsupported requested capabilities must remain visible. A literal metadata test or one diagnostic workload cannot complete those requirements or establish shipping artefact equivalence.
