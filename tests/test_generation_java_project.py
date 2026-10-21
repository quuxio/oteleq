"""Real JDK dependency reads, private source roots and immutable classpath inputs."""
import argparse
from contextlib import redirect_stdout
import copy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import discovery
import generation
import java_build
import java_classpath
import java_launch
import java_project
import policy

JAVA = Path(os.environ.get("OTELC_JAVA") or shutil.which("java")).resolve()
JAVAC = JAVA.with_name("javac")


class JavaProjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="java dependency fixtures ")
        cls.addClassCleanup(temporary.cleanup)
        cls.fixtures = Path(temporary.name).resolve()
        for package, name, body in (("dep", "Library", "public static int value(int n){return n+5;}"),
                                    ("other", "More", "public static int value(){return 11;}")):
            source = cls.fixtures / (name + ".java")
            source.write_text("package " + package + ";public class " + name + "{" + body + "}\n")
            output = cls.fixtures / package
            subprocess.run([JAVAC, "-encoding", "UTF-8", "-proc:none", "-d", output, source],
                           check=True, capture_output=True, timeout=30)
        cls.jar = cls.fixtures / "library.jar"
        with zipfile.ZipFile(cls.jar, "w") as archive:
            archive.write(cls.fixtures / "dep/dep/Library.class", "dep/Library.class")
            archive.writestr("jar-resource.txt", "jar-data")
        cls.directory = cls.fixtures / "other"
        (cls.directory / "directory-resource.txt").write_text("directory-data")
        (cls.directory / "empty-resource").mkdir()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="java source context ")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.source = self.base / "application"
        self.source.mkdir()
        self.jar = self.source / "lib/library.jar"
        self.jar.parent.mkdir()
        shutil.copyfile(self.__class__.jar, self.jar)
        self.directory = self.base / "external classes"
        shutil.copytree(self.__class__.directory, self.directory)
        for name, text in {
            "src/main/java/app/App.java": "package app;public class App {static int selected(int n){return dep.Library.value(n)+other.More.value()+Generated.value()+Helper.value();}}",
            "src/main/java/app/Helper.java": "package app;class Helper {static int value(){return 3;}}",
            "build/generated/app/Generated.java": "package app;class Generated {static int value(){return 17;}}",
            "pom.xml": "<project/>\n", "gradle.lockfile": "unchanged\n"
        }.items():
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        self.options = java_project.settings({"source_roots": ["src/main/java", "build/generated"],
                                               "classpath": ["lib/library.jar", str(self.directory)]})

    def workspace(self):
        workspace = self.base / "workspace"
        workspace.mkdir()
        context = java_project.prepare(self.source, workspace, self.options, discovery.IGNORED)
        contents = generation.manifest(self.source, excluded=discovery.IGNORED,
                                       excluded_files=context["excluded_source_jars"])
        contents = generation.java_source_manifest(self.source, self.options, contents)
        generation.snapshot_source(self.source, workspace, contents)
        java_project.directories(workspace / "snapshot", self.options)
        data = {"java_context": context, "java_context_manifest": java_project.context_manifest(workspace),
                "excluded_directories": sorted(discovery.IGNORED), "configuration": {"adapters": {"java": self.options}}}
        return workspace, data

    def build(self):
        workspace, data = self.workspace()
        folder = self.base / "attempt"
        folder.mkdir()
        project = folder / "project"
        shutil.copytree(workspace / "snapshot", project)
        driver = project / "src/main/java/app/OteleqDriver.java"
        driver.write_text('package app;class OteleqDriver {public static void main(String[] args)throws Exception {'
            'System.out.print(App.selected(7)+":"+new String(OteleqDriver.class.getResourceAsStream("/jar-resource.txt").readAllBytes(),java.nio.charset.StandardCharsets.UTF_8)'
            '+":"+new String(OteleqDriver.class.getResourceAsStream("/directory-resource.txt").readAllBytes(),java.nio.charset.StandardCharsets.UTF_8));}}')
        context = java_project.materialise(workspace, data, folder, project)
        classes = folder / "scratch/classes"
        application = java_build.build(project, [project / "src/main/java/app/App.java", driver],
            "app.OteleqDriver", JAVA, classes, folder, os.environ.copy(), generation.execute, context=context)
        return folder, project, classes, context, application

    def test_configuration_preserves_defaults_and_order_and_refuses_unsafe_paths(self):
        self.assertEqual(java_project.settings({"backend": "legacy"}), {})
        self.assertEqual(policy.validate({})["adapters"]["java"], {"backend": "legacy"})
        configured = policy.validate({"adapters": {"java": self.options}})["adapters"]["java"]
        self.assertEqual(configured, {"backend": "legacy", **self.options})
        self.assertEqual(java_project.settings({"classpath": []})["source_roots"], ["."])
        for value in (None, "src", [], ["/outside"], ["../outside"], ["src", "src"], ["src:*"], [True], ["a\\b"]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                java_project.settings({"source_roots": value})
        for value in (None, ["*.jar"], ["a:b"], ["line\n.jar"], [3], ["same", "same"]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                java_project.settings({"classpath": value})

    def test_real_compile_binds_all_units_and_actual_jar_and_directory_reads(self):
        folder, project, classes, context, application = self.build()
        self.assertEqual(set(application["bindings"]), {"app.App", "app.Helper", "app.Generated", "app.OteleqDriver"})
        self.assertEqual(application["bindings"]["app.Generated"]["policy_path"], "build/generated/app/Generated.java")
        self.assertTrue(application["bindings"]["app.OteleqDriver"]["policy_path"].startswith("_oteleq_generated/"))
        metadata = generation.read(folder / java_build.COMPILER_METADATA_FILENAME)
        self.assertEqual(metadata["schema_version"], 2)
        reads = metadata["class_reads_sha256"]
        self.assertTrue(any(name.startswith("jar:") and name.endswith("!/dep/Library.class") for name in reads))
        self.assertTrue(any(name.endswith("/other/More.class") for name in reads))
        java_classpath.class_reads(reads, context["entries"])
        paths = os.pathsep.join(application["classpath"])
        command = [JAVA, "-Xshare:off", "-Xlog:class+load=info:file=" + str(folder / java_launch.CLASS_LOG),
                   "-cp", paths, application["main_class"]]
        result = subprocess.run(command, capture_output=True, timeout=30, check=False)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"43:jar-data:directory-data", b""))
        java_launch.origins(folder, folder, {"otelc_function": "app.App.selected(int)"}, context=context)
        origins = generation.read(folder / "verified-origins.json")
        self.assertLessEqual({"app.App", "app.OteleqDriver", "dep.Library", "other.More"}, set(origins))
        java_build.verify(project, classes, folder)
        for fault in ("options", "schema", "foreign-read", "changed-read"):
            altered = copy.deepcopy(metadata)
            if fault == "options": altered["options"].append("-parameters")
            elif fault == "schema": altered["schema_version"] = 1
            elif fault == "foreign-read": altered["class_reads_sha256"]["file:/outside.class"] = "0" * 64
            else: altered["class_reads_sha256"][next(iter(reads))] = "0" * 64
            original, generated = java_build.files(project), set()
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                java_build.bindings(altered, project, classes, original, generated, "fixture", context=context)

    def test_context_freezes_resources_empty_directories_and_guards_original_and_private_bytes(self):
        workspace, data = self.workspace()
        self.assertNotIn("lib/library.jar", generation.manifest(workspace / "snapshot"))
        self.assertTrue((workspace / "snapshot/build/generated/app/Generated.java").is_file())
        java_project.verify(workspace, data)
        original = self.jar.read_bytes()
        self.jar.write_bytes(original + b"changed")
        with self.assertRaisesRegex(ValueError, "original dependency changed"):
            java_project.verify(workspace, data)
        java_project.verify(workspace, data, originals=False)
        self.jar.write_bytes(original)
        private = workspace / "java-context/classpath/0001"
        (private / "empty-resource").rmdir()
        with self.assertRaisesRegex(ValueError, "frozen dependency differs"):
            java_project.verify(workspace, data)

    def test_exported_context_works_without_original_dependencies_and_rechecks_each_attempt(self):
        workspace, data = self.workspace()
        data["original_source"] = str(self.source)
        shutil.rmtree(self.source)
        shutil.rmtree(self.directory)
        folder = self.base / "detached"
        folder.mkdir()
        project = folder / "project"
        shutil.copytree(workspace / "snapshot", project)
        context = java_project.materialise(workspace, data, folder, project)
        self.assertEqual(len(java_project.runtime_classpath(folder / "classes", context)), 3)
        java_project.verify_attempt(folder, context)
        path = Path(context["entries"][1]["path"]) / "directory-resource.txt"
        path.write_text("changed")
        with self.assertRaisesRegex(ValueError, "private dependency bytes changed"):
            java_project.verify_attempt(folder, context)

    def test_source_context_refuses_module_links_missing_units_and_duplicate_classes(self):
        (self.source / "src/main/java/module-info.java").write_text("module sample {}")
        with self.assertRaisesRegex(ValueError, "named Java modules"):
            java_project.source_files(self.source, self.options, discovery.IGNORED)
        (self.source / "src/main/java/module-info.java").unlink()
        linked = self.source / "src/main/java/link"
        linked.symlink_to(self.directory, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            java_project.source_files(self.source, self.options, discovery.IGNORED)
        linked.unlink()
        with self.assertRaisesRegex(ValueError, "no Java units"):
            java_project.source_files(self.source, {"source_roots": ["lib"]}, set())
        duplicate = self.base / "duplicate.jar"
        shutil.copyfile(self.jar, duplicate)
        self.options["classpath"].append(str(duplicate))
        workspace = self.base / "refused";workspace.mkdir()
        with self.assertRaisesRegex(ValueError, "duplicate class definitions"):
            java_project.prepare(self.source, workspace, self.options, discovery.IGNORED)

    def test_internal_large_jars_use_the_dependency_budget_and_keep_all_original_bytes(self):
        with zipfile.ZipFile(self.jar, "a") as archive:
            archive.writestr("large-resource.bin", b"x" * (generation.MAX_FILE + 1))
        with self.assertRaisesRegex(ValueError, "snapshot limit"):
            generation.manifest(self.source, excluded=discovery.IGNORED)
        workspace, data = self.workspace()
        java_project.verify(workspace, data)
        self.assertEqual((workspace / "java-context/classpath/0000.jar").read_bytes(), self.jar.read_bytes())

    def test_public_plan_generation_export_detach_and_cleanup_bind_the_java_context(self):
        provider = self.base / "provider";provider.mkdir()
        cli = self.base / "cli";cli.write_text("fixed CLI")
        orphan = self.source / "Orphan.java"
        orphan.write_text("class Orphan {static int selected(int n){return n;}}")
        configuration = self.base / "equivalence.toml"
        configuration.write_text('languages=["java"]\n[functions]\ninclude=["*selected(int)"]\n'
            '[adapters.java]\nsource_roots=' + json.dumps(self.options["source_roots"]) + '\nclasspath='
            + json.dumps(self.options["classpath"]) + '\n[[fixtures]]\nfunction="app.App.selected(int)"\ncases=[[7]]\n')
        request = argparse.Namespace(source=self.source, otelc_root=provider, workspace_parent=self.base,
                                     config=configuration, language=None, exclude=[], cases=1)
        with patch.dict(os.environ, {"OTELEQ_EXECUTABLE": str(cli)}), \
             patch.object(generation.capture, "selected_tools", return_value={"java": JAVA}), \
             patch.object(generation.capture, "artefacts", return_value={"unit": "fixed"}), \
             patch.object(generation, "decoder", return_value=None):
            with redirect_stdout(io.StringIO()) as output:
                generation.plan(request)
            workspace = Path(output.getvalue().strip())
            data = generation.read(workspace / generation.PLAN_FILE)
            self.assertIn("build/generated/app/Generated.java", data["source_manifest"])
            self.assertNotIn("lib/library.jar", data["source_manifest"])
            entries = {entry["otelc_function"]: entry for entry in data["inventory"]}
            self.assertEqual(entries["app.App.selected(int)"]["status"], "ready")
            self.assertIn("outside declared source roots", entries["Orphan.selected(int)"]["reason"])
            self.assertNotEqual(data["source_sha256"], generation.identity(data["source_manifest"]))
            with redirect_stdout(io.StringIO()):
                generation.generate(argparse.Namespace(workspace=workspace))
            self.assertEqual(len(generation.read(workspace / "tests/corpus.json")), 1)
            for command in ("run", "export-tests"):
                output = self.directory / command
                request = argparse.Namespace(command=command, workspace=workspace, report_dir=output,
                                             destination=output, apply=True)
                with self.subTest(command=command), self.assertRaisesRegex(ValueError, "outside declared dependencies"):
                    (generation.run if command == "run" else generation.export_tests)(request)
                self.assertFalse(output.exists())
            destination = self.base / "exported"
            export = argparse.Namespace(workspace=workspace, destination=destination, apply=False)
            with redirect_stdout(io.StringIO()) as output:
                generation.export_tests(export)
            self.assertIn("java-context", json.loads(output.getvalue())["copy"])
            export.apply = True
            with redirect_stdout(io.StringIO()):
                generation.export_tests(export)
            shutil.rmtree(self.source)
            shutil.rmtree(self.directory)
            generation.load_workspace(destination, generated=True)
            edited = destination / "java-context/classpath/0001/directory-resource.txt"
            original = edited.read_bytes();edited.write_bytes(b"changed")
            cleanup = argparse.Namespace(workspace=destination)
            with self.assertRaisesRegex(ValueError, "Java context changed"):
                generation.clean(cleanup)
            edited.write_bytes(original)
            self.assertEqual(generation.clean(argparse.Namespace(workspace=destination)), 0)
            self.assertEqual(generation.clean(argparse.Namespace(workspace=workspace)), 0)

    def test_prepared_probe_cleanup_requires_the_sealed_original_probe_bytes(self):
        workspace, data = self.workspace()
        probe = workspace / generation.java_provider.DIRECTORY / "target/probe.stdout"
        probe.parent.mkdir(parents=True)
        probe.write_text("retained capability response")
        data["java_provider_manifest"] = generation.manifest(workspace / generation.java_provider.DIRECTORY)
        data["source_manifest"] = generation.manifest(workspace / "snapshot")
        generation.write(workspace / generation.PLAN_FILE, data)
        generation.write(workspace / generation.OWNED_MARKER, {"schema_version": 1, "plan_sha256": generation.identity(data)})
        original = probe.read_bytes();probe.write_bytes(b"changed")
        cleanup = argparse.Namespace(workspace=workspace)
        with self.assertRaisesRegex(ValueError, "provider probes changed"):
            generation.clean(cleanup)
        probe.write_bytes(original)
        shutil.rmtree(self.source)
        shutil.rmtree(self.directory)
        self.assertEqual(generation.clean(argparse.Namespace(workspace=workspace)), 0)

    def test_prepared_application_requires_the_complete_private_dependency_inventory(self):
        folder, project, classes, context, application = self.build()
        manifest = folder / java_build.PREPARED_APPLICATION_FILENAME
        record = {"manifest": java_launch.identity(manifest), "main_class": application["main_class"],
                  "ordered_classpath": application["classpath"], "bindings": application["bindings"],
                  "sources": [java_launch.identity(Path(name)) for name in sorted({row["source"] for row in application["bindings"].values()})],
                  "classpath": [java_launch.identity(path) for path in sorted(java_project.classpath_files(classes, context))]}
        java_launch.verify_application(record, application, manifest, classes, context=context)
        altered = copy.deepcopy(record)
        altered["classpath"] = [row for row in altered["classpath"] if not row["path"].endswith("directory-resource.txt")]
        with self.assertRaisesRegex(ValueError, "missing, duplicate or unexpected"):
            java_launch.verify_application(altered, application, manifest, classes, context=context)
        empty = {**context, "entries": []}
        options = java_project.compiler_options(project, classes, empty)
        self.assertEqual(options[options.index("-classpath") + 1], str(classes))

    def test_dependency_output_overlap_refuses_before_copying_or_creating_files(self):
        destination = self.directory / "new-workspace"
        with patch.object(java_classpath, "inspect", side_effect=AssertionError("must refuse before inspecting")):
            with self.assertRaisesRegex(ValueError, "outside declared dependencies"):
                java_project.prepare(self.source, destination, self.options, discovery.IGNORED)
        self.assertFalse(destination.exists())
        workspace, data = self.workspace()
        locations = java_project.original_locations(data)
        self.assertIn(self.directory, locations)
        for name in ("report", "export", "shrink"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "outside declared dependencies"):
                java_project.protect_destination(self.directory / name, locations)
        java_project.protect_destination(self.base / "independent-report", locations)

    def test_declared_generated_units_can_be_the_entire_source_tree(self):
        shutil.rmtree(self.source)
        unit = self.source / "target/generated/Only.java"
        unit.parent.mkdir(parents=True)
        unit.write_text("class Only {static int selected(int n){return n;}}")
        self.assertEqual(generation.manifest(self.source, excluded=discovery.IGNORED), {})
        provider = self.base / "provider";provider.mkdir()
        cli = self.base / "cli";cli.write_text("fixed CLI")
        config = self.base / "generated.toml"
        config.write_text('languages=["java"]\n[adapters.java]\nsource_roots=["target/generated"]\n')
        with patch.dict(os.environ, {"OTELEQ_EXECUTABLE": str(cli)}), \
             patch.object(generation.capture, "selected_tools", return_value={"java": JAVA}), \
             patch.object(generation.capture, "artefacts", return_value={"unit": "fixed"}), redirect_stdout(io.StringIO()) as output:
            generation.plan(argparse.Namespace(source=self.source, otelc_root=provider, workspace_parent=self.base,
                                               config=config, language=None, exclude=[], cases=1))
        workspace = Path(output.getvalue().strip())
        data = generation.read(workspace / generation.PLAN_FILE)
        self.assertEqual(set(data["source_manifest"]), {"target/generated/Only.java"})
        self.assertEqual(next(entry for entry in data["inventory"] if entry["name"] == "Only.selected")["status"], "ready")


class JavaClasspathRefusals(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="java classpath refusals ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def test_implicit_lookup_multi_release_and_ambiguous_jar_layouts_refuse(self):
        cases = [({"META-INF/MANIFEST.MF": "Manifest-Version: 1.0\nClass-Path: elsewhere.jar\n"}, "Class-Path"),
                 ({"META-INF/MANIFEST.MF": "Class-\n Path: elsewhere.jar\n"}, "Class-Path"),
                 ({"META-INF/INDEX.LIST": "JarIndex-Version: 1.0"}, "indexes"),
                 ({"META-INF/versions/21/Thing.class": b"class"}, "multi-release"),
                 ({"meta-inf/manifest.mf": "Manifest-Version: 1.0"}, "manifest path"),
                 ({"../Thing.class": b"class"}, "unsafe JAR"),
                 ({"java/lang/Replacement.class": b"class"}, "replace java")]
        for index, (entries, message) in enumerate(cases):
            jar = self.root / (str(index) + ".jar")
            with zipfile.ZipFile(jar, "w") as archive:
                for name, content in entries.items(): archive.writestr(name, content)
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                java_classpath.inspect(jar)

    def test_changed_uris_links_nonregular_files_and_bounds_refuse(self):
        folder = self.root / "classes";folder.mkdir()
        path = folder / "Foo.class";path.write_bytes(b"class")
        record = {"path": str(folder), **java_classpath.inspect(folder)}
        java_classpath.class_reads({path.as_uri(): java_classpath.digest(path)}, [record])
        for reads in ([], {path.as_uri(): "0" * 64}, {"https://example.com/Foo.class": "0" * 64},
                      {"jar:file:/elsewhere.jar!/Foo.class": "0" * 64}, {"jar:file:/elsewhere.jar": "0" * 64}):
            with self.subTest(reads=reads), self.assertRaises(ValueError):
                java_classpath.class_reads(reads, [record])
        link = folder / "linked.class";link.symlink_to(path)
        with self.assertRaisesRegex(ValueError, "symlink"):
            java_classpath.inspect(folder)
        link.unlink()
        with patch.object(java_classpath, "MAX_FILES", 0), self.assertRaisesRegex(ValueError, "entry budget"):
            java_classpath.inspect(folder)
        with patch.object(java_classpath, "MAX_FILE_BYTES", 1), self.assertRaisesRegex(ValueError, "bounded regular"):
            java_classpath.digest(path)
        jar = self.root / "invalid.jar";jar.write_bytes(b"not a jar")
        with self.assertRaisesRegex(ValueError, "invalid JAR"):
            java_classpath.inspect(jar)


if __name__ == "__main__":
    unittest.main()
