"""Only an explicit owned SDK cache is evicted; retained compiler inputs survive."""

import json
import argparse
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "adapters/generation"))
import go_cache
import go_files
import go_project
import generation


class GoCacheTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / "pool"
        self.evidence = self.base / "evidence"
        self.evidence.mkdir()
        self.options = {"directory": str(self.root), "max_bytes": 1024 ** 2}
        self.source = self.base / "application"
        self.source.mkdir()
        (self.source / "main.go").write_text("package main\n")
        self.original = go_files.freeze(self.source)

    def entry(self, cache, number, size, *, executable=False):
        key = format(number, "064x") + "-d"
        shard = cache / key[:2]
        shard.mkdir(exist_ok=True)
        path = shard / key
        if executable:
            path.mkdir()
            member = path / "inspect"
        else:
            member = path
        member.write_bytes(b"x" * size)
        os.utime(path, ns=(number, number))
        return path

    def test_settings_are_closed_canonical_and_source_backend_only(self):
        self.assertEqual(go_cache.settings({"directory": str(self.root)}),
                         {"directory": str(self.root), "max_bytes": 1024 ** 3})
        for value in (None, [], {}, {**self.options, "extra": 1},
                      *[{**self.options, "directory": name} for name in ("relative", "/", "/tmp/../x", "/tmp//x", "/tmp/", "bad\0path")],
                      *[{**self.options, "max_bytes": size} for size in (True, 0, 1.5, "1", 2 ** 63)]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                go_cache.settings(value)
        with self.assertRaisesRegex(ValueError, "requires a source-v1"):
            go_project.settings({"build_cache": self.options})
        value = go_project.settings({"backend": "source-scope-v1", "build_cache": self.options})
        self.assertEqual(value["build_cache"], self.options)

    def test_private_lease_reuses_cache_and_evicts_oldest_entries_and_executables(self):
        with go_cache.lease(self.options, [self.source], self.evidence) as environment:
            cache = Path(environment["GOCACHE"])
            first = self.entry(cache, 1, 700000)
            second = self.entry(cache, 2, 700000, executable=True)
            third = self.entry(cache, 3, 400000)
        self.assertFalse(first.exists())
        self.assertFalse(second.exists())
        self.assertTrue(third.exists())
        receipt = json.loads((self.evidence / "sdk-cache-after.json").read_text())
        self.assertEqual((receipt["before_bytes"], receipt["after_bytes"], receipt["complete"]), (1800000, 400000, True))
        self.assertEqual(len(receipt["removed"]), 2)
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)
        self.original.verify()
        other = self.base / "another-evidence"; other.mkdir()
        with go_cache.lease(self.options, [self.source], other) as reused:
            self.assertEqual(reused, environment)
            self.assertTrue(third.exists())
        self.original.verify()

    def test_failed_build_keeps_intermediates_and_does_not_publish_successful_cleanup(self):
        with self.assertRaisesRegex(ValueError, "compiler failed"):
            with go_cache.lease(self.options, [self.source], self.evidence) as environment:
                retained = self.entry(Path(environment["GOCACHE"]), 1, 1500000)
                raise ValueError("compiler failed")
        self.assertTrue(retained.exists())
        self.assertFalse((self.evidence / "sdk-cache-after.json").exists())
        other = self.base / "next"; other.mkdir()
        with go_cache.lease(self.options, [self.source], other):
            self.assertFalse(retained.exists())

    def test_cache_lease_refuses_concurrent_use_without_touching_the_active_cache(self):
        other = self.base / "other"; other.mkdir()
        with go_cache.lease(self.options, [self.source], self.evidence) as environment:
            entry = self.entry(Path(environment["GOCACHE"]), 1, 10)
            before = go_files.file(entry)
            with self.assertRaisesRegex(ValueError, "already in use"):
                with go_cache.lease(self.options, [self.source], other):
                    self.fail("concurrent compiler admitted")
            self.assertEqual(go_files.file(entry), before)

    def test_source_overlap_foreign_roots_markers_and_links_are_refused(self):
        for directory in (self.source, self.source / "cache", self.base):
            with self.subTest(directory=directory), self.assertRaisesRegex(ValueError, "overlaps"):
                with go_cache.lease({**self.options, "directory": str(directory)}, [self.source], self.evidence):
                    self.fail("source overlap admitted")
        foreign = self.base / "foreign"; foreign.mkdir(mode=0o700)
        with self.assertRaises(FileNotFoundError):
            with go_cache.lease({**self.options, "directory": str(foreign)}, [], self.evidence):
                self.fail("unmarked cache adopted")
        with go_cache.lease(self.options, [self.source], self.evidence):
            pass
        marker = self.root / go_cache.MARKER
        value = json.loads(marker.read_text()); value["schema_version"] = True
        marker.write_text(json.dumps(value)); marker.chmod(0o600)
        other = self.base / "second"; other.mkdir()
        with self.assertRaisesRegex(ValueError, "foreign.*marker"):
            with go_cache.lease(self.options, [], other):
                self.fail("changed marker admitted")
        link = self.base / "linked"; link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "private real directory"):
            with go_cache.lease({**self.options, "directory": str(link)}, [], other):
                self.fail("linked root admitted")

    def test_hardlinks_symlinks_special_files_and_unknown_keys_refuse_before_eviction(self):
        for kind in ("hardlink", "symlink", "fifo", "foreign", "directory"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                cache = Path(temporary).resolve()
                first = self.entry(cache, 1, 10)
                if kind == "hardlink":
                    first.unlink(); os.link(self.source / "main.go", first)
                elif kind == "symlink":
                    first.unlink(); first.symlink_to(self.source / "main.go")
                elif kind == "fifo":
                    first.unlink(); os.mkfifo(first)
                elif kind == "foreign":
                    (cache / "unrecognised").write_text("retain")
                else:
                    first.unlink(); first.mkdir(); (first / "nested").mkdir()
                with self.assertRaises((ValueError, OSError)):
                    go_cache.trim(cache, 0, cache / "receipt.json")
                self.assertTrue(first.exists())
                receipt = json.loads((cache / "receipt.json").read_text())
                self.assertFalse(receipt["complete"])
                self.assertEqual(receipt["removed"], [])
                # Remove the deliberate hardlink before checking original nlink/ctime.
                if kind == "hardlink":
                    first.unlink()

    def test_changed_cache_entries_cannot_be_evicted_under_old_file_facts(self):
        cache = self.base / "cache"; cache.mkdir()
        item = self.entry(cache, 1, 10)
        descriptor = os.open(cache, go_cache.DIRECTORY_FLAGS)
        self.addCleanup(os.close, descriptor)
        entry, = go_cache.entries(descriptor)
        item.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "changed before eviction"):
            go_cache.remove(descriptor, entry)
        self.assertEqual(item.read_bytes(), b"changed")

    def test_an_unleased_writer_cannot_make_a_false_completed_size_receipt(self):
        cache = self.base / "cache"; cache.mkdir()
        self.entry(cache, 1, 10)
        remove = go_cache.remove
        def changed(root, entry):
            remove(root, entry)
            self.entry(cache, 2, 20)
        with patch.object(go_cache, "remove", side_effect=changed), \
                self.assertRaisesRegex(ValueError, "changed during eviction"):
            go_cache.trim(cache, 0, self.evidence / "receipt.json")
        receipt = json.loads((self.evidence / "receipt.json").read_text())
        self.assertFalse(receipt["complete"])
        self.assertEqual(len(receipt["removed"]), 1)
        self.assertTrue((cache / "00" / (format(2, "064x") + "-d")).is_file())

    def test_control_files_are_not_cache_entries_or_eligible_for_eviction(self):
        cache = self.base / "cache"; cache.mkdir()
        for name in ("README", "trim.txt"):
            (cache / name).write_text("Go cache control")
        go_cache.trim(cache, 0, self.evidence / "receipt.json")
        self.assertEqual({p.name for p in cache.iterdir()}, {"README", "trim.txt"})

    def test_retargeted_cache_root_or_build_directory_cannot_select_a_foreign_eviction(self):
        for target in ("root", "build"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary).resolve()
                pool, foreign, evidence = (base / name for name in ("pool", "foreign", "evidence"))
                foreign.mkdir(); (foreign / "build").mkdir(); evidence.mkdir()
                item = self.entry(foreign / "build", 1, 2 * 1024 ** 2)
                before = go_files.file(item)
                with self.assertRaisesRegex(ValueError, "changed"):
                    with go_cache.lease({**self.options, "directory": str(pool)}, [], evidence):
                        if target == "root":
                            pool.rename(base / "original")
                            pool.symlink_to(foreign, target_is_directory=True)
                        else:
                            (pool / "build").rename(base / "original-build")
                            os.rename(foreign / "build", pool / "build")
                            item = pool / "build" / item.parent.name / item.name
                after = go_files.file(item)
                self.assertEqual(after[0]["sha256"], before[0]["sha256"])
                self.assertEqual(after[1], before[1])

    def test_planning_refuses_original_source_and_sdk_overlap_before_creating_a_workspace(self):
        sdk = self.base / "sdk"; sdk.mkdir()
        for root in (self.source, sdk):
            policy = self.base / "policy.toml"
            policy.write_text('schema_version=1\nlanguages=["go"]\n[adapters.go]\n'
                'backend="source-scope-v1"\nbuild_cache={directory='
                + json.dumps(str(root / "cache")) + '}\n')
            args = argparse.Namespace(source=self.source, otelc_root=sdk, config=policy,
                                      language=None, cases=None, exclude=[])
            with self.subTest(root=root), patch.object(generation.capture, "temporary_parent") as create, \
                    self.assertRaisesRegex(ValueError, "overlaps"):
                generation.plan(args)
            create.assert_not_called()
            self.assertFalse((root / "cache").exists())
        self.original.verify()


if __name__ == "__main__":
    unittest.main()
