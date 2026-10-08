<p align="center">
  <img src="docs/assets/quux-mark.png" width="160" alt="quux">
</p>

# oteleq

**Behavioural equivalence evidence for instrumented applications. A [quux](https://quux.io) project.**

[![CI](https://github.com/quuxio/oteleq/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/quuxio/oteleq/actions/workflows/ci.yml)
[![Status](https://img.shields.io/badge/status-initial%20comparator-blue)](docs/roadmap.md)
[![License](https://img.shields.io/badge/license-AGPL--3.0-blue)](LICENSE)

---

[![Quality Gate Status](https://img.shields.io/badge/quality%20gate-not%20analysed-lightgrey)](docs/quality.md)
[![Bugs](https://img.shields.io/badge/bugs-not%20analysed-lightgrey)](docs/quality.md)
[![Code Smells](https://img.shields.io/badge/code%20smells-not%20analysed-lightgrey)](docs/quality.md)
[![Coverage](https://img.shields.io/badge/coverage-not%20analysed-lightgrey)](docs/quality.md)
[![Duplicated Lines (%)](https://img.shields.io/badge/duplication-not%20analysed-lightgrey)](docs/quality.md)
[![Lines of Code](https://img.shields.io/badge/lines%20of%20code-not%20analysed-lightgrey)](docs/quality.md)
[![Reliability Rating](https://img.shields.io/badge/reliability-not%20analysed-lightgrey)](docs/quality.md)
[![Security Rating](https://img.shields.io/badge/security-not%20analysed-lightgrey)](docs/quality.md)
[![Technical Debt](https://img.shields.io/badge/technical%20debt-not%20analysed-lightgrey)](docs/quality.md)
[![Maintainability Rating](https://img.shields.io/badge/maintainability-not%20analysed-lightgrey)](docs/quality.md)
[![Vulnerabilities](https://img.shields.io/badge/vulnerabilities-not%20analysed-lightgrey)](docs/quality.md)
[![Repo Traffic](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fquuxio%2Foteleq%2Fmain%2F.badges%2Ftraffic.json&cacheSeconds=3600)](https://github.com/quuxio/oteleq)

---

oteleq aims to generate tests that compare application behaviour with and without [otelc](https://github.com/quuxio/otelc) instrumentation across C, C++, Rust, Python, Java, JavaScript, TypeScript and Go. It compares results, errors, observable global and instance state, and declared side effects, while accounting for emitted OpenTelemetry telemetry separately.

The result is **equivalence over these tests and observations**. It is not a blanket proof that every function is identical.

Tests are generated in a separate transient directory. Users can retain them or choose to incorporate them into their application repository, using a framework that may differ from the application's existing tests.

**Status: an initial Rust workload comparator is implemented; full language adapters and automatic test generation remain planned.** Start with [running the comparator and the otelc task example](docs/workload-comparison.md). Read the [design](docs/design.md), [language plan](docs/languages.md) and [delivery roadmap](docs/roadmap.md), or start with the [documentation index](docs/README.md).
