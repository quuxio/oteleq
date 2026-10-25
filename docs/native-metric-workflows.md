# Native metric workflow qualification

The [experimental native control profile](native-metric-controls.md) has an independent qualifier for selected prepared C/C++ free functions. It checks generated tests, their framework entrypoint, replay, detached export, scalar reduction and current-source promotion. Its result is **equivalence over these tests and observations**.

Implementation and literal reader regressions are separate from genuine application qualification. The complete hosted matrix must pass, with its exact source, SDK, tools and raw evidence audited, before this corpus is admitted. This document does not claim that the matrix has passed.

## Workloads and observations

Each language starts with all four collection/emission states. One unchanged application and build then execute all four states through independent setters and an effective export-off barrier. Suppressed windows last at least one export interval. The same application restores both flags and exports retained measurements before shutdown.

Each startup state covers normal calls, a deliberately restored intermediate state difference and recursive calls. C++ also covers a prescribed `std::runtime_error` whose message contains a newline. The recursive fixture uses an opaque helper in another translation unit, preserving observable before/after depth reads at optimisation level two.

Independent checks require all four original scalar frames, complete before/outcome/after graphs for `state`, `calls` and `depth`, exact returns or exception bytes, nine private checkpoint publications and every immutable host snapshot. They decode complete serial trace trees and cumulative metric series directly. Traces cover every selected call; metrics cover collection-enabled calls. Emission-disabled measurements must appear after restoration. Running queue dimensions remain unavailable; final SDK units must match complete downstream receipt.

Promotion requires fresh execution of the original source and a relocated changed checkout. The changed source has a different return and one new selected function with its own return. Recursive compiler databases are relocated explicitly. A restored intermediate difference must remain detectable after reduction from argument five to zero, including framework execution and replay of the reduced suite.

## Run one shard

Use the reviewed SDK source revision `acb13d7735526448209df37b7e6b98e5717befdb`, matched LLVM 22 tools and an installed consumer from the exact candidate source. Both source checkouts must be clean. The SDK and evidence paths must be new external directories, with at least 8 GiB free before builds and each subsequent operation.

```sh
python tests/qualify_native_metrics.py \
  --otelc-root /absolute/path/to/pinned-otelc \
  --sdk-build /external/new-native-sdk \
  --report-dir /external/new-native-evidence \
  --cli /absolute/path/to/quux-oteleq \
  --language cpp --start 01
```

The driver builds the original SDK once per shard. It retains started-command markers, terminal exits and both output channels. Inspect an incomplete operation before recovery; an observation timeout does not authorise a restart.

The [hosted workflow](../.github/workflows/native-metrics.yml) runs eight shards: two languages by four initial states, with at most two shards active together. Expected complete denominators are 104 distinct application launch records per C shard and 132 per C++ shard: 944 across the full matrix. These are required counts, not observed results. Copied shrink reports are checked against their original processes and do not create new launches. Each workload also requires fourteen altered-evidence refusals without application reruns.

Source archives, original SDK products, complete runtime evidence and build failures are uploaded even when a job fails. Original source and product file facts are checked again before acceptance.

## Component checks and limits

```sh
make native-metric-qualification-check PYTHON=/absolute/path/to/python
```

This target checks authored literal records and enforces a separate 80% statement-coverage floor for each qualifier module. It builds no SDK and launches no native application. Required CI, genuine workflow qualification, raw evidence audit and independent review remain separate gates.

The corpus covers diagnostic synchronous scalar free-function workflows. Receivers, variable per-call arguments, lifetime/resource live controls, concurrent schedules, broader build graphs, performance and shipping artefacts remain open. Existing prepared and lifetime records retain their original scope and source identities.
