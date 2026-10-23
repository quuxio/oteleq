# Rebuilt Python provider integration

Status: metadata negotiation and prepared-transport validation are implemented. Generated execution through the rebuilt Python provider remains blocked. The default Python backend retains its existing qualified legacy behaviour.

## Explicit selection

The project policy can select the new boundary:

```toml
languages = ["python"]

[adapters.python]
backend = "prepared"
import_roots = ["src"]
```

Planning retains each selected callable and records why execution is unavailable. It does not fall back to the legacy backend. Generated and detached strict suites fail blocked callables; an empty runnable corpus cannot become passing equivalence evidence.

## Implemented checks

The consumer probes `otelc.prepared_python.protocols()` once per workspace using the selected interpreter with `-I -S -B`. The complete closed descriptor must match request/plan/prepared/command/execution 1, journal 1 with record kinds 1-4, code descriptor 2 with readable versions `[2]`, health 2, SDK 1 and code comparisons 1. `source_complete` remains false. Site hooks and application imports are absent from this metadata probe.

The full schema-3 policy and public capability response remain separate records. Candidate declarations do not count as implemented support. A provider without an explicit Python implementation or candidate declaration is refused. The frozen `209b60c` provider advertises only JavaScript/TypeScript candidates; its prepare-only Python API remains useful for checking transport independently.

The installed-input catalogue retains maintained Python/native sources, requirements, prebuilt native products, actual installed package bytes and literal internal file-link targets. It preserves the selected interpreter's virtual-environment spelling. Bytecode caches are excluded. Missing/unreadable inputs, directory links, escaping file links, special files and count/byte limits cause refusal. Interpreter/OS libraries and general application import closure remain separate gaps.

The independent prepared reader checks caller-owned policy, literal script/argument spelling, environment absence versus empty values, interpreter identity, request and plan hashes, prepared file bytes and the fixed supervisor command. Receipt data cannot select another executable or option. Private metadata requires owned mode-0600 regular files with one completed link inside an owned mode-0700 runtime. Native identities must match the pre-existing frozen product catalogue; this transport check does not independently qualify its compiler recipe or prove code origin.

Provider probes share the plan seal and survive detached export. Revalidation rejects changed probes and backend substitution. A separate attempt guard prevents a direct or edited prepared entry from reaching the legacy launcher.

## Remaining admission requirements

An actual qualified source profile requires selected-source origin evidence in **both baseline and instrumented lanes**, from the same SDK-independent observer. The plain lane must have no SDK telemetry. Exact input/read transactions, compiler or loader return objects, selected descendants and instrumented VM/telemetry code IDs need independent binding. Equal code descriptors alone cannot establish source origin.

The new versioned origin journal, independent native recipe checks, actual process/final-health readers, decoded telemetry witness and generated execution qualification remain in progress. Missing origin, loss, truncation, unsupported loaders or unavailable per-action attribution must stay visible. The full [completion checklist](completion.md) remains in scope.

## Reproduce metadata qualification

Use a new independent copy of the recorded otelc source and the selected installed SDK Python. Preparation may build native tools in that copy. Do not point this command at a live or frozen shared provider.

```sh
make python-provider-metadata-otelc \
  PYTHON=/absolute/path/to/qualified-sdk-python \
  OTELC_ROOT=/absolute/path/to/independent-otelc-copy \
  REPORT_DIR=/absolute/path/to/new-report
```

The command retains actual prepare-only responses for both lanes, validates them against independent intent, refuses altered commands/plans/lanes, and checks that the application body did not run or change. It also checks real CLI inventory accounting, blocked generated/detached suites and probe preservation. These are metadata and refusal checks. They do not qualify execution or shipping artefacts.
