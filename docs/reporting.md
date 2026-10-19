# HTML and JUnit reports

`render-report` presents a retained schema-1 generated-run `report.json` as a standalone HTML page and JUnit XML. It runs entirely in the Rust CLI: Python, otelc, the original application and its workspace do not need to exist. It never executes commands or reads paths recorded by the input document.

```sh
quux-oteleq render-report /absolute/path/to/run/report.json \
  --output-dir /absolute/path/to/new-presentation
```

From an oteleq source checkout, the equivalent build-and-render target is:

```sh
make report INPUT_REPORT=/absolute/path/to/run/report.json \
  PRESENTATION_DIR=/absolute/path/to/new-presentation
```

Open `new-presentation/index.html` and configure your CI's JUnit publisher to consume `new-presentation/junit.xml`. The destination must be new; existing directories and files are refused. Its parent must exist. On Unix, the directory has mode `0700` and generated files have mode `0600`. Rendering does not modify the source report or delete evidence. A write failure can leave a partial presentation directory; inspect it and choose another new destination.

## Counts and verdicts

The page shows the number of retained paired cases separately from the callable inventory. Multiple cases for one function are multiple case results. Inventory entries which are blocked, excluded or lack a retained case have separate rows. Every observation retains the comparison's source/policy/artefact identities, declared byte channels, repeat counts, reasons, differences and scope gaps. Requested and actual scalar arguments remain distinct; large integer digits are retained without conversion to floating point.

| Retained result | HTML | JUnit |
| --- | --- | --- |
| `equivalent_observed` | One matched case | Successful test case |
| `different_observed` | Observed difference, with byte or typed field details | `failure` |
| Comparator blocked/inconclusive or tool/build error | Incomplete evidence | `error` |
| Blocked inventory callable | Reason and missing capability | `error`, never skipped |
| Ready callable with no retained case | Untested in this report | `error` |
| Deliberately excluded callable | Excluded, with no equivalence claim | `skipped` |
| No retained cases or source preservation not established | Run qualification gap | Additional `error` |

A single-case replay can succeed as an individual execution while this whole-inventory presentation remains incomplete. Other ready callables without retained cases and all blocked inventory entries stay visible. Rendering a partial report cannot convert it into full-source success.

Rendering exits `0` for complete observed matches, `1` for differences, `2` for command argument errors, `3` for incomplete evidence/inventory, and `4` for input/schema/output errors. Incomplete evidence takes precedence over differences. The XML is still written for valid reports with a nonzero result. These presentation exits do not change the existing generator or byte-comparator exit contracts.

## Evidence and data boundaries

The claim remains **equivalence over these tests and observations**. This is a presentation of producer-supplied evidence; it does not rerun comparisons against raw bundles, authenticate captures or establish equivalence for another artefact or input. Keep the original report, case bundles, raw observations, telemetry and build evidence for review. A rendered page alone is not a replay bundle or shipping qualification.

The renderer checks the supported schema, identity formats, unique inventory/case IDs, callable mapping and consistency of retained comparison verdicts. It refuses contradictory successful results, such as a matched case with differences or fewer than two repeats per lane. Reports are bounded to 16 MiB, 10,000 inventory entries and 1,024 concrete cases. `compare-workload` JSON is a different format and is not accepted by this command.

HTML and XML escape application text. Invalid XML control characters are displayed as visible escapes. The HTML has no scripts, external assets or network requests and declares a restrictive content security policy. Scope gaps are preserved. Typed generated results retain their full fixture contract, execution checks and per-pair field differences. The renderer validates pair coverage and refuses a qualified result with hidden gaps or inconsistent differences. Configured redaction and richer per-capability statuses remain on the [completion checklist](completion.md).

No redaction is applied. Arguments, policies, paths and observations can contain application data. Keep presentation files private and review their contents before publishing them or uploading them as CI artefacts. Redaction before durable capture is a separate unimplemented capability; removing values from a page cannot qualify the missing observations.
