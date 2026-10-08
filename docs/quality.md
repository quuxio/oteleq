# Repository quality and badges

## Current scope

CI validates Markdown, illustrative JSON/TOML syntax and the Rust comparator. The required Rust job runs formatting, Clippy, regression tests and a minimum 80% line-coverage gate over product `src/` files; integration-test code is excluded from that measurement. Passing comparator CI does not qualify language discovery, generation or unobserved application state.

Install the locked documentation tools and run:

```sh
make setup
make check
```

The validation dependencies follow otelc's locked Markdown tooling. `npm ci` disables package lifecycle scripts. GitHub Actions are pinned to the same full action commits as otelc's published workflow. Document prose is kept on logical lines and relative documentation links are checked during delivery.

## README conventions

The README uses the quux brand mark, centred header, concise aim, blue CI/status/licence badges, separator lines and the full usual quality badge set from otelc: quality gate, bugs, code smells, coverage, duplication, lines of code, reliability, security, technical debt, maintainability and vulnerabilities.

All quality-analysis badges currently say **not analysed** and link here. They are explicit design-stage status badges, not SonarQube measurements. A SonarQube project or application quality gate is not provisioned by this design delivery. Replace them with real project badge endpoints only after analysis is configured and its scope is documented. The status badge says **initial comparator**. Quality-analysis badges remain **not analysed**; the Rust coverage gate is not a SonarQube measurement.

## Traffic badge

The traffic workflow updates `.badges/traffic.json` from GitHub's authenticated repository views endpoint hourly and on manual dispatch. It runs only on `main` in `quuxio/oteleq`. Counts cover GitHub's rolling 14-day window; failed API reads fail the workflow and cannot publish a zero-value substitute.

`TRAFFIC_TOKEN` stores the saved quuxio credential, explicitly authorised for persistence in this repository's Actions secrets on 8 October 2026. It is exposed only to the traffic-read step in this workflow. The badge commit uses the separate automatic `GITHUB_TOKEN` with `contents: write`. Actions are pinned to a full commit, and traffic maintenance commits do not rerun documentation CI.

This credential retains its original GitHub permissions; storing it as `TRAFFIC_TOKEN` does not narrow those permissions. Its value is absent from source, badge output and workflow logs. Traffic counts are unrelated to product adoption or behavioural equivalence.

## Implementation quality

The [roadmap](roadmap.md) defines the remaining core and adapter gates. For Homebrew Rust on this Mac, run `make check COVERAGE_ENV='LLVM_COV=/opt/homebrew/opt/llvm@22/bin/llvm-cov LLVM_PROFDATA=/opt/homebrew/opt/llvm@22/bin/llvm-profdata'`; rustup installations instead need the matching `llvm-tools-preview` component and pinned `cargo-llvm-cov` 0.8.7. Meaningful comparator, codec, process-isolation, source-preservation and incomplete-evidence regression tests are required. Publish actual implementation coverage with language/component scope. A shared test corpus must include incorrect instrumentation fixtures that change results, global state, receiver state and effects so the checker demonstrates difference detection.

This repository's maintained implementation uses [AGPL-3.0](../LICENSE). The design calls for an explicit permissive licence for independently authored generated harness boilerplate before implementation release, so incorporating generated tests has a documented licensing boundary. Runner dependencies and target application source retain their own licences; copying application source into a private workspace does not relicense it.
