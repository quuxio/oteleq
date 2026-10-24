# Audit locked repository dependencies

`make dependency-audit` checks `Cargo.lock`, `ci/requirements.txt` and `ci/markdownlint/package-lock.json` against current OSV advisories. It downloads the pinned [OSV-Scanner 2.7.0 release](https://github.com/google/osv-scanner/releases/tag/v2.7.0), verifies the selected platform SHA-256 before execution, and retains the raw result, command, scanner identity, input facts and summary in a new `build/dependency-audit/scan-*` directory.

```sh
make dependency-audit PYTHON=/path/to/python3
```

Python 3.12 or newer and network access to the pinned GitHub release and OSV service are required. macOS and Linux tool downloads have separately pinned AMD64/ARM64 identities. The scanner runs without application execution or call-analysis filtering. Python manifest resolution is disabled: the repository's complete pinned validation requirements are checked directly; Cargo and npm transitive versions come from their lockfiles.

## Acceptance and evidence

The runner derives its expected package inventories independently from all three files. Every source and package/version must appear in scanner output. Missing files, empty or partial inventories, changed input bytes/file facts, malformed results, tool errors and timeouts fail the command. The initial implementation was exercised against 25 Cargo, 3 Python and 75 npm package/version records; each future run records its own counts.

An empty explicit scanner configuration prevents repository-local advisory exclusions from hiding findings. Any reported advisory fails the audit. `0` means the complete scan found no known advisories, `1` means advisories were found, and `2` means the audit could not establish a complete result. A failed or interrupted scan keeps its available command/output files for inspection.

This checks the stated repository dependency inventories and the advisory data returned at that time. It does not establish that all vulnerabilities are known, or scan arbitrary target applications, external SDK installations, compilers or operating-system packages. The [supported inventory documentation](https://google.github.io/osv-scanner/supported-languages-and-lockfiles/) explains the upstream manifest/lockfile distinction.

## CI and maintenance

The required documentation CI job runs the online audit for every pull request and main push. A separate weekly/manual workflow checks current main even when its source has not changed. Both retain raw audit evidence for seven days. Dependabot proposes weekly updates for Cargo, pinned Python validation requirements, npm tooling and GitHub Actions; normal review and protected checks apply.

`make check` runs the offline runner regressions and its independent 80% coverage floor through `make dependency-audit-check`. Network advisory queries remain a separate `make dependency-audit` command and CI step. Tests reject missing sources/packages, wrong versions, invalid advisory/exit relationships, changed files and unverified downloads.

To update the scanner, review its upstream release, update `VERSION` and all four platform digests in `ci/dependency_audit.py`, then run the offline checks and a real online scan. The cached executable is verified on every run. A different cached digest is an error; inspect the named file before replacing it.
