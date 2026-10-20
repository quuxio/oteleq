"""Real plain workers in all eight languages write independently observed data."""
from contextlib import redirect_stdout
import argparse
import copy
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "adapters/generation"), str(ROOT / "examples")]
import filesystem_effects as effects
import generation
import harness
import policy
import typed_capture

NATIVE = '''#include <stdio.h>
#include <stdlib.h>
int selected(void){char path[4096];snprintf(path,sizeof(path),"%s/out.bin",getenv("APP_DATA_DIR"));FILE* file=fopen(path,"wb");unsigned char data[]={111,107,0,255};fwrite(data,1,4,file);fclose(file);return 7;}
'''
SOURCES = {
    "c": ("source.c", "int", NATIVE),
    "cpp": ("source.cpp", "int", NATIVE),
    "rust": ("source.rs", "i32", 'fn selected()->i32{let path=std::path::PathBuf::from(std::env::var("APP_DATA_DIR").unwrap()).join("out.bin");std::fs::write(path,[111u8,107,0,255]).unwrap();7}'),
    "go": ("source.go", "int", 'package main\nimport("os";"path/filepath")\nfunc selected() int{if err:=os.WriteFile(filepath.Join(os.Getenv("APP_DATA_DIR"),"out.bin"),[]byte{111,107,0,255},0600);err!=nil{panic(err)};return 7}\n'),
    "java": ("App.java", "int", 'class App{static int selected() throws Exception{java.nio.file.Files.write(java.nio.file.Path.of(java.lang.System.getenv("APP_DATA_DIR"),"out.bin"),new byte[]{111,107,0,(byte)255});return 7;}}'),
    "python": ("source.py", "int", 'import os\nfrom pathlib import Path\ndef selected()->int:\n Path(os.environ["APP_DATA_DIR"],"out.bin").write_bytes(b"ok\\0\\xff")\n return 7\n'),
    "javascript": ("source.mjs", "number", 'import fs from "node:fs";\nfunction selected(){fs.writeFileSync(process.env.APP_DATA_DIR+"/out.bin",Buffer.from([111,107,0,255]));return 7;}\n'),
    "typescript": ("source.mts", "number", 'import fs from "node:fs";\nfunction selected():number{fs.writeFileSync(process.env.APP_DATA_DIR+"/out.bin",Buffer.from([111,107,0,255]));return 7;}\n'),
}


class PlainFilesystemWorkerTests(unittest.TestCase):
    def test_all_eight_real_workers_return_seven_and_capture_exact_binary_file_bytes(self):
        for language, (name, output, source) in SOURCES.items():
            with self.subTest(language=language), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                (folder / name).write_text(source)
                entry = {"language": language, "path": name, "name": "App.selected" if language == "java" else "selected",
                         "output": output, "line": 3 if language == "python" else 1, "parameters": [], "globals": [], "file_functions": [], "package": "", "package_end": len("package main")}
                driver = harness.materialise(folder, entry, [])
                command = self.compile_worker(language, folder, driver)
                configured = policy.validate({"effects": {"filesystem": [{"name": "data", "environment": "APP_DATA_DIR"}]}})
                states, selected = effects.prepare(folder, configured)
                observation = folder / "observation"
                result = subprocess.run(command, cwd=folder, env={**os.environ, **selected, "OTELEQ_OBSERVATION": str(observation), "GOTOOLCHAIN": "local"}, capture_output=True, timeout=30, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, b"")
                captured, complete = effects.finish(states, folder)
                self.assertTrue(complete)
                boundary = json.loads(bytes(captured["filesystem:data"]))
                self.assertEqual(len(boundary["before"]["entries"]), 1)
                file = next(value for value in boundary["after"]["entries"] if value["path_hex"] == b"out.bin".hex())
                self.assertEqual(file["hex"], "6f6b00ff")
                typed = typed_capture.observation(observation.read_bytes(), entry, {"case_id": "case", "function_id": "selected", "fixture_sha256": "a" * 64})
                value = typed["outcome"]["graph"]["roots"]["result"]
                self.assertEqual(struct.unpack('>d', bytes.fromhex(value["bits"]))[0] if value["kind"] == "float" else int(value["value"]), 7)

    def compile_worker(self, language, folder, driver):
        if language in ("python", "javascript", "typescript"):
            return [sys.executable if language == "python" else os.environ.get("OTELC_NODE") or shutil.which("node"), driver]
        binary = folder / "application"
        if language in ("c", "cpp"):
            variable, name = ("OTELC_CLANG", "clang") if language == "c" else ("OTELC_CLANGXX", "clang++")
            compile_command = [os.environ.get(variable) or shutil.which(name), "-std=c11" if language == "c" else "-std=c++17", driver, "-o", binary]
            command = [binary]
        elif language == "rust":
            compile_command = [os.environ.get("OTELC_RUSTC") or shutil.which("rustc"), "--edition=2024", driver, "-o", binary]
            command = [binary]
        elif language == "go":
            compile_command = [os.environ.get("OTELC_GO") or shutil.which("go"), "build", "-o", binary, driver]
            command = [binary]
        else:
            compile_command = [os.environ.get("OTELC_JAVAC") or shutil.which("javac"), "-d", folder, folder / "App.java", driver]
            command = [os.environ.get("OTELC_JAVA") or shutil.which("java"), "-cp", folder, "OteleqDriver"]
        result = subprocess.run(compile_command, cwd=folder, env={**os.environ, "GOTOOLCHAIN": "local"}, capture_output=True, timeout=60, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return command


class FilesystemExecutionTests(unittest.TestCase):
    def test_real_attempt_binds_after_build_preserves_source_and_keeps_incomplete_channels(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary); source = base / "source"; source.mkdir(); sdk = base / "sdk"; sdk.mkdir()
            text = 'import os\nfrom pathlib import Path\ndef sample(link:bool)->int:\n root=Path(os.environ["APP_DATA_DIR"])\n if link:(root/"out").symlink_to(root/"seed.bin")\n else:(root/"out").write_bytes((root/"seed.bin").read_bytes()+b"new")\n return 7\n'
            (source / "source.py").write_text(text)
            config = base / "policy.toml"
            config.write_text('schema_version=1\nlanguages=["python"]\n[[effects.filesystem]]\nname="data"\nenvironment="APP_DATA_DIR"\nfiles=[{path="seed.bin",hex="00ff"}]\n')
            tools = {"python": Path(sys.executable)}
            selected = {"tool:python": "a" * 64}
            with patch.dict(os.environ, {"OTELEQ_EXECUTABLE": sys.executable}), patch.object(generation.capture, "selected_tools", return_value=tools), patch.object(generation.capture, "artefacts", return_value=selected), redirect_stdout(io.StringIO()) as out:
                generation.plan(argparse.Namespace(source=source, otelc_root=sdk, workspace_parent=base, language=None, exclude=[], cases=2, config=config))
                workspace = Path(out.getvalue().strip())
                generation.generate(argparse.Namespace(workspace=workspace))
                _, data = generation.load_workspace(workspace, generated=True)
                entry = next(item for item in data["inventory"] if item["status"] == "ready")
                cases = generation.read(workspace / "tests/corpus.json")
                def build(root, project, candidate, driver, policy_path, selected_tools, environment, *rest):
                    self.assertNotIn("APP_DATA_DIR", environment)
                    return [sys.executable, driver]
                with patch.object(generation.capture, "stable"), patch.object(generation, "build_command", side_effect=build):
                    captured_attempts = {}
                    for case in cases:
                        folder = base / ("attempt-" + str(case["arguments"][0]))
                        result = generation.attempt(workspace, data, entry, case, "baseline", folder, None)
                        captured_attempts[case["arguments"][0]] = result
                        self.assertEqual(result["capture_complete"], not case["arguments"][0])
                        self.assertIn("filesystem:data", result["channels"])
                        captured = json.loads(bytes(result["channels"]["filesystem:data"]))
                        self.assertEqual(captured["before"]["entries"][-1]["hex"], "00ff")
                        self.assertEqual(captured["after"]["complete"], not case["arguments"][0])
                        self.assertTrue((folder / "filesystem-controls.json").is_file())
                frame = copy.deepcopy(captured_attempts[False])
                frame["witness"] = {"functions": {entry["otelc_function"]: 1}}
                def captured(*arguments):
                    arguments[5].mkdir()
                    return frame
                destination = base / "comparison"; destination.mkdir()
                ordinary = next(case for case in cases if case["arguments"] == [False])
                with patch.object(generation, "attempt", side_effect=captured), patch.object(generation, "execute", return_value=subprocess.CompletedProcess([], 0, b'{"verdict":"equivalent_observed"}', b"")):
                    generation.compare_case(workspace, data, entry, ordinary, destination, None)
                bundle = generation.read(destination / "typed-bundle.json")
                self.assertIn("filesystem:data", bundle["scope"]["channels"])
                self.assertEqual(bundle["cases"][0]["baseline"][0]["execution"]["channels"]["filesystem:data"], frame["channels"]["filesystem:data"])
                budget = copy.deepcopy(data)
                observed_folder = base / "attempt-False"
                budget["configuration"]["limits"]["max_capture_bytes"] = (observed_folder / "observation").stat().st_size + 1
                with self.assertRaisesRegex(ValueError, "channel budget"):
                    generation.qualify_attempt(budget, entry, "baseline", observed_folder, subprocess.CompletedProcess([], 0, b"", b""), [], [], "service", None, extra_channels={"filesystem:data": frame["channels"]["filesystem:data"]})
                self.assertEqual((source / "source.py").read_text(), text)
                _, verified = generation.load_workspace(workspace, generated=True)
                self.assertEqual(data["source_manifest"], verified["source_manifest"])


if __name__ == "__main__":
    unittest.main()
