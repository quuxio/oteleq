"""Prepared metadata cannot replace the known JDK, flags, products or controls."""
import copy
from contextlib import nullcontext
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import quote

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import generation
import java_launch as launch
import java_provider as provider


class JavaLaunchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="java-launch-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / "sdk"
        self.folder = self.base / "evidence with spaces"
        self.project = self.folder / "project";self.project.mkdir(parents=True)
        self.classes = self.folder / "scratch/classes";self.classes.mkdir(parents=True)
        self.runtime = self.base / "runtime";self.runtime.mkdir(mode=0o700)
        self.java = self.base / "jdk/bin/java";self.java.parent.mkdir(parents=True);self.java.write_bytes(b"java")
        self.tools = {"java": self.java}
        self.entry = {"language": "java", "java_backend": "prepared", "path": "App.java", "otelc_function": "App.selected(int)"}
        bindings = {}
        for name in ("App", "OteleqDriver"):
            source = self.project / (name + ".java");source.write_text("class " + name + " {}")
            product = self.classes / (name + ".class");product.write_bytes(name.encode())
            bindings[name] = {"source": str(source), "policy_path": source.name,
                              "source_sha256": launch.identity(source)["sha256"], "class_sha256": launch.identity(product)["sha256"],
                              "provenance": "compiler"}
        self.application = {"schema_version": 1, "main_class": "OteleqDriver", "classpath": [str(self.classes)], "bindings": bindings}
        self.manifest = self.folder / "prepared-application.json";self.manifest.write_text(json.dumps(self.application))
        self.data = provider.configuration(self.entry, "http://127.0.0.1:54321", "case")
        self.selection = {"methods": {"App": ["selected"]}, "types": [], "resources": []}
        for name in (provider.AGENT, provider.EXTENSION):
            path = self.root / name;path.parent.mkdir(parents=True, exist_ok=True);path.write_bytes(b"jar")
        (self.runtime / "agent.properties").write_text(launch.properties(launch.agent_values(self.data, "App", "selected")))
        (self.runtime / "plan.properties").write_text(launch.properties(launch.plan_values(self.runtime, self.data, self.selection)))
        (self.runtime / "selection.json").write_text(json.dumps(self.selection))

    def value(self, plain=False):
        application = {"manifest": launch.identity(self.manifest), "main_class": "OteleqDriver",
                       "ordered_classpath": [str(self.classes)], "bindings": copy.deepcopy(self.application["bindings"]),
                       "classpath": [launch.identity(path) for path in sorted(self.classes.iterdir())],
                       "sources": [launch.identity(self.project / (name + ".java")) for name in ("App", "OteleqDriver")]}
        tooling = [self.java]
        if not plain:
            tooling += [self.root / provider.AGENT, self.root / provider.EXTENSION,
                        self.runtime / "agent.properties", self.runtime / "plan.properties", self.runtime / "selection.json"]
        return {"schema_version": 1, "language": "java", "plain": plain, "jvm_profile": "diagnostic-no-cds",
                "agent_diagnostics": None if plain else str(self.runtime / "agent.log"),
                "health_report": None if plain else str(self.runtime / "health.json"),
                "selection_sha256": None if plain else provider.digest(self.selection),
                "argv": launch.expected_argv(self.root, self.java, self.classes, "OteleqDriver", self.runtime,
                                             self.data, "App", "selected", plain),
                "main_class": "OteleqDriver", "ordered_classpath": [str(self.classes)], "application": application,
                "tooling": [launch.identity(path) for path in tooling], "java_version": "openjdk version 21",
                "policy_sha256": provider.digest(self.data), "loaded_origins": str(self.runtime / "class-load.log"),
                "control_socket": None if plain else str(self.runtime / "control.sock")}

    def verify(self, value, plain=False):
        launch.verify(value, root=self.root, project=self.project, folder=self.folder, tools=self.tools,
                      runtime=self.runtime, entry=self.entry, data=self.data, plain=plain)

    def test_plain_and_instrumented_full_fixed_contract(self):
        self.verify(self.value());self.verify(self.value(True), True)
        self.assertEqual(self.value(True)["argv"], [str(self.java), "-Xshare:off",
            "-Xlog:class+load=info:file=" + str(self.runtime / "class-load.log"), "-cp", str(self.classes), "OteleqDriver"])
        self.assertIn("-Dotel.instrumentation.methods.include=App[selected]", self.value()["argv"])
        self.assertEqual(launch.properties({"x": "\"\\ \n\u00e9\U0001f680"}), 'x="\\\\\\ \\n\\u00e9\\ud83d\\ude80\n')

    def test_altered_executable_flags_scope_paths_and_bindings_refuse(self):
        for fault in ("schema", "extra", "java", "flags", "main", "classpath", "profile", "policy", "origin", "health",
                      "selection", "bindings", "duplicate", "source", "tooling"):
            value = self.value()
            if fault == "schema": value["schema_version"] = True
            elif fault == "extra": value["ignored"] = True
            elif fault == "java": value["argv"][0] = "/unapproved/java"
            elif fault == "flags": value["argv"].insert(1, "-javaagent:/unapproved.jar")
            elif fault == "main": value["main_class"] = "Other"
            elif fault == "classpath": value["ordered_classpath"] = ["/other/classes"]
            elif fault == "profile": value["jvm_profile"] = "default"
            elif fault == "policy": value["policy_sha256"] = "0" * 64
            elif fault == "origin": value["loaded_origins"] = "/other/log"
            elif fault == "health": value["health_report"] = "/other/health.json"
            elif fault == "selection": value["selection_sha256"] = "0" * 64
            elif fault == "bindings": value["application"]["bindings"]["App"]["source_sha256"] = "0" * 64
            elif fault == "duplicate": value["application"]["sources"].append(copy.deepcopy(value["application"]["sources"][0]))
            elif fault == "source": value["application"]["sources"][0]["sha256"] = "0" * 64
            else: value["tooling"][0]["mtime_ns"] = True
            with self.subTest(fault=fault), self.assertRaises(ValueError):self.verify(value)
        plain = self.value(True);plain["selection_sha256"] = "0" * 64
        with self.assertRaises(ValueError):self.verify(plain, True)

    def test_rehashed_controls_selection_and_foreign_source_still_refuse(self):
        path = self.runtime / "plan.properties"
        path.write_text(path.read_text().replace("metrics.collection=true", "metrics.collection=false"))
        with self.assertRaisesRegex(ValueError, "configuration or live controls"):self.verify(self.value())
        path.write_text(launch.properties(launch.plan_values(self.runtime, self.data, self.selection)))
        (self.runtime / "selection.json").write_text('{"methods":{},"types":[],"resources":[]}')
        with self.assertRaisesRegex(ValueError, "resolved method"):self.verify(self.value())
        self.application["bindings"]["App"]["source"] = str(self.project / "Foreign.java")
        self.manifest.write_text(json.dumps(self.application))
        with self.assertRaisesRegex(ValueError, "compiler-owned source"):self.verify(self.value())

    def test_metadata_cannot_initiate_a_query_for_an_unapproved_path(self):
        row = launch.identity(self.java);row["path"] = "/unapproved/path"
        with patch.object(launch, "identity", side_effect=AssertionError("foreign query")) as read:
            with self.assertRaisesRegex(ValueError, "unexpected prepared input"):launch.files([row], {self.java})
            read.assert_not_called()
        with self.assertRaises(ValueError):launch.files([{}], {self.java})
        link = self.base / "link";link.symlink_to(self.java)
        with self.assertRaisesRegex(ValueError, "not a regular file"):launch.identity(link)

    def test_public_prepare_records_only_verified_argv_and_retains_failure_channels(self):
        value = self.value()
        (self.folder / "policy.toml").write_text(provider.policy(self.entry, "http://127.0.0.1:54321", "case"))
        execute = Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps(value).encode(), b""))
        result = launch.prepare(self.root, self.project, self.folder, self.tools, self.runtime,
                                self.entry, self.data, False, {}, execute)
        self.assertEqual(result, value["argv"])
        self.assertEqual(json.loads((self.folder / launch.LAUNCH_FILE).read_text()), value)
        self.assertIn("--prepare-only", execute.call_args.args[0])
        execute.return_value = subprocess.CompletedProcess([], 1, b"", b"failure")
        with self.assertRaisesRegex(ValueError, "preparation failed"):
            launch.prepare(self.root, self.project, self.folder, self.tools, self.runtime, self.entry, self.data, True, {}, execute)
        self.assertIn("--plain", execute.call_args.args[0])

    def test_owned_short_runtime_archives_before_cleanup_including_failure(self):
        for failed in (False, True):
            destination = self.base / ("failed" if failed else "completed");destination.mkdir()
            try:
                with launch.runtime(self.entry, destination) as runtime:
                    self.assertLess(len(os.fsencode(runtime / "control.sock")), 100)
                    runtime.mkdir(mode=0o700);(runtime / "health.json").write_text("observed")
                    if failed:raise RuntimeError("application failed")
            except RuntimeError:
                self.assertTrue(failed)
            self.assertFalse(runtime.exists())
            self.assertEqual((destination / "sdk-runtime/health.json").read_text(), "observed")
            self.assertEqual(json.loads((destination / "runtime-archive.json").read_text())["original"], str(runtime))
        with launch.runtime({"language": "python"}, self.folder) as runtime:self.assertIsNone(runtime)
        with patch.object(launch.os, "name", "nt"), self.assertRaisesRegex(ValueError, "POSIX"):
            with launch.runtime(self.entry, self.folder):self.fail("unsupported platform entered")

    def test_runtime_links_special_files_and_budgets_refuse(self):
        foreign = self.base / "foreign";foreign.write_text("preserve")
        for fault in ("link", "fifo", "bytes", "count"):
            destination = self.base / ("budget-" + fault);destination.mkdir()
            limit = (patch.object(launch, "MAX_RUNTIME_BYTES" if fault == "bytes" else "MAX_RUNTIME_FILES",
                                  1 if fault == "bytes" else 0) if fault in ("bytes", "count") else nullcontext())
            with self.subTest(fault=fault), limit, self.assertRaises(ValueError):
                with launch.runtime(self.entry, destination) as runtime:
                    runtime.mkdir(mode=0o700)
                    if fault == "link":(runtime / "link").symlink_to(foreign)
                    elif fault == "fifo":os.mkfifo(runtime / "fifo")
                    else:
                        (runtime / "file").write_bytes(b"xx")
            self.assertFalse(runtime.exists())
        self.assertEqual(foreign.read_text(), "preserve")

    def test_real_loaded_source_origins_reject_missing_changed_and_duplicate_loaders(self):
        log = self.runtime / "class-load.log"
        source = "file:" + quote(str(self.classes), safe="/") + "/"
        correct = ''.join('[1s][class,load] ' + name + ' source: ' + source + '\n' for name in ("App", "OteleqDriver"))
        log.write_text(correct)
        launch.origins(self.runtime, self.folder, self.entry)
        for text in ("", correct.replace(source, "file:/other/"), correct + correct.splitlines()[0] + "\n"):
            log.write_text(text)
            with self.subTest(text=text), self.assertRaises(ValueError):launch.origins(self.runtime, self.folder, self.entry)

    def test_pid_record_write_failure_still_reaps_the_owned_process(self):
        output = self.base / "process-case"
        with patch.object(generation, "write", side_effect=OSError("record write failed")), \
             patch.object(generation, "finish_process", wraps=generation.finish_process) as cleanup:
            with self.assertRaises(OSError):
                generation.execute([sys.executable, "-c", "import time;time.sleep(30)"], self.base,
                                   dict(os.environ), output, record_process=True)
            cleanup.assert_called_once()
            self.assertIsNotNone(cleanup.call_args.args[0].poll())


if __name__ == "__main__":
    unittest.main()
