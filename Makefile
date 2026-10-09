PYTHON ?= python3
COVERAGE_ENV ?=
MARKDOWNLINT ?= ./ci/markdownlint/node_modules/.bin/markdownlint

.PHONY: help setup lint examples docs-check observer-check capture-otelc core-check coverage check

help:
	@printf '%s\n' 'setup     Install locked documentation tools' 'lint      Validate repository Markdown' 'examples  Parse illustrative JSON and TOML' 'observer-check Test diagnostic capture and enforce 80% per new observer module' 'capture-otelc Compare all eight real otelc diagnostic workloads (OTELC_ROOT, REPORT_DIR)' 'core-check Rust formatting, Clippy and comparator tests' 'coverage  Enforce 80% Rust product line coverage' 'check     Run all documentation and product gates'

setup:
	npm ci --ignore-scripts --prefix ci/markdownlint

lint:
	$(MARKDOWNLINT) '**/*.md' --ignore 'ci/markdownlint/node_modules/**'

examples:
	$(PYTHON) -c 'import json, pathlib, tomllib; files = list(pathlib.Path("examples").rglob("*.json")) + list(pathlib.Path(".badges").glob("*.json")); [json.loads(p.read_text()) for p in files]; tomllib.loads(pathlib.Path("examples/equivalence.toml").read_text()); print("JSON and TOML syntax valid")'

docs-check: lint examples
	$(MAKE) observer-check

observer-check:
	$(PYTHON) -m coverage run --data-file=.observer.coverage --source=examples -m unittest discover -s tests -p 'test_capture_*.py' -v
	$(PYTHON) -m coverage report --data-file=.observer.coverage --include='*/otelc_capture.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.observer.coverage --include='*/capture_otelc_languages.py' --fail-under=80

capture-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) examples/capture_otelc_languages.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" $(CAPTURE_ARGS)

core-check:
	cargo fmt --all -- --check
	cargo clippy --all-targets --locked -- -D warnings
	cargo test --locked

coverage:
	$(COVERAGE_ENV) cargo llvm-cov --all-targets --locked --ignore-filename-regex '/tests/' --fail-under-lines 80

check: docs-check core-check coverage
