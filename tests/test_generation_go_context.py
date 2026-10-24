"""Literal upstream inputs reconstruct a complete independently expected profile."""

from contextlib import contextmanager
import copy
import io
import json
from pathlib import Path
import stat
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import go_context as context
import go_files as files


def archive(values: dict[str, bytes], *, extra=None) -> bytes:
    """Use a compact fixture archive; production checks the complete release hash."""
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as target:
        for name, data in values.items():
            member = tarfile.TarInfo(name); member.size = len(data)
            target.addfile(member, io.BytesIO(data))
        if extra is not None:
            member, data = extra
            target.addfile(member, None if data is None else io.BytesIO(data))
    return output.getvalue()


class GoContextTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.fixture = json.loads((REPO / "tests/fixtures/go-context-profile.json").read_text())
        self.original = {name: text.encode() for name, text in self.fixture["upstream_inputs"].items()}
        self.licence = (REPO / "adapters/generation/go_context_APACHE.txt").read_bytes()
        self.bundle = self.base / "bundle.tgz"
        self.bundle.write_bytes(archive(self.original))

    @contextmanager
    def pinned_file_boundary(self):
        # Isolate the already-tested file/hash boundary for this compact archive.
        # Real full-release compatibility is qualified separately, without a stub.
        reader = files.file
        def read(path, *args, **kwargs):
            identity, facts, raw = reader(path, *args, **kwargs)
            if path == self.bundle:
                identity = {**identity, "sha256": self.fixture["bundle_sha256"]}
            return identity, facts, raw
        with patch.object(files, "file", side_effect=read):
            yield

    def test_complete_literal_profile_matches_all_twenty_one_expected_hashes(self):
        self.assertEqual(context.BUNDLE_SHA256, self.fixture["bundle_sha256"])
        with patch("subprocess.run", side_effect=AssertionError("context executed a command")), \
                patch("subprocess.Popen", side_effect=AssertionError("context launched a target")):
            values = context.render(context.members(self.bundle.read_bytes()), self.licence)
        self.assertEqual({name: context.digest(value) for name, value in values.items()}, self.fixture["expected_files"])
        self.assertEqual(len(values), 21)
        manifest = json.loads(values["context-bundle.json"])
        self.assertIs(manifest["tasks"], False)
        self.assertEqual(manifest["telemetry_context"], "span-and-baggage-v1")

    def test_expected_profile_is_created_before_build_and_keeps_owned_file_facts(self):
        before = files.file(self.bundle)[:2]
        with self.pinned_file_boundary():
            expected = context.prepare(self.bundle, self.base / "expected")
        expected.verify()
        self.assertEqual({name: value["sha256"] for name, value in expected.identities.items()}, self.fixture["expected_files"])
        self.assertEqual(files.file(self.bundle)[:2], before)
        for path in [expected.root, *expected.root.rglob("*")]:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700 if path.is_dir() else 0o600)
        (expected.root / "NOTICE.upstream").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            expected.verify()

    def test_unpinned_bundle_refuses_before_creating_expected_source(self):
        output = self.base / "expected"
        with self.assertRaisesRegex(ValueError, "bundle differs"):
            context.prepare(self.bundle, output)
        self.assertFalse(output.exists())

    def test_closed_source_denominator_and_literal_licence_cannot_be_substituted(self):
        for value in ([], {}, {**self.original, "foreign": b"x"},
                      {**self.original, next(iter(self.original)): "text"},
                      {**self.original, next(iter(self.original)): b"x" * (context.MAX_MEMBER_BYTES + 1)}):
            with self.subTest(value=type(value).__name__), self.assertRaisesRegex(ValueError, "source denominator"):
                context.render(value, self.licence)
        for licence in ("text", b"changed"):
            with self.subTest(licence=licence), self.assertRaisesRegex(ValueError, "licence differs"):
                context.render(self.original, licence)

    def test_each_fixed_patch_requires_the_original_unique_source_shape(self):
        path = "instrumentation_temp/go.opentelemetry.io/otel/sdk/trace/otel_trace_context.go"
        for marker in (b"import (\n", b"ended *atomic.Bool\n}", b"&spanWrapper{span, tc.sw, stateForSpan(span)}",
                       b"&spanWrapper{last, nil, tc.sw.ended}"):
            value = copy.copy(self.original); value[path] = value[path].replace(marker, b"changed")
            with self.subTest(marker=marker), self.assertRaisesRegex(ValueError, "fixed patch"):
                context.render(value, self.licence)
        path = "instrumentation_temp/runtime/otelc.yaml"
        for replacement in (b"changed\n", b"goroutine_propagate:\ngoroutine_propagate:\n"):
            value = copy.copy(self.original); value[path] = value[path].replace(b"goroutine_propagate:\n", replacement)
            with self.assertRaisesRegex(ValueError, "task reset rule"):
                context.render(value, self.licence)

    def test_archive_refuses_missing_duplicate_linked_and_oversized_selected_members(self):
        name = next(iter(self.original))
        for kind in ("missing", "duplicate", "link", "oversized"):
            values = copy.copy(self.original); extra = None
            if kind == "missing":
                values.pop(name)
            else:
                member = tarfile.TarInfo(name)
                data = b""
                if kind == "link":
                    values.pop(name); member.type = tarfile.SYMTYPE; member.linkname = "/never-read"; data = None
                elif kind == "oversized":
                    values.pop(name); member.size = context.MAX_MEMBER_BYTES + 1; data = b"x" * member.size
                extra = member, data
            raw = archive(values, extra=extra)
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                context.members(raw)
        member = tarfile.TarInfo("../../never-extracted"); member.size = 1
        self.assertEqual(context.members(archive(self.original, extra=(member, b"x"))), self.original)
        self.assertFalse((self.base.parent / "never-extracted").exists())

    def test_incomplete_archive_stream_is_not_a_complete_member(self):
        member = tarfile.TarInfo(next(iter(self.original))); member.size = 1
        fake = unittest.mock.MagicMock()
        fake.__enter__.return_value = fake
        fake.__iter__.return_value = iter([member])
        fake.extractfile.return_value = io.BytesIO(b"")
        with patch.object(context.tarfile, "open", return_value=fake), self.assertRaisesRegex(ValueError, "incomplete Go context archive member"):
            context.members(b"not read")

    def test_existing_output_and_noncanonical_parents_are_not_replaced(self):
        output = self.base / "expected"; output.mkdir(); (output / "keep").write_text("keep")
        with self.pinned_file_boundary(), self.assertRaises(FileExistsError):
            context.prepare(self.bundle, output)
        self.assertEqual((output / "keep").read_text(), "keep")
        alias = self.base / "alias"; alias.symlink_to(self.base, target_is_directory=True)
        for output in (Path("relative"), alias / "new"):
            with self.subTest(output=output), self.assertRaisesRegex(ValueError, "canonical parent"):
                context.prepare(self.bundle, output)

    def test_changed_source_during_final_snapshot_cannot_be_published(self):
        freeze = files.freeze
        changed = False
        def mutate(path):
            nonlocal changed
            result = freeze(path)
            if not changed:
                changed = True
                (path / "NOTICE.upstream").write_bytes(b"changed")
            return result
        with self.pinned_file_boundary(), patch.object(files, "freeze", side_effect=mutate), self.assertRaises(ValueError):
            context.prepare(self.bundle, self.base / "expected")


if __name__ == "__main__":
    unittest.main()
