# Java runtime archive integration

## Current status

The explicit prepared `archive-methods-v1` profile integrates the independent consumer resolver into generated project workflows. Its [304-JVM qualification](qualification/java-archives-2026-10-22.json) uses frozen consumer runtime `646857c` and SDK `c06eb43`, with complete independent state/outcome checks, compiler/runtime member identities, decoded telemetry and source preservation. It requires that matching runtime-archive contract and helper tool. The original `stock-methods-v1` and `safe-methods-v1` recipes retain their existing behaviour and refuse versioned layouts. Invocation-scoped attribution remains open.

## Select the profile

```toml
[adapters.java]
backend = "prepared"
profile = "archive-methods-v1"
source_roots = ["src/main/java", "target/generated-sources"]
classpath = ["lib/library.jar", "build/dependency-classes"]
```

Source roots default to `["."]` and the classpath defaults to empty for this profile. It accepts at most 255 explicit dependency entries, leaving one slot for compiled application output. JARs keep their complete original bytes and resources. Ordered directories and JARs are copied independently into each attempt. Planning binds the actual selected JDK and effective dependency catalogue; every attempt repeats independent JDK resolution before SDK preparation and verifies it again after execution. Export carries the private dependencies and original probe records. Changed source, tools, catalogues or dependency bytes require a new plan.

The matching provider must supply `adapters/java/target/java-extension-0.2.0-SNAPSHOT-helper-tool.jar` in addition to the corrected extension, official agent and pinned bootstrap parser patch. The profile explicitly disables task and HTTP instrumentation in its schema-3 policy. If application classes collide with active SDK helper namespaces, the consumer independently derives the mapping and reproduces the pinned helper transformation before checking the SDK's private extension, properties and descriptor. Application classes and dependencies are preserved.

The resolver follows the selected JDK's `JarFile` runtime APIs without loading application classes. It records the actual effective ZIP member name and SHA-256, the complete original archive hash, the JDK feature and the archive's position in the full ordered classpath. Ordinary, inactive, false, active, intermediate, future, versioned-only, folded-manifest and identical-byte fixtures have direct regression coverage. Package metadata remains visible; module metadata is excluded from ordinary class definitions. The tests compare selected class bytes with independently constructed fixture classes and actual plain-JVM method/resource outcomes.

## Compiler reads and runtime selection

Compiler evidence retains its literal JAR URI and the digest of the bytes read. The physical member catalogue is separate from effective runtime classes. Both readings can be valid when the compiler and runtime select different members.

On the characterised OpenJDK 21, a folded `Multi-Release: tr` value with a continuation line containing a space followed by `ue` parses as the attribute value `true`, while `JarFile.isMultiRelease()` is false. The ordinary JVM uses the base member, while javac and feature-matched javap can use a versioned member. The consumer delegates selection to the actual chosen JDK; it does not implement another manifest/version algorithm in Python or infer a unique entry from its hash.

Metadata inspection uses deterministic ordinary JARs containing unmodified copies of exactly the selected class members under their logical names. This preserves case-distinct and Unicode-distinct class names on case-insensitive or normalising filesystems, where directory extraction can silently overwrite one class with another. These private JARs are for inspection only. Application launches must retain their original ordered JAR/directory classpath and resource bytes. Tests check each distinct class through javap, verify byte-for-byte repeatability and confirm that application initialisers have not executed. Identical bytes in base and versioned members do not permit a different claimed member identity.

## Producer/consumer contract

The agreed new prepared profile keeps the 16 launch fields. Every JAR-containing prepared classpath uses launch schema 2, including ordinary JARs. Directory-only launches retain schema 1. The schema-2 `application` adds exactly `archive_resolution` to its existing six fields. Old frozen providers and their schema-1 records retain their original meaning.

`archive_resolution` has exactly `schema_version = 1`, `profile = "java-runtime-archives-v1"`, integer `jdk_feature` and ordered `archives`. Each archive has exactly `classpath_index`, canonical `path`, complete-file `sha256`, boolean `multi_release` and `classes`. The index is zero-based in the full launch classpath, including the compiled output and intervening directories. Each effective binary class maps to exactly its real `entry` and `sha256`.

The new provider must bind its resolver helper-tool identity in both plain and instrumented launches containing a JAR. Instrumented schema-2 launches also bind the actual javap executable from the same selected full JDK. Consumer verification compares the producer's complete claim with an independent selected-JDK result. Missing/extra archives, fields, classes, changed bytes, incorrect JDK features and different entry identities cannot pass. The consumer receipt retains its exact JDK/resolver input set, fixed command and original probe result; removing a tool hash or changing that local evidence cannot weaken verification. Duplicate definitions, implicit manifest Class-Path/index expansion, unsafe/duplicate ZIP entries and changed resolver inputs are refused. Ambient Java option variables and explicit multi-release selection property overrides are outside this profile.

## Checks and remaining work

The corpus covers eleven archive variants through direct, fixed replay, generated and exported suites. A second detached run removes both original source and external dependency directories. It also covers same-return global mutation, scalar reduction from `[7]` to `[0]`, independently reproduced real helper relocation, 48 private receiver JVMs with four live metric states, ordinary private receiver compatibility and 13 input/evidence controls. All 112 frozen provider files and 25 owned workspaces are revalidated after execution. Copied original shrink evidence is retained separately and does not inflate the 304 actual JVMs.

`make check` runs the real JDK matrix and enforces separate 80% line-coverage floors for `java_archives.py` and the compiled `OteleqArchives` resolver. JaCoCo is confined to regression probes; application/provider qualification uses ordinary JVMs.

`make generation-java-archive-otelc OTELC_ROOT=/absolute/provider REPORT_DIR=/new/report` runs the maintained fixed JDK21 corpus against the actual provider. It checks direct, generated, replay and detached-export routes, complete independently specified scalar graphs, literal compiler reads, runtime members and loaded origins. Active and identical-member evidence controls reject altered member identities even when the class bytes are equal. The corpus also covers scalar reduction and same-process metric states. This target requires the matching qualified provider and ordinary JDK21 tools; its actual result remains separate from the component regressions.

Shipping artefacts, custom classloaders, application changes to JDK selection properties and general Maven/Gradle/module integration remain outside this profile.

The result remains **equivalence over these tests and observations**.
