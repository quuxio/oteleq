# Planning after retaining tests in an application

An explicitly exported oteleq bundle can live in a new application subdirectory. A later `plan` treats a verified bundle as retained diagnostic output and excludes its snapshot, generated callers and tests from application discovery and copying. This prevents recursive snapshots, duplicate Java units and helper functions appearing as new application targets.

## Verification and reporting

A marker alone cannot hide source. The planner checks the ownership/schema and plan identity, complete frozen snapshot, generated-suite manifest and any native context, Java context or prepared-provider probes. It performs these checks without running the old CLI, original application or external toolchain. A valid older frozen bundle therefore remains separate from new application inputs.

[Current-source suites](current-source-tests.md) have a separate owned kind. Their six-file layout, exact known runner/licence/instructions, content hashes and validated frozen policy must match. They contain no copied application source. A valid suite is excluded as generated output; unknown, edited, linked or extra contents stop planning. Source and report records distinguish these exclusions from frozen workspaces.

An edited snapshot or test, missing seal, changed context, unknown top-level entry or linked top-level entry stops planning. The bundle is retained for inspection. Remove it from the selected application or restore its exact original contents before creating another plan. Ordinary source exclusions still apply; an explicitly selected Java generated-source root receives the same bundle checks even under a normally excluded build directory.

`plan.json` records `owned_source_exclusions`: each relative path, workspace ID when available, plan digest and reason. `report.json` records the exclusions actually verified for its source tree at execution. HTML source/policy details and JUnit properties present those exclusions without adding tests, skipped cases or passing coverage. Adding or removing a valid retained bundle does not change the application-source identity; every execution rechecks current bundles and application bytes. Editing an ordinary application file still invalidates the plan.

Export moves the original exclusion list into `original_owned_source_exclusions` and starts the detached snapshot's exclusion list empty. Its copied snapshot contains only application inputs. Replay, generated suites and scalar reduction retain their usual frozen source/tool requirements. Existing bundles continue using their own qualified CLI.

## Explicit build inputs and ownership

Java source-root enumeration and the ordinary snapshot use the same excluded roots. An explicit Java source root, internal classpath entry or native compiler input inside a retained bundle is an error: it cannot be silently removed from a requested build. Select the actual application source or dependency instead.

`runs/` and `go-cache/` remain reserved tool-owned output within a verified workspace, as in the cleanup contract. They are excluded with that bundle and can be removed by `clean`. Keep user code and other unrelated files outside those reserved directories. The planner does not certify the authenticity of a self-resealed plan or inspect every generated run/cache entry as application code.

The result remains **equivalence over these tests and observations**. This selection fix does not add broader build-system, language, shipping-artefact or instrumentation capabilities.

## Qualify the workflow

With a qualified legacy provider and its language tools, run:

```sh
make generation-retained-source-otelc \
  PYTHON=/absolute/path/to/otelc/.venv/bin/python \
  OTELC_ROOT=/absolute/path/to/otelc \
  REPORT_DIR=/absolute/path/to/new-retention-proof
```

The maintained corpus uses eight language IDs, fixed scalar arguments and complete independently declared before/outcome/after graphs. It checks replanning after in-source export, an explicit Java source-root context, generated suites, a second retained bundle, detached runs with original source unavailable, visible report exclusions and prelaunch refusal controls. Unit regressions separately cover explicit native inputs, generated Java roots, missing contexts, source changes and cleanup preservation.

The [22 October qualification](qualification/retained-source-2026-10-22.json) completes 136 actual application launches against frozen legacy provider `d6d03b7`. Eight source files and eight selected ready functions remain unchanged after retention. Four invalid-bundle controls stop planning; all direct/generated/detached routes and two replays pass complete literal graph and instrumentation checks. The public record distinguishes runtime `f5515ac` from the corrected qualifier `2204d43`; their application runtime code is identical. All 7,360 recorded provider inputs and eight external tools remain unchanged. Full local validation passes 752 distinct regressions, with 99% line coverage for owned-workspace validation; the rendered HTML and JUnit scope/counts were checked separately.

If the qualification stops after its first direct and generated-suite routes, the maintainer script accepts `--resume` with the same paths and CLI. It revalidates both retained routes and frozen source/provider/tool identities before proceeding. Later partial routes are refused and retained for inspection. This option does not restart an active run or change the application's public CLI.
