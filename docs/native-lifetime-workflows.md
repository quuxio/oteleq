# Hosted native lifetime workflow checks

<!-- markdownlint-disable MD013 -->

Status: a maintained genuine-workflow development driver and hosted job. No passing hosted execution is claimed yet. The separate [public profiles](native-lifetime-generation.md) have literal component evidence; this job must build and execute their actual SDK/application path before it can add runtime evidence.

## Run in one original environment

The `Native lifetime workflow qualification` GitHub Actions workflow uses Ubuntu 24.04, LLVM 22, Python 3.12 and Rust 1.98.1. It checks out the exact consumer revision and reviewed otelc source `acb13d7735526448209df37b7e6b98e5717befdb`, which includes the object/ABI errno correction and both native lifetime ABIs. It builds a new noncoverage shared SDK and the consumer in the same job. Existing build manifests are neither copied nor rebound to another path or filesystem identity.

The workflow starts for changes to its own definition or driver and supports manual dispatch after it is available on main. It uses read-only repository permission, disables persisted checkout credentials and passes no account secrets to SDK or application processes. LLVM installation reuses the pinned SDK's verified-key installation script, with matching Clang frontend tools. SDK and application commands retain their original output and failures. Qualification commands require the configured 8 GiB free-space floor before starting.

To run the driver in a suitable original Linux environment:

```sh
python tests/qualify_native_lifetimes.py \
  --otelc-root /absolute/reviewed-otelc-checkout \
  --sdk-build /absolute/new-native-sdk \
  --report-dir /absolute/new-lifetime-evidence \
  --cli /absolute/quux-oteleq
```

Both output directories must be new and outside application/tool source inputs. The driver verifies the SDK source commit, snapshots tracked consumer/provider source facts, builds the shared library without coverage and freezes both SDK products. The generated tests remain in external transient workspaces.

## Corpus and acceptance boundary

Three ordinary fixtures cover C resource completion, C++ object completion and a C same-return/global-state difference. Each call creates and releases one `Item`, changes a declared scalar global and exposes the application errno after the lifetime operation. The independent application oracle checks the exact return value, initial/final global graphs, integer representation, errno, clean application channels and every repeat. Equal but invalid outcomes refuse.

The driver exercises generated execution, the generated framework, replay and detached exported suites. The intentional state difference also exercises scalar reduction, the preserved original report, every trial/confirmation and the reduced framework. Copied reports join the original four-launch record; they are not counted as new launches. Original application launch identifiers, evidence bytes/file facts and SDK/source facts remain held through the final audit.

`qualification.json` explicitly labels a successful result as genuine public workflow development. The consumer independently checks the SDK's complete lifetime/function receipt; this driver also checks its literal completed-instance, canonical function witness and final SDK units. An additional independent complete raw lifetime audit and altered-evidence corpus remain required before broader admission. Current-source promotion, zero/censored/exception profiles, all startup/live states, production artefacts and the wider completion checklist remain open.

## Evidence and component tests

The workflow retains original evidence, SDK build logs/products and exact source archives for seven days, including failed runs. Artifact names include both run and attempt IDs. A missing success summary or failed job remains incomplete evidence. Downloaded archives do not acquire the original job's filesystem identities and cannot silently recertify its products.

```sh
make native-lifetime-workflow-check PYTHON=/absolute/path/to/python
```

These component tests use literal records and mocked orchestration, enforce an 80% statement floor and start no SDK/compiler/application workload. Required documentation CI includes this gate. Workflow syntax controls separately pin the reviewed source, read-only permission, original-job build and failure retention.
