# oteleq documentation

This is the application design, dated 8 October 2026. The executable names, commands, protocols and configuration below are proposed interfaces; they do not run yet.

| Document | Use it to |
| --- | --- |
| [System design](design.md) | Understand the Rust core, isolated execution and evidence boundary |
| [Languages](languages.md) | See discovery, generation, build integration and limits for all eight languages |
| [Test generation](test-generation.md) | Understand automatic inputs, fixtures, sequences and optional incorporation |
| [Observations](observations.md) | Understand return values, errors, global/object mutations and side effects |
| [CLI and configuration](cli-and-configuration.md) | Review the proposed workflow, example policy and adapter protocol |
| [Delivery roadmap](roadmap.md) | See implementation stages and acceptance requirements |
| [Repository quality](quality.md) | Run document checks and interpret badges |

The language requirement follows otelc's published [language list](https://github.com/quuxio/otelc/blob/3d5b2d7c9167d9cc6fb1be876a05f83a9d6c6e5a/docs/languages.md) and [schema-2 policy](https://github.com/quuxio/otelc/blob/3d5b2d7c9167d9cc6fb1be876a05f83a9d6c6e5a/docs/common-configuration.md). That reference is a design baseline, not a compatibility claim for future releases.
