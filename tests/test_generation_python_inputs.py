"""Installed Python catalogue records real bytes, aliases and bounded gaps."""

import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import python_inputs as inputs


def fake_provider(root: Path) -> tuple[Path, Path]:
    sdk, installed = root / "sdk", root / "installed"
    names = [*inputs.REQUIRED, "bin/quux-otelc", "requirements.txt", "requirements-dev.txt",
             "ci/build_python_inputs.py", *("native/python/" + name for name in inputs.NATIVE_SOURCES),
             "build/tools/python-inputs/fixed/build.json", "build/tools/python-inputs/fixed/otelc-python-inputs",
             "build/tools/python-inputs/fixed/libotelc_python_inputs.so"]
    for name in names:
        path = sdk / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    installed.mkdir()
    (installed / "sdk.py").write_text("wheel source")
    (installed / "sdk.dist-info").mkdir()
    (installed / "sdk.dist-info/RECORD").write_text("metadata is also pinned")
    return sdk, installed


class PythonInputsTests(unittest.TestCase):
    def test_native_encoder_builder_dependency_is_inventoried_without_admitting_a_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            sdk, installed = fake_provider(Path(temporary))
            helper = sdk / "ci/native_encoder.py"
            helper.write_text("maintained builder dependency")
            with patch.object(inputs, "dependency_roots", return_value=[installed]):
                before = inputs.artefacts(sdk, {"python": Path(sys.executable)})
                self.assertEqual(before["ci/native_encoder.py"], hashlib.sha256(helper.read_bytes()).hexdigest())
                helper.write_text("changed builder dependency")
                self.assertNotEqual(inputs.artefacts(sdk, {"python": Path(sys.executable)}), before)
                helper.unlink(); helper.symlink_to("missing.py")
                with self.assertRaises(FileNotFoundError):
                    inputs.artefacts(sdk, {"python": Path(sys.executable)})

    def test_selected_venv_spelling_and_explicit_site_paths_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            prefix = Path(temporary)
            python = prefix / "bin/python"
            (prefix / "pyvenv.cfg").write_text("virtual environment")
            with patch.object(inputs.sys, "executable", str(python)), \
                 patch.object(inputs.sysconfig, "get_paths", return_value={"purelib": "/explicit", "platlib": "/explicit"}) as paths:
                self.assertEqual(inputs.dependency_roots(python), [Path("/explicit")])
                paths.assert_called_once_with(scheme="venv", vars={"base": str(prefix), "platbase": str(prefix)})
            (prefix / "pyvenv.cfg").unlink()
            with patch.object(inputs.sys, "executable", str(python)), \
                 patch.object(inputs.sysconfig, "get_paths", return_value={"purelib": "/pure", "platlib": "/plat"}) as paths:
                self.assertEqual(inputs.dependency_roots(python), [Path("/pure"), Path("/plat")])
                paths.assert_called_once_with()
            with self.assertRaisesRegex(ValueError, "venv spelling"):
                inputs.dependency_roots(prefix / "other-python")

    def test_catalogue_preserves_installed_bytes_sources_products_and_literal_file_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            sdk, installed = fake_provider(Path(temporary))
            (installed / "alias.py").symlink_to("sdk.py")
            with patch.object(inputs, "dependency_roots", return_value=[installed]):
                tools = {"python": Path(sys.executable)}
                before = inputs.artefacts(sdk, tools)
                self.assertIn("otelc/python_recipe.py", before)
                self.assertIn("build/tools/python-inputs/fixed/build.json", before)
                name = "installed:" + str(installed) + ":alias.py"
                self.assertEqual(before[name], hashlib.sha256(b"wheel source").hexdigest())
                self.assertEqual(before["link-target:" + name], hashlib.sha256(b"sdk.py").hexdigest())
                (installed / "sdk.dist-info/RECORD").write_text("changed installed metadata")
                self.assertNotEqual(inputs.artefacts(sdk, tools), before)

    def test_tool_link_spelling_and_target_are_both_retained(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sdk, installed = fake_provider(root)
            binary, link = root / "python-real", root / "python"
            binary.write_bytes(b"interpreter")
            link.symlink_to(binary.name)
            with patch.object(inputs, "dependency_roots", return_value=[installed]):
                result = inputs.artefacts(sdk, {"python": link})
            self.assertEqual(result["tool:python"], hashlib.sha256(b"interpreter").hexdigest())
            self.assertEqual(result["tool-link:python"], hashlib.sha256(os.fsencode(binary.name)).hexdigest())

    def test_missing_api_or_prebuilt_product_does_not_trigger_a_build(self):
        for name in ("otelc/prepared_python.py", "native/python/CodeCapture.c", "build/tools/python-inputs/fixed/otelc-python-inputs"):
            with tempfile.TemporaryDirectory() as temporary:
                sdk, installed = fake_provider(Path(temporary))
                (sdk / name).unlink()
                with patch.object(inputs, "dependency_roots", return_value=[installed]), self.assertRaises(ValueError):
                    inputs.artefacts(sdk, {"python": Path(sys.executable)})

    def test_unreadable_trees_and_missing_roots_are_not_empty_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "missing or linked"):
                inputs.files(root / "missing")
            def denied(directory, onerror):
                onerror(PermissionError("denied"))
            with patch.object(inputs.os, "walk", denied), self.assertRaisesRegex(PermissionError, "denied"):
                inputs.files(root)

    def test_bytecode_is_outside_scope_but_unexpected_links_and_special_files_refuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "__pycache__").mkdir()
            (root / "__pycache__/cached.pyc").write_bytes(b"cache")
            (root / "cache.pyc").write_bytes(b"cache")
            (root / "source.py").write_text("source")
            (root / "data.txt").write_text("data")
            self.assertEqual(inputs.files(root, suffixes={".py"}), [root / "source.py"])
            link = root / "linked"
            link.symlink_to(root / "__pycache__", target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "linked input directory"):
                inputs.files(root)
            link.unlink()
            fifo = root / "fifo"
            os.mkfifo(fifo)
            with self.assertRaisesRegex(ValueError, "non-regular"):
                inputs.catalogue([("fifo", fifo, root)])

    def test_file_links_cannot_escape_scope_or_name_a_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inside, outside = root / "inside", root / "outside.py"
            inside.mkdir(); outside.write_text("outside")
            link = inside / "link.py"
            link.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "escapes"):
                inputs.catalogue([("link", link, inside)])
            link.unlink(); link.symlink_to(inside)
            with self.assertRaisesRegex(ValueError, "regular file"):
                inputs.catalogue([("link", link, inside)])

    def test_declared_count_and_byte_budgets_refuse_before_hashing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "input.py"
            path.write_bytes(b"too large")
            with patch.object(inputs, "MAX_FILES", 0):
                with self.assertRaisesRegex(ValueError, "file count"):
                    inputs.files(root)
                with self.assertRaisesRegex(ValueError, "file count"):
                    inputs.catalogue([("input", path, root)])
            with patch.object(inputs, "MAX_BYTES", 1), patch.object(inputs.capture, "file_digest") as digest:
                with self.assertRaisesRegex(ValueError, "input bytes"):
                    inputs.catalogue([("input", path, root)])
                digest.assert_not_called()
