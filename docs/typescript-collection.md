# TypeScript emitters and collection observations

TypeScript receiver fixtures can request the same ordered call, release and bounded collection observations as JavaScript. Choose the emitter explicitly in the generation policy; it is frozen for both baseline and instrumented execution, generated/exported suites, scalar shrinking and replay.

```toml
schema_version = 1
languages = ["typescript"]

[adapters.typescript]
backend = "source"

[functions]
include = ["sample.Counter.add"]

[[fixtures]]
source = "sample.mts"
function = "sample.Counter.add"
cases = [[7]]
receiver = { factory = "Counter", arguments = [10] }
sequence = [
  { action = "call", arguments = "case" },
  { action = "call", arguments = [2] },
  { action = "release" },
  { action = "collect", gc_rounds = 64, settle_turns = 4 },
]
```

`source` is the default Microsoft TypeScript API emitter. `native` selects the separately installed Microsoft native compiler. The compiler binaries, package/adapter inputs and Node executable are part of the selected provider identity. An unavailable native compiler or unsupported provider is a blocker; the runner never substitutes the other backend.

## Public capability gate

During planning, collection requests and native-emitter targets run the selected provider's config-only command:

```text
otelc --config POLICY --language typescript config --json --require-supported
```

No application is launched by that query. The consumer requires schema 2, the selected language/backend, successful execution availability, the exact selected functions and enabled traces. A collection request additionally requires acknowledgement of the original declared class, collection boundary and empty resource configuration. Older providers which refuse TypeScript collection remain named blocked inventory entries.

The actual request, command, status, stdout/stderr and validated response are retained in the inventory and exported plan. Each application attempt records `typescript-controls.json`, pins `OTELC_TYPESCRIPT_BACKEND` for the compiler-only baseline, and writes the same backend into the instrumented policy. Provider/tool identity is rechecked around execution. A private filename is never treated as a capability declaration.

## Observations and limits

The ordinary receiver codec preserves original source class/method identity, independent construction, declared own data, aliases and cycles. Selected source factories provide actual creation-span links; direct source constructors require unlinked lifetime roots. Both emitters use the [ordered sequence contract](ordered-sequences.md), exact application channels and actual lifetime accounting. Missing collection, censored instances, incomplete export or nonzero losses stay inconclusive.

The test control exposes GC to the selected Node runtime. Retry counts remain raw evidence outside typed equality. This does not compare collection timing, prove leaks, observe destruction or qualify a shipping artefact.

Supported `.ts` files need a declared module context; explicit `.mts`/`.cts` formats remain distinct. The diagnostic corpus supplies its own unchanged module manifest. Arbitrary package/build integration remains open. Producer support for private fields, parameter properties, namespaces or class expressions does not add those codecs to oteleq: the existing ordinary receiver restrictions still apply. General action targets, asynchronous factories and other language receiver sequences need further work.

The maintained actual corpus runs both emitters with `.ts`, `.mts` and `.cts`, async methods/source factories, expected errors, temporary mutation, application finalizers and retained-object gaps. It also checks generated/exported suites, scalar shrinking/replay, changed-source refusal and the actual older provider's prelaunch refusal:

```sh
make generation-typescript-sequence-otelc \
  PYTHON=/absolute/path/to/otelc/.venv/bin/python \
  OTELC_ROOT=/absolute/path/to/qualified/typescript-provider \
  UNSUPPORTED_OTELC_ROOT=/absolute/path/to/older/provider \
  REPORT_DIR=/tmp/new-typescript-qualification
```

Actual qualification must name exact consumer/provider products and compiler/runtime versions. Implementation tests and development launches do not establish a different provider's compatibility. The result remains **equivalence over these tests and observations**.

## Published qualification

The [20 October record](qualification/typescript-collection-2026-10-20.json) names runtime `3f6bd8e`, its frozen executable and provider `266e1ba` on macOS ARM64/Node24.21. Microsoft source 6.0.3 and native 7.0.2 each completed 132 actual launches: five matching cases, one detected temporary mutation and one correctly inconclusive retained receiver. Both generated/exported frameworks, scalar reduction/replay, six altered-evidence controls and a changed-source refusal passed per emitter. Source inputs were preserved.

The actual older `c65a35c` provider blocked all seven collection targets per emitter before application launch. The full local gate passed 339 regressions with Rust line coverage at 97.29% and the new provider module at 95%; exact-runtime remote checks passed with zero Sonar findings. The 272 raw capture folders include eight byte-identical preserved original shrink attempts; there were 264 actual launches.
