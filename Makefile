PYTHON ?= python3
NODE ?= node
COVERAGE_ENV ?=
MARKDOWNLINT ?= ./ci/markdownlint/node_modules/.bin/markdownlint

.PHONY: help setup lint examples docs-check observer-check generation-check effect-qualification-check node-observer-check node-sequence-check java-observer-check generation-java-receiver-otelc generation-otelc generation-policy-otelc generation-rust-otelc generation-native-otelc generation-shrink-otelc generation-python-project-otelc generation-receiver-otelc generation-node-receiver-otelc generation-go-build-otelc generation-go-project-otelc generation-sequence-otelc generation-typescript-sequence-otelc generation-filesystem-otelc generation-http-otelc resource-otelc capture-otelc report core-check coverage check

help:
	@printf '%s\n' 'setup     Install locked validation tools' 'lint      Validate repository Markdown' 'examples  Parse illustrative JSON and TOML' 'observer-check Test diagnostic capture and enforce 80% per observer module' 'generation-check Test inventory, generators, state and workspace contracts' 'effect-qualification-check Test shared effect qualification routes and enforce 80% coverage' 'node-observer-check Validate Node observer and enforce 80% V8 coverage' 'generation-otelc Qualify generated tests and mutation detection (OTELC_ROOT, REPORT_DIR)' 'generation-policy-otelc Qualify configured domains, repeats and scalar boundaries' 'generation-rust-otelc Qualify Rust build/application channel separation' 'generation-native-otelc Qualify native scalar type guards and visible aliases' 'generation-shrink-otelc Qualify declared-domain shrinking across all eight adapters' 'generation-python-project-otelc Qualify regular Python package imports and source guards' 'generation-receiver-otelc Qualify declared Python receivers and mutation controls' 'generation-java-receiver-otelc Qualify Java receiver fixtures and private/static state' 'java-observer-check Enforce 80% Java observer line coverage' 'generation-node-receiver-otelc Qualify JavaScript/TypeScript receiver fixtures and mutation controls' 'generation-go-build-otelc Qualify retained Go builds and compiler-free replay' 'generation-go-project-otelc Qualify real Go packages, module roots and tags' 'node-sequence-check Validate ordered Node receiver and bounded GC observations' 'generation-sequence-otelc Qualify ordered receiver steps and collection boundaries' 'generation-typescript-sequence-otelc Qualify both TypeScript collection emitters and older-provider refusal' 'generation-filesystem-otelc Qualify declared filesystem effects across all eight languages' 'generation-http-otelc Qualify scripted HTTP requests/responses across all eight languages' 'resource-otelc Qualify fixed Python resource-close observations' 'capture-otelc Compare all eight real otelc diagnostic workloads (OTELC_ROOT, REPORT_DIR)' 'report    Render retained JSON as HTML/JUnit (INPUT_REPORT, PRESENTATION_DIR)' 'core-check Rust formatting, Clippy and comparator tests' 'coverage  Enforce 80% Rust product line coverage' 'check     Run all documentation and product gates'

setup:
	npm ci --ignore-scripts --prefix ci/markdownlint
	$(PYTHON) ci/java_coverage.py setup

lint:
	$(MARKDOWNLINT) '**/*.md' --ignore 'ci/markdownlint/node_modules/**'

examples:
	$(PYTHON) -c 'import json, pathlib, tomllib; files = list(pathlib.Path("examples").rglob("*.json")) + list(pathlib.Path(".badges").glob("*.json")); [json.loads(p.read_text()) for p in files]; tomllib.loads(pathlib.Path("examples/equivalence.toml").read_text()); print("JSON and TOML syntax valid")'

docs-check: lint examples
	$(MAKE) observer-check
	$(MAKE) generation-check

node-observer-check:
	$(NODE) --test --experimental-test-coverage --test-coverage-include='adapters/generation/node_observe.mjs' --test-coverage-lines=80 --test-coverage-functions=80 --test-coverage-branches=80 tests/node_observer.test.mjs

node-sequence-check:
	$(NODE) --expose-gc --test --experimental-test-coverage --test-coverage-include='adapters/generation/node_sequence.mjs' --test-coverage-lines=80 --test-coverage-functions=80 --test-coverage-branches=80 tests/node_sequence.test.mjs

effect-qualification-check:
	$(PYTHON) -m coverage run --data-file=.effect-qualification.coverage --include='*/effect_qualification.py' -m unittest discover -s tests -p 'test_generation_*qualification.py'
	$(PYTHON) -m coverage report --data-file=.effect-qualification.coverage --fail-under=80

java-observer-check:
	$(PYTHON) ci/java_coverage.py check

generation-check: node-observer-check node-sequence-check java-observer-check effect-qualification-check
	$(PYTHON) -m coverage run --data-file=.generation.coverage --source=adapters/generation,ci -m unittest discover -s tests -p 'test_generation*.py' -v
	$(PYTHON) -m coverage report --data-file=.generation.coverage --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/generation.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/discovery.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/harness.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/python_project.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/go_project.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/node_receivers.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/java_receivers.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/java_graph.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/java_coverage.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/policy.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/domains.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/shrinking.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/sequences.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/typescript_provider.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/filesystem_effects.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/http_effects.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/observe.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/typed_capture.py' --fail-under=80

generation-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_generation.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq" $(GENERATION_ARGS)

generation-policy-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_project_policy.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq" $(GENERATION_ARGS)

generation-rust-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_rust_build.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq" $(GENERATION_ARGS)

generation-native-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_native_types.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq"

generation-shrink-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_shrinking.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq"

generation-python-project-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_python_project.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq"

generation-receiver-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_receivers.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq"

generation-java-receiver-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_java_receivers.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq"

generation-node-receiver-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_node_receivers.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq"

generation-go-build-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_go_builds.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq"

generation-go-project-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_go_project.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq"

generation-sequence-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_sequences.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq"

generation-typescript-sequence-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(UNSUPPORTED_OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_typescript_sequences.py --otelc-root "$(OTELC_ROOT)" --unsupported-otelc-root "$(UNSUPPORTED_OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq"

generation-filesystem-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_filesystem.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq"

generation-http-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_http.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq"

resource-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_resource.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq"

observer-check:
	$(PYTHON) -m coverage run --data-file=.observer.coverage --source=examples -m unittest discover -s tests -p 'test_capture_*.py' -v
	$(PYTHON) -m coverage report --data-file=.observer.coverage --include='*/otelc_capture.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.observer.coverage --include='*/otelc_collection.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.observer.coverage --include='*/otelc_resource.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.observer.coverage --include='*/capture_otelc_languages.py' --fail-under=80

capture-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) examples/capture_otelc_languages.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --comparator "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq" $(CAPTURE_ARGS)

report:
	test -n "$(INPUT_REPORT)" && test -n "$(PRESENTATION_DIR)"
	cargo run --locked -- render-report "$(INPUT_REPORT)" --output-dir "$(PRESENTATION_DIR)"

core-check:
	cargo fmt --all -- --check
	cargo clippy --all-targets --locked -- -D warnings
	cargo test --locked

coverage:
	$(COVERAGE_ENV) cargo llvm-cov --all-targets --locked --ignore-filename-regex '/tests/' --fail-under-lines 80

check: docs-check core-check coverage
