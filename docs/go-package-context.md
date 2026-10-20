# Go module and package context

Use explicit module roots when selected Go functions need their real package, sibling files or imports:

```toml
schema_version = 1
languages = ["go"]

[adapters.go]
module_roots = [".", "services/api"]
build_tags = ["integration"]

[functions]
include = ["internal.counter.api.selected", "services.api.cmd.api.selected"]

[[fixtures]]
source = "internal/counter/api.go"
function = "*.selected"
cases = [[7]]
```

Paths are canonical POSIX paths relative to `--source`. Each selected source must have its nearest `go.mod` inside the immutable snapshot and that module root must be configured. Nested modules are explicit. Empty `module_roots` retains standalone file mode; build tags require module mode. `build_tags` defaults to an empty list. Both discovery and compilation receive the same frozen tag list. Module mode disables ambient Go workspace and user Go environment configuration; it does not apply a source `go.work`.

## What is tested

The selected Go compiler runs `go list -deps -export -json -mod=readonly` to determine the active package files and actual compiler export data. The inventory type checks those files together, without running application initialisers. Source function parameters keep their declared syntax and resolve supported named/alias scalar types to concrete input domains. The generated caller casts its concrete primitive inputs to those declared types. Reflected observations retain the actual named type labels and exact floating point bits.

A library package gets a reserved exported diagnostic bridge appended to the selected file in the private copy. A generated `main` imports the real library path and invokes that bridge. This permits legal access to private functions and package variables while retaining lexical import aliases, sibling files, internal-package access and real dependency resolution. The original source tree receives no helper or test file.

A `main` package builds its actual directory with active siblings. The private caller replaces the original entrypoint even when that entrypoint is in a different file. Resolved calls/references to the original `main` keep that original function; local variables with the same name retain their own bindings. Attempts run from their private module root, recorded in `working-directory.json`. Package initialisers still run as application code in each lane; they do not execute during inventory or compilation. Helpers change the diagnostic build's callable set, so this is not shipping artefact qualification.

All supported scalar variables from the active selected package become before/after roots, including inferred and named types declared in sibling files. Blank `_` bindings are not stored roots. Imported packages' independent globals and initialiser side effects are outside those state roots; stdout/stderr and termination remain separately observed. Rich objects, mutable argument graphs and effect capture need further codecs and contracts.

Go function selection in the user policy remains relative to the repository source root. The frozen entry also records `otelc_runtime_function`, relative to its module root, because the provider uses its build working directory for function names. The generated provider policy, typed observation contract and witness require that exact runtime name. Report labels retain the repository identity; the presenter validates its binding to the module root. Retained raw telemetry is unchanged.

## Boundaries and evidence

Inactive host/tag files and `_test.go` callables remain visible with explicit blockers if selected. Package initialisers have distinct `init@filename:line` identities and require startup fixtures; `init` is not directly callable. Methods retain their receiver-qualified identities but require receiver fixtures. Generics, variadic/complex inputs and unsupported state remain blockers. Context failures retain the file's syntactic callable inventory where parsing is possible.

Source workspaces, project cgo/assembly/SWIG, local replacements escaping the snapshot and reserved helper/path collisions are refused. In-snapshot local replacements can participate in ordinary module resolution. The provider's original/resolved module, language and runtime-default preservation guards still apply; an incompatible SDK graph refuses rather than changing the application's language version. SDK dependency isolation, general build recipes, cross compilation and test-package execution remain open.

Every attempt uses the [retained Go build/replay contract](go-build-bundles.md), including actual binaries, separate compiler channels, selected compiler/tools, loaded source/dependency hashes, module graphs and exact on-lane telemetry. Required active package files and any generated importing worker must appear in the compiler's input manifest. Per-attempt project paths are excluded from the external dependency fingerprint across repeats; the complete private source/harness identities are retained separately.

```sh
make generation-go-project-otelc \
  OTELC_ROOT=/absolute/path/to/qualified/otelc \
  REPORT_DIR=/private/tmp/new-go-project-qualification
```

The maintained corpus exercises libraries, a nested module, an internal package, an in-snapshot replacement, named scalar imports, sibling state/entrypoints, explicit tags, an expected panic, negative zero and a same-return mutation control. It also runs generated/exported suites and scalar shrinking/replay. Actual runs and exact revisions are separate evidence from plain-worker regressions. The conclusion remains **equivalence over these tests and observations**.

The [exact-revision macOS ARM64 record](qualification/go-packages-2026-10-20.json) qualifies runtime `5c18f1b` against frozen provider `5ea90fa`: six cases, five matches, one deliberate same-return state difference and 112 actual launches. Generated/exported suites, shrinking from `7` to `0`, fresh confirmation/replay, three changed-source refusals, raw byte and exact selected-span controls pass. The initial driver stopped after 108 launches because its checker assumed copied evidence had a new build origin; a regression fixes that assumption, all 108 retained launches were revalidated and the final four replay launches completed with unchanged runtime code. Both driver logs remain retained.
