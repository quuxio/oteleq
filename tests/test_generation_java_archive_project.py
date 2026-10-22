"""Real JDK archive project contexts and closed new-provider launch contracts."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import discovery
import generation
import java_archive_context as archive_context
import java_archives
import java_build
import java_helper_binding as helpers
import java_launch
import java_profiles as profiles
import java_project
import java_provider as provider
import policy

JAVA = Path(os.environ.get("OTELC_JAVA") or shutil.which("java")).resolve()


class JavaArchiveProjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="java archive source fixtures ")
        cls.addClassCleanup(temporary.cleanup)
        cls.fixtures = Path(temporary.name).resolve()
        cls.variants = {}
        for number in (8, 21):
            folder = cls.fixtures / str(number)
            folder.mkdir()
            source = folder / "Flags.java"
            source.write_text("package dep;public class Flags {public static final int VALUE=" + str(number)
                              + "; public static int value(){return " + str(number) + ";}}")
            subprocess.run([JAVA.with_name("javac"), "-d", folder, source],
                           capture_output=True, check=True, timeout=30)
            cls.variants[number] = (folder / "dep/Flags.class").read_bytes()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="java archive project ")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.source = self.base / "application"
        (self.source / "src/app").mkdir(parents=True)
        (self.source / "src/app/App.java").write_text("package app;public class App {static int total=2;"
            "public static int selected(int n){total+=n;return n+dep.Flags.VALUE+dep.Flags.value();}}")
        self.jar = self.source / "lib.jar"
        self.write_jar(b"true")
        self.options = policy.validate({"adapters": {"java": {"backend": "prepared", "profile": profiles.ARCHIVES,
                                       "source_roots": ["src"], "classpath": ["lib.jar"]}}})["adapters"]["java"]
        self.environment = {key: value for key, value in os.environ.items() if key not in java_archives.JAVA_OPTIONS}
        self.tools = {"java": JAVA, "javac": JAVA.with_name("javac"), "javap": JAVA.with_name("javap"),
                      "java-modules": java_build.module_image(JAVA)}

    def write_jar(self, flag: bytes) -> None:
        with zipfile.ZipFile(self.jar, "w") as archive:
            archive.writestr("META-INF/MANIFEST.MF", b"Manifest-Version: 1.0\r\nMulti-Release: " + flag + b"\r\n\r\n")
            archive.writestr("dep/Flags.class", self.variants[8])
            archive.writestr("META-INF/versions/21/dep/Flags.class", self.variants[21])
            archive.writestr("resource.bin", b"untouched\x00resource")

    def workspace(self):
        workspace = self.base / "workspace"
        workspace.mkdir()
        context = java_project.prepare(self.source, workspace, self.options, discovery.IGNORED,
                                       java=JAVA, environment=self.environment, execute=generation.execute)
        contents = generation.manifest(self.source, excluded=discovery.IGNORED,
                                       excluded_files=context["excluded_source_jars"])
        generation.snapshot_source(self.source, workspace, contents)
        data = {"java_context": context, "java_context_manifest": java_project.context_manifest(workspace),
                "tools": {"java": {key: str(value) for key, value in self.tools.items()}},
                "excluded_directories": sorted(discovery.IGNORED), "configuration": {"adapters": {"java": self.options}}}
        return workspace, data

    def build(self):
        workspace, data = self.workspace()
        folder = self.base / "attempt"
        folder.mkdir()
        project = folder / "project"
        shutil.copytree(workspace / "snapshot", project)
        driver = project / "src/app/OteleqDriver.java"
        driver.write_text("package app;class OteleqDriver {public static void main(String[] args){System.out.print(App.selected(7));}}")
        context = java_project.materialise(workspace, data, folder, project)
        classes = folder / "scratch/classes"
        application = java_build.build(project, [project / "src/app/App.java", driver], "app.OteleqDriver", JAVA,
                                       classes, folder, self.environment, generation.execute, context=context)
        return folder, project, classes, context, application

    def test_explicit_profile_selects_fixed_context_defaults_and_modern_recipe(self):
        configured = policy.validate({"adapters": {"java": {"backend": "prepared", "profile": profiles.ARCHIVES}}})
        self.assertEqual(configured["adapters"]["java"]["source_roots"], ["."])
        self.assertTrue(profiles.corrected(profiles.ARCHIVES))
        self.assertFalse(profiles.corrected(profiles.STOCK))
        with self.assertRaisesRegex(ValueError, "prepared backend"):
            policy.validate({"adapters": {"java": {"profile": profiles.ARCHIVES}}})
        entry = {"path": "App.java", "otelc_function": "App.selected(int)", "java_profile": profiles.ARCHIVES}
        settings = provider.configuration(entry, "http://127.0.0.1:4318", "case")
        self.assertEqual(settings["context"], {"tasks": False, "http": False})
        values = java_launch.agent_values(settings, "App", "selected", profiles.ARCHIVES)
        self.assertEqual(values["otel.instrumentation.executors.enabled"], "false")
        self.assertEqual(values["otel.instrumentation.methods.enabled"], "false")
        self.assertEqual(values["otel.instrumentation.otelc-methods.enabled"], "true")
        self.assertNotIn("context", provider.configuration({**entry, "java_profile": profiles.SAFE}, "http://127.0.0.1:4318", "case"))

    def test_plan_copies_complete_archives_and_keeps_raw_and_effective_members(self):
        original = self.jar.read_bytes()
        workspace, data = self.workspace()
        context = data["java_context"]
        java_project.verify(workspace, data)
        self.assertEqual(context["schema_version"], 2)
        entry = context["entries"][0]
        self.assertEqual(entry["classes"]["dep.Flags"]["entry"], "META-INF/versions/21/dep/Flags.class")
        self.assertEqual(set(entry["members"]), {"dep/Flags.class", "META-INF/versions/21/dep/Flags.class"})
        self.assertEqual((workspace / "java-context/classpath/0000.jar").read_bytes(), original)
        self.assertEqual(self.jar.read_bytes(), original)
        entry_fn = {"language": "java", "path": "src/app/App.java", "status": "ready"}
        java_project.bind_entry(entry_fn, context)
        self.assertEqual(entry_fn["java_context_profile"], archive_context.PROFILE)
        self.assertFalse(archive_context.configured(None))

    def test_real_compile_retains_literal_versioned_class_reads_and_private_inputs(self):
        folder, project, classes, context, application = self.build()
        metadata = json.loads((folder / "java-compiler.json").read_text())
        self.assertTrue(any("META-INF/versions/21/dep/Flags.class" in uri for uri in metadata["class_reads_sha256"]))
        result = subprocess.run([JAVA, "-cp", os.pathsep.join(application["classpath"]), application["main_class"]],
                                capture_output=True, check=True, timeout=30)
        self.assertEqual(result.stdout, b"49")
        java_build.verify(project, classes, folder)
        paths = java_project.runtime_classpath(classes, context)
        archive_context.prepare_attempt(paths, context, JAVA, folder, self.environment, generation.execute)
        claim = archive_context.expected_resolution(paths, context)
        archive_context.verify_attempt(claim, paths, context, JAVA, folder)
        claim["jdk_feature"] += 1
        with self.assertRaisesRegex(ValueError, "differs from the selected JDK"):
            archive_context.verify_attempt(claim, paths, context, JAVA, folder)

    def test_frozen_context_is_portable_and_changed_inputs_or_jdk_still_refuse(self):
        workspace, data = self.workspace()
        exported = self.base / "exported"
        shutil.copytree(workspace, exported)
        detached = copy.deepcopy(data)
        shutil.rmtree(self.source)
        java_project.verify(exported, detached, originals=False)
        context = detached["java_context"]
        context["archive_feature"] += 1
        (exported / "java-context/context.json").write_text(json.dumps(context, indent=2) + "\n")
        detached["java_context_manifest"] = java_project.context_manifest(exported)
        with self.assertRaisesRegex(ValueError, "JDK feature"):
            java_project.verify(exported, detached, originals=False)
        context["archive_feature"] -= 1
        context["archive_jdk"][str(JAVA)] = "0" * 64
        (exported / "java-context/context.json").write_text(json.dumps(context, indent=2) + "\n")
        detached["java_context_manifest"] = java_project.context_manifest(exported)
        with self.assertRaisesRegex(ValueError, "selected JDK changed"):
            java_project.verify(exported, detached, originals=False)

    def test_forged_effective_catalogue_refuses_against_a_fresh_jdk_before_launch(self):
        folder, project, classes, context, _ = self.build()
        context["entries"][0]["classes"]["dep.Flags"] = {
            "entry": "dep/Flags.class", "sha256": hashlib.sha256(self.variants[8]).hexdigest()}
        with self.assertRaisesRegex(ValueError, "differs from the frozen catalogue"):
            archive_context.prepare_attempt(java_project.runtime_classpath(classes, context), context, JAVA,
                                            folder, self.environment, generation.execute)

    def test_originals_private_records_duplicates_and_missing_execution_context_refuse(self):
        workspace, data = self.workspace()
        with zipfile.ZipFile(self.jar, "a") as archive:
            archive.writestr("added-resource", b"changed")
        with self.assertRaisesRegex(ValueError, "original dependency changed"):
            java_project.verify(workspace, data)
        data["java_context"]["profile"] = java_project.PROFILE
        (workspace / "java-context/context.json").write_text(json.dumps(data["java_context"], indent=2) + "\n")
        data["java_context_manifest"] = java_project.context_manifest(workspace)
        with self.assertRaisesRegex(ValueError, "configuration differs"):
            java_project.verify(workspace, data)
        output = self.base / "missing-jdk"
        output.mkdir()
        with self.assertRaisesRegex(ValueError, "selected JDK"):
            java_project.prepare(self.source, output, self.options, discovery.IGNORED)

    def test_directory_only_context_retains_an_empty_archive_resolution(self):
        self.options["classpath"] = []
        workspace, data = self.workspace()
        context = data["java_context"]
        java_project.verify(workspace, data)
        empty = workspace / "java-context/empty-classes"
        resolution = archive_context.expected_resolution([empty], context)
        self.assertEqual(resolution["archives"], [])
        self.assertEqual(context["schema_version"], 2)

    def test_new_launch_contract_requires_schema2_complete_claim_and_exact_tooling(self):
        folder, project, classes, context, application = self.build()
        root = self.base / "sdk"
        runtime = self.base / "runtime"
        runtime.mkdir()
        for name in (provider.AGENT, provider.HELPER, profiles.PATCH):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixed product")
        extension = root / provider.EXTENSION
        extension.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(extension, "w") as archive:
            archive.writestr("io/quux/otelc/methods/Runtime.class", b"helper")
        paths = java_project.runtime_classpath(classes, context)
        archive_context.prepare_attempt(paths, context, JAVA, folder, self.environment, generation.execute)
        helpers.prepare(root, paths, context, JAVA, folder, self.environment, generation.execute)
        entry = {"language": "java", "java_backend": "prepared", "java_profile": profiles.ARCHIVES,
                 "path": "src/app/App.java", "otelc_function": "app.App.selected(int)"}
        data = provider.configuration(entry, "http://127.0.0.1:4318", "case")
        manifest = folder / "prepared-application.json"
        selected = {"methods": {"app.App": ["selected"]}, "types": [], "resources": []}
        (runtime / "selection.json").write_text(json.dumps(selected))
        (runtime / "agent.properties").write_text(java_launch.properties(java_launch.agent_values(data, "app.App", "selected", profiles.ARCHIVES)))
        (runtime / "plan.properties").write_text(java_launch.properties(java_launch.plan_values(runtime, data, selected)))
        for plain in (True, False):
            bound = {"manifest": java_launch.identity(manifest), "main_class": application["main_class"],
                     "ordered_classpath": application["classpath"], "bindings": application["bindings"],
                     "classpath": [java_launch.identity(path) for path in java_project.classpath_files(classes, context)],
                     "sources": [java_launch.identity(Path(binding["source"])) for binding in application["bindings"].values()],
                     "archive_resolution": archive_context.expected_resolution(paths, context)}
            tools = {JAVA, root / provider.HELPER}
            if not plain:
                tools |= {self.tools["javap"], root / provider.AGENT, root / provider.EXTENSION, root / profiles.PATCH,
                          runtime / "selection.json", runtime / "agent.properties", runtime / "plan.properties"}
            value = {"schema_version": 2, "language": "java", "plain": plain, "jvm_profile": "diagnostic-no-cds",
                     "agent_diagnostics": None if plain else str(runtime / "agent.log"),
                     "health_report": None if plain else str(runtime / "health.json"),
                     "selection_sha256": None if plain else provider.digest(selected),
                     "argv": java_launch.expected_argv(root, JAVA, classes, application["main_class"], runtime, data,
                              "app.App", "selected", plain, profiles.ARCHIVES, context=context),
                     "main_class": application["main_class"], "ordered_classpath": application["classpath"],
                     "application": bound, "tooling": [java_launch.identity(path) for path in tools],
                     "java_version": "OpenJDK21", "policy_sha256": provider.digest(data),
                     "loaded_origins": str(runtime / "class-load.log"), "control_socket": None if plain else str(runtime / "control.sock")}
            def verify(item):
                java_launch.verify(item, root=root, project=project, folder=folder, tools=self.tools,
                                   runtime=runtime, entry=entry, data=data, plain=plain, context=context)
            verify(value)
            for fault in ("schema", "missing-tool", "feature", "member", "extra"):
                changed = copy.deepcopy(value)
                if fault == "schema": changed["schema_version"] = 1
                elif fault == "missing-tool": changed["tooling"] = [row for row in changed["tooling"] if row["path"] != str(root / provider.HELPER)]
                elif fault == "feature": changed["application"]["archive_resolution"]["jdk_feature"] += 1
                elif fault == "member": changed["application"]["archive_resolution"]["archives"][0]["classes"]["dep.Flags"]["entry"] = "dep/Flags.class"
                else: changed["application"]["unknown"] = 1
                with self.subTest(plain=plain, fault=fault), self.assertRaises(ValueError):
                    verify(changed)


if __name__ == "__main__":
    unittest.main()
