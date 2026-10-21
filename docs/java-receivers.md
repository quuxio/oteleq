# Java receiver fixtures

Declare an existing constructor or same-class static factory to test an ordinary Java instance method. Each attempt constructs independently and captures the receiver, scalar method arguments, declared own-static roots and return or exception observation. This supports **equivalence over these tests and observations**. The generated reflection helper is a diagnostic access change; it does not qualify a shipping artefact.

```java
class Counter {
    private int value;
    private static int total;
    Counter self = this;
    Counter(int start) { value = start; }
    Counter add(int amount) {
        value += amount;
        total += amount;
        return this;
    }
}
```

```toml
schema_version = 1
languages = ["java"]

[functions]
include = ["Counter.add(int)"]

[[fixtures]]
function = "Counter.add(int)"
cases = [[7]]
receiver = { factory = "Counter", arguments = [10] }
domains = [{ kind = "integer", minimum = 0, maximum = 7 }]
```

Use the normal `plan --config`, `generate`, `run`, per-case `replay` and `export-tests` commands. Export first produces a dry-run plan; `--apply` writes into a new external directory. Constructor inputs remain fixed when scalar method arguments are reduced. Select a unique existing same-class static factory by its method name, for example `receiver = { factory = "make", arguments = [10] }`. Private constructors, factories, methods and fields can use declared reflection access when the JVM permits it. Overloaded constructors/factories require another fixture profile; the adapter does not guess a declaration.

## Observation contract

The frozen source declaration binds field names, types and modifiers. Private field reads use reflection; capture does not call application getters, equality, hashing or formatting methods. Bootstrap wrapper and String values retain reference identity separately from their primitive payloads. Source instances and arrays preserve aliases and cycles, including returned receiver and array aliases. Primitive widths, signs, floating-point bits and UTF-16 string units remain exact within the supported runtime representation. Identity is local to each boundary; replacements that preserve the same graph and aliases can remain unobserved. Cross-boundary allocation identity remains open.

Required context roots are `receiver`, one `argument:N` per scalar method argument, and `static:Class.field` for every declared static field of the receiver class. All three boundaries retain them. Return graphs add `result`; exception graphs add `error`. Missing roots, extra/missing fields, opaque classes, invalid reference types, malformed values and exceeded bounds refuse capture. The limits are 64 source classes, 256 declared fields per class, 512 graph nodes, 32 reference levels, 4,096 array elements and 256 KiB encoded per graph.

The [closed Java exception list](automatic-generation.md#selection-and-inputs) records exact exception class and message only. Causes, suppressed exceptions, stack traces and other exception internals are unobserved. Custom exception classes and non-Exception throwables require another codec. Construction failures are incomplete fixture evidence and cannot count as matching target exceptions. Failure reporting discards application causes to avoid calling their formatters.

## Scope and qualification

The current profile uses JDK 21 and ordinary concrete top-level source classes extending `Object`, without implemented interfaces, generic class parameters, inherited storage, records, enums or native methods. Fields can contain supported primitives, bootstrap wrappers/strings, plain source instances and bounded arrays. Statics on another source class require an explicit initialisation fixture and remain blocked. Mutable argument factories, constructor targets as separate actions, Java sequences, external classpaths, modules and general project/dependency integration remain open. No additional module-opening flags are inferred.

Discovery parses source with annotation processing disabled and explicit JDK API imports. Application classpath names cannot replace those inventory APIs. The existing instrumentation witness remains name-bound; the proposed invocation-scoped producer API is unavailable. This fixture does not upgrade that witness claim.

`make java-observer-check` measures the actual compiled observer and [compiler frontend](java-build-bundles.md), enforcing 80% line coverage for each. `make setup` installs checksum-pinned [JaCoCo 0.8.15](https://www.jacoco.org/jacoco/trunk/doc/changes.html); the coverage agent is confined to regression probes. Real otelc qualification runs without JaCoCo.

`make generation-java-receiver-otelc OTELC_ROOT=/absolute/frozen/otelc REPORT_DIR=/new/external/evidence` exercises private constructor/factory access, instance/static mutation controls, arrays, cycles, returned aliases, strings, void and expected exceptions through run, per-case replay and generated/exported unittest suites. The [exact-revision corpus](qualification/java-receivers-2026-10-20.json) completes eight cases and 151 actual launches on runtime `5ada5d5`: six matching cases, two deliberate same-return state differences, scalar shrinking from 7 to 0 and seven fixture/source/snapshot refusal controls. Its 155 retained attempt folders include four copied original shrink attempts; those copies are counted once. Independent checks revalidate 31 qualified reports, three failed-fixture reports, two blocked reports, all 3,279 raw files and original source preservation. The frozen provider remains `0419a51`; this does not qualify a later producer version or another platform.
