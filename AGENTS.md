# Repository guidance

- If `~/.agents/AGENTS.md` exists, read it and follow the relevant guidance.
- Rust `compare-workload` compares repeated byte channels. The embedded scalar generator implements plan/generate/run/replay/export-tests/clean with AST inventories for all eight languages, private paired execution and explicit blockers. Full semantic/build-aware adapters and the broader configuration/graph protocol remain proposed. Keep actual capabilities and design interfaces distinct.
- Use the `quuxio` GitHub account and credentials for all remote operations. Verify the API identity before each operation. Never use `stephenlclarke` credentials. Use `/opt/homebrew/bin/gh` directly on Stephen's Mac because other wrappers may override explicitly supplied credentials.
- The intended implementation uses a Rust core and language-specific adapters. Cover all eight current otelc language IDs: `c`, `cpp`, `rust`, `python`, `java`, `javascript`, `typescript`, `go`.
- Preserve application and dependency sources, build manifests and lockfiles. Generate tests, access helpers and private build copies in a new directory outside the target repository. Copying tests into the repository is an explicit user choice.
- Account for every discovered function. Missing fixtures, unsupported constructs, incomplete state observation and unverified instrumentation are visible results, never successful skipped tests.
- Describe outcomes as "equivalence over these tests and observations". Include test corpus, observation scope, source/build identity and gaps. Unit harness evidence is not evidence for a different shipping artefact.
- Run `make check` for documentation changes. Application implementation must add meaningful checks described in `docs/roadmap.md` and keep every affected document current.
