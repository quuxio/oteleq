# Native lifetime telemetry receipt

<!-- markdownlint-disable MD013 -->

Status: maintainer components for independently checking recorded C++ object and C resource telemetry. Public generated lifetime selection and the complete retained/replayed/promoted workflow still require integration. The [provider components](native-lifetime-provider.md) supply the separately checked builds, owned processes and final health.

## Caller expectations before execution

`native_lifetime_intent.freeze` publishes a new private expectation record while the accepted SDK runtime contains only its three preparation records. The output file must be external to application sources, build products, SDK inputs/products and the runtime. Existing files, aliases, changed original facts and late publication refuse.

Each expected observation declares:

- The source type USR and name obtained from the caller's independently frozen compiler facts.
- The selected serial call path containing creation, and the path containing release when completion is expected.
- Whether shutdown must censor the observation.
- The explicit destructor exception-exit flag for completed C++ observations.

The root index is zero-based. Further path indices identify selected nested calls in their observed serial order. Missing paths, overlapping/ambiguous siblings, excessive depth and incomplete call trees refuse. These paths have the declared synchronous diagnostic scope; general action/thread attribution requires its separate protocol.

The test contract supplies expected counts and outcomes before launch. SDK inventories or observed telemetry cannot become a replacement oracle. The source catalogue must contain the declared type, and its exported name must identify one source USR. Ambiguous names refuse because the current SDK's span/metric labels cannot distinguish those source identities.

The frozen `Intent` retains the original preparation and expectation file identities. Its dictionaries are decoded as fresh primitive values; the expected observations and paths are immutable tuples. Records cannot be rewritten or rehashed to recertify another test.

## Complete trace receipt

`native_lifetime_receipt.witness` requires the same accepted owned launch and final execution. It decodes every raw trace and metric body under bounded routes, resources, SDK identity and instrumentation scopes. Duplicate span/instance identities, foreign records, missing signals and incomplete final units refuse.

Function spans retain the existing complete selected call-tree checks. A lifetime span is a separate root with an exact link to the function active at creation. Each instance must match its declared admission ordinal, source type name, creation link and time boundary. Completed observations end at the declared destructor/free entry. Shutdown-censored observations retain that distinct label and follow completion of the selected calls. Garbage collection is a separate observation kind and is not inferred from either boundary.

The reader retains the original raw-body hash, caller record identity, source USR, call paths, span identities, duration and completion/censoring result. Typed bool fields remain distinct from string identities. Dropped attributes/events/links, extra events, altered link metadata and undeclared instance counts refuse.

## Metric and health accounting

All function instruments and the five lifetime instruments are consumed: admitted, completed, incomplete, duration and live. Every cumulative sample and live-gauge sample is retained. Counter resets, duplicate timestamps, invalid wire types, unknown labels/instruments, wrong units/temporality, impossible histogram ranges and decreasing cumulative histogram state refuse.

Final lifetime histogram counts, buckets and extrema match the durations encoded by the raw lifetime spans. Nanosecond counts convert to binary64 before division, matching the SDK's C++ `chrono::duration<double>` arithmetic, including durations above `2**53` nanoseconds. Sums use a bounded binary64 accumulation error because completion/export ordering can differ. This cross-checks the two SDK encodings; independent measurement of real constructor/release timing remains a separate concern. Live samples are bounded by the declared admissions and finish at zero; precise per-sample event timing is outside this component's scope.

Final SDK function/lifetime counters, sampled spans, downstream trace units and metric points must match the complete receipt. Completed and censored totals remain separate. Fixed startup collection/emission states are checked against the original policy. Live control changes require independent checkpoints and separate qualification.

## Development evidence

A frozen uncommitted development snapshot on macOS ARM64 uses genuine SDK `6475be4`, LLVM 22.1.8 and an explicitly selected coverage-enabled diagnostic SDK recipe. Four actual applications cover plain/on C++ construction/destruction and plain/on C allocation/free. The caller records precede application release. Each SDK lane yields one completed instance, two spans and twelve points, with creation links, release boundaries, span-derived durations and final units checked by the new reader. All 630 consumer files, 503 provider files and both SDK product facts remain unchanged during that window.

An earlier attempt refused the SDK recipe before any application because caller coverage selection was missing. That failed attempt remains separate. The passing development snapshot is distinct from exact-revision or public generated-suite qualification.

A separate direct SDK callback probe at `6475be4` also exposed C++ object-completion `errno` leakage. The four ordinary application fixtures do not exercise that callback scenario. Functional/state equivalence and SDK transparency require their own paired observations and defect controls; valid telemetry/health accounting alone does not establish them.

## Run the component checks

```sh
make native-lifetime-receipt-check PYTHON=/absolute/path/to/python
```

The target runs literal protobuf/prelaunch/health substitution controls and the existing function telemetry regressions. It enforces 80% statement coverage separately for caller intent, lifetime metrics, lifetime receipt and shared function telemetry. The full generation gate has the same per-module floors. The modules are embedded in the Rust distribution and included in generator identity.

The [completion checklist](completion.md) still requires independent frontend pipeline integration, generated and retained workflows, actual startup/live schedules, source preservation, review, final checks and published execution evidence. Shipping artefacts and broader platform/performance qualification retain separate acceptance evidence.
