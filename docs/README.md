# oteleq documentation

As of 9 October 2026, `quux-oteleq compare-workload` runs the Rust comparator, with diagnostic capture integrations for all eight otelc languages. [Automatic scalar test generation](automatic-generation.md) now inventories and executes supported functions across all eight languages in private workspaces. Broader semantic/build-aware and graph protocols remain proposed interfaces.

| Document | Use it to |
| --- | --- |
| [Automatic generation](automatic-generation.md) | Generate, run, replay and retain the implemented scalar suite |
| [Workload comparison](workload-comparison.md) | Run the implemented comparator and capture the actual otelc task example |
| [Usefulness and adoption](adoption.md) | Assess current value, remaining adoption gaps and measured comparator optimisations |
| [Eight-language capture](eight-language-capture.md) | Compare ordinary and instrumented C, C++, Rust, Python, Java, JavaScript, TypeScript and Go workloads |
| [System design](design.md) | Understand the Rust core, isolated execution and evidence boundary |
| [Languages](languages.md) | See discovery, generation, build integration and limits for all eight languages |
| [Test generation](test-generation.md) | Understand automatic inputs, fixtures, sequences and optional incorporation |
| [Observations](observations.md) | Understand return values, errors, global/object mutations and side effects |
| [CLI and configuration](cli-and-configuration.md) | Look up current commands/flags and distinguish proposed policy/adapter interfaces |
| [Delivery roadmap](roadmap.md) | See implementation stages and acceptance requirements |
| [Repository quality](quality.md) | Set up pinned checks, inspect published qualification and interpret badges |

The language requirement follows otelc's published [language list](https://github.com/quuxio/otelc/blob/3d5b2d7c9167d9cc6fb1be876a05f83a9d6c6e5a/docs/languages.md) and [schema-2 policy](https://github.com/quuxio/otelc/blob/3d5b2d7c9167d9cc6fb1be876a05f83a9d6c6e5a/docs/common-configuration.md). That reference is a design baseline, not a compatibility claim for future releases.
