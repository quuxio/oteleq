"""Independent data fixtures, descriptor capture, bounded gaps and required channels."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "adapters/generation"), str(ROOT / "examples")]
import filesystem_effects as effects
import policy


def configuration(**changes):
    return policy.validate({"effects": {"filesystem": [{"name": "data", "environment": "APP_DATA_DIR", **changes}]}})


class FilesystemEffectTests(unittest.TestCase):
    def test_defaults_multiple_roots_and_binary_seed_policy_are_frozen(self):
        first, second = policy.validate({}), policy.validate({})
        self.assertEqual(first["effects"], {"filesystem": []})
        first["effects"]["filesystem"].append({})
        self.assertEqual(second, policy.DEFAULTS)
        supplied = {"effects": {"filesystem": [{"name": "data", "environment": "APP_DATA_DIR", "files": [{"path": "nested/seed.bin", "hex": "00FF", "mode": 0o640}]},
                                                 {"name": "cache", "environment": "APP_CACHE_DIR"}]}}
        result = policy.validate(supplied)
        self.assertEqual(effects.channels(result), ["filesystem:data", "filesystem:cache"])
        self.assertEqual(result["effects"]["filesystem"][0]["files"][0]["hex"], "00ff")
        supplied["effects"]["filesystem"][0]["files"][0]["hex"] = "ff"
        self.assertEqual(result["effects"]["filesystem"][0]["files"][0]["hex"], "00ff")

    def test_unknown_unsafe_duplicate_and_over_budget_declarations_refuse(self):
        invalid = [{"path_mode": True}, {"path_mode": "normalise"}, {"name": "../data"}, {"environment": "HOME"}, {"environment": "PATH"},
                   {"environment": "OTELC_CONFIG"}, {"environment": "NODE_OPTIONS"},
                   {"environment": "LD_PRELOAD"}, {"environment": "APP=data"},
                   {"files": {}}, {"directories": "data"}, {"files": [{"path": "a", "hex": "0"}]},
                   {"files": [{"path": "a", "hex": "zz"}]}, {"files": [{"path": "a", "mode": True}]},
                   {"files": [{"path": "a"}, {"path": "a"}]}, {"files": [{"path": "a"}], "directories": ["a"]},
                   {"files": [{"path": "a"}, {"path": "a/b"}]},
                   {"max_entries": 2, "files": [{"path": "a/b"}]},
                   {"max_bytes": 0, "files": [{"path": "a", "hex": "00"}]},
                   {"max_depth": 1, "directories": ["a/b"]}, {"max_depth": True}, {"max_entries": 0},
                   {"unknown": 1}, {"files": [{"path": "a", "unknown": 1}]}]
        invalid += [{"directories": [name]} for name in ("", "/root", "../root", "a/../b", "a//b", "a\\b", "C:root", "a/.", "a\0b")]
        for item in invalid:
            with self.subTest(item=item), self.assertRaises(ValueError):configuration(**item)
        for value in ({"network": {}}, {"filesystem": {}}, {"filesystem": [{}] * 9}):
            with self.subTest(value=value), self.assertRaises(ValueError):policy.validate({"effects": value})
        for key in ("name", "environment"):
            declarations = [{"name": "data", "environment": "APP_DATA_DIR"}, {"name": "other", "environment": "APP_OTHER_DIR"}]
            declarations[1][key] = declarations[0][key]
            with self.assertRaisesRegex(ValueError, "distinct"):policy.validate({"effects": {"filesystem": declarations}})

    def test_independent_fixtures_retain_binary_contents_names_kinds_and_modes(self):
        configured = configuration(files=[{"path": "nested/seed.bin", "hex": "00ff010a", "mode": 0o640}], directories=["empty"])
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            states, environment = effects.prepare(base / "first", configured)
            other, other_environment = effects.prepare(base / "second", configured)
            root = Path(environment["APP_DATA_DIR"])
            self.assertNotEqual(environment, other_environment)
            self.assertEqual(states[0]["before"], other[0]["before"])
            self.assertEqual((root / "nested/seed.bin").read_bytes(), b"\0\xff\1\n")
            (root / "nested/seed.bin").write_bytes(b"changed")
            (root / "created").write_bytes(b"new")
            (root / "created").chmod(0o600)
            captured, complete = effects.finish(states, base / "first")
            untouched, untouched_complete = effects.finish(other, base / "second")
            self.assertTrue(complete and untouched_complete)
            value = json.loads(bytes(captured["filesystem:data"]))
            after = {bytes.fromhex(row["path_hex"]): row for row in value["after"]["entries"]}
            self.assertEqual(after[b"nested/seed.bin"], {"path_hex": b"nested/seed.bin".hex(), "kind": "file", "mode": 0o640, "hex": b"changed".hex()})
            self.assertEqual(after[b"created"]["hex"], b"new".hex())
            pristine = json.loads(bytes(untouched["filesystem:data"]))
            self.assertEqual(pristine["before"], pristine["after"])
            self.assertNotIn(str(root), json.dumps(value))
            with self.assertRaises(FileExistsError):effects.prepare(base / "first", configured)

    def test_byte_entry_and_depth_limits_are_incomplete_without_passing_truncation(self):
        for changes, make in [({"max_bytes": 2}, lambda root: (root / "file").write_bytes(b"123")),
                              ({"max_entries": 1}, lambda root: (root / "file").touch()),
                              ({"max_depth": 1}, lambda root: (root / "a/b").mkdir(parents=True))]:
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary); configured = configuration(**changes)
                states, environment = effects.prepare(folder, configured)
                make(Path(environment["APP_DATA_DIR"]))
                captured, complete = effects.finish(states, folder)
                self.assertFalse(complete)
                self.assertTrue(json.loads(bytes(captured["filesystem:data"]))["after"]["gaps"])

    def test_symlinks_and_fifos_are_gaps_and_external_target_bytes_are_never_read(self):
        for kind in ("symlink", "fifo"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary); configured = configuration()
                states, environment = effects.prepare(folder, configured)
                root = Path(environment["APP_DATA_DIR"])
                if kind == "symlink":
                    outside = folder / "private-target"; outside.write_bytes(b"UNOBSERVED EXTERNAL CONTENT")
                    (root / "link").symlink_to(outside)
                else:os.mkfifo(root / "pipe")
                captured, complete = effects.finish(states, folder)
                self.assertFalse(complete)
                self.assertNotIn(b"UNOBSERVED EXTERNAL CONTENT".hex(), bytes(captured["filesystem:data"]).decode())

    def test_root_removal_or_file_replacement_are_complete_observed_effects(self):
        for replacement in (False, True):
            with self.subTest(replacement=replacement), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary); configured = configuration()
                states, environment = effects.prepare(folder, configured); root = Path(environment["APP_DATA_DIR"])
                root.rmdir()
                if replacement:root.write_bytes(b"replacement")
                captured, complete = effects.finish(states, folder)
                value = json.loads(bytes(captured["filesystem:data"]))
                self.assertTrue(complete)
                self.assertEqual(value["after"]["entries"][0]["kind"], "file" if replacement else "absent")

    def test_changed_during_read_disappearing_entries_and_missing_parent_remain_gaps(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary); configured = configuration()
            states, environment = effects.prepare(folder, configured); root = Path(environment["APP_DATA_DIR"])
            actual = effects.os.fstat
            calls = 0
            def changing(descriptor):
                nonlocal calls
                observed = actual(descriptor); calls += 1
                if calls != 2:return observed
                fields = {name: getattr(observed, name) for name in ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns", "st_nlink")}
                fields["st_size"] += 1
                return SimpleNamespace(**fields)
            with patch.object(effects.os, "fstat", side_effect=changing):self.assertFalse(effects.snapshot(root, states[0]["settings"])["complete"])
            with patch.object(effects.Reader, "names", return_value=["disappeared"]):self.assertFalse(effects.snapshot(root, states[0]["settings"])["complete"])
            shutil.rmtree(root.parent)
            self.assertFalse(effects.snapshot(root, states[0]["settings"])["complete"])

    def test_seed_setup_refuses_existing_links_and_does_not_write_outside_its_fixture(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary); outside = base / "outside"; outside.mkdir()
            folder = base / "attempt"; folder.mkdir()
            (folder / "filesystem-fixtures").symlink_to(outside, target_is_directory=True)
            configured = configuration(files=[{"path": "seed", "hex": "ff"}])
            with self.assertRaises(OSError):
                effects.prepare(folder, configured)
            self.assertEqual(list(outside.iterdir()), [])

    def test_permission_only_change_and_multiple_environment_roots_remain_observed(self):
        configured = policy.validate({"effects": {"filesystem": [
            {"name": "data", "environment": "APP_DATA_DIR", "directories": ["nested"], "files": [{"path": "nested/seed", "hex": "ff", "mode": 0o640}]},
            {"name": "cache", "environment": "APP_CACHE_DIR"}]}})
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary); states, environment = effects.prepare(folder, configured)
            (Path(environment["APP_DATA_DIR"]) / "nested/seed").chmod(0o600)
            captured, complete = effects.finish(states, folder)
            self.assertTrue(complete)
            self.assertEqual(set(captured), {"filesystem:data", "filesystem:cache"})
            data = json.loads(bytes(captured["filesystem:data"]))
            self.assertEqual(data["before"]["entries"][-1]["hex"], data["after"]["entries"][-1]["hex"])
            self.assertEqual(data["before"]["entries"][-1]["mode"], 0o640)
            self.assertEqual(data["after"]["entries"][-1]["mode"], 0o600)

    def test_metadata_budget_is_bounded_before_building_an_oversized_capture(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary); configured = configuration()
            states, environment = effects.prepare(folder, configured)
            root = Path(environment["APP_DATA_DIR"])
            captured = effects.snapshot(root, states[0]["settings"], budget=1)
            self.assertFalse(captured["complete"])
            self.assertIn("encoded observation budget", captured["gaps"][0])

    def test_relative_bindings_keep_the_literal_environment_equal_across_independent_workers(self):
        configured = configuration(path_mode="relative")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary); environments = []
            for name in ("baseline", "instrumented"):
                folder = base / name
                project = folder / "project"; project.mkdir(parents=True)
                states, environment = effects.prepare(folder, configured, working_directory=project)
                environments.append(environment)
                self.assertEqual((project / environment["APP_DATA_DIR"]).resolve(), states[0]["root"].resolve())
            self.assertEqual(environments[0], environments[1])
            with self.assertRaisesRegex(ValueError, "declared worker directory"):
                effects.prepare(base / "missing-context", configured)

    def test_unsupported_host_and_initial_capture_failure_refuse_before_launch(self):
        configured = configuration()
        for status in ("ready", "blocked", "excluded"):
            entry = {"status": status, "reason": "prior"}
            with patch.object(effects.os, "supports_fd", set()):effects.bind(entry, configured)
            self.assertEqual(entry["status"], "blocked" if status == "ready" else status)
            if status != "ready":self.assertEqual(entry["reason"], "prior")
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(effects.os, "supports_fd", set()), self.assertRaisesRegex(ValueError, "POSIX"):
                effects.prepare(Path(temporary), configured)
            with patch.object(effects, "snapshot", return_value={"complete": False, "gaps": ["unavailable"]}), self.assertRaisesRegex(ValueError, "initial fixture"):
                effects.prepare(Path(temporary), configured)


if __name__ == "__main__":
    unittest.main()
