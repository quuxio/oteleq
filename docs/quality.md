# Repository quality and badges

## Current scope

CI validates Markdown and the syntax of illustrative JSON/TOML artefacts. This is a design repository; there is no product implementation to exercise or measure. Passing documentation CI is not application test evidence.

Install the locked documentation tools and run:

```sh
make setup
make check
```

The validation dependencies follow otelc's locked Markdown tooling. `npm ci` disables package lifecycle scripts. GitHub Actions are pinned to the same full action commits as otelc's published workflow. Document prose is kept on logical lines and relative documentation links are checked during delivery.

## README conventions

The README uses the quux brand mark, centred header, concise aim, blue CI/status/licence badges, separator lines and the full usual quality badge set from otelc: quality gate, bugs, code smells, coverage, duplication, lines of code, reliability, security, technical debt, maintainability and vulnerabilities.

All quality-analysis badges currently say **not analysed** and link here. They are explicit design-stage status badges, not SonarQube measurements. A SonarQube project or application quality gate is not provisioned by this design delivery. Replace them with real project badge endpoints only after analysis is configured and its scope is documented. The status badge stays **design** until an executable exists.

## Traffic badge

The traffic badge is a dated snapshot of GitHub's authenticated repository views endpoint, published in `.badges/traffic.json`. It is initialised during this delivery using the verified quuxio identity. An unsuccessful API read cannot publish a zero-value substitute. The date in the badge identifies the snapshot; counts cover GitHub's rolling 14-day window at that time.

Refresh the snapshot through an authorised quuxio API read when needed. No account credential is stored in GitHub Actions and no traffic-refresh workflow is configured. Automated refresh would require a separately authorised token with suitably limited repository/traffic scope. Traffic counts are unrelated to product adoption or behavioural equivalence.

## Implementation quality

The [roadmap](roadmap.md) defines the future core and adapter gates. Meaningful comparator, codec, process-isolation, source-preservation and incomplete-evidence regression tests are required. Publish actual implementation coverage with language/component scope. A shared test corpus must include incorrect instrumentation fixtures that change results, global state, receiver state and effects so the checker demonstrates difference detection.

This repository's maintained implementation uses [AGPL-3.0](../LICENSE). The design calls for an explicit permissive licence for independently authored generated harness boilerplate before implementation release, so incorporating generated tests has a documented licensing boundary. Runner dependencies and target application source retain their own licences; copying application source into a private workspace does not relicense it.
