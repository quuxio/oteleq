# Declared return values

A fixture can declare an independently known scalar return value. A baseline that returns another value is blocked, even when both builds agree. A valid baseline followed by a different instrumented result remains an observed difference. The comparison still checks the other requested state, effects, application output and instrumentation witness.

## Configure an expectation

Use `kind = "return_value"` with a value from the shared [typed observation format](typed-comparison.md):

```toml
[[fixtures]]
language = "python"
function = "api.increment"
cases = [[7]]
expected_baseline = { kind = "return_value", value = { kind = "integer", type = "python.int", value = "8", signed = true } }
```

This expectation applies to every concrete case matched by this fixture. Choose inputs for which the same declared result is valid. The value is supplied by the user; oteleq does not derive it from an observed baseline. The default `{ kind = "return" }` continues to require a successful return without specifying its value.

## Supported values

Expectations use complete scalar records: `null`, `undefined`, `unit`, `boolean`, `integer`, `float`, `string` and `bytes`. Their type labels must match the selected language codec exactly. For example, Java `int` returns use `java.lang.Integer`; a native C `int` uses `c.int` with its actual compiler width. Inspect the documented codec or a retained typed bundle to find the representation, then review the expected value independently.

Integers use canonical decimal strings, an explicit `signed` flag and an optional `bits` width. An omitted width becomes an explicit unbounded width in the frozen plan; it does not match a fixed-width integer. Policy integer expectations are limited to 4,096 characters. Floats use exact lowercase hexadecimal bits, including signed zero and NaN payloads. Strings use exact hexadecimal code units with `utf8`, `utf16_be`, `codepoints32_be` or `raw_bytes` encoding. No value, type or encoding is normalised for comparison.

Graph references, opaque values and unbound storage cannot be declared as scalar returns. Malformed expectations fail policy validation before application execution. The Rust comparator also validates the contract independently.

## Repeats, sequences and retained tests

Every baseline repeat must satisfy the expectation. A declared ordered receiver call can supply its own `expected_baseline`; release and collection steps cannot declare a returned value. Intermediate call results are checked even when the final call succeeds.

Plans, concrete corpora, generated suites, replay and export retain the same expectation. Scalar shrinking also retains it: a trial that violates the baseline expectation cannot replace the original qualified difference. Expected object graphs, per-input expected-value lists and inferred business preconditions remain outside this contract.

The conclusion remains **equivalence over these tests and observations**. A declared scalar result strengthens the fixture check; it does not establish correctness for untested inputs or unobserved state.

## Qualify the workflow

With the required language tools and a qualified legacy otelc provider prepared, run:

```sh
make generation-return-otelc PYTHON=/absolute/path/to/otelc/.venv/bin/python \
  OTELC_ROOT=/absolute/path/to/otelc REPORT_DIR=/tmp/new-return-qualification
```

The corpus checks an independently expected result and a deliberately wrong expectation in each language. It exercises public run, generated suites, detached export and replay. The wrong expectations must fail the strict suite. This route uses the existing provider contracts; the replacement SDK needs separate adapter integration and qualification.

The [21 October qualification](qualification/expected-returns-2026-10-21.json) records 260 actual launches against frozen otelc `d6d03b7`: four 16-case routes and one four-launch replay. All eight valid expectations match, while all eight deliberately wrong expectations are blocked in every full route. The recorded source, products and dependencies remain unchanged.

If the final replay is interrupted after all four initial execution routes complete, the Python qualifier accepts `--resume` with the same paths. It rechecks every retained report and the sealed export/tool identities before launching another replay. Missing routes and changed providers are refused.
