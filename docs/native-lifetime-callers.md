# Native lifetime caller pipeline

<!-- markdownlint-disable MD013 -->

Status: compiler-bound scalar callers use independent C++ object/C resource discovery before SDK compilation. [Public lifetime configuration](native-lifetime-generation.md) connects explicit fixture expectations to owned execution, with [ten-fixture qualification](qualification/native-workflows-2026-10-26.json). Broader profiles remain open. Separate [build](native-lifetime-provider.md) and [receipt](native-lifetime-receipt.md) readers check the resulting evidence.

## Before SDK compilation

`native_lifetime_caller.prepare` accepts the independently inventoried source request and an earlier frozen semantic-tool context. It creates private accessors, VFS overlays and a neutral driver outside application and SDK inputs. The actual Clang frontend checks the original declaration, signature, invocation reference and helper profiling exclusion. Complete per-unit compiler inputs and existence/search probes remain distinct from lifetime metadata.

The pipeline compiles a separate caller-owned semantic helper using fixed commands and the frozen source, headers and Clang/LLVM libraries. Compiler dependency queries run before and after compilation. On macOS the complete helper/dSYM product set is checked and the bounded Mach-O images must share the expected CPU and UUID. SDK metadata cannot select a new tool or input path.

Each application unit then supplies its original flags, compilation directory, physical source and private VFS overlay to that helper. C++ queries retain the selected compiler's explicitly observed target triple. Neutral drivers acquire no lifetime probes. Complete source/type/construction/allocation/release facts are frozen before build4/build5 SDK compilation, with source/type selection evaluated independently.

The result holds the original caller files, compiler state, semantic helper and lifetime build intent. `Caller.recheck` repeats full compiler input/search probes and semantic queries after SDK compilation or execution. New existence-only inputs, changed type/site facts, foreign contexts, changed tools and restored bytes with different file facts refuse. Original accepted records are not refreshed from a producer response.

Expected runtime instance counts, call paths and completion/censoring outcomes still come from the test contract. Discovering a constructor or allocation site does not predict how often a test will execute it.

## Development evidence

A frozen uncommitted development snapshot on macOS ARM64 uses actual LLVM 22.1.8 and genuine held SDK `6475be4` inputs. C++ and C cases bind their generated scalar calls to the original source declaration, retain one selected `Item` type and one construction/allocation site, and pass fresh compiler/semantic rechecks. The C++ build4 intent holds 1,477 caller evidence files; the C build5 intent holds 1,312. Both SDK output directories remain absent: this probe starts no SDK builds or application workloads.

All 634 consumer files, 503 provider files and both original SDK products retain their bytes and file facts during the passing window. An earlier attempt exposed a missing retained-byte read for the macOS UUID check; the fixed branch has a matching positive/altered-UUID regression. A second attempt correctly refused a probe policy without the required context configuration. Both failed attempts remain separate from the passing record.

This is private frontend integration evidence. It does not qualify an exact published execution revision, public generated or retained suites, same-process controls, shipping artefacts or SDK transparency.

## Run the component checks

```sh
make native-lifetime-caller-check PYTHON=/absolute/path/to/python
```

The target checks the new pipeline and existing compiler-bound function callers, with separate 80% statement floors. Tests use actual Clang frontend/VFS discovery and explicit nonexecuted literal SDK tools, plus bounded Mach-O/UUID, command failure, original-channel, source-boundary and substitution controls. The SDK build3 reader continues to refuse enabled lifetime policies. The new module is embedded in the Rust distribution and included in generator identity.

The [completion checklist](completion.md) still requires exact-revision generated/replayed/reduced/promoted qualification of the experimental public integration, actual startup/live schedules, source preservation and final release evidence.
