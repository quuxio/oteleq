# Repository quality and badges

## Current scope

CI validates Markdown, illustrative JSON/TOML syntax, diagnostic capture observers and the Rust comparator. The required Rust job runs formatting, Clippy, regression tests and a minimum 80% line-coverage gate over product `src/` files; integration-test code is excluded from that measurement. The documentation job tests the capture observers and enforces at least 80% line coverage separately for each new eight-language capture module. CI uses fake witness fixtures and private subprocesses; actual otelc toolchain qualification uses the separate eight-language integration run. CI also checks the scalar generator, syntax discovery, harness materialisation, state observers, process limits and source preservation, with 80% coverage gates on each Python module. Real otelc execution is qualified separately; unobserved state and unsupported build contexts remain outside the claim.

Install the locked documentation tools and run:

```sh
rustup toolchain install 1.98.1 --profile minimal \
  --component rustfmt --component clippy --component llvm-tools-preview
rustup run 1.98.1 cargo install cargo-llvm-cov --version 0.8.7 --locked
make setup
python3 -m venv .venv
.venv/bin/python -m pip install --only-binary=:all: coverage==7.16.2
rustup run 1.98.1 make check PYTHON=.venv/bin/python
```

Use Python 3.12+ and Node 24/npm for these contributor tools. Rust 1.98.1 and matching LLVM tools are pinned in CI. A newer compiler may build the application, but its coverage instrumentation requires matching LLVM tools; do not assume Homebrew's current Rust is compatible with LLVM 22.

The validation dependencies follow otelc's locked Markdown tooling. `npm ci` disables package lifecycle scripts. GitHub Actions are pinned to full action commits. Document prose is kept on logical lines and relative documentation links are checked during delivery. `make lint examples` checks Markdown and illustrative syntax; `make docs-check` also runs observer/generation regressions, while `make check` includes Rust checks and coverage.

## Published qualification

The implementation baseline is [`e02915f`](https://github.com/quuxio/oteleq/commit/e02915f65f191544e03ad9280e1a9fe5fc95d3fc), verified on 9 October 2026. Its [main CI run](https://github.com/quuxio/oteleq/actions/runs/37940456205) passed. The local complete gate passed 91 regressions: 18 Rust, 55 capture and 18 generation tests, with 96.87% Rust product line coverage and every gated Python module above 80%. SonarCloud reported zero unresolved issues without suppressions. These figures belong to that recorded revision; the live CI and quality badges show subsequent analyses.

[Generation qualification](https://github.com/quuxio/oteleq/pull/9) exercised 24 matching scalar cases/96 launches across all eight languages, eight generated framework cases, exported replay and three same-return/different-object-state controls. The final path-guard implementation was separately rerun through all eight languages and a mutation control. Sources remained unchanged. These runs qualify the maintained macOS ARM64 fixtures, rather than arbitrary repositories or Linux/Windows execution.

Additional fixed corpora qualified [Java executor context](https://github.com/quuxio/oteleq/pull/10) and [native/classic TypeScript](https://github.com/quuxio/oteleq/pull/12#issuecomment-6082963291). The latter was repeated against frozen otelc `a7605b725219d573cd4ab53f035682194bc08e68`, with all 22 provider hashes unchanged. Each TypeScript backend matched two baseline/two instrumented runs, exact application channels, 11 spans, 5 roots, 1 escaping error and complete zero-loss export. Provider revisions and observation scope appear in [eight-language capture](eight-language-capture.md).

## README conventions

The README uses the quux brand mark, centred header, concise aim, blue CI/status/licence badges, separator lines and the full usual quality badge set from otelc: quality gate, bugs, code smells, coverage, duplication, lines of code, reliability, security, technical debt, maintainability and vulnerabilities.

SonarCloud automatic analysis is active for [`quuxio_oteleq`](https://sonarcloud.io/summary/new_code?id=quuxio_oteleq). The verified main analysis on 9 October 2026 indexed Python and YAML. Supported measures, including the computed quality gate, use live project badge endpoints. Automatic analysis does not ingest our Rust/Python coverage reports, so the coverage badge says **not reported**. These are separate from the required CI coverage gates; a quality-gate pass does not establish whole-product coverage or behavioural equivalence. The status badge says **scalar test generation**.

The review fixed the CI dependency-install finding by requiring a wheel for the pinned coverage tool and simplified reported validation/test complexity. [PR #8](https://github.com/quuxio/oteleq/pull/8) closed the native executable-selection finding: fixed defaults or explicit tool overrides select the compiler, and metadata only verifies its canonical directory as text. Metadata cannot select code to execute or initiate filesystem queries. [Generation and capture reviews](#published-qualification) also resolved their scanner findings without suppressions and qualified Java launch alignment, backend identity and both path-argument forms. Trusted local application execution remains the declared boundary; content identities and private copies do not contain malicious target code.

## Traffic badge

The traffic workflow runs from `main` in `quuxio/oteleq`, but checks out and updates `.badges/traffic.json` on the separate `traffic-badges` branch hourly and on manual dispatch. The README reads that branch's badge data. This keeps generated traffic commits outside protected application source. Counts cover GitHub's rolling 14-day window; failed API reads fail the workflow and cannot publish a zero-value substitute.

`TRAFFIC_TOKEN` stores the saved quuxio credential, explicitly authorised for persistence in this repository's Actions secrets on 8 October 2026. It is exposed only to the traffic-read step in this workflow. The badge commit uses the separate automatic `GITHUB_TOKEN` with `contents: write`. Actions are pinned to a full commit, and traffic maintenance commits do not rerun documentation CI.

This credential retains its original GitHub permissions; storing it as `TRAFFIC_TOKEN` does not narrow those permissions. Its value is absent from source, badge output and workflow logs. Traffic counts are unrelated to product adoption or behavioural equivalence.

## Main branch protection

The active `Protect main` repository ruleset blocks deletion and force pushes, requires pull requests, and requires current passing documentation/design, Rust comparator/coverage and SonarCloud checks from their configured GitHub Apps. There are no bypass actors. Pull requests must be up to date with main before merging; no second human approval is required for this personal repository. The separate `traffic-badges` data branch allows the existing badge updater to publish without bypassing main protection.

## Implementation quality

The [roadmap](roadmap.md) defines the remaining core and adapter gates. Use the pinned rustup workflow above for reproducible coverage. A qualified non-rustup distribution can supply matching `LLVM_COV` and `LLVM_PROFDATA` paths through `COVERAGE_ENV`; verify that their LLVM version matches that compiler's instrumentation. Meaningful comparator, codec, process-isolation, source-preservation and incomplete-evidence regression tests are required. Publish actual implementation coverage with language/component scope. Extend the shared defect corpus with changed results, globals, receivers and effects as each observation capability is delivered.

This repository's maintained implementation uses [AGPL-3.0](../LICENSE). Generated harness boilerplate now carries the [MIT licence](../adapters/generation/GENERATED-LICENSE.txt), so incorporating it has a documented licensing boundary. Runner dependencies and target application source retain their own licences; copying application source into a private workspace does not relicense it.
