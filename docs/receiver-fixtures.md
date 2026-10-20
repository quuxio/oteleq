# Receiver fixtures

The generator supports declared receivers for ordinary instance methods on plain Python, JavaScript and TypeScript classes. Each attempt constructs a fresh instance, binds the selected source method, then captures its supported instance state, own declared class data roots and module globals before and after the call. The shared graph protocol preserves aliases and cycles, including a method returning its receiver.

Other language receivers, inherited classes, private/dunder Python methods, private class data, slots/native storage, arbitrary mutable arguments and Python asynchronous calls remain unsupported. Node supports awaiting an ordinary async method and [ordered calls/release with bounded JavaScript collection](ordered-sequences.md); arbitrary targets, scheduler and iteration sequences remain open. They remain visible gaps rather than passing skipped tests.

## Declare a constructor

No change to the target source is required when its existing constructor accepts supported scalar arguments:

```python
class Counter:
    total = 0

    def __init__(self, start: int):
        self.value = start

    def add(self, amount: int) -> int:
        self.value += amount
        Counter.total += amount
        return self.value
```

Select the method and declare its independent construction inputs:

```toml
schema_version = 1
languages = ["python"]

[functions]
include = ["app.Counter.add"]

[[fixtures]]
function = "app.Counter.add"
cases = [[7]]
receiver = { factory = "Counter", arguments = [10] }
domains = [{ kind = "integer", minimum = 0, maximum = 7 }]
```

Use the normal `plan --config`, `generate` and `run` commands. Tests and access helpers are generated in the private transient directory. The policy's `cases` are method arguments; its `receiver.arguments` are constructor arguments. Python's implicit receiver parameter is excluded from the generated argument list. Domain declarations are optional and apply to method arguments for scalar shrinking.

The example observes `receiver.value`, the declared `static:Counter.total` root, module globals and argument/result graphs. Required receiver/static roots are retained in the typed contract. Source-wide inventory still includes the constructor and other callables: this policy explicitly selects only `Counter.add`, and excludes the others from its equivalence claim.

Regular source packages use the same [explicit import-root policy](python-package-context.md). Function IDs continue to use their original source-relative class/method names. Constructor arguments must explicitly cover its supported positional parameters; implicit no-argument constructors are supported. Custom allocation, inherited state and changed constructor/method bindings refuse capture.

## Existing application factory functions

A policy can also name one existing ordinary synchronous function in the selected module, such as `receiver = { factory = "make_counter", arguments = [10] }`. Its declaration, concrete arguments and source body are frozen. It must return an instance of exactly the selected source class. Decorated, ambiguous, replaced or unsupported factories remain blockers. External fixture files and general factories for arbitrary argument types remain open.

Construction executes inside each private application worker. It must complete successfully without invoking the selected method; missing construction, wrong classes and missing method witnesses cannot qualify. Construction failures are incomplete fixture evidence, not matching method outcomes. Python does not yet compare constructor/action sequences as separate targets. Node can opt into the ordered method/release mode below.

## JavaScript and TypeScript

Use the same `receiver` policy for a named top-level source class and a method ID such as `sample.Counter.add`. Set `languages = ["javascript"]` for `sample.mjs`, or `["typescript"]` for `sample.mts`:

```javascript
export class Counter {
    static total = 0;
    constructor(start) { this.value = start; }
    add(amount) {
        this.value += amount;
        Counter.total += amount;
        return this.value;
    }
}
function make_counter(start) { return new Counter(start); }
```

A TypeScript source can annotate the constructor/method parameters with `: number`. Constructor or factory inputs are frozen separately from method `cases`; both use the adapter's concrete scalar representations. A synchronous same-module factory can return the exact selected class. The factory and class bindings are checked before and after construction and each observed call boundary. Construction must not itself invoke the selected target. Ordinary async methods are awaited; generators, async factories and arbitrary action targets remain unsupported. See [ordered sequences](ordered-sequences.md) for supported method/release/collection steps.

The private source copy gains an observer import and a first class static block which captures source method descriptors before original static initialisers. This changes reflective class source text and is an explicit diagnostic access-helper delta. Original method bodies and target files remain unchanged; it does not qualify a shipping artefact. Replaced methods, changed prototype shapes/extensibility, inheritance, private/computed/literal members, accessors/decorators, generic/abstract classes and constructors returning replacement objects are refused. An implicit constructor or a bare/`this` return is supported.

Instance own data properties preserve values, order, descriptor flags, aliases/cycles and extensibility. Each declared static field has a `static:Counter.name` root carrying presence, value and descriptor flags, so deletion remains visible. Only the selected frozen prototype receives its declared class tag. Proxies and known native brands such as Date, Map, Set, boxed primitives, promises and typed arrays refuse observation even if their prototypes were changed. Arbitrary native handles/internal slots and undeclared or inherited state remain outside the codec's scope; this is not a native-allocation provenance proof.

Run `make generation-node-receiver-otelc OTELC_ROOT=/absolute/path/to/otelc REPORT_DIR=/private/tmp/new-node-receiver-qualification` for the separate maintained actual-provider corpus. It checks both language IDs, matching/expected-error cases, same-return instance/static mutation controls, generated/exported suites, scalar shrinking and missing/wrong-class/root refusals. Unit parser and observer checks do not establish actual otelc qualification.

## Observation and replay

The observer reads ordinary stored state through builtin metadata. It does not call application getters, `repr`, custom serialisers or dynamic method lookup. Unsupported descriptors/storage and incomplete requested roots prevent qualification. Mutations to declared class data and receiver state can produce differences even when the method returns the same value in both lanes.

The corpus, reports, fixture identity and standalone HTML/JUnit details retain constructor/factory inputs. Generated suites, export and replay reconstruct the receiver independently. Scalar shrinking preserves the fixed construction fixture, its source bindings and required roots, while reducing method arguments; it does not shrink receiver construction inputs or object/action sequences.

Only declared own class data roots and supported stored instance state are observed. Dynamic class attributes outside those declarations, inherited/imported state, application accessors, external effects and unrequested dimensions remain outside the scope. Source/plan/ownership guards continue to apply. The claim remains **equivalence over these tests and observations**, with diagnostic caller evidence kept separate from shipping artefacts.

`make generation-receiver-otelc OTELC_ROOT=/absolute/path/to/otelc REPORT_DIR=/private/tmp/new-receiver-qualification` runs the maintained actual-provider corpus, including instance/static mutation controls, aliases, cycles, expected errors, generated/exported suites, scalar shrinking and refusal controls. Retain each provider/toolchain run before claiming it qualified.

The [exact-revision macOS ARM64 corpus](qualification/receivers-2026-10-20.json) covers five cases, 80 qualified launches plus one refused wrong-class launch, generated/exported suites and shrinking/replay. Three cases match; both deliberate same-return instance/static mutation controls are detected. The initial development corpus remains separate.

The [exact-revision Node corpus](qualification/node-receivers-2026-10-20.json) qualifies both language IDs on macOS ARM64: six cases each, 184 qualified launches and two refused wrong-class launches (186 total). Four cases match per language; both same-return instance/static differences are detected. Generated/exported suites, expected TypeError, awaited completion, alias/cycle checks, shrinking 7 to 0 with fixed construction and missing-factory/root controls pass. The first successful development run remains separately labelled.
