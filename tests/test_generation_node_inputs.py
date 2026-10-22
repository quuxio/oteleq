"""Retained source journals and compiler files cannot drift after SDK verification."""

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import node_inputs as inputs


class NodeInputTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.project = self.base / "project"
        self.project.mkdir()
        self.source = self.project / "app.cts"
        self.source.write_text("function add(value:number){return value+1;}\n")
        self.provider = self.base / "provider"
        for name in ("node_modules/typescript-api/lib/typescript.js",
                     "node_modules/@typescript/typescript-darwin-arm64/lib/tsc"):
            path = self.provider / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixed installed compiler fixture")
        self.counter = 0

    def artifact(self, raw, runtime, prefix, path=None):
        content = raw.encode() if isinstance(raw, str) else raw
        digest = hashlib.sha256(content).hexdigest()
        filename = runtime / (prefix + "-module-" + digest + ".txt")
        filename.write_bytes(content)
        return {"file": str(filename), "sha256": digest, "size": len(content), **({"path": str(path)} if path else {})}

    def fixture(self, backend="native", plain=False):
        """Compiler protocol fixtures do not execute or emulate the compiler itself."""
        self.counter += 1
        runtime = self.base / ("runtime-" + str(self.counter))
        runtime.mkdir()
        prefix = "node-plain" if plain else "node"
        value = {"runtime": str(runtime), "project": str(self.project), "provider": str(self.provider),
                 "entry": str(self.source), "compiler": backend, "plain": plain, "language": "typescript"}
        original = self.source.read_bytes()
        digest = hashlib.sha256(original).hexdigest()
        read = {"kind": "source", "path": str(self.source), "requested_path": str(self.source),
                "sha256": digest, "text_sha256": digest, "size": len(original)}
        request = {"kind": "module_requested", "path": str(self.source), "logical_source": "app.cts",
                   "url": self.source.as_uri(), "module_type": "typescript", "load_id": 1}
        private = self.base / ("otelc-native-typescript-" + str(self.counter))
        settings = {"target": 9, "module": "node16" if backend == "native" else 1,
                    "sourceMap": True, "inlineSourceMap": False, "inlineSources": True, "removeComments": False,
                    "declaration": False, "declarationMap": False, "emitDeclarationOnly": False, "noEmit": False,
                    "allowImportingTsExtensions": False, "rewriteRelativeImportExtensions": False,
                    "verbatimModuleSyntax": False, "isolatedModules": True}
        if backend == "native":
            settings.update(rootDir=str(private), outDir=str(private / "emitted"), noEmitOnError=False,
                            noCheck=True, noResolve=True, incremental=False, composite=False, types=[], moduleResolution="node16")
        options = {"compilerOptions": settings, "files": [str(private / "app.cts")]} if backend == "native" else settings
        files = {"input": self.artifact(original, runtime, prefix, private / "app.cts" if backend == "native" else self.source),
                 "options": self.artifact(json.dumps(options), runtime, prefix, private / "tsconfig.json" if backend == "native" else None),
                 "output": self.artifact('function add(value){return value+1;}', runtime, prefix, private / "emitted/app.cjs" if backend == "native" else None),
                 "map": self.artifact('{"version":3,"mappings":""}', runtime, prefix, private / "emitted/app.cjs.map" if backend == "native" else None)}
        if backend == "native":
            files["preparation_map"] = self.artifact(json.dumps({"file": "app.cts", "sources": [str(self.source)], "sourcesContent": [original.decode()]}), runtime, prefix)
        executable = self.provider / ("node_modules/@typescript/typescript-darwin-arm64/lib/tsc" if backend == "native" else "node_modules/typescript-api/lib/typescript.js")
        compiler = {"backend": backend, "version": "7.0.2" if backend == "native" else "6.0.3",
                    "compiler_path": str(executable), "cwd": str(self.project), "files": files,
                    "transformer_profile": "none" if plain else "original-identities-v1"}
        compiler.update({"argv": [str(executable), "--project", files["options"]["path"]]} if backend == "native" else {"method": "transpileModule"})
        emission = {**{key: request[key] for key in ("path", "url", "logical_source", "load_id")}, "format": "commonjs",
                    "source_sha256": digest, "output_file": files["output"]["file"], "sha256": files["output"]["sha256"],
                    "size": files["output"]["size"]}
        compiled = {**emission, "kind": "compiled", "map_file": files["map"]["file"],
                    "map_sha256": files["map"]["sha256"], "map_size": files["map"]["size"]}
        records = [request, read, {"kind": "compilation", "path": str(self.source), "load_id": 1, "compiler": compiler},
                   compiled, {**emission, "kind": "loaded" if plain else "instrumented"}]
        manifest = {"runtime": {"platform": "darwin", "architecture": "arm64"}}
        self.journal(records, value)
        return records, value, manifest

    def journal(self, records, value):
        prefix = "node-plain" if value["plain"] else "node"
        filename = Path(value["runtime"]) / (prefix + "-sources.jsonl")
        filename.write_text("".join(json.dumps(record) + "\n" for record in records))
        return filename

    def test_native_and_api_plain_and_selected_records_keep_complete_artifacts(self):
        for backend in ("native", "api"):
            for plain in (False, True):
                with self.subTest(backend=backend, plain=plain):
                    records, value, manifest = self.fixture(backend, plain)
                    inputs.verify(records, value, manifest)

    def test_changed_or_linked_artifacts_and_namespace_substitution_refuse(self):
        records, value, _ = self.fixture()
        record = records[2]["compiler"]["files"]["input"]
        runtime = Path(value["runtime"])
        for changed in ({**record, "file": str(self.source)}, {**record, "size": True}, {**record, "sha256": "g" * 64}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                inputs.artifact(changed, runtime, "node")
        filename = Path(record["file"])
        filename.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            inputs.artifact(record, runtime, "node")
        filename.unlink()
        filename.symlink_to(self.source)
        with self.assertRaises(ValueError):
            inputs.artifact(record, runtime, "node")

    def test_raw_journal_must_match_verified_records_and_end_at_a_complete_line(self):
        records, value, manifest = self.fixture()
        filename = self.journal(records, value)
        filename.write_text(filename.read_text().rstrip())
        with self.assertRaisesRegex(ValueError, "truncated"):
            inputs.verify(records, value, manifest)
        changed = copy.deepcopy(records)
        changed[0]["logical_source"] = "other.cts"
        self.journal(changed, value)
        with self.assertRaisesRegex(ValueError, "actual read journal"):
            inputs.verify(records, value, manifest)

    def test_fixed_compiler_tool_profile_and_original_input_cannot_be_substituted(self):
        for backend in ("native", "api"):
            records, value, manifest = self.fixture(backend)
            for key, changed in (("version", "unknown"), ("compiler_path", str(self.source)),
                                 ("cwd", str(self.base)), ("transformer_profile", "none"),
                                 ("argv" if backend == "native" else "method", ["arbitrary"] if backend == "native" else "arbitrary")):
                edited = copy.deepcopy(records)
                edited[2]["compiler"][key] = changed
                self.journal(edited, value)
                with self.subTest(backend=backend, key=key), self.assertRaises(ValueError):
                    inputs.verify(edited, value, manifest)
            edited = copy.deepcopy(records)
            edited[2]["compiler"]["files"].pop("output")
            self.journal(edited, value)
            with self.assertRaises(ValueError):
                inputs.verify(edited, value, manifest)
            edited = copy.deepcopy(records)
            edited[1]["text_sha256"] = "0" * 64
            self.journal(edited, value)
            with self.assertRaises(ValueError):
                inputs.verify(edited, value, manifest)

    def test_missing_duplicate_or_foreign_module_phases_refuse_even_when_rehashed(self):
        records, value, manifest = self.fixture()
        variants = [records[:-1], records + [records[-1]], records[1:],
                    [{**records[0], "load_id": True}, *records[1:]],
                    [{**records[0], "url": "file:///foreign.cts"}, *records[1:]],
                    [*records[:3], {**records[3], "path": str(self.project / "other.cts")}, records[4]],
                    [*records[:3], {**records[3], "logical_source": "other.cts"}, records[4]],
                    [*records, {"kind": "unknown"}]]
        for edited in variants:
            self.journal(edited, value)
            with self.subTest(edited=edited), self.assertRaises(ValueError):
                inputs.verify(edited, value, manifest)

    def test_source_and_emission_map_identity_are_rechecked(self):
        records, value, manifest = self.fixture()
        edited = copy.deepcopy(records)
        edited[1]["path"] = str(self.base / "foreign.cts")
        self.journal(edited, value)
        with self.assertRaises(ValueError):
            inputs.verify(edited, value, manifest)
        edited = copy.deepcopy(records)
        edited[3].pop("map_size")
        self.journal(edited, value)
        with self.assertRaisesRegex(ValueError, "emission map"):
            inputs.verify(edited, value, manifest)
        edited = copy.deepcopy(records)
        edited[3]["source_sha256"] = "0" * 64
        self.journal(edited, value)
        with self.assertRaisesRegex(ValueError, "preceding source"):
            inputs.verify(edited, value, manifest)
        edited = [record for record in records if record["kind"] != "compiled"]
        self.journal(edited, value)
        with self.assertRaisesRegex(ValueError, "compiler phase"):
            inputs.verify(edited, value, manifest)

    def test_rehashed_compiler_options_and_output_paths_still_require_the_fixed_recipe(self):
        for backend in ("native", "api"):
            records, value, manifest = self.fixture(backend)
            compiler = records[2]["compiler"]
            original = copy.deepcopy(compiler)
            metadata = compiler["files"]["options"]
            options = json.loads(Path(metadata["file"]).read_bytes())
            settings = options["compilerOptions"] if backend == "native" else options
            settings["noEmit"] = True
            compiler["files"]["options"] = self.artifact(json.dumps(options), Path(value["runtime"]), "node", metadata.get("path"))
            self.journal(records, value)
            with self.subTest(backend=backend), self.assertRaisesRegex(ValueError, "emission flags"):
                inputs.verify(records, value, manifest)
            records[2]["compiler"] = copy.deepcopy(original)
            if backend == "native":
                records[2]["compiler"]["files"]["output"]["path"] = str(self.base / "foreign.cjs")
                message = "output recipe"
            else:
                options["noEmit"] = False
                options["module"] = 200
                records[2]["compiler"]["files"]["options"] = self.artifact(json.dumps(options), Path(value["runtime"]), "node")
                message = "module format"
            self.journal(records, value)
            with self.subTest(backend=backend), self.assertRaisesRegex(ValueError, message):
                inputs.verify(records, value, manifest)

    def test_rehashed_journal_cannot_move_emission_before_compilation(self):
        for backend in ("native", "api"):
            records, value, manifest = self.fixture(backend)
            for indices in ((0, 1, 4, 3, 2), (0, 1, 3, 2, 4), (0, 1, 2, 4, 3)):
                edited = [records[index] for index in indices]
                self.journal(edited, value)
                with self.subTest(backend=backend, order=indices), self.assertRaisesRegex(ValueError, "phase order"):
                    inputs.verify(edited, value, manifest)


if __name__ == "__main__":
    unittest.main()
