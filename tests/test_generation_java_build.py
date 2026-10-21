"""Real JDK class/source bindings and refusal controls for retained Java builds."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import generation
import java_build
sys.path.insert(0, str(REPO / "tests"))
import qualify_java_receivers

JAVA = Path(os.environ.get("OTELC_JAVA") or shutil.which("java"))


class JavaBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="oteleq-java-compiler-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name).resolve()
        cls.project = cls.root / "project with spaces"
        cls.project.mkdir()
        (cls.project / "sample").mkdir()
        app = cls.project / "sample/App.java"
        app.write_bytes(('package sample;\r\n// UTF-8 cafe \u00e9\r\n'
            'class App {static {try {java.nio.file.Files.writeString(java.nio.file.Path.of(System.getProperty("app.marker")),"ran");}'
            'catch(Exception failure){throw new AssertionError(failure);}}\r\n'
            'static class Nested{}\r\nstatic Object object(){return new Runnable(){public void run(){}};}\r\n'
            'static int run(){return Other.value();}}\r\n').encode())
        (cls.project / "sample/Other.java").write_text('package sample;class Other {static int value(){return 7;}}\n')
        driver = cls.project / "sample/OteleqDriver.java"
        driver.write_text('package sample;class OteleqDriver {public static void main(String[] args){System.out.print(App.run());}}\n')
        cls.folder = cls.root / "evidence"
        cls.folder.mkdir()
        cls.classes = cls.folder / "classes"
        cls.environment = {"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}
        cls.application = java_build.build(cls.project, [app, driver], "sample.OteleqDriver", JAVA,
                                          cls.classes, cls.folder, cls.environment, generation.execute)
        cls.metadata = json.loads((cls.folder / "java-compiler.json").read_text())
        cls.original = java_build.files(cls.project)

    def test_nested_anonymous_implicit_and_driver_classes_have_compiler_origins(self):
        bindings = self.application["bindings"]
        self.assertEqual(set(bindings), {"sample.App", "sample.App$Nested", "sample.App$1", "sample.Other", "sample.OteleqDriver"})
        for name in ("sample.App", "sample.App$Nested", "sample.App$1"):
            self.assertEqual(bindings[name]["policy_path"], "sample/App.java")
            self.assertEqual(bindings[name]["source_sha256"], self.original["sample/App.java"])
        self.assertEqual(bindings["sample.Other"]["policy_path"], "sample/Other.java")
        self.assertEqual(bindings["sample.OteleqDriver"]["policy_path"], "_oteleq_generated/sample/OteleqDriver.java")
        self.assertFalse((self.project / "APP_INITIALISED").exists())
        java_build.verify(self.project, self.classes, self.folder)
        marker = self.folder / "application-started"
        result = subprocess.run([JAVA, "-Dapp.marker=" + str(marker), "-cp", self.classes, "sample.OteleqDriver"],
                                capture_output=True, check=False, timeout=10, env=self.environment)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"7", b""))
        self.assertEqual(marker.read_text(), "ran")
        java_build.verify(self.project, self.classes, self.folder)

    def test_compiler_reads_exact_utf8_crlf_sources_and_complete_jdk_identity(self):
        read = self.metadata["source_reads_sha256"]
        for name in ("sample/App.java", "sample/Other.java", "sample/OteleqDriver.java"):
            self.assertEqual(read[str(self.project / name)], self.original[name])
        identity = json.loads((self.folder / "java-compiler-identity.json").read_text())
        self.assertIn(str(JAVA.resolve().parent.parent / "lib/modules"), identity["inputs_sha256"])
        self.assertEqual(identity["inputs_sha256"][str(self.folder / "compiler-tool/OteleqCompile.java")], java_build.digest(java_build.FRONTEND))
        self.assertIn("-proc:none", self.metadata["options"])

    def test_independent_qualification_rejects_changed_compiler_origin_and_products(self):
        # The qualification layout deliberately differs from this unit fixture.
        with patch.object(qualify_java_receivers, "check_build", return_value=5) as checker:
            self.assertEqual(qualify_java_receivers.verify_builds(self.folder),
                             {"retained_manifests": 1, "unique_manifest_identities": 1, "retained_class_bindings": 5})
            checker.assert_called_once_with(self.folder)
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary).resolve()
            project = folder / "project";project.mkdir()
            source = project / "App.java";source.write_text("class App {}")
            classes = folder / "scratch/classes"
            java_build.build(project, [source], "App", JAVA, classes, folder, self.environment, generation.execute)
            self.assertEqual(qualify_java_receivers.check_build(folder), 1)
            path = folder / "prepared-application.json"
            original = path.read_bytes()
            for fault in ("source", "class", "origin", "provenance"):
                changed = json.loads(original)
                if fault == "source": changed["bindings"]["App"]["source_sha256"] = "0" * 64
                elif fault == "class": changed["bindings"]["App"]["class_sha256"] = "0" * 64
                elif fault == "origin": changed["bindings"]["App"]["source"] = str(project / "Other.java")
                else: changed["bindings"]["App"]["provenance"] = "unbound compiler"
                path.write_text(json.dumps(changed))
                record = json.loads((folder / "build-identities.json").read_text())
                record["prepared_application_sha256"] = java_build.digest(path)
                (folder / "build-identities.json").write_text(json.dumps(record))
                with self.subTest(fault=fault), self.assertRaises(AssertionError):
                    qualify_java_receivers.check_build(folder)
            path.write_bytes(original)
            # Copies retain the original launch paths and independently sealed bytes.
            record["prepared_application_sha256"] = java_build.digest(path)
            (folder / "build-identities.json").write_text(json.dumps(record))
            copied = folder / "copied";copied.mkdir()
            for name in ("project", "scratch", "build", "compiler-tool"):
                shutil.copytree(folder / name, copied / name)
            for name in ("java-compiler.json", "java-compiler-identity.json", "prepared-application.json", "build-identities.json"):
                shutil.copyfile(folder / name, copied / name)
            self.assertEqual(qualify_java_receivers.check_build(copied), 1)

    def test_missing_ambiguous_foreign_duplicate_and_changed_origins_refuse(self):
        for fault in ("version", "failed", "no-reads", "no-outputs", "extra-fields", "metadata-fields", "options", "jdk-version", "unbound", "many", "outside", "duplicate", "changed-read", "binary-name"):
            data = copy.deepcopy(self.metadata)
            output = data["outputs"][0]
            if fault == "version": data["schema_version"] = True
            elif fault == "failed": data["success"] = False
            elif fault == "no-reads": data["source_reads_sha256"] = []
            elif fault == "no-outputs": data["outputs"] = []
            elif fault == "extra-fields": output["unknown"] = "ignored"
            elif fault == "metadata-fields": data["unknown"] = "ignored"
            elif fault == "options": data["options"].append("-g")
            elif fault == "jdk-version": data["java_version"] = None
            elif fault == "unbound": output["origins"] = []
            elif fault == "many": output["origins"] *= 2
            elif fault == "outside": output["origins"] = [str(self.root / "other.java")]
            elif fault == "duplicate": data["outputs"].append(copy.deepcopy(output))
            elif fault == "changed-read": data["source_reads_sha256"][output["origins"][0]] = "0" * 64
            else: output["class"] = "other.Name"
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                java_build.bindings(data, self.project, self.classes, self.original, set(), "test compiler")

    def test_extra_class_and_mutated_products_cannot_pass_post_run_verification(self):
        extra = self.classes / "Extra.class"
        try:
            extra.write_bytes(b"not a compiler product")
            with self.assertRaisesRegex(ValueError, "unrecorded"):
                java_build.bindings(self.metadata, self.project, self.classes, self.original, set(), "test compiler")
            with self.assertRaisesRegex(ValueError, "products changed"):
                java_build.verify(self.project, self.classes, self.folder)
        finally:
            extra.unlink()

    def test_changed_evidence_sources_links_and_absent_modules_refuse(self):
        evidence = self.folder / "prepared-application.json"
        original = evidence.read_bytes()
        try:
            evidence.write_bytes(original + b" ")
            with self.assertRaisesRegex(ValueError, "compiler evidence changed"):
                java_build.verify(self.project, self.classes, self.folder)
        finally:
            evidence.write_bytes(original)
        linked = self.project / "link"
        try:
            linked.symlink_to(self.project / "sample/App.java")
            with self.assertRaisesRegex(ValueError, "symlink"):
                java_build.files(self.project)
        finally:
            linked.unlink()
        with self.assertRaisesRegex(ValueError, "module image"):
            java_build.compiler_inputs(Path(sys.executable))
        with self.assertRaisesRegex(ValueError, "origin"):
            java_build.contained(None, self.project)

    def test_invalid_layouts_and_sources_refuse_before_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            project = root / "project";project.mkdir()
            source = project / "App.java";source.write_text("class App {}")
            folder = root / "evidence";folder.mkdir()
            for classes, sources in ((project / "classes", [source]), (folder / "classes", []),
                                     (folder / "classes", [source, source])):
                with patch.object(generation, "execute") as execute:
                    with self.subTest(classes=classes, sources=sources), self.assertRaises(ValueError):
                        java_build.build(project, sources, "App", JAVA, classes, folder, self.environment, execute)
                    execute.assert_not_called()

    def test_compile_failures_and_source_mutation_keep_evidence_and_refuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve();project = root / "project";project.mkdir()
            source = project / "Broken.java";source.write_text("class Broken { syntax error }")
            folder = root / "bad";folder.mkdir()
            with self.assertRaisesRegex(ValueError, "compilation failed"):
                java_build.build(project, [source], "Broken", JAVA, folder / "classes", folder,
                                 self.environment, generation.execute)
            self.assertTrue((folder / "build/stderr").read_bytes())
            source.write_text("class Broken {}")
            folder = root / "changed";folder.mkdir()
            def changed(*args, **kwargs):
                result = generation.execute(*args, **kwargs)
                source.write_text("class Broken {} // changed")
                return result
            with self.assertRaisesRegex(ValueError, "source or compiler changed"):
                java_build.build(project, [source], "Broken", JAVA, folder / "classes", folder, self.environment, changed)


if __name__ == "__main__":
    unittest.main()
