# Retained Java compiler bindings

Generated Java attempts compile their private application and caller through the selected JDK's public `JavaCompiler` API. A fixed file manager records each emitted binary class name, class-file path and originating source. Nested, anonymous and implicitly compiled source classes retain their actual compiler origin; class basenames and `SourceFile` attributes do not establish that binding.

## Select the JDK

Use a complete JDK 21, including `lib/modules`. On macOS, select its actual executable rather than the `/usr/bin/java` system launcher:

```sh
export OTELC_JAVA=/absolute/path/to/jdk/bin/java
export OTELC_JAVAC=/absolute/path/to/jdk/bin/javac
```

The plan freezes the Java and javac executable contents and the selected JDK module image. The compiler frontend and observer are embedded in the oteleq executable. Changed tool, module-image, source or generated-suite identities require a new plan.

## Build profile

The standalone fixed profile uses UTF-8, `-proc:none`, `-implicit:class`, the private source root as its compilation classpath and a new separate class-output directory. The frontend itself runs with an empty isolated classpath, so application classes cannot replace its compiler APIs. Compilation does not initialise application classes.

Each source's exact characters read by the compiler are hashed as UTF-8 and checked against the frozen source bytes, preserving CRLF and non-ASCII text. Every emitted class needs exactly one recorded source origin and a matching class-file hash. Missing, duplicate, changed or unrecorded outputs fail the build contract. Source, compiler inputs, class products and retained metadata are checked again after application execution.

Explicit [source/dependency context](java-project-context.md) adds a separately fixed compilation recipe with declared source roots and ordered private JAR/class/resource inputs. Compiler metadata schema 2 also records the URI and byte hash of every actual classpath class read. Source origins, generated driver identity and output checks remain required.

Annotation processors, arbitrary compiler flags, module-path builds and custom classloaders remain outside these profiles. This does not provide general Java build-system integration. The JDK module image is covered by a content hash; native JDK/OS libraries are not comprehensively hashed. These are trusted local diagnostic builds, with no protection against malicious change-and-revert activity.

## Retained attempt records

Each successful compilation retains the following outside the private application source:

| Record | Contents |
| --- | --- |
| `build/stdout`, `build/stderr` | Raw compiler metadata and diagnostics |
| `compiler-tool/OteleqCompile.java` | Exact frontend used for this compilation |
| `java-compiler.json` | Compiler version, fixed options, source reads and class origins |
| `java-compiler-identity.json` | Actual launch arguments and Java/module/frontend content hashes |
| `scratch/classes/` | Actual compiled application, observer and caller classes |
| `prepared-application.json` | Schema-1 main class, classpath and source/class bindings |
| `build-identities.json` | Complete private source/product inventories and retained metadata hashes |

The prepared manifest follows the replacement otelc SDK's published Java input format. Its public loader was first checked separately against an immutable SDK source revision without starting an application JVM. The optional [prepared provider](java-prepared-provider.md) now uses that manifest through ordinary generated paired execution, with independent argv, loaded-origin, PID and direct health/OTLP checks. The default Java backend retains the pre-rebuild provider contract. Live-control sequences and invocation-scoped attribution remain open.

## Validation

`make check` includes real JDK regressions for nested/anonymous classes, implicit source discovery, exact UTF-8/CRLF reads, source preservation, application initialisation isolation and changed-input/product refusal controls. `java_build.py` has an independent 80% Python line floor. `make java-observer-check` separately measures the compiled observer and compiler frontend, each with an 80% line floor. Checksum-pinned JaCoCo is confined to those regression probes and is absent from actual otelc qualification.

`make generation-java-receiver-otelc` rechecks compiler bindings and every retained class product alongside its complete independent state/result oracles, generated/exported suites, replay and scalar reduction. Its exact-revision qualification is separate from ordinary compiler regressions and does not qualify another SDK or platform.

The file-manager hooks are documented in the [JDK 21 API](https://docs.oracle.com/en/java/javase/21/docs/api/java.compiler/javax/tools/ForwardingJavaFileManager.html). Both output methods are covered by the compiled probes; the newer method must not record an output a second time through the older override.

## Published qualification

The [21 October record](qualification/java-compiler-2026-10-21.json) names runtime `8843816`, its frozen executable and the unchanged pre-rebuild provider `d6d03b7` on macOS ARM64/JDK 21. Its eight-case corpus completes 151 actual application launches: six matching cases, two deliberate same-return state differences, seven refusal controls, generated/exported suites, per-case replay and scalar shrinking from seven to zero. All 155 retained manifests and 467 retained class bindings are checked independently; four copied original shrink attempts are counted once.

The frozen replacement SDK `760a526` separately accepts all 151 unique manifests and 455 class bindings through its public `PreparedApplication.load` interface. Four altered-manifest controls are refused. All 7,360 legacy-provider records and 55 frozen replacement-SDK source files remain unchanged. This loader check starts no application JVM and does not qualify generic replacement-SDK execution.
