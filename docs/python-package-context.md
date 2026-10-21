# Python package context

The scalar generator can import regular Python source packages under their real module names. This opt-in policy supports relative imports, package initialisers and source layouts such as `src/pkg/api.py`. It preserves the original source tree and installs no application dependencies.

```toml
schema_version = 1
languages = ["python"]

[adapters.python]
import_roots = ["src"]

[functions]
include = ["src.pkg.api.selected"]

[[fixtures]]
function = "src.pkg.api.selected"
cases = [[7]]
```

Use `import_roots = ["."]` when the package directory is directly inside the selected source root. Paths must be distinct, canonical and relative to that source root. The configured order controls import resolution. Each selected file must match exactly one import root. Parent directories must be regular packages with `__init__.py`; ambiguous roots, shadowed modules, invalid module names and namespace packages remain visible blockers.

Declared receiver constructors and factories retain these same import checks. A construction fixture cannot clear an invalid package context or select the standalone loader as a fallback.

```sh
quux-oteleq plan --source /absolute/path/to/project \
  --otelc-root /absolute/path/to/otelc \
  --workspace-parent /private/tmp/oteleq \
  --config /absolute/path/to/equivalence.toml
quux-oteleq generate --workspace /absolute/path/printed/by/plan
quux-oteleq run --workspace /absolute/path/printed/by/plan \
  --report-dir /private/tmp/new-package-report
```

The report directory and workspace parent must already satisfy the normal [workspace rules](automatic-generation.md). The generated driver places the private copied import roots on `sys.path`, checks the resolved module origin, imports the selected module, then verifies its source function identity before invoking it. Qualified function IDs continue to use source-relative paths, including `src` and `__init__`; import module names use the configured roots. Import resolution cannot silently replace the selected source with another module.

An empty import-root list retains the standalone file loader. Every changed policy or generator revision requires a new plan. Source snapshots, local dependency files, plan identities, private source guards and generated-suite ownership checks continue to apply. Exported suites retain the frozen import context and private source copy.

`make generation-python-project-otelc OTELC_ROOT=/absolute/path/to/otelc REPORT_DIR=/private/tmp/new-python-project-qualification` runs the maintained real-provider qualification for regular and `src` layouts, relative/absolute imports, package initialisers, module-local mutation, generated and exported suites, independent value oracles and changed-local-dependency refusal controls. Unit regressions are included in `make check`, with a separate 80% coverage floor for the import-context module. The [exact-revision macOS ARM64 corpus](qualification/python-package-2026-10-20.json) covers four cases, 48 actual launches and two changed-dependency refusal controls. Qualification of another provider/toolchain requires retaining that actual run's results.

## Scope and limits

The observed state is the selected module's declared roots and input-reachable values. Package initialisation and imported helpers execute as application code; their independent module globals are outside the observation unless separately supported and declared. Business preconditions, arbitrary receivers/factories, package managers, editable installations, build backends, namespace packages, extension modules, dependency installation and general `pyproject.toml` interpretation remain open. Already installed external dependencies and interpreter/sysroot files are outside the application source identity.

The result remains **equivalence over these tests and observations**. A generated package caller does not qualify a shipping application artefact.
