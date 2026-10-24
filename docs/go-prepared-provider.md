# Rebuilt Go provider integration

Status: independent public-protocol and health readers are implemented. Generated preparation, compiler-selected source/build checks, owned launch integration and actual-provider workflow qualification remain in progress. These components do not admit the rebuilt provider through the scalar generator. The existing [retained Go build/replay profile](go-build-bundles.md) remains a separate recorded contract.

## Explicit protocol boundary

The reader accepts the published `go-source-v1` descriptor: build 2; request, plan, prepared, command and execution 1; health 3; embedded SDK; `source_complete = false`. Missing or additional fields, another profile, substituted versions and numeric/boolean coercions are refused. Metadata cannot select an older combined compiler/launcher or qualify source closure.

The application and SDK share one native Go PID. The prepared supervisor has a separate PID. The complete consumer must bind both to its actual owned process group and fixed build/launch recipe before accepting runtime evidence. Receiving a valid descriptor alone cannot establish that relation.

## Independent health reader

`go_health.read(runtime)` reads a completed `health.json` only from an owned canonical mode-0700 directory. The report must be an owned mode-0600 bounded regular file with one link. Links, FIFOs, replaced files, changed bytes/file facts, oversized reports and duplicate JSON keys are refused. The reader does not import the provider or execute retained code.

`validate` binds the closed schema-3 report to caller-owned application PID, policy digest and compiler selection digest. The reader retains the complete raw controls, lifecycle, probe, exporter and unavailable-delivery fields. A running snapshot is not assumed to be atomic or quiescent.

`qualify` separately requires a final successful flush/shutdown, closed clean probes, exact independently counted function/auxiliary completions, no active or lost observations and matching decoded trace/metric batch receipt. Trace span totals and queue loss/pending counts are checked separately. Metric point totals are not available from the SDK exporter record: the reader retains independent received points and leaves the SDK point total explicitly unavailable.

Observed GC, successful resource release, pending objects and unreleased resources remain distinct counters. A clean SDK drain does not invent a GC or release boundary for a censored object. An unobserved trace exporter supplies no fabricated zero queue counters. The SDK's downstream and partial-rejection fields remain unavailable; actual receipt belongs to the independent receiver.

## Component checks and remaining work

```sh
PYTHONPATH=tests python -m unittest -v test_generation_go_health
```

The maintained literal wire fixtures cover protocol substitutions, wrong process/policy/selection, missing and unknown fields, exact unsigned counters, live/final separation, censored lifetimes, unavailable trace observation, failed exports/drains, receiver disagreements and private-file races. Both modules are embedded with the generator and have independent 80% line-coverage floors.

Next connect preparation and public protocol probes, independently checked compiler/build inputs, owned execution and decoded OTLP to generated/replayed/framework/detached/reduced/promoted workflows. Existing receiver/package support, live metric schedules, source/dependency preservation and refusal controls require qualification against the new provider. Broader Go builds, cgo/workspaces, asynchronous/resource actions, shipping artefacts and the [full completion checklist](completion.md) remain open.

The intended result remains **equivalence over these tests and observations**.
