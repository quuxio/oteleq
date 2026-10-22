"""Selected JDK runtime members, literal compiler reads and exact metadata bytes."""
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
from unittest.mock import patch
import warnings
import zipfile

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import generation
import java_archives as archives
import java_classpath as classpath


class JavaRuntimeArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="java runtime archives ")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name).resolve()
        cls.java = Path(shutil.which(os.environ.get("OTELC_JAVA", "java"))).resolve()
        cls.javac = str(cls.java.parent / "javac")
        cls.environment = {key: value for key, value in os.environ.items() if key not in archives.JAVA_OPTIONS}
        cls.classes = cls.root / "application"
        cls.classes.mkdir()
        cls.marker = cls.root / "initialised"
        cls.variants = {}
        for value in (8, 9, 17, 21, 22):
            folder = cls.root / str(value)
            folder.mkdir()
            source = folder / "Flags.java"
            source.write_text('package dep; public class Flags { public static final int VALUE=' + str(value)
                              + '; public static int value(){return ' + str(value) + ';} static { try {'
                              + 'java.nio.file.Files.write(java.nio.file.Paths.get('
                              + json.dumps(str(cls.marker)) + '),"ran".getBytes(java.nio.charset.StandardCharsets.UTF_8));'
                              + '} catch(java.io.IOException failure){throw new ExceptionInInitializerError(failure);} } }')
            subprocess.run([cls.javac, "--release", "8", "-d", str(folder), str(source)],
                           capture_output=True, check=True, env=cls.environment, timeout=30)
            cls.variants[value] = (folder / "dep/Flags.class").read_bytes()
        cls.matrix = {}
        recipes = {
            "ordinary": (None, []),
            "inactive": (None, [9, 17, 21, 22]),
            "false": (b"false", [9, 17, 21]),
            "active": (b"true", [9, 17, 21, 22]),
            "intermediate": (b"true", [9, 17, 22]),
            "future": (b"true", [22]),
            "version-only": (b"true", [9]),
            "folded": (b"tr\r\n ue", [21]),
            "identical": (b"true", [21]),
        }
        for name, (attribute, versions) in recipes.items():
            jar = cls.root / (name + ".jar")
            members = {} if name == "version-only" else {"dep/Flags.class": cls.variants[8]}
            for version in versions:
                members[f"META-INF/versions/{version}/dep/Flags.class"] = cls.variants[8 if name == "identical" else version]
            with zipfile.ZipFile(jar, "w") as archive:
                manifest = b"Manifest-Version: 1.0\r\n"
                if attribute is not None:
                    manifest += b"Multi-Release: " + attribute + b"\r\n"
                archive.writestr(classpath.MANIFEST, manifest + b"\r\n")
                for entry, data in members.items():
                    archive.writestr(entry, data)
                archive.writestr("resource.txt", "8")
                for version in versions:
                    archive.writestr(f"META-INF/versions/{version}/resource.txt", str(version))
            cls.matrix[name] = jar

    def setUp(self):
        self.folder = self.root / self._testMethodName
        self.folder.mkdir()
        self.marker.unlink(missing_ok=True)

    def inspect(self, name: str) -> dict:
        jar = self.matrix[name]
        paths = [self.classes, jar]
        result = archives.inspect(paths, self.java, self.folder / name, self.environment, generation.execute)
        self.assertFalse(self.marker.exists(), "metadata inspection initialised application code")
        return result

    def test_actual_runtime_members_match_plain_jvm_methods_and_resources(self):
        # The plain JVM outcome is independent of both producer and consumer metadata.
        for name, jar in self.matrix.items():
            with self.subTest(name=name):
                record = self.inspect(name)
                resolution = record["resolution"]
                self.assertEqual(resolution["jdk_feature"], 21)
                selected = resolution["archives"][0]
                self.assertEqual(selected["classpath_index"], 1)
                member = selected["classes"]["dep.Flags"]
                with zipfile.ZipFile(jar) as source:
                    data = source.read(member["entry"])
                self.assertEqual(hashlib.sha256(data).hexdigest(), member["sha256"])
                values = [value for value, candidate in self.variants.items() if data == candidate]
                self.assertEqual(len(values), 1)
                application = self.folder / ("App-" + name + ".java")
                application.write_text('class App { public static void main(String[] args) throws Exception {'
                                       'System.out.print(dep.Flags.value()+":"+new String('
                                       'App.class.getClassLoader().getResourceAsStream("resource.txt").readAllBytes()));}}')
                result = subprocess.run([str(self.java), "-cp", str(jar), str(application)],
                                        capture_output=True, check=True, env=self.environment, timeout=30)
                resource = 21 if name == "identical" else values[0]
                self.assertEqual(result.stdout, f"{values[0]}:{resource}".encode())
                self.marker.unlink()

    def test_literal_compiler_member_can_differ_from_runtime_member(self):
        record = self.inspect("folded")
        jar = self.matrix["folded"]
        project = self.folder / "source"
        products = self.folder / "products"
        project.mkdir()
        products.mkdir()
        source = project / "App.java"
        source.write_text('class App { static int selected(){return dep.Flags.VALUE;} }')
        command = [str(self.java), "-cp", str(self.classes),
                   str(REPO / "adapters/generation/OteleqCompile.java"), "--context-v2",
                   str(project), str(products), "1", str(project), "1", str(jar), str(source)]
        result = subprocess.run(command, capture_output=True, check=True, env=self.environment, timeout=30)
        reads = json.loads(result.stdout)["class_reads_sha256"]
        entry = {"path": str(jar), "kind": "jar", "classes": record["resolution"]["archives"][0]["classes"],
                 "members": record["raw_archives"][str(jar)]["members"]}
        classpath.class_reads(reads, [entry])
        for uri, digest in reads.items():
            with self.subTest(uri=uri):
                self.assertIn(digest, entry["members"].values())
        bad = {next(iter(reads)): "0" * 64}
        with self.assertRaisesRegex(ValueError, "different or undeclared"):
            classpath.class_reads(bad, [entry])
        self.assertFalse(self.marker.exists())

    def test_exact_metadata_view_uses_runtime_bytes_and_preserves_every_archive(self):
        for name in ("active", "folded", "identical"):
            with self.subTest(name=name):
                record = self.inspect(name)
                jar = self.matrix[name]
                original = jar.read_bytes()
                view = archives.materialise(record, [self.classes, jar], self.folder / (name + "-view"),
                                            java=self.java, folder=self.folder / name)
                self.assertEqual(view[0], self.classes)
                member = record["resolution"]["archives"][0]["classes"]["dep.Flags"]
                with zipfile.ZipFile(view[1]) as metadata:
                    self.assertEqual(hashlib.sha256(metadata.read("dep/Flags.class")).hexdigest(), member["sha256"])
                javap = str(self.java.parent / "javap")
                result = subprocess.run([javap, "-constants", "-cp", os.pathsep.join(map(str, view)), "dep.Flags"],
                                        capture_output=True, check=True, env=self.environment, timeout=30)
                expected = 8 if member["sha256"] == hashlib.sha256(self.variants[8]).hexdigest() else 21
                self.assertIn(f"VALUE = {expected};".encode(), result.stdout)
                self.assertEqual(jar.read_bytes(), original)
                self.assertFalse(self.marker.exists())

    def test_equal_bytes_do_not_allow_a_different_member_identity(self):
        record = self.inspect("identical")
        claim = copy.deepcopy(record["resolution"])
        claim["archives"][0]["classes"]["dep.Flags"]["entry"] = "dep/Flags.class"
        with self.assertRaisesRegex(ValueError, "differs from the selected JDK"):
            archives.verify(claim, record, [self.classes, self.matrix["identical"]],
                            java=self.java, folder=self.folder / "identical")

    def test_closed_schema_full_classpath_indices_and_jdk_feature_are_bound(self):
        record = self.inspect("active")
        paths = [self.classes, self.matrix["active"]]
        faults = ("schema", "feature", "extra", "missing", "index", "sha", "member", "binary", "unknown", "multi")
        for fault in faults:
            claim = copy.deepcopy(record["resolution"])
            archive = claim["archives"][0]
            if fault == "schema": claim["schema_version"] = True
            elif fault == "feature": claim["jdk_feature"] += 1
            elif fault == "extra": claim["unexpected"] = True
            elif fault == "missing": claim["archives"] = []
            elif fault == "index": archive["classpath_index"] = 0
            elif fault == "sha": archive["sha256"] = "0" * 64
            elif fault == "member": archive["classes"]["dep.Flags"]["entry"] = "absent.class"
            elif fault == "binary": archive["classes"]["../outside"] = archive["classes"].pop("dep.Flags")
            elif fault == "unknown": archive["unknown"] = 0
            else: archive["multi_release"] = 1
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                archives.verify(claim, record, paths, java=self.java, folder=self.folder / "active")
        for claim in (None, [], 0, True, "record"):
            with self.subTest(claim=claim), self.assertRaisesRegex(ValueError, "unsupported resolution"):
                archives.verify(claim, record, paths, java=self.java, folder=self.folder / "active")

    def test_duplicate_inputs_ambient_options_and_existing_outputs_refuse(self):
        jar = self.matrix["active"]
        for key in archives.JAVA_OPTIONS:
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "ambient"):
                archives.inspect([jar], self.java, self.folder / key, {key: ""}, generation.execute)
        with self.assertRaisesRegex(ValueError, "ordered classpath"):
            archives.catalogues([jar, jar])
        with self.assertRaisesRegex(ValueError, "new and outside"):
            archives.inspect([jar], self.java, self.folder, self.environment, generation.execute)
        for key in ("jdk.util.jar.version", "jdk.util.jar.enableMultiRelease"):
            result = subprocess.run([str(self.java), "-D" + key + "=8", "-cp", str(self.classes),
                                     str(archives.FRONTEND), str(jar)], capture_output=True,
                                    env=self.environment, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b"default JDK selection", result.stderr)

    def test_changed_retained_jars_tools_and_failed_probes_refuse(self):
        jar = self.folder / "copy.jar"
        shutil.copyfile(self.matrix["active"], jar)
        paths = [self.classes, jar]
        record = archives.inspect(paths, self.java, self.folder / "probe", self.environment, generation.execute)
        original = jar.read_bytes()
        with zipfile.ZipFile(jar, "a") as archive:
            archive.writestr("changed-resource", "changed")
        with self.assertRaisesRegex(ValueError, "inputs changed"):
            archives.verify(record["resolution"], record, paths, java=self.java, folder=self.folder / "probe")
        jar.write_bytes(original)
        frontend = Path(next(path for path in record["inputs_sha256"] if path.endswith(".java")))
        frontend.write_text(frontend.read_text() + "\n// changed\n")
        with self.assertRaisesRegex(ValueError, "inputs changed"):
            archives.verify(record["resolution"], record, paths, java=self.java, folder=self.folder / "probe")
        def failed(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 1, b"", b"failed")
        with self.assertRaisesRegex(ValueError, "resolution failed"):
            archives.inspect(paths, self.java, self.folder / "failed", self.environment, failed)

    def test_raw_member_catalogue_refuses_unsafe_implicit_and_unbounded_inputs(self):
        recipes = ({"../Flags.class": b"class"}, {"META-INF/INDEX.LIST": b"index"},
                   {classpath.MANIFEST: b"Manifest-Version: 1.0\r\nClass-Path: hidden.jar\r\n\r\n"})
        for index, members in enumerate(recipes):
            jar = self.folder / f"bad-{index}.jar"
            with zipfile.ZipFile(jar, "w") as archive:
                for name, data in members.items(): archive.writestr(name, data)
            with self.subTest(index=index), self.assertRaises(ValueError):
                classpath.jar_members(jar)
        duplicate = self.folder / "duplicate.jar"
        with warnings.catch_warnings(), zipfile.ZipFile(duplicate, "w") as archive:
            warnings.simplefilter("ignore", UserWarning)
            archive.writestr("Flags.class", b"a")
            archive.writestr("Flags.class", b"b")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            classpath.jar_members(duplicate)
        for key in ("MAX_CLASS_BYTES", "MAX_TOTAL_BYTES", "MAX_FILES"):
            with self.subTest(limit=key), patch.object(classpath, key, 0), self.assertRaises(ValueError):
                classpath.jar_members(self.matrix["active"])
        malformed = self.folder / "malformed.jar"
        malformed.write_bytes(b"not a jar")
        with self.assertRaisesRegex(ValueError, "invalid JAR"):
            classpath.jar_members(malformed)

    def test_missing_tool_hashes_changed_commands_and_forged_local_results_refuse(self):
        record = self.inspect("active")
        paths = [self.classes, self.matrix["active"]]
        probe = self.folder / "active"
        for fault in ("missing-tool", "extra-tool", "command", "unknown-field", "result"):
            edited = copy.deepcopy(record)
            if fault == "missing-tool":
                del edited["inputs_sha256"][str(self.java)]
            elif fault == "extra-tool":
                edited["inputs_sha256"]["/not/a/selected/tool"] = "0" * 64
            elif fault == "command":
                edited["argv"][0] = "/not/the/selected/java"
            elif fault == "unknown-field":
                edited["unknown"] = 0
            else:
                edited["resolution"]["archives"][0]["multi_release"] = False
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                archives.verify(edited["resolution"], edited, paths, java=self.java, folder=probe)

    def test_metadata_view_preserves_case_and_unicode_distinct_class_names(self):
        names = ("Foo", "foo", "Caf\u00e9", "Cafe\u0301")
        expected = {}
        jar = self.folder / "distinct.jar"
        with zipfile.ZipFile(jar, "w") as target:
            for index, name in enumerate(names):
                folder = self.folder / str(index)
                folder.mkdir()
                source = folder / (name + ".java")
                source.write_text("package distinct; public class " + name
                                  + " { public static final int VALUE=" + str(index + 7) + "; }")
                subprocess.run([self.javac, "-encoding", "UTF-8", "-d", str(folder), str(source)],
                               capture_output=True, check=True, env=self.environment, timeout=30)
                member = "distinct/" + name + ".class"
                data = (folder / member).read_bytes()
                target.writestr(member, data)
                expected[member] = hashlib.sha256(data).hexdigest()
        original = jar.read_bytes()
        paths = [self.classes, jar]
        probe = self.folder / "probe"
        record = archives.inspect(paths, self.java, probe, self.environment, generation.execute)
        view = archives.materialise(record, paths, self.folder / "view", java=self.java, folder=probe)[1]
        if view.is_dir():
            observed = {member: classpath.digest(view / member) for member in expected}
        else:
            with zipfile.ZipFile(view) as archive:
                observed = {name: hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist()}
        self.assertEqual(observed, expected)
        self.assertEqual(view.suffix, ".jar")
        repeated = archives.materialise(record, paths, self.folder / "repeated-view", java=self.java, folder=probe)[1]
        self.assertEqual(view.read_bytes(), repeated.read_bytes())
        with self.assertRaisesRegex(ValueError, "new and outside"):
            archives.materialise(record, paths, self.folder / "view", java=self.java, folder=probe)
        for index, name in enumerate(names):
            result = subprocess.run([str(self.java.parent / "javap"), "-constants", "-cp", str(view), "distinct." + name],
                                    capture_output=True, check=True, env=self.environment, timeout=30)
            self.assertIn(f"VALUE = {index + 7};".encode(), result.stdout)
        self.assertEqual(jar.read_bytes(), original)

    def test_ordinary_generation_still_refuses_unqualified_versioned_jars(self):
        for name, jar in self.matrix.items():
            if name == "ordinary":
                self.assertIn("dep.Flags", classpath.inspect(jar)["classes"])
                continue
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "qualified producer profile"):
                classpath.inspect(jar)

    def test_full_classpath_indices_package_metadata_and_duplicate_classes(self):
        package = self.folder / "package-info.java"
        package.write_text("@Deprecated package metadata;\n")
        compiled = self.folder / "package"
        subprocess.run([self.javac, "-d", str(compiled), str(package)],
                       capture_output=True, check=True, env=self.environment, timeout=30)
        jar = self.folder / "metadata.jar"
        with zipfile.ZipFile(jar, "w") as source:
            source.writestr("metadata/package-info.class", (compiled / "metadata/package-info.class").read_bytes())
            source.writestr("module-info.class", b"ignored module metadata")
            source.writestr("META-INF/irrelevant.class", b"ignored metadata")
        intervening = self.folder / "intervening"
        intervening.mkdir()
        paths = [self.classes, self.matrix["ordinary"], intervening, jar]
        record = archives.inspect(paths, self.java, self.folder / "indexed", self.environment, generation.execute)
        values = record["resolution"]["archives"]
        self.assertEqual([row["classpath_index"] for row in values], [1, 3])
        self.assertEqual(set(values[1]["classes"]), {"metadata.package-info"})
        with self.assertRaisesRegex(ValueError, "duplicate class definitions"):
            archives.inspect([self.matrix["ordinary"], self.matrix["active"]], self.java,
                             self.folder / "duplicates", self.environment, generation.execute)


if __name__ == "__main__":
    unittest.main()
