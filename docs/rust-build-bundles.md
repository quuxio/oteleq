# Rust build records and replay

Generated Rust callers build only the lane being tested. The plain lane uses the explicitly selected compiler; the instrumented lane uses otelc's build-only API and then replays the retained executable. Compiler output is retained separately from application stdout/stderr. A combined compile-and-launch provider is unsupported.

The consumer implements three distinct contracts. Supporting a record format does not qualify an untested provider.

| Backend | Build schema | Additional compiler evidence |
| --- | --- | --- |
| Legacy `compiler` | 1 | Fixed baseline flags, source/application/plan/adapter/SDK hashes and selected compiler provenance |
| Original-source `compiler` | 3 | Fixed profile, MIR driver, original compiler request and emitted-instance inventory |
| Explicit `llvm` | 2 | Profile1/inventory2 or profile2/inventory3, with actual LLVM resolution records |

The [20 October compiler record](qualification/rust-compiler-2026-10-20.json) qualifies runtime `ed09f13` against content-verified candidate provider `aca9d5a`: 108 actual launches and 14 altered build-record refusals. Another 24 actual launches confirm legacy schema1 compatibility against frozen provider `0419a51`. Existing LLVM and earlier compiler records retain their original runtime/provider identities. The current scalar caller remains standalone and synchronous; fixed producer diagnostics do not enable Cargo, general module graphs, generated async targets or receiver codecs. This candidate corpus does not qualify a later producer revision or release.

## Original-source compiler profile

`target/debug/otelc-rust-compiler.json` has profile schema1 and `backend="compiler"`. The supported profile identifies Rust 1.98.1, commit `48a229ceaefd4985c50990b14116b6d856af0985`, macOS ARM64 and LLVM 22.1.8. `OTELC_RUSTC` must select that actual compiler. The consumer hashes its bytes and reads its verbose version; metadata cannot choose an executable.

The SDK and MIR driver have fixed provider-relative paths: `target/debug/libquux_otelc_rust.rlib` and `target/debug/otelc-rust-mir`. The descriptor, driver, SDK and compiler-resolvable SDK products are frozen with the plan. Adding/removing/changing a dependency, redirecting a product through a symlink or altering the selected compiler invalidates that identity. Compiler sysroot libraries and OS libraries remain outside the content manifest.

The profile and manifest must agree. A provider with the original-source profile cannot substitute a legacy schema1 build; schema3 requires the actual profile. The separate LLVM backend does not satisfy this contract.

## Retained schema3 evidence

Each instrumented attempt retains `application`, `build.json`, `plan.json`, `profile.json`, `compiler-request.json` and `inventory.json`.

`build.compiler_driver` binds the profile, driver, request and inventory SHA-256 values. The retained profile must be byte-identical to the selected provider's descriptor. The complete compiler recipe must match the diagnostic caller: original relative entry path, `--edition=2024 -O -g`, private output, fixed SDK dependency lookup, selected sysroot and fixed probe crate. Unexpected flags, a substituted tool or an output outside the caller's scratch directory refuse the run.

The request binds the original source/root, loaded-source hashes, resolved policy, protected provider source roots and dependency-discovery arguments. Its policy is the exact Rust `Plan` projection of the retained resolved plan. The inventory must agree with the source/discovery records. Every ordinary target and the independent startup need one emitted compiler instance, an exact original declaration and distinct symbols. The caller's source/function selectors remain frozen alongside that exact target set. Expanded or uninstantiated targets cannot satisfy the supported scalar caller. Other loaded source graphs remain unavailable in this profile.

The fixed eight-language Rust capture declares its curated async targets separately. Only those exact original future declarations can use the compiler's completion lowering; a different unsupported reason or an undeclared async target refuses. The compiler can retain constructor and coroutine-body symbols under one future owner; all are retained against that same declaration. Inlining changes which symbols remain. Source-policy selection and symbol counts do not establish timed invocations or a complete drop-glue map: constructor creation is unmeasured, and decoded runtime evidence covers first poll through completion, cancellation or unwind. Ordinary scalar instances remain unique. This does not enable general generated async fixtures.

Original-source generated and fixed captures require an empty future registry with admission available, independently of drained trace counters. The legacy provider retains its separate qualified health contract.

Profiles are bounded to 64 KiB, requests to 8 MiB, inventory/build/plan records to 4 MiB and function inventories to 65,536 entries. Required records must be regular files. Missing or altered data cannot become an equivalence verdict.

Build records establish compiler provenance within the trusted-provider boundary. They are not signed attestations against an actor replacing every artefact and recomputing all hashes. Emitted symbols and name-bound spans do not authenticate a particular invocation. The [invocation witness](action-witness.md) remains unavailable.

## Independent semantic fixtures

`tests/fixtures/rust_compiler_semantics.rs` has no SDK imports. Plain-compiler regression tests check source-derived column/tracked-caller observations, fixed closure/future layout, compile-time `Send`, unpolled drop, pending/completed/cancelled futures, a typed panic payload and exactly-once destruction. `rust_compiler_aliases.rs` and `rust_compiler_shared.rs` supply two logical module paths to one read-only physical source; the regression verifies both links, bytes and permissions after compilation.

The fixed paired corpus additionally checks those original, SDK-free fixtures against the candidate's real compiler instrumentation. Both semantic lanes produce the independently specified column/caller/layout values and completion/cancellation/unwind drop counts. The aliased-module workload preserves two logical links, the shared physical bytes and read-only mode. Actual decoded spans, complete future-registry health, loss/pending counters and source preservation are required. These are curated producer diagnostics; generated module/async adapters remain open in the [completion checklist](completion.md).

## Qualified corpus

| Scope | Actual application launches | Observations |
| --- | --- | --- |
| Four generated scalar cases, all four routes | 96 | u128 extreme, f32 and signed zero, logical source path; exact typed record and stderr oracles; build warnings stay separate |
| Fixed recursive/future/error workload | 4 | Eight spans/four trees per on attempt, including completion, cancellation and escaping unwind |
| Independent semantic workload | 4 | Six spans with separate cancellation/unwind errors; column, tracked caller, closure/future layout, `Send`, payload and exactly-once drops |
| Read-only aliased modules | 4 | Two selected logical function identities and two root spans; source links, bytes and permissions preserved |
| Legacy schema1 compatibility | 24 | The same four scalar cases against the separately frozen older provider |

All 132 command identities are unique. The 14 retained-bundle controls perform no application launches; they reject rehashed request policy/source/discovery, inventory source/name/role/emission/position, compiler version/output, backend/profile changes, downgrade and linked records. The scalar oracle requires a complete typed record line, so an expected value such as `7` cannot accept `70` or a prefixed/suffixed record. Fixed standard capture retains raw channels, telemetry and build identities; it does not retain detached private binaries after its workspace is removed.

Run the fixed producer corpus with `make rust-semantic-otelc OTELC_ROOT=/absolute/qualified/provider REPORT_DIR=/absolute/new/report`. `--workload semantics` or `--workload aliases` on `tests/qualify_rust_semantics.py` selects one fixed workload; supply `--cli` for the actual oteleq comparator. `make generation-rust-otelc` additionally runs all four default scalar cases through generated and exported suites, including their per-case replay routes. The LLVM qualifier retains its separate contract.
