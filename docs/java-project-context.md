# Java source roots and dependencies

Declare existing Java source roots and an ordered classpath in the equivalence policy. oteleq freezes the dependency bytes and compiles all Java units under those roots in each independent private attempt. The original application, JARs, class directories, build manifests and lockfiles remain unchanged.

```toml
schema_version = 1
languages = ["java"]

[adapters.java]
backend = "prepared"
profile = "safe-methods-v1"
source_roots = ["src/main/java", "target/generated-sources/example"]
classpath = [
  "/absolute/dependencies/library.jar",
  "target/dependency-classes",
  "src/main/resources",
]
```

Run the ordinary [planning and generation commands](automatic-generation.md#build-and-run) with `--config /absolute/path/to/equivalence.toml`. Prepare generated sources and dependency products before planning. oteleq does not invoke Maven or Gradle, resolve dependencies, run annotation processors or write build products into the application.

## Inputs and isolation

Source roots are literal paths relative to `--source`; they cannot leave that repository. Explicit roots can retain generated Java source under otherwise excluded directories such as `target`. Empty declared roots are preserved. All units in the declared roots are compiled together, including helpers that are excluded as test targets. A selected callable outside those roots is a visible blocker.

Classpath entries are existing JARs or class/resource directories. Relative entries resolve against `--source`; absolute entries can refer to an existing dependency cache. Order is preserved. Duplicate resolved locations or class definitions are refused. Wildcards, path-list separators, implicit JAR `Class-Path` attributes, JAR indexes and multi-release layouts are refused. JARs retain their complete original bytes; they are never flattened or repacked.

The workspace owns `java-context/`, containing the frozen dependency copies and `context.json`. Each attempt receives separate copies under `java-classpath/`. Resource files and empty dependency directories are retained. Changes to original dependencies, frozen context, private copies or metadata invalidate the relevant checks. An exported suite carries its context and can run without the original application or dependency locations. It still requires the frozen CLI, SDK and language tools.

Workspace parents, report directories, export destinations and reduction outputs must stay outside declared dependency inputs. The check runs before creating those outputs. A dependency cannot contain the owned workspace; copying it would recurse into its own output.

Declared internal JARs are retained in the dependency context rather than duplicated into the source snapshot. The source identity includes both source and context contents. Source files keep the ordinary 8 MiB per-file, 10,000-file and 256 MiB snapshot budgets. Dependency inputs have separate limits: 128 MiB per regular file, 16 MiB per class definition and 512 MiB for combined input bytes. Directory inventories and the complete context have bounded entry counts; expanded JAR contents are also bounded at 512 MiB. Oversized inputs fail rather than becoming partial captures.

## Compiler and runtime evidence

The [fixed JDK frontend](java-build-bundles.md) uses UTF-8, disabled annotation processing, the declared private source path and the explicit private dependency classpath. An empty dependency list uses an owned empty directory, avoiding javac's implicit working-directory classpath. All generated driver files remain diagnostic helpers in both lanes.

Context builds emit compiler metadata schema 2. It adds actual classpath class reads, including the JAR/file URI and the SHA-256 of the bytes read. Every classpath read must match its frozen catalogue. Source reads, compiler-owned output origins and output bytes retain the existing checks. Source products cannot duplicate a dependency class. Standalone builds without these settings keep compiler metadata schema 1 and their original fixed recipe.

Runtime classpaths contain the compiled application first, followed by the declared private dependency copies. The runner fixes this recipe independently of SDK metadata. Loaded application and catalogued dependency classes must have the expected origins, with no duplicate loaded identity for those names. Prepared launch evidence includes every dependency resource file or complete JAR alongside the source/class bindings. `java-build-context.json` and its digest remain with each attempt.

## Observation scope and current limits

The claim remains **equivalence over these tests and observations**. Compiling a sibling source or loading a dependency does not add its globals to the selected method's observation scope. Existing scalar and declared receiver codecs retain their own limits. Private diagnostic callers do not qualify a different shipping artefact.

Named Java modules, module-path builds, multi-release JARs, arbitrary compiler/JVM flags, annotation processing, Maven/Gradle build execution and custom classloader qualification remain open. SDK/runtime compatibility requires actual-provider qualification; passing compiler regressions alone is insufficient.

`make check` covers real JDK compilation, actual JAR/directory class reads, generated source roots, resource loading, loaded origins, large internal JARs, detached context, source/dependency mutation controls and guarded cleanup. `java_project.py` and `java_classpath.py` each have an 80% line-coverage floor. Prepared-provider capability probes are sealed, exported and checked before cleanup, including when the original application is unavailable.
