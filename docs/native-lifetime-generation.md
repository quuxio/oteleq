# Generated native lifetime tests

<!-- markdownlint-disable MD013 -->

Status: experimental public configuration and orchestration with [18-shard exact-revision qualification](qualification/native-workflows-2026-10-26.json) for ten named lifetime fixtures and generated/retained/replayed/reduced/promoted routes. Completed, explicit-zero, censored and prescribed C++ exception boundaries have separate original evidence. Select these profiles only with a matching SDK that provides the complete requested protocol. The existing [function-only profile](native-prepared-provider.md) keeps its separate qualification.

## Configure independent expectations

Start with [the example policy](../examples/equivalence-native-lifetimes.toml). It selects a C++ scalar free function that constructs and destroys one `Item` during its call. Adapt the function, source path, selected types and observations to the application. The generated tests stay in the external transient workspace and use the ordinary [plan, generate and run commands](native-prepared-provider.md#select-the-candidate).

| Setting | C++ object profile | C resource profile |
| --- | --- | --- |
| Language and adapter table | `cpp`, `adapters.cpp` | `c`, `adapters.c` |
| Explicit `profile` | `native-objects-owned-v1` | `native-resources-owned-v1` |
| Required source-build protocol | build4 / object inventory2 | build5 / resource inventory1 / resolution1 |
| Completion observation | Destructor entry | Standard `free` entry |
| Completed instance `exception_exit` | Required boolean | Omit |

Both profiles require explicit adapter `lifetimes.include` type patterns. Optional `exclude` defaults to `[]`; `max_live` defaults to 4096 and accepts 1 to 1000000. The matching SDK must expose both object and resource ABI headers. The C profile additionally freezes the selected LLVM `llvm-nm` input before reading build metadata. Existing source/compilation-database settings and build timeouts still apply.

Every selected function needs a matching `[[fixtures]]` declaration with `lifetimes`. Each observation declares:

- `type`: the selected source type name, resolved to exactly one compiler type identity before the SDK application build.
- `creation_path`: the selected synchronous call path. One generated free-function call has root `[0]`; a nested serial child can be `[0, 0]`.
- `complete`: whether destruction/free occurs during a declared call or the SDK records an instance still live at shutdown.
- `release_path`: required for a completed instance. Omit it for an incomplete instance.
- `exception_exit`: required for a completed C++ object and omitted for C resources or incomplete objects.

For example, the C resource fixture portion can be:

```toml
[[fixtures]]
language = "c"
source = "src/workload.c"
function = "workload"
cases = [[5]]
lifetimes = [{type = "Item", creation_path = [0], release_path = [0], complete = true}]
```

The declaration order is the expected admission order. All cases covered by one fixture use the same declarations. Use separate fixture selections when different callables need different contracts. An explicit `lifetimes = []` means zero expected instances; an absent declaration blocks the selected function. An incomplete declaration such as `{type = "Item", creation_path = [0], complete = false}` requires visible censored shutdown and does not claim completed release. Expected counts, paths and outcomes are never learned from emitted telemetry.

## Bind and check the execution

Planning materialises the original compiler-known source/header names selected by the generation policy. The SDK receives those literal paths, including selected header types. Ambiguous same-name functions in different selected sources within one target refuse before the SDK application build. Literal source paths containing `*` or `?`, more than 1024 selected input names, receivers and ordered action fixtures remain unsupported in these profiles.

The [caller frontend](native-lifetime-callers.md) independently discovers its helper headers, LLVM libraries and host target using fixed bounded queries. It builds the caller-owned semantic tool, binds private VFS/accessor/neutral-driver inputs and freezes complete source type/site facts. The test's type names then resolve against those earlier compiler observations. Missing or ambiguous identities refuse. A private `expected-lifetimes-before-build.json` record seals these resolved expectations before the producer compiles the application.

The separately checked build4/build5 reader supplies the owned preparation/session path. A second `expected-lifetimes.json` record binds the same observations to the accepted preparation before any application execution. Original frontend/compiler/expectation facts are rechecked after the SDK build and after execution. A changed file cannot be accepted by restoring its old bytes and refreshing its identity.

The [direct receipt](native-lifetime-receipt.md) checks every function and lifetime span, creation links, completed versus censored outcomes, full metric series and owned final SDK counters. `native-verified-lifetimes.json` retains that complete receipt. The common comparator receives only its defined function-witness fields and function-span count; lifetime spans and counters remain explicitly checked in the separate retained receipt. The plain lane requires absent SDK telemetry and final SDK health.

This establishes equivalence over the declared application tests and observations, with an independent instrumentation receipt. It does not prove every function, input, lifetime, concurrent schedule or shipping artefact is identical. Baseline execution does not acquire an instrumentation-based lifetime oracle.

## Contributor checks and remaining qualification

The separate [hosted workflow driver](native-lifetime-workflows.md) builds a fixed noncoverage SDK and exercises genuine public routes with literal return/state/errno oracles and original source/product facts. The ten-fixture corpus has 296 original applications, 148 instrumented receipts and 140 altered-evidence refusals. The earlier 100-launch completed-lifetime record remains independently scoped.

```sh
make native-lifetime-public-check PYTHON=/absolute/path/to/python
```

The target checks literal query discovery, explicit profiles, independent expectations, prebuild ordering, public orchestration, unchanged function-only behaviour and separate module coverage floors of 80%. It executes no compiler, SDK build or application. Other caller/build/receipt targets retain their own real-compiler or literal scope. Both new modules are embedded in the Rust distribution and included in generator identity. The example policy is parsed and validated by a regression.

The recorded generated/framework/detached execution, replay, reduction and current-source promotion retain exact source/CLI/SDK identities. Broader callable/build support, native lifetime/resource live schedules, production artefacts and platform/performance qualification remain open in the [completion checklist](completion.md). Function-only live metric schedules have their separate [qualification](native-metric-workflows.md).
