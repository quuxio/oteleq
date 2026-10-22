# Java runtime archive integration

## Current status

The independent consumer resolver and its regression checks are implemented. Generated project workflows still refuse versioned JAR layouts. The replacement SDK launch-schema-2 integration and exact-provider qualification are in progress; this component alone does not enable multi-release JAR support or invocation-scoped attribution.

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

`make check` runs the real JDK matrix and enforces separate 80% line-coverage floors for `java_archives.py` and the compiled `OteleqArchives` resolver. JaCoCo is confined to regression probes; application/provider qualification uses ordinary JVMs.

Before generated workflows can accept this profile, integrate the frozen SDK's public launcher, compiler/runtime catalogues and exact tooling record. Qualify direct, generated, replay, detached export and scalar reduction routes, loaded origins, source/resource preservation, same-process metric controls and their refusal controls against the actual provider. Shipping artefacts, custom classloaders, application changes to JDK selection properties and general Maven/Gradle/module integration remain outside this component.

The result remains **equivalence over these tests and observations**.
