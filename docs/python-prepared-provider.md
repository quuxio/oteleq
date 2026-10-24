# Rebuilt Python provider integration

Status: metadata negotiation, prepared transport and independent execution/journal/health/OTLP readers are implemented. The explicit origin profile also connects generated synchronous workers to compiler/module execution and selected-source coverage. The [424-launch diagnostic qualification](qualification/python-generated-origins-2026-10-24.json) covers the recorded generated and retained workflows on Python 3.12/3.14. Full-project release qualification remains open. The default Python backend retains its existing qualified legacy behaviour. Prepared selection without the explicit origin profile remains blocked.

## Explicit selection

The project policy can select the new boundary:

```toml
languages = ["python"]

[adapters.python]
backend = "prepared"
profile = "python-native-origins-v2"
import_roots = ["src"]
```

Planning retains each selected callable and probes the complete matching public protocol and capability response. Only the explicit origin profile can reach the generated prepared launcher. Missing capabilities, unsupported callables and the original input-only profile remain visible blockers, with no legacy fallback. Generated and detached strict suites fail blocked callables; an empty runnable corpus cannot become passing equivalence evidence.

## Implemented checks

The consumer probes `otelc.prepared_python.protocols()` once per workspace using the selected interpreter with `-I -S -B`. The complete closed descriptor must match request/plan/prepared/command/execution 1, journal 1 with record kinds 1-4, code descriptor 2 with readable versions `[2]`, health 2, SDK 1 and code comparisons 1. `source_complete` remains false. Site hooks and application imports are absent from this metadata probe.

The full schema-3 policy and public capability response remain separate records. Candidate declarations do not count as implemented support. A provider without an explicit Python implementation or candidate declaration is refused. Capability metadata alone does not establish a qualified execution route.

The installed-input catalogue retains maintained Python/native sources, requirements, the native builder and its maintained `ci/native_encoder.py` and `ci/native_origin_chain.py` dependencies when present, prebuilt native products, actual installed package bytes and literal internal file-link targets. Helper presence inventories bytes; it does not select or qualify an execution profile. The catalogue preserves the selected interpreter's virtual-environment spelling. Bytecode caches are excluded. Missing/unreadable inputs, directory links, escaping file links, special files and count/byte limits cause refusal. Interpreter/OS libraries and general application import closure remain separate gaps.

The independent prepared reader checks caller-owned policy, literal script/argument spelling, environment absence versus empty values, interpreter identity, request and plan hashes, prepared file bytes and the fixed supervisor command. Receipt data cannot select another executable or option. Private metadata requires owned mode-0600 regular files with one completed link inside an owned mode-0700 runtime. Native identities must match the pre-existing frozen product catalogue; this transport check does not independently qualify its compiler recipe or prove code origin.

Provider probes share the plan seal and survive detached export. Revalidation rejects changed probes and backend substitution. A separate attempt guard prevents a direct or edited prepared entry from reaching the legacy launcher.

## Runtime readers

The execution-1 reader checks the consumer's actual supervisor PID, parent PID, fixed argv and exit against the prepared request/plan digests and final process records. Application and SDK identities must remain distinct. SDK spawn/readiness, launch ID, exit and final phase must agree. The consumer constructs its command from independent intent; producer receipts cannot choose an executable.

The journal-1 reader independently checks bounded framing, exact EOF, record order, actual application PID, source bytes/opened-file identity, code IDs, interpreter versions and final capture counts. The descriptor-2 reader validates complete typed graphs, aliases, reachability, cycles, depth and filename/offset consistency as data. It never compiles, unmarshals or executes retained descriptors. These observations do not bind a source read to a compiler result or prove a selected code object's source origin.

For the fixed all-on synchronous workload, the OTLP reader binds both signals to the service, actual application PID and SDK launch. It checks captured VM code IDs, exact function labels, complete local trace trees, exceptions, cumulative call/duration/exception counts and selected-span exemplars. Histogram sums must fit their observed extrema and populated buckets, with binary64 summation/subnormal rounding bounds. Bucket upper boundaries are inclusive; an observation at a boundary cannot move to the next bucket. Retained cumulative extrema cannot contract, and unchanged counts cannot change sums, buckets or extrema. Added sums must fit only the new bucket observations, accounting for both snapshots' rounding and requiring newly expanded extrema to occur among the added values. Exemplar timestamps must be positive and precede their export; the pinned SDK can timestamp its first measurement before lazy aggregation creation. Numeric values and received trace identities remain checked. These are aggregate code observations; they do not provide per-action attribution. See the OpenTelemetry [exemplar data model](https://opentelemetry.io/docs/specs/otel/metrics/data-model/#exemplars).

The health-2 reader reconstructs the public view from the separately retained SDK-1 report and decoded local receipt. Missing counters, loss, unfinished work, failed exports, suppressed collection/emission and inconsistent public summaries refuse qualification. Aggregate flush, downstream receipt and partial rejection remain unavailable. SDK metric-point units remain null; independent collector point counts are reported separately. Plain lanes require no SDK process, health record or OTLP.

## Source-origin and generated execution

### Explicit origin-journal reader

`python_origin.decode(data, actual_application_pid)` independently reads only journal 2 (`OTLCPY2\0`), with closed kinds 1-7. The default runtime reader selects journal 1 and refuses journal 2; only caller-owned explicit origin-profile intent selects the version-2 runtime route. Metadata negotiation and generated execution do not switch formats implicitly. `python_origin.read(path, pid)` additionally requires an owned, bounded, non-followed mode-0600 regular file after its owning process has stopped.

The reader checks consecutive records, exact terminal counts and data-byte totals, actual PID and consistent descriptor/interpreter/filesystem profiles. Each compiler root must reference an earlier source read, with unique root/transaction/read-token identities and a supported entry or ordinary `.py` loader route. Each first-execution identity follows a bounded sequence of direct code-valued `co_consts` edges. Paths and bytecode offsets must agree with that member. Aliased paths cannot give the same root/member a second execution identity.

An SDK join references earlier execution and code records with a one-to-one pairing. Independent subgraph matching preserves exact primitive/float bits, metadata, ordered slots and aliases; frozenset order is ignored. Backtracking retains later outer constraints, so an equal unordered constant cannot hide a contradictory alias. A shared 1,000,000-step allowance bounds every join in one journal; exhaustion refuses the journal. Descriptors remain data: the consumer never compiles, unmarshals or executes retained code.

These checks validate the declared relations' consistency. They do not prove that the producer observed a genuine read, compiler return or selected VM execution. `capture_complete` reports only finalisation and raw loss counters; an empty journal or missing selected join cannot establish selection coverage. Synthetic wire fixtures and exhaustive small-graph permutation oracles test the component, separately from authentic producer qualification.

### Selected-source coverage component

`python_selection.freeze(path)` retains bounded canonical source bytes and opened-file facts before launch. `verify` takes those caller-owned facts, the selected ordinary function or declared plain receiver method's qualified name and source line, the selected interpreter version and optimisation level, and an independently decoded journal. Expected selection never comes from producer receipts.

Every selected callable needs a compiler-root/source-read relation and an actual first execution of its exact declared descendant. Source bytes, device/inode, modification time and mode must match the frozen input. The ordinary compiler profile fixes input flags to zero and checks the declared optimisation level. Repeated compilations retain separate root/execution identities; these are not invocation counts. Empty, read-only and unexecuted captures cannot satisfy selection coverage.

The plain lane refuses SDK code records or joins. The instrumented lane requires an SDK code join for every selected execution and accounts for every captured SDK code ID. These checks preserve missing coverage as a refusal. They do not establish per-action attribution or complete dependency closure. The module is embedded and sealed with the generator, with an independent 80% line floor. Producer, reader and actual generated-workflow qualification remain separate evidence.

### Runtime admission

The explicit metadata/runtime route selects `profile = "python-native-origins-v2"` alongside `backend = "prepared"`. Its closed format descriptor fixes request/plan/prepared/command/execution 2, journal 2 kinds 1-7, descriptor 2, health 2 and SDK 1. It requires `code_comparisons = null`, since the SDK's separate post-run comparison API does not accept this journal. The original profile, cache and command spelling remain unchanged by default.

The consumer derives the native `--origin-loader-root` argument from the canonical application root. It recomputes raw source/code/origin summaries, requires the native entry's compiler root and module execution, checks every compiler root stays inside that root, and accounts for SDK code joins independently. Plain lanes refuse SDK records and telemetry. The declared optimisation environment accepts absent, empty or literal `0`, `1`, `2` values; other spellings refuse the origin profile before launch. Neither format negotiation nor a complete producer summary replaces selected-source execution checks.

An actual qualified source profile requires selected-source origin evidence in **both baseline and instrumented lanes**, from the same SDK-independent observer. The plain lane must have no SDK telemetry. Exact input/read transactions, compiler or loader return objects, selected descendants and instrumented VM/telemetry code IDs need independent binding. Equal code descriptors alone cannot establish source origin.

### Generated worker boundary

`python_launch.py` uses one fixed isolated public-API bootstrap for preparation and independently constructs the SDK supervisor command. A separate fixed interpreter probe observes the selected launcher's native `argv0`; Homebrew framework spelling must not be guessed from the virtual-environment path. Preparation cannot change the frozen SDK products, installed inputs or selected application bytes/file facts.

Before launch, the consumer freezes the target's source, qualified name and line, plus any declared existing source constructor or factory. Both lanes must execute those exact source descendants. The instrumented policy includes the target and source creation function; SDK code IDs must all join that declared selection. A default builtin constructor supplies no source callable and is not invented as source evidence.

Each attempt retains the actual supervisor PID and fixed argv, caller PID, application PID and separate SDK identity. After execution, source facts, launch records, native journals, typed observations, application channels and declared effects are rechecked. Instrumented attempts decode both OTLP signals, require the requested number of independent serial target roots and one source creation root where declared, and check final SDK health directly. Recursive span totals remain separate from the number of requested calls. No legacy runtime report is synthesised.

The [exact-revision diagnostic record](qualification/python-generated-origins-2026-10-24.json) checks 424 actual application launches, 212 SDK processes and 108 independently recomputed comparisons across the two recorded runtimes. Current-origin capture covers the native script entry and ordinary source loaders inside the application root. Application cache-only loads, unsupported loaders, complete dependency closure, broader async/resource actions, live metric controls, per-action attribution and shipping qualification remain open. Missing origin, loss or truncation is a refusal. The full [completion checklist](completion.md) remains in scope.

## Reproduce generated workflow qualification

Use an independent SDK copy with matching prebuilt native origin products and a pinned, complete SDK Python environment. The command covers generated execution, fixed receiver constructors/factories, exceptions, recursion, a deliberate same-return mutation, replay, retained unittest, detached export and scalar reduction. A second corpus adds generated scalar domains, globals, complete filesystem bytes/kinds/permissions and scripted HTTP, plus current-source promotion through unchanged bodies, changed bodies and an added function. It compares complete raw and typed state/effect graphs against independently declared fixture oracles.

```sh
make generation-python-origins-otelc \
  PYTHON=/absolute/path/to/qualified-sdk-python \
  OTELC_ROOT=/absolute/path/to/independent-prebuilt-otelc-copy \
  REPORT_DIR=/absolute/path/to/new-report
```

The qualifier also supports `--recheck` with the same CLI, interpreter and provider. This rechecks retained source, process, journal, telemetry, health and comparison evidence without new application launches; a separate metadata-only interpreter probe observes the actual launcher spelling. Retained JSON comparison normalises object keys while preserving boolean/integer distinctions. Copied original shrink observations retain their original process identity and do not increase launch counts. The [integrated exact-revision record](qualification/python-generated-origins-2026-10-24.json) records 80 reports and 432 raw/typed observations; eight copied original shrink observations do not add launches. Promotion audits bind every historical plan and complete private snapshot to its independently declared stage body, then check the restored original source. The earlier failed combined audits remain preserved. Broader capabilities and full-project release qualification remain open.

## Reproduce metadata qualification

Use a new independent copy of the recorded otelc source and the selected installed SDK Python. Preparation may build native tools in that copy. Do not point this command at a live or frozen shared provider.

```sh
make python-provider-metadata-otelc \
  PYTHON=/absolute/path/to/qualified-sdk-python \
  OTELC_ROOT=/absolute/path/to/independent-otelc-copy \
  REPORT_DIR=/absolute/path/to/new-report
```

The command retains actual prepare-only responses for both lanes, validates them against independent intent, refuses altered commands/plans/lanes, and checks that the application body did not run or change. It also checks real CLI inventory accounting, blocked generated/detached suites and probe preservation. These are metadata and refusal checks. They do not qualify execution or shipping artefacts.

## Reproduce fixed-workload runtime qualification

Use a new independent source-only SDK copy for each selected interpreter. The command builds native products during preparation, then freezes those products, maintained inputs and actual installed package bytes before application execution. Do not reuse a live or frozen shared provider, or modify its source/products while a run is active.

```sh
make python-provider-runtime-otelc \
  PYTHON=/absolute/path/to/qualified-sdk-python \
  OTELC_ROOT=/absolute/path/to/independent-otelc-copy \
  REPORT_DIR=/absolute/path/to/new-report
```

It runs ordinary, recursive and handled-exception fixtures twice in each lane: twelve actual applications and six SDK processes. Every attempt has fresh application files, receiver/global/static state and runtime records. Complete binary stdout/stderr and the fixture's declared state summary must match independent literal expectations. This fixed application oracle does not qualify generated object observers. The command records the caller PID before launch, retains actual owner/application/SDK identities, raw journals and OTLP bodies, HTTP responses and input catalogues, and refuses altered actual evidence. Source and installed-input preservation are checked after every lane and at the end.

The output explicitly retains `source_profile_status = "blocked"` and `source_origin = "unavailable"`. It qualifies transport and pipeline accounting for those workloads. Generated suites, source-origin admission, live metric schedules, async/resource actions, compiler recipe closure and shipping artefacts need their own evidence.

To exercise the explicit origin readers against an owned matching SDK copy, add `PYTHON_PROFILE=python-native-origins-v2` to that command. It additionally freezes source bytes/opened-file facts before every application launch, checks the declared workload's compiler/first-execution/SDK relations in both lanes, and refuses changed source facts, unexecuted names and wrong lane roles. A successful origin run reports `fixed-selected-workloads-qualified`; generated suites, broader callables, live controls and per-action attribution still need their own qualification. A failed or partial run remains failed evidence.
