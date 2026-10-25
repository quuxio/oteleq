"""Maintainer recipes use the consumer executable that Cargo actually built."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class QualificationRecipeTests(unittest.TestCase):
    def test_native_project_recipe_selects_only_an_explicit_prepared_sdk_and_storage_floor(self):
        for backend in ('legacy', 'prepared'):
            result = subprocess.run(['make', '--no-print-directory', '-n', 'generation-native-project-otelc',
                'OTELC_ROOT=/tmp/provider', 'REPORT_DIR=/tmp/native-evidence', 'NATIVE_BACKEND=' + backend,
                'NATIVE_SDK_BUILD=/tmp/held-sdk', 'NATIVE_MIN_FREE_BYTES=123456'],
                cwd=ROOT, capture_output=True, text=True, check=True)
            self.assertIn('--backend "' + backend + '"', result.stdout)
            self.assertIn('--min-free-bytes "123456"', result.stdout)
            self.assertEqual('--sdk-build "/tmp/held-sdk"' in result.stdout, backend == 'prepared')

    def test_native_caller_recipe_has_its_own_compiler_checks_and_coverage_floor(self):
        result = subprocess.run(['make', '--no-print-directory', '-n', 'native-caller-check',
            'PYTHON=/selected/python'], cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertIn('test_generation_native_callers', result.stdout)
        self.assertIn('test_generation_native_workers', result.stdout)
        self.assertIn('test_generation_native_frontend', result.stdout)
        self.assertIn("--include='*/native_unit_caller.py' --fail-under=80", result.stdout)
        self.assertNotIn('cargo build', result.stdout)

    def test_native_provider_components_have_a_focused_compiler_free_recipe(self):
        result = subprocess.run(['make', '--no-print-directory', '-n', 'native-provider-check',
            'PYTHON=/selected/python'], cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertIn('/selected/python -m coverage run', result.stdout)
        for name in ('test_generation_native_prepared_inputs', 'test_generation_native_prepared_build',
                     'test_generation_native_prepared', 'test_generation_native_execution', 'test_generation_native_session',
                     'test_generation_native_telemetry', 'test_generation_native_units'):
            self.assertIn(name, result.stdout)
        self.assertIn('--data-file=.native-provider.coverage', result.stdout)
        self.assertIn('--fail-under=80', result.stdout)
        self.assertIn("--include='*/native_unit_build.py' --fail-under=80", result.stdout)
        self.assertNotIn('cargo build', result.stdout)
        self.assertNotIn('--otelc-root', result.stdout)

    def test_all_qualification_recipes_honour_default_relative_and_spaced_target_directories(self):
        targets = {}
        target = None
        for line in (ROOT / "Makefile").read_text().splitlines():
            if line and not line[0].isspace() and line.endswith(":"):
                target = line[:-1]
            for flag in ("--cli", "--comparator"):
                if line.startswith("\t") and flag + " " in line:
                    targets[target] = flag
        self.assertEqual(len(targets), 47)
        self.assertIn("generation-go-controls-otelc", targets)
        self.assertIn("generation-python-controls-otelc", targets)
        self.assertIn("generation-python-cache-workflows-otelc", targets)
        self.assertIn("generation-python-caches-otelc", targets)
        self.assertIn("generation-python-origins-otelc", targets)
        self.assertIn("python-provider-metadata-otelc", targets)
        self.assertIn("generation-cpp-sequence-otelc", targets)
        self.assertIn("generation-python-sequence-otelc", targets)
        self.assertIn("generation-project-tests-otelc", targets)
        self.assertIn("generation-preconditions-otelc", targets)
        self.assertIn("generation-domains-otelc", targets)
        self.assertIn("generation-input-walks-otelc", targets)
        self.assertIn("generation-retained-source-otelc", targets)
        self.assertIn("generation-node-project-otelc", targets)
        self.assertIn("generation-node-source-collection-otelc", targets)
        self.assertIn("generation-node-source-effects-otelc", targets)
        self.assertIn("generation-node-source-channels-otelc", targets)
        self.assertIn("generation-node-controls-otelc", targets)
        self.assertIn("generation-native-project-otelc", targets)
        self.assertIn("generation-http-otelc", targets)
        self.assertIn("generation-java-receiver-otelc", targets)
        self.assertIn("generation-java-sequence-otelc", targets)
        self.assertIn("generation-java-controls-otelc", targets)
        self.assertIn("generation-java-actions-otelc", targets)
        self.assertIn("generation-java-startup-otelc", targets)
        self.assertIn("generation-java-project-otelc", targets)
        self.assertIn("generation-java-archive-otelc", targets)
        self.assertIn("generation-go-receiver-otelc", targets)
        self.assertIn("generation-go-source-otelc", targets)
        self.assertIn("rust-semantic-otelc", targets)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            cargo = base / "cargo"
            cargo.write_text("#!/bin/sh\nexit 0\n")
            cargo.chmod(0o700)
            python = base / "record-python"
            python.write_text(f"#!{sys.executable}\nimport json,os,sys\nfrom pathlib import Path\n"
                              "Path(os.environ['OTELEQ_RECIPE_RECORD']).write_text(json.dumps(sys.argv[1:]))\n")
            python.chmod(0o700)
            record = base / "arguments.json"
            for directory in (None, "relative target", str(base / "external target")):
                environment = {**os.environ, "PATH": str(base) + os.pathsep + os.environ["PATH"],
                               "OTELEQ_RECIPE_RECORD": str(record)}
                environment.pop("CARGO_TARGET_DIR", None)
                if directory is not None:
                    environment["CARGO_TARGET_DIR"] = directory
                expected = str(Path(directory or ROOT / "target") / "debug/quux-oteleq")
                for name, flag in targets.items():
                    with self.subTest(target=name, directory=directory):
                        result = subprocess.run(["make", "--no-print-directory", "-s", name,
                            "OTELC_ROOT=" + str(base / "provider"), "REPORT_DIR=" + str(base / "evidence"),
                            "UNSUPPORTED_OTELC_ROOT=" + str(base / "old-provider"), "BEFORE_CLI=" + str(base / "old-cli"), "PYTHON=" + str(python),
                            "GENERATION_ARGS=", "CAPTURE_ARGS="], cwd=ROOT, env=environment,
                            capture_output=True, text=True, check=False)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        arguments = json.loads(record.read_text())
                        self.assertEqual(arguments[arguments.index(flag) + 1], expected)
                        if name in ('generation-node-controls-otelc', 'generation-java-startup-otelc',
                                    'generation-python-controls-otelc', 'generation-go-controls-otelc'):
                            self.assertEqual(arguments[arguments.index('--startup-state') + 1], 'both-on')
                        if name == 'generation-java-startup-otelc':
                            self.assertEqual(arguments[arguments.index('--java-profile') + 1], 'safe-methods-v1')
                        if name == 'generation-java-actions-otelc':
                            self.assertEqual(arguments[arguments.index('--java-profile') + 1], 'safe-methods-v1')

    def test_python_control_recipe_retains_profile_startup_and_separate_audit(self):
        result = subprocess.run(['make', '--no-print-directory', '-n', 'generation-python-controls-otelc',
            'OTELC_ROOT=/tmp/provider', 'REPORT_DIR=/tmp/evidence', 'AUDIT_DIR=/tmp/audit-two',
            'PYTHON_CONTROL_STARTUP=both-off', 'PYTHON_CONTROL_PROFILE=python-native-cache-origins-v3',
            'GENERATION_ARGS=--retained-only'], cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertIn('tests/qualify_python_controls.py', result.stdout)
        self.assertIn('--profile "python-native-cache-origins-v3" --startup-state "both-off"', result.stdout)
        self.assertIn('--audit-dir "/tmp/audit-two" --retained-only', result.stdout)

    def test_go_control_recipe_retains_startup_and_separate_retained_audit(self):
        result = subprocess.run(['make', '--no-print-directory', '-n', 'generation-go-controls-otelc',
            'OTELC_ROOT=/tmp/provider', 'REPORT_DIR=/tmp/evidence', 'AUDIT_DIR=/tmp/go-audit',
            'GO_CONTROL_STARTUP=both-off', 'GO_CONTROL_MIN_FREE_BYTES=123456', 'GENERATION_ARGS=--retained-only'],
            cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertIn('tests/qualify_go_controls.py', result.stdout)
        self.assertIn('--startup-state "both-off" --retained-only', result.stdout)
        self.assertIn('--audit-dir "/tmp/go-audit"', result.stdout)
        self.assertIn('--min-free-bytes "123456"', result.stdout)

    def test_java_action_recipe_retains_explicit_profile_and_retained_only_mode(self):
        result = subprocess.run(['make', '--no-print-directory', '-n', 'generation-java-actions-otelc',
            'OTELC_ROOT=/tmp/provider', 'REPORT_DIR=/tmp/evidence', 'PYTHON=/selected/python',
            'JAVA_ACTION_PROFILE=archive-methods-v1', 'GENERATION_ARGS=--retained-only'],
            cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertIn('/selected/python tests/qualify_java_generated_actions.py', result.stdout)
        self.assertIn('--java-profile "archive-methods-v1" --retained-only', result.stdout)

    def test_node_control_recipe_retains_the_explicit_startup_state(self):
        result = subprocess.run(['make', '--no-print-directory', '-n', 'generation-node-controls-otelc',
            'OTELC_ROOT=/tmp/provider', 'REPORT_DIR=/tmp/evidence', 'NODE_CONTROL_STARTUP=both-off'],
            cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertIn('--startup-state "both-off"', result.stdout)

    def test_python_runtime_recipe_checks_owned_roots_without_building_a_cli(self):
        result = subprocess.run(['make', '--no-print-directory', '-n', 'python-provider-runtime-otelc',
            'OTELC_ROOT=/tmp/provider', 'REPORT_DIR=/tmp/evidence', 'PYTHON=/selected/python'],
            cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertIn('/selected/python tests/qualify_python_provider_runtime.py', result.stdout)
        self.assertIn('--otelc-root "/tmp/provider" --report-dir "/tmp/evidence"', result.stdout)
        self.assertNotIn('cargo build', result.stdout)

    def test_java_binding_recipe_runs_only_the_explicit_offline_qualification(self):
        result = subprocess.run(['make', '--no-print-directory', '-n', 'generation-java-bindings-otelc',
            'OTELC_ROOT=/tmp/provider', 'REPORT_DIR=/tmp/evidence', 'PYTHON=/selected/python'],
            cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertIn('/selected/python tests/qualify_java_action_bindings.py', result.stdout)
        self.assertIn('--otelc-root "/tmp/provider" --report-dir "/tmp/evidence"', result.stdout)
        self.assertNotIn('cargo build', result.stdout)

    def test_native_lifetime_recipe_retains_its_reader_and_runtime_module_floors(self):
        result = subprocess.run(['make', '--no-print-directory', '-n', 'native-lifetime-check',
            'PYTHON=/selected/python'], cwd=ROOT, capture_output=True, text=True, check=True)
        for module in ('native_lifetime_build', 'native_lifetime_inventory', 'native_prepared',
                       'native_execution', 'native_health'):
            self.assertIn("--include='*/" + module + ".py' --fail-under=80", result.stdout)
        for suite in ('test_generation_native_lifetime_build', 'test_generation_native_lifetime_execution',
                      'test_generation_native_prepared', 'test_generation_native_execution'):
            self.assertIn(suite, result.stdout)
        self.assertNotIn('cargo build', result.stdout)
        self.assertNotIn('native-provider.coverage', result.stdout)

    def test_native_lifetime_receipt_recipe_has_four_independent_component_floors(self):
        result = subprocess.run(['make', '--no-print-directory', '-n', 'native-lifetime-receipt-check',
            'PYTHON=/selected/python'], cwd=ROOT, capture_output=True, text=True, check=True)
        for module in ('native_lifetime_intent', 'native_lifetime_metrics', 'native_lifetime_receipt', 'native_telemetry'):
            self.assertIn("--include='*/" + module + ".py' --fail-under=80", result.stdout)
        self.assertIn('test_generation_native_lifetime_receipt', result.stdout)
        self.assertIn('test_generation_native_telemetry', result.stdout)
        self.assertNotIn('cargo build', result.stdout)
        self.assertNotIn('.native-lifetime.coverage', result.stdout)

    def test_native_lifetime_caller_recipe_keeps_both_compiler_binding_floors(self):
        result = subprocess.run(['make', '--no-print-directory', '-n', 'native-lifetime-caller-check',
            'PYTHON=/selected/python'], cwd=ROOT, capture_output=True, text=True, check=True)
        for module in ('native_lifetime_caller', 'native_unit_caller'):
            self.assertIn("--include='*/" + module + ".py' --fail-under=80", result.stdout)
        self.assertIn('test_generation_native_lifetime_caller', result.stdout)
        self.assertIn('test_generation_native_callers', result.stdout)
        self.assertNotIn('cargo build', result.stdout)

    def test_native_lifetime_public_recipe_keeps_literal_boundaries_and_each_module_floor(self):
        result = subprocess.run(['make', '--no-print-directory', '-n', 'native-lifetime-public-check',
            'PYTHON=/selected/python'], cwd=ROOT, capture_output=True, text=True, check=True)
        for module in ('native_lifetime_policy', 'native_lifetime_frontend', 'native_source', 'native_source_run'):
            self.assertIn("--include='*/" + module + ".py' --fail-under=80", result.stdout)
        for name in ('test_generation_native_lifetime_policy', 'test_generation_native_lifetime_frontend',
                     'test_generation_native_lifetime_run', 'test_generation_native_source_run'):
            self.assertIn(name, result.stdout)
        self.assertNotIn('cargo build', result.stdout)
        self.assertNotIn('--otelc-root', result.stdout)

    def test_native_lifetime_workflow_recipe_runs_literal_oracles_without_sdk_work(self):
        result = subprocess.run(['make', '--no-print-directory', '-n', 'native-lifetime-workflow-check',
            'PYTHON=/selected/python'], cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertIn('test_generation_native_lifetime_workflow', result.stdout)
        self.assertIn('--include=\'*/qualify_native_lifetimes.py\'', result.stdout)
        self.assertIn('--data-file=.native-lifetime-workflow.coverage --fail-under=80', result.stdout)
        self.assertNotIn('native_launch', result.stdout)
        self.assertNotIn('cargo build', result.stdout)

    def test_help_names_the_http_qualification_target(self):
        result = subprocess.run(["make", "help"], cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertIn("generation-http-otelc Qualify scripted HTTP", result.stdout)
        self.assertIn('native-provider-check Check native prepared readers and ownership', result.stdout)
        self.assertIn("generation-java-handles-otelc Qualify generated private-handle", result.stdout)
        self.assertIn("generation-project-tests-otelc Qualify current-source suites", result.stdout)
        self.assertIn("generation-preconditions-otelc Qualify numeric relations", result.stdout)
        self.assertIn("generation-native-project-otelc Qualify explicit C/C++ targets", result.stdout)
        self.assertIn("generation-java-project-otelc Qualify Java roots", result.stdout)
        self.assertIn("generation-node-project-otelc Qualify Node module formats", result.stdout)
        self.assertIn("generation-node-source-collection-otelc Qualify source SDK collection", result.stdout)
        self.assertIn("generation-node-source-effects-otelc Qualify source SDK file/HTTP", result.stdout)
        self.assertIn("generation-node-source-channels-otelc Qualify nonempty binary", result.stdout)
        self.assertIn("generation-java-startup-otelc Qualify Java startup flags", result.stdout)
        self.assertIn("generation-python-sequence-otelc Qualify ordered Python package receivers", result.stdout)
        self.assertIn("generation-go-controls-otelc Qualify source-scope Go live states", result.stdout)

    def test_handle_binding_recipe_uses_the_prebuilt_sdk_without_building_a_cli(self):
        result = subprocess.run(['make', '--no-print-directory', '-n', 'generation-java-handles-otelc',
            'OTELC_ROOT=/tmp/provider', 'REPORT_DIR=/tmp/evidence', 'PYTHON=/selected/python'],
            cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertIn('/selected/python tests/qualify_java_handle_bindings.py', result.stdout)
        self.assertIn('--otelc-root "/tmp/provider" --report-dir "/tmp/evidence"', result.stdout)
        self.assertNotIn('cargo build', result.stdout)

    def test_java_startup_recipe_retains_explicit_state_and_profile(self):
        result = subprocess.run(['make', '--no-print-directory', '-n', 'generation-java-startup-otelc',
            'OTELC_ROOT=/tmp/provider', 'REPORT_DIR=/tmp/evidence', 'JAVA_CONTROL_STARTUP=both-off',
            'JAVA_STARTUP_PROFILE=archive-methods-v1'], cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertIn('--startup-state "both-off"', result.stdout)
        self.assertIn('--java-profile "archive-methods-v1"', result.stdout)


if __name__ == "__main__":
    unittest.main()
