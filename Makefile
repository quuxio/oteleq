PYTHON ?= python3
NODE ?= node
COVERAGE_ENV ?=
JAVA_BACKEND ?= legacy
GETTER_EXPECTATION ?= different
JAVA_PROFILE ?= stock-methods-v1
PYTHON_PROFILE ?= python-native-inputs-v1
JAVA_ACTION_PROFILE ?= safe-methods-v1
NODE_CONTROL_STARTUP ?= both-on
JAVA_CONTROL_STARTUP ?= both-on
JAVA_STARTUP_PROFILE ?= safe-methods-v1
PYTHON_CONTROL_STARTUP ?= both-on
PYTHON_CONTROL_PROFILE ?= python-native-origins-v2
GO_SOURCE_BACKEND ?= source-v1
GO_CONTROL_STARTUP ?= both-on
AUDIT_DIR ?= $(REPORT_DIR)-audit
MARKDOWNLINT ?= ./ci/markdownlint/node_modules/.bin/markdownlint
DEPENDENCY_AUDIT_OUTPUT ?= $(CURDIR)/build/dependency-audit

.PHONY: dependency-audit dependency-audit-check
.PHONY: generation-go-controls-otelc

.PHONY: generation-project-tests-otelc generation-preconditions-otelc generation-domains-otelc generation-input-walks-otelc generation-retained-source-otelc generation-native-project-otelc generation-return-otelc generation-java-sequence-otelc generation-java-controls-otelc generation-java-project-otelc generation-java-archive-otelc generation-node-project-otelc
.PHONY: node-source-context-check
.PHONY: generation-java-actions-otelc
.PHONY: python-provider-metadata-otelc
.PHONY: python-provider-runtime-otelc
.PHONY: generation-python-origins-otelc
.PHONY: generation-python-caches-otelc
.PHONY: generation-python-cache-workflows-otelc
.PHONY: generation-python-controls-otelc
.PHONY: generation-node-source-collection-otelc generation-node-source-effects-otelc generation-node-source-channels-otelc
.PHONY: generation-node-controls-otelc generation-java-startup-otelc generation-cpp-sequence-otelc generation-python-sequence-otelc generation-java-bindings-otelc generation-java-handles-otelc

.PHONY: help setup lint examples docs-check observer-check generation-check effect-qualification-check node-observer-check node-sequence-check java-observer-check go-observer-check cpp-observer-check generation-cpp-receiver-otelc generation-go-receiver-otelc generation-go-source-otelc generation-java-receiver-otelc generation-otelc generation-policy-otelc generation-rust-otelc rust-semantic-otelc generation-native-otelc generation-shrink-otelc generation-python-project-otelc generation-receiver-otelc generation-node-receiver-otelc generation-go-build-otelc generation-go-project-otelc generation-sequence-otelc generation-typescript-sequence-otelc generation-filesystem-otelc generation-http-otelc resource-otelc capture-otelc report core-check coverage check

help:
	@printf '%s\n' 'generation-go-controls-otelc Qualify source-scope Go live states, retained suites and promotion (GO_CONTROL_STARTUP, AUDIT_DIR)'
	@printf '%s\n' 'generation-go-source-otelc Qualify rebuilt Go receiver, retained and shrink workflows (GO_SOURCE_BACKEND)'
	@printf '%s\n' 'generation-python-controls-otelc Qualify Python startup/live metric states and retained/promoted suites (PYTHON_CONTROL_PROFILE, PYTHON_CONTROL_STARTUP, AUDIT_DIR)'
	@printf '%s\n' 'dependency-audit Check all locked repository dependencies against current OSV advisories' 'dependency-audit-check Test the audit runner offline and enforce 80% coverage'
	@printf '%s\n' 'generation-python-cache-workflows-otelc Qualify complete cached Python matrix, receivers, effects and retained/promoted workflows'
	@printf '%s\n' 'generation-python-caches-otelc Qualify explicit ordinary Python cache decisions and source fallback'
	@printf '%s\n' 'generation-python-origins-otelc Qualify explicit prepared Python receivers, effects and retained/promoted workflows'
	@printf '%s\n' 'python-provider-runtime-otelc Qualify a fixed Python runtime/source profile; generated admission stays separate'
	@printf '%s\n' 'python-provider-metadata-otelc Check rebuilt Python preparation and blocked generated suites; use an owned SDK copy'
	@printf '%s\n' 'generation-node-controls-otelc Qualify four same-process Node metric states and retained suites'
	@printf '%s\n' 'generation-project-tests-otelc Qualify current-source suites, changed bodies and new functions across eight languages'
	@printf '%s\n' 'generation-preconditions-otelc Qualify numeric relations, ordered calls and reduction across eight languages'
	@printf '%s\n' 'generation-domains-otelc Qualify declared domains through eight-language retained suites'
	@printf '%s\n' 'generation-input-walks-otelc Qualify strict input walks across eight languages (BEFORE_CLI)'
	@printf '%s\n' 'generation-retained-source-otelc Qualify eight-language in-source retention, replanning and detached suites'
	@printf '%s\n' 'generation-node-project-otelc Qualify Node module formats, detached suites and reduction'
	@printf '%s\n' 'generation-node-source-collection-otelc Qualify source SDK collection and censored lifetimes through retained suites'
	@printf '%s\n' 'generation-node-source-effects-otelc Qualify source SDK file/HTTP effects and current-source promotion'
	@printf '%s\n' 'generation-node-source-channels-otelc Qualify nonempty binary application output and output-only differences'
	@printf '%s\n' 'generation-java-project-otelc Qualify Java roots, JARs/resources, detached suites and reduction (JAVA_BACKEND, JAVA_PROFILE)'
	@printf '%s\n' 'generation-java-archive-otelc Qualify the explicit JDK21 runtime archive project profile'
	@printf '%s\n' 'generation-java-controls-otelc Qualify same-PID Java metric states (JAVA_PROFILE, GETTER_EXPECTATION, optional LEGACY_OTELC_ROOT)'
	@printf '%s\n' 'generation-java-startup-otelc Qualify Java startup flags and retained routes (JAVA_CONTROL_STARTUP, JAVA_STARTUP_PROFILE)'
	@printf '%s\n' 'generation-java-bindings-otelc Qualify offline action bindings without starting the application'
	@printf '%s\n' 'generation-java-handles-otelc Qualify generated private-handle bytecode and offline bindings'
	@printf '%s\n' 'generation-java-actions-otelc Qualify generated Java action execution, retained routes and altered-evidence refusals (JAVA_ACTION_PROFILE)'
	@printf '%s\n' 'generation-java-sequence-otelc Qualify Java call sequences and recursive telemetry (JAVA_BACKEND)'
	@printf '%s\n' 'generation-cpp-sequence-otelc Qualify ordered C++ state, errors, aliases and recursive telemetry'
	@printf '%s\n' 'generation-python-sequence-otelc Qualify ordered Python package receivers and complete raw/typed graphs'
	@printf '%s\n' 'generation-return-otelc Qualify declared return values and equal-wrong controls in all eight languages'
	@printf '%s\n' 'generation-native-project-otelc Qualify explicit C/C++ targets, detached suites and reduction'
	@printf '%s\n' 'setup     Install locked validation tools' 'lint      Validate repository Markdown' 'examples  Parse illustrative JSON and TOML' 'observer-check Test diagnostic capture and enforce 80% per observer module' 'generation-check Test inventory, generators, state and workspace contracts' 'effect-qualification-check Test shared effect qualification routes and enforce 80% coverage' 'node-observer-check Validate Node observer and enforce 80% V8 coverage' 'generation-otelc Qualify generated tests and mutation detection (OTELC_ROOT, REPORT_DIR)' 'generation-policy-otelc Qualify configured domains, repeats and scalar boundaries' 'generation-rust-otelc Qualify Rust build/application channel separation' 'rust-semantic-otelc Qualify fixed original-source Rust layout and lifetime workloads' 'generation-native-otelc Qualify native scalar type guards and visible aliases' 'generation-shrink-otelc Qualify declared-domain shrinking across all eight adapters' 'generation-python-project-otelc Qualify regular Python package imports and source guards' 'generation-receiver-otelc Qualify declared Python receivers and mutation controls' 'generation-java-receiver-otelc Qualify Java receiver fixtures and private/static state' 'java-observer-check Enforce 80% Java observer line coverage' 'go-observer-check Enforce 80% compiled Go observer statement coverage' 'cpp-observer-check Enforce 80% compiled C++ observer line coverage' 'generation-cpp-receiver-otelc Qualify C++ receivers and private storage/aliases' 'generation-go-receiver-otelc Qualify Go receiver factories and private/global storage' 'generation-node-receiver-otelc Qualify JavaScript/TypeScript receiver fixtures and mutation controls' 'generation-go-build-otelc Qualify retained Go builds and compiler-free replay' 'generation-go-project-otelc Qualify real Go packages, module roots and tags' 'node-sequence-check Validate ordered Node receiver and bounded GC observations' 'generation-sequence-otelc Qualify ordered receiver steps and collection boundaries' 'generation-typescript-sequence-otelc Qualify both TypeScript collection emitters and older-provider refusal' 'generation-filesystem-otelc Qualify declared filesystem effects across all eight languages' 'generation-http-otelc Qualify scripted HTTP requests/responses across all eight languages' 'resource-otelc Qualify fixed Python resource-close observations' 'capture-otelc Compare all eight real otelc diagnostic workloads (OTELC_ROOT, REPORT_DIR)' 'report    Render retained JSON as HTML/JUnit (INPUT_REPORT, PRESENTATION_DIR)' 'core-check Rust formatting, Clippy and comparator tests' 'coverage  Enforce 80% Rust product line coverage' 'check     Run all documentation and product gates'

setup:
	npm ci --ignore-scripts --prefix ci/markdownlint
	$(PYTHON) ci/java_coverage.py setup

generation-project-tests-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_project_tests.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq" $(GENERATION_ARGS)

generation-preconditions-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_preconditions.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq" $(GENERATION_ARGS)

generation-domains-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_domains.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq"

generation-input-walks-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)" && test -n "$(BEFORE_CLI)"
	cargo build --locked
	$(PYTHON) tests/qualify_input_walks.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --before-cli "$(BEFORE_CLI)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq"

generation-retained-source-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_retained_source.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq"

generation-return-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_returns.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq"

generation-java-project-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_java_project.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq" --java-backend "$(JAVA_BACKEND)" $(if $(filter prepared,$(JAVA_BACKEND)),--java-profile "$(JAVA_PROFILE)",)

generation-java-archive-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_java_archives.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq"

generation-native-project-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_native_project.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq"

lint:
	$(MARKDOWNLINT) '**/*.md' --ignore 'ci/markdownlint/node_modules/**'

examples:
	$(PYTHON) -c 'import json, pathlib, tomllib; files = list(pathlib.Path("examples").rglob("*.json")) + list(pathlib.Path(".badges").glob("*.json")); [json.loads(p.read_text()) for p in files]; tomllib.loads(pathlib.Path("examples/equivalence.toml").read_text()); print("JSON and TOML syntax valid")'
	$(NODE) --test tests/workflow_syntax.test.mjs

dependency-audit:
	$(PYTHON) ci/dependency_audit.py --output "$(DEPENDENCY_AUDIT_OUTPUT)"

dependency-audit-check:
	mkdir -p build
	$(PYTHON) -m coverage run --data-file=build/dependency-audit-unit.coverage --source=ci.dependency_audit -m unittest discover -s tests -p test_dependency_audit.py -v
	$(PYTHON) -m coverage report --data-file=build/dependency-audit-unit.coverage --fail-under=80

docs-check: lint examples dependency-audit-check
	$(MAKE) observer-check
	$(MAKE) generation-check

node-observer-check:
	$(NODE) --test --experimental-test-coverage --test-coverage-include='adapters/generation/node_observe.mjs' --test-coverage-lines=80 --test-coverage-functions=80 --test-coverage-branches=80 tests/node_observer.test.mjs

node-sequence-check:
	$(NODE) --expose-gc --test --experimental-test-coverage --test-coverage-include='adapters/generation/node_sequence.mjs' --test-coverage-lines=80 --test-coverage-functions=80 --test-coverage-branches=80 tests/node_sequence.test.mjs tests/node_checkpoint.test.mjs
	$(NODE) --test --experimental-test-coverage --test-coverage-include='adapters/generation/node_checkpoint.mjs' --test-coverage-lines=80 --test-coverage-functions=80 --test-coverage-branches=80 tests/node_checkpoint.test.mjs

effect-qualification-check:
	$(PYTHON) -m coverage run --data-file=.effect-qualification.coverage --include='*/effect_qualification.py' -m unittest discover -s tests -p 'test_generation_*qualification.py'
	$(PYTHON) -m coverage report --data-file=.effect-qualification.coverage --fail-under=80

java-observer-check:
	$(PYTHON) ci/java_coverage.py check

go-observer-check:
	$(PYTHON) ci/go_coverage.py

cpp-observer-check:
	$(PYTHON) ci/cpp_coverage.py

node-source-context-check:
	$(NODE) --test --experimental-test-coverage --test-coverage-include='adapters/generation/node_source_context.mjs' --test-coverage-lines=80 --test-coverage-functions=80 --test-coverage-branches=80 tests/node_source_context.test.mjs

generation-check: node-observer-check node-sequence-check node-source-context-check java-observer-check go-observer-check cpp-observer-check effect-qualification-check
	$(PYTHON) -m coverage run --data-file=.generation.coverage --source=adapters/generation,ci -m unittest discover -s tests -p 'test_generation*.py' -v
	$(PYTHON) -m coverage report --data-file=.generation.coverage --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/evidence_archive.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/evidence_attributes.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/evidence_files.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/evidence_index.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/qualification_archive.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/generation.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/owned_workspace.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/return_expectations.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/java_build.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/java_project.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/java_classpath.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/java_archives.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/java_archive_context.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/java_helper_binding.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/node_project.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/node_source.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/python_provider.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/python_inputs.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/python_prepared.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/python_journal.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/python_code.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/python_code_match.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/python_origin.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/python_selection.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/python_cache.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/python_execution.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/python_health.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/go_provider.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/go_health.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/go_files.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/go_context.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/go_context_sources.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/go_build.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/go_caller.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/go_source.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/go_source_run.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/go_telemetry.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/go_hooks.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/go_prepared.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/go_execution.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/go_launch.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/go_rendezvous.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/go_control.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/go_tooling.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/go_live.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/go_control_receipt.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/python_telemetry.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/python_launch.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/live_control.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/python_control.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/python_control_receipt.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/python_live.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/python_checkpoint.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/node_source_worker.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/node_source_context.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/node_launch.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/node_inputs.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/node_execution.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/node_telemetry.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/node_control.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/node_control_receipt.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/node_live.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/java_health.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/java_witness.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/java_action.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/java_action_session.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/java_actions.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/java_action_launch.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/java_action_run.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/java_action_telemetry.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/java_action_receipt.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/java_action_bindings.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/java_handle_callers.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/java_provider.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/java_profiles.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/java_launch.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/java_telemetry.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/java_control.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/java_live.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/java_control_receipt.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/discovery.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/harness.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/python_project.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/go_project.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/go_receivers.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/go_graph.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/cpp_models.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/native_names.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/native_dependencies.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/native_frontend.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/native_project.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/native_context.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/native_workers.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/native_workspace.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/native_profile.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/cpp_receivers.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/cpp_worker.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/cpp_graph.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/cpp_coverage.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/node_receivers.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/java_receivers.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/java_graph.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/java_coverage.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/go_coverage.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/policy.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/domains.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/preconditions.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/project_tests.py' --fail-under=80
	$(PYTHON) -m coverage report --data-file=.generation.coverage --include='*/project_runner.py' --fail-under=80
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

rust-semantic-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_rust_semantics.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq"

generation-native-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_native_types.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq"

generation-shrink-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_shrinking.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq"

generation-cpp-receiver-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_cpp_receivers.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq"

generation-cpp-sequence-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_cpp_sequences.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq"

generation-python-sequence-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_python_sequences.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq"

python-provider-runtime-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	$(PYTHON) tests/qualify_python_provider_runtime.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --profile "$(PYTHON_PROFILE)"

generation-python-origins-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_python_generated_origins.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq"

generation-python-caches-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_python_caches.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq"

generation-python-cache-workflows-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_python_cached_workflows.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq" $(GENERATION_ARGS)

python-provider-metadata-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_python_provider_metadata.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq"

generation-python-controls-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)" && test -n "$(AUDIT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_python_controls.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq" --profile "$(PYTHON_CONTROL_PROFILE)" --startup-state "$(PYTHON_CONTROL_STARTUP)" --audit-dir "$(AUDIT_DIR)" $(GENERATION_ARGS)

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
	$(PYTHON) tests/qualify_java_receivers.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq" --java-backend "$(JAVA_BACKEND)"

generation-java-sequence-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_java_sequences.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq" --java-backend "$(JAVA_BACKEND)"

generation-java-controls-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_java_controls.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq" --getter-expectation "$(GETTER_EXPECTATION)" --java-profile "$(JAVA_PROFILE)" $(if $(LEGACY_OTELC_ROOT),--legacy-root "$(LEGACY_OTELC_ROOT)",)

generation-java-bindings-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	$(PYTHON) tests/qualify_java_action_bindings.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)"

generation-java-handles-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	$(PYTHON) tests/qualify_java_handle_bindings.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)"

generation-java-actions-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_java_generated_actions.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq" --java-profile "$(JAVA_ACTION_PROFILE)" $(GENERATION_ARGS)

generation-java-startup-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_java_startup.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq" --startup-state "$(JAVA_CONTROL_STARTUP)" --java-profile "$(JAVA_STARTUP_PROFILE)"

generation-node-project-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_node_project.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq" $(GENERATION_ARGS)

generation-node-source-collection-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_node_source_collection.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq"

generation-node-source-effects-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_node_source_effects.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq" $(GENERATION_ARGS)

generation-node-source-channels-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_node_source_channels.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq" $(GENERATION_ARGS)

generation-node-controls-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_node_controls.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq" --startup-state "$(NODE_CONTROL_STARTUP)"

generation-node-receiver-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_node_receivers.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq" $(GENERATION_ARGS)

generation-go-build-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_go_builds.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq"

generation-go-receiver-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_go_receivers.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq"

generation-go-source-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_go_receivers.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq" --backend "$(GO_SOURCE_BACKEND)" $(GENERATION_ARGS)

generation-go-controls-otelc:
	test -n "$(OTELC_ROOT)" && test -n "$(REPORT_DIR)"
	cargo build --locked
	$(PYTHON) tests/qualify_go_controls.py --otelc-root "$(OTELC_ROOT)" --report-dir "$(REPORT_DIR)" --audit-dir "$(AUDIT_DIR)" --cli "$${CARGO_TARGET_DIR:-$(CURDIR)/target}/debug/quux-oteleq" --startup-state "$(GO_CONTROL_STARTUP)" $(GENERATION_ARGS)

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
	$(PYTHON) -m coverage report --data-file=.observer.coverage --include='*/otelc_rust_build.py' --fail-under=80
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
