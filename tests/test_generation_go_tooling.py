"""Independent module-hash vectors, fixed tooling queries and immutable bindings."""

from contextlib import ExitStack
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import go_tooling as tooling

BASE = {"go.mod": "922eb7887afdadf05ba634990e3b3367b728c23f8c68c266f0d46a78e71f907a",
        "tool/internal/instrument/apply_func.go": "e38369de3c8a501307f136127e3b3ee98ddc26ed070037bf3965c0e13fe05a43",
        "tool/data/otelc-bundle.tgz": "6800e9d30bcbb0f6b09e02fdd24bcc053505045a2117b2e201ee472b7e86e652"}
MODULE_SUM = "h1:ZEY+X+gezdltq2rydqyuIkI2L12jpwe0OE670PuWjEw="
GO_MOD_SUM = "h1:qkAoaTjraNQN0Q0pZFmZPtUuQ3WVy7ModzSC5+o/eKU="
AFTER = "379e9a0ef892cb857cfd40de0835c035fba5b697321518ff89a871ebde0ffc6b"


def fixture(test, base, *, directory=None):
    """Compact source bytes stub only pinned vendor hashes; real source is qualified separately."""
    stack = ExitStack()
    test.addCleanup(stack.close)
    for name, value in (("MODULE_SUM", MODULE_SUM), ("MODULE_GO_SUM", GO_MOD_SUM),
                        ("PATCH_BEFORE", BASE[tooling.PATCH_FILE]), ("PATCH_AFTER", AFTER)):
        stack.enter_context(patch.object(tooling, name, value))
    stack.enter_context(patch.object(tooling.go_context, "BUNDLE_SHA256", BASE["tool/data/otelc-bundle.tgz"]))
    directory = directory if directory is not None else base / "installed"
    source = directory / "source"
    values = {"go.mod": b"module go.opentelemetry.io/otelc\n",
              tooling.PATCH_FILE: b"fixture patched apply source\n",
              "tool/data/otelc-bundle.tgz": b"fixture bundle\n"}
    for name, data in values.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    compiler = base / "go/bin/go"
    compiler.parent.mkdir(parents=True)
    compiler.write_bytes(b"fixture compiler, never executed")
    compiler.chmod(0o700)
    weaver = directory / "bin/otelc"
    weaver.parent.mkdir()
    weaver.write_bytes(b"fixture private weaver, never executed")
    weaver.chmod(0o700)
    bundle = base / "bundle.tgz"
    bundle.write_bytes(values["tool/data/otelc-bundle.tgz"])
    manifest = {"schema_version": 1, "kind": "otelc.go-weaver-source", "profile": tooling.PATCH_PROFILE,
                "base_module": tooling.MODULE, "base_version": tooling.VERSION,
                "module_sum": MODULE_SUM, "module_go_sum": GO_MOD_SUM, "version": tooling.PRIVATE_VERSION,
                "patch": {"file": tooling.PATCH_FILE, "before_sha256": BASE[tooling.PATCH_FILE], "after_sha256": AFTER},
                "base_files": BASE.copy(), "files": BASE | {tooling.PATCH_FILE: AFTER}}
    metadata = (str(weaver) + ": go1.27.3\n\tpath\t" + tooling.MODULE + "/tool/cmd/otelc\n\tmod\t"
                + tooling.MODULE + "\t(devel)\t\n")
    tools = {"schema_version": 2, "module": tooling.MODULE, "version": tooling.VERSION,
             "module_sum": MODULE_SUM, "module_go_sum": GO_MOD_SUM, "go_version": "go1.27.3",
             "platform": {"GOOS": "darwin", "GOARCH": "arm64"}, "build_metadata": metadata,
             "patch_profile": tooling.PATCH_PROFILE, "version_output": "otelc version " + tooling.PRIVATE_VERSION}
    for name, path in (("go", compiler), ("weaver", weaver), ("bundle", bundle)):
        tools[name], tools[name + "_sha256"] = str(path), hashlib.sha256(path.read_bytes()).hexdigest()
    publish(directory, tools, manifest)
    return directory, compiler, tools, manifest


def publish(directory, tools, manifest):
    raw = (json.dumps(manifest, sort_keys=True) + "\n").encode()
    (directory / tooling.MANIFEST).write_bytes(raw)
    tools["source_manifest_sha256"] = hashlib.sha256(raw).hexdigest()
    (directory / "toolchain.json").write_text(json.dumps(tools) + "\n")


def query(tools, command, cwd, **options):
    """Literal native compiler observations, without executing fixture binaries."""
    if command[1:2] == ["env"]:
        value = json.dumps({"GOROOT": str(Path(tools["go"]).parent.parent), "GOVERSION": "go1.27.3",
                            **tools["platform"], "GOHOSTOS": "darwin", "GOHOSTARCH": "arm64"})
    elif command[1:3] == ["version", "-m"]:
        value = tools["build_metadata"]
    else:
        value = tools["version_output"] + "\n"
    return subprocess.CompletedProcess(command, 0, value.encode(), b"")


class GoToolingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.directory, self.compiler, self.tools, self.manifest = fixture(self, self.base)

    def prepare(self, execute=None):
        return tooling.prepare(self.directory, self.compiler,
                               execute or (lambda *args, **options: query(self.tools, *args, **options)))

    def test_hash1_matches_literal_vectors_and_rejects_ambiguous_names_or_digests(self):
        self.assertEqual(tooling.module_hash(BASE, prefix=tooling.MODULE + "@v1.0.1/"), MODULE_SUM)
        self.assertEqual(tooling.module_hash({"go.mod": BASE["go.mod"]}), GO_MOD_SUM)
        for value in (None, [], {}, {1: "a" * 64}, {"a\nb": "a" * 64}, {"a\rb": "a" * 64},
                      {"../outside": "a" * 64}, {".git/config": "a" * 64}, {"a": 1}, {"a": "A" * 64}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                tooling.module_hash(value)

    def test_fixed_inputs_and_three_native_queries_are_retained_and_sealed(self):
        seen = []
        def execute(command, cwd, **options):
            seen.append(command)
            self.assertEqual(cwd, self.directory)
            self.assertEqual(options, {"max_output_bytes": 1024 * 1024})
            return query(self.tools, command, cwd, **options)
        binding = self.prepare(execute)
        binding.verify()
        self.assertEqual(len(binding.source.identities), 3)
        self.assertEqual([row["command"] for row in binding.queries], seen)
        self.assertEqual(seen[-2:], [[str(self.compiler), "version", "-m", str(self.directory / "bin/otelc")],
                                    [str(self.directory / "bin/otelc"), "version"]])
        binding.tools["platform"]["GOARCH"] = "another"
        with self.assertRaisesRegex(ValueError, "tooling metadata changed"):
            binding.verify()

    def test_inspection_never_executes_a_tool_and_cannot_supply_prepared_queries(self):
        with patch("subprocess.run", side_effect=AssertionError("inspection executed a tool")):
            binding = tooling.read(self.directory, self.compiler)
        self.assertEqual(binding.queries, [])
        with self.assertRaisesRegex(ValueError, "missing.*queries"):
            tooling.checked_queries(binding)

    def test_pins_changed_paths_versions_types_and_binary_bytes_refuse(self):
        original = copy.deepcopy(self.tools)
        for key, value in (("schema_version", True), ("schema_version", 2.0), ("schema_version", 1),
                           ("module_sum", "h1:other"), ("weaver", "/another/tool"), ("go", "/another/go"),
                           ("platform", {"GOOS": False, "GOARCH": "arm64"}), ("extra", True),
                           ("source_manifest_sha256", "0" * 64)):
            changed = {**original, key: value}
            (self.directory / "toolchain.json").write_text(json.dumps(changed))
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                tooling.read(self.directory, self.compiler)
        (self.directory / "toolchain.json").write_text(json.dumps(original))
        self.compiler.write_bytes(b"different compiler")
        with self.assertRaisesRegex(ValueError, "tool bytes differ"):
            tooling.read(self.directory, self.compiler)

    def test_rehashed_other_sources_and_altered_patch_cannot_change_the_upstream_catalogue(self):
        for mutate in (lambda value: value["base_files"].update({"extra.go": "a" * 64}),
                       lambda value: value["files"].update({tooling.PATCH_FILE: "a" * 64}),
                       lambda value: value["patch"].update(before_sha256="0" * 64),
                       lambda value: value.update(extra=True)):
            value = copy.deepcopy(self.manifest)
            mutate(value)
            publish(self.directory, self.tools, value)
            with self.assertRaises(ValueError):
                tooling.read(self.directory, self.compiler)

    def test_accepted_source_files_queries_and_original_file_facts_cannot_be_repaired(self):
        binding = self.prepare()
        path = self.directory / "source/go.mod"
        path.write_bytes(path.read_bytes())
        with self.assertRaisesRegex(ValueError, "source changed"):
            binding.verify()
        binding = self.prepare()
        binding.queries[0]["stdout"] = "{}"
        with self.assertRaisesRegex(ValueError, "tooling metadata changed"):
            binding.verify()
        binding = self.prepare()
        path = self.directory / "toolchain.json"
        path.write_bytes(path.read_bytes())
        with self.assertRaisesRegex(ValueError, "input changed"):
            binding.verify()

    def test_source_changes_during_queries_vcs_inputs_links_and_nonexecutables_refuse(self):
        def changed(command, cwd, **options):
            value = query(self.tools, command, cwd, **options)
            (self.directory / "source/go.mod").write_bytes((self.directory / "source/go.mod").read_bytes())
            return value
        with self.assertRaisesRegex(ValueError, "source changed"):
            self.prepare(changed)
        vcs = self.directory / "source/.git"
        vcs.mkdir()
        with self.assertRaisesRegex(ValueError, "VCS input"):
            tooling.read(self.directory, self.compiler)
        vcs.rmdir()
        link = self.directory / "source/linked"
        link.symlink_to(self.base / "outside")
        with self.assertRaises(ValueError):
            tooling.read(self.directory, self.compiler)
        link.unlink()
        self.compiler.chmod(0o600)
        with self.assertRaisesRegex(ValueError, "not executable"):
            tooling.read(self.directory, self.compiler)

    def test_query_errors_foreign_native_metadata_and_changed_command_recipes_refuse(self):
        for change in (lambda value: setattr(value, "returncode", 7),
                       lambda value: setattr(value, "stderr", b"tool error"),
                       lambda value: setattr(value, "stdout", b"x" * (1024 * 1024 + 1)),
                       lambda value: setattr(value, "stdout", b"{}")):
            def execute(command, cwd, **options):
                value = query(self.tools, command, cwd, **options)
                change(value)
                return value
            with self.assertRaises(ValueError):
                self.prepare(execute)
        binding = self.prepare()
        for index, value in ((0, "{}"), (1, "wrong metadata"), (2, "otelc version v1.0.1")):
            rows = copy.deepcopy(binding.queries)
            rows[index]["stdout"] = value
            changed = tooling.binding(binding.directory, binding.tools, binding.source, binding.reads, rows)
            with self.assertRaises(ValueError):
                changed.verify()
        rows = copy.deepcopy(binding.queries)
        rows[0]["command"] = ["another", "command"]
        with self.assertRaisesRegex(ValueError, "recipe changed"):
            tooling.binding(binding.directory, binding.tools, binding.source, binding.reads, rows).verify()
