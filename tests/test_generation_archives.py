"""Cold receipt archives retain bytes/metadata and refuse unsafe restoration."""

from contextlib import redirect_stderr, redirect_stdout
import copy
import fcntl
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

from ci import evidence_archive as archive
from ci import evidence_attributes as attributes
from ci import evidence_files as files
from ci import evidence_index as records
from ci.qualification_archive import main


class EvidenceArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name).resolve()
        self.root = self.directory / "corpus"
        self.root.mkdir(mode=0o700)
        self.store = self.directory / "archive"
        self.names = ["a/node-runtime/node-launch.json", "b/sdk-runtime/class-load.log"]
        self.originals = {}
        for ordinal, name in enumerate(self.names):
            path = self.root / name
            path.parent.mkdir(parents=True, mode=0o700)
            path.write_bytes((b"receipt bytes\n" * 100) + bytes([ordinal]))
            path.chmod(0o640)
            os.utime(path, ns=(1_700_000_000_000_123_456, 1_700_000_000_000_123_456 + ordinal))
            self.originals[name] = files.read(self.root, name)[0]
        self.plan = self.directory / "selection.json"
        self.selection = {"schema_version": 1, "kind": records.KIND,
                          "root": str(self.root), "paths": self.names}
        self.write_selection()

    def write_selection(self):
        self.plan.write_text(json.dumps(self.selection))

    def pack(self):
        result = archive.pack(self.root, self.plan, self.store)
        self.sha = result["index_sha256"]
        return result

    def index(self):
        return json.loads((self.store / archive.INDEX).read_bytes())

    def rewrite_index(self, value):
        value.pop("seal_sha256", None)
        value["seal_sha256"] = records.digest(records.canonical(value))
        content = records.canonical(value) + b"\n"
        path = self.store / archive.INDEX
        path.chmod(0o600)
        path.write_bytes(content)
        path.chmod(0o444)
        self.sha = records.digest(content)

    def replace_archive(self, payload):
        path = self.store / archive.ARCHIVE
        path.chmod(0o600)
        path.write_bytes(payload)
        path.chmod(0o444)
        value = self.index()
        value["archive_sha256"] = hashlib.sha256(payload).hexdigest()
        self.rewrite_index(value)

    def tar(self, members):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:", format=tarfile.PAX_FORMAT) as stream:
            for member, content in members:
                stream.addfile(member, io.BytesIO(content) if member.isreg() else None)
        return gzip.compress(output.getvalue())

    def member(self, name, content):
        member = tarfile.TarInfo(name)
        member.mode, member.size = 0o600, len(content)
        return member, content

    def test_round_trip_preserves_bytes_metadata_and_independent_files(self):
        result = self.pack()
        self.assertEqual(result["originals_removed"], 0)
        self.assertEqual(archive.verify(self.root, self.store, self.sha)["files"], 2)
        self.assertEqual(archive.materialise(self.root, self.store, self.sha)["already_present"], 2)
        removed = archive.evict(self.root, self.store, self.sha, cold=True)
        self.assertEqual(removed["evicted"], 2)
        self.assertEqual(archive.status(self.root, self.store, self.sha)["archived"], self.names)
        self.assertEqual(archive.evict(self.root, self.store, self.sha, cold=True)["already_archived"], 2)
        result = archive.materialise(self.root, self.store, self.sha)
        self.assertEqual(result["restored"], 2)
        for name, expected in self.originals.items():
            self.assertEqual(files.read(self.root, name)[0], expected)
            self.assertEqual((self.root / name).stat().st_nlink, 1)
        self.assertEqual(archive.status(self.root, self.store, self.sha)["present"], self.names)

    def test_eviction_requires_explicit_cold_confirmation(self):
        self.pack()
        with self.assertRaisesRegex(records.ArchiveError, "confirmation"):
            archive.evict(self.root, self.store, self.sha)
        self.assertTrue(all((self.root / name).is_file() for name in self.names))

    def test_changed_content_or_metadata_prevents_all_eviction(self):
        self.pack()
        path = self.root / self.names[-1]
        path.chmod(0o600)
        with self.assertRaisesRegex(records.ArchiveError, "metadata differs"):
            archive.evict(self.root, self.store, self.sha, cold=True)
        self.assertTrue((self.root / self.names[0]).exists())
        path.chmod(self.originals[self.names[-1]]["mode"])
        os.utime(path, ns=(1, 1))
        with self.assertRaises(records.ArchiveError):
            archive.evict(self.root, self.store, self.sha, cold=True)

    def test_restore_preflights_later_conflicts_before_writing_anything(self):
        self.pack()
        (self.root / self.names[0]).unlink()
        (self.root / self.names[1]).write_bytes(b"conflicting input")
        with self.assertRaisesRegex(records.ArchiveError, "metadata differs"):
            archive.materialise(self.root, self.store, self.sha)
        self.assertFalse((self.root / self.names[0]).exists())

    def test_wrong_index_anchor_seal_root_and_version_refuse(self):
        self.pack()
        with self.assertRaisesRegex(records.ArchiveError, "index SHA256"):
            archive.verify(self.root, self.store, "0" * 64)
        original = self.index()
        for key, value in (("root", "/elsewhere"), ("schema_version", True),
                           ("kind", "other"), ("archive_sha256", "g" * 64)):
            changed = copy.deepcopy(original); changed[key] = value
            self.rewrite_index(changed)
            with self.subTest(key=key), self.assertRaises(records.ArchiveError):
                archive.verify(self.root, self.store, self.sha)
        self.rewrite_index(original)
        changed = self.index(); changed["seal_sha256"] = "0" * 64
        path = self.store / archive.INDEX
        path.chmod(0o600); path.write_bytes(records.canonical(changed)); path.chmod(0o444)
        with self.assertRaisesRegex(records.ArchiveError, "seal"):
            archive.verify(self.root, self.store, records.digest(path.read_bytes()))

    def test_invalid_index_entries_are_rejected_even_with_recomputed_seal(self):
        self.pack()
        original = self.index()
        cases = []
        for key, value in (("size", True), ("size", -1), ("size", records.MAX_FILE_BYTES+1),
                           ("mode", 0o4755), ("uid", os.getuid()+1), ("gid", -1),
                           ("mtime_ns", -1), ("sha256", "x"), ("path", "../node-runtime/node-launch.json")):
            changed = copy.deepcopy(original); changed["files"][0][key] = value; cases.append(changed)
        changed = copy.deepcopy(original); changed["files"].append(changed["files"][0]); cases.append(changed)
        changed = copy.deepcopy(original); changed["files"] = []; cases.append(changed)
        changed = copy.deepcopy(original); changed["files"][0]["extra"] = 1; cases.append(changed)
        for changed in cases:
            self.rewrite_index(changed)
            with self.subTest(changed=changed), self.assertRaises(records.ArchiveError):
                archive.verify(self.root, self.store, self.sha)

    def test_archive_hash_corruption_and_truncated_gzip_are_not_accepted(self):
        self.pack()
        content = (self.store / archive.ARCHIVE).read_bytes()
        path = self.store / archive.ARCHIVE
        path.chmod(0o600); path.write_bytes(content[:-8]); path.chmod(0o444)
        with self.assertRaisesRegex(records.ArchiveError, "archive SHA256"):
            archive.verify(self.root, self.store, self.sha)
        for broken in (content[:-8], content[:-8] + bytes([content[-8] ^ 1]) + content[-7:]):
            self.replace_archive(broken)
            with self.assertRaises((EOFError, OSError)):
                archive.verify(self.root, self.store, self.sha)
        self.assertTrue(all((self.root / name).exists() for name in self.names))

    def test_members_must_be_exact_unique_regular_payloads(self):
        self.pack()
        members = [self.member(name, files.read(self.root, name)[1]) for name in self.names]
        cases = [members[:1], members + [members[0]], members[::-1]]
        for key, value in (("name", "../outside"), ("type", tarfile.SYMTYPE),
                           ("type", tarfile.LNKTYPE), ("type", tarfile.CHRTYPE),
                           ("mode", 0o644), ("uid", 1), ("mtime", 1)):
            changed = copy.deepcopy(members); setattr(changed[0][0], key, value); cases.append(changed)
        changed = copy.deepcopy(members); changed[0][0].pax_headers={"comment":"extra"}; cases.append(changed)
        changed = copy.deepcopy(members); changed[0]=(changed[0][0], b"x"*changed[0][0].size); cases.append(changed)
        for members in cases:
            self.replace_archive(self.tar(members))
            with self.subTest(member=members[0][0].name), self.assertRaises(records.ArchiveError):
                archive.verify(self.root, self.store, self.sha)

    def test_hidden_trailing_member_and_decompression_bomb_refuse(self):
        self.pack()
        content=(self.store / archive.ARCHIVE).read_bytes()
        self.replace_archive(content + gzip.compress(b"hidden data"))
        with self.assertRaisesRegex(records.ArchiveError, "nonzero data"):
            archive.verify(self.root, self.store, self.sha)
        self.replace_archive(gzip.compress(b"\0" * 200_000))
        with self.assertRaisesRegex(records.ArchiveError, "expansion"):
            archive.verify(self.root, self.store, self.sha)

    def test_symlink_parent_leaf_and_multiple_links_cannot_select_evidence(self):
        leaf = self.root / self.names[0]
        content = leaf.read_bytes(); leaf.unlink(); leaf.symlink_to(self.root / self.names[1])
        with self.assertRaises(OSError): self.pack()
        self.assertTrue(leaf.is_symlink())
        leaf.unlink(); leaf.write_bytes(content)
        os.link(leaf, self.root / "linked")
        with self.assertRaisesRegex(records.ArchiveError, "metadata"):
            files.read(self.root, self.names[0])
        (self.root / "linked").unlink()
        parent = self.root / "linked-parent"
        parent.symlink_to(leaf.parent, target_is_directory=True)
        with self.assertRaises(OSError):
            files.read(self.root, "linked-parent/node-launch.json")

    def test_special_modes_and_unowned_directories_refuse(self):
        path = self.root / self.names[0]
        # macOS may clear set-ID bits on this test volume; exercise the guard
        # with an explicit stat result rather than depending on that policy.
        value = list(path.stat()); value[0] |= 0o4000
        with self.assertRaises(records.ArchiveError): files._metadata(os.stat_result(value))
        path.parent.chmod(0o777)
        with self.assertRaisesRegex(records.ArchiveError, "directory"):
            files.read(self.root, self.names[0])

    def test_restore_refuses_symlink_and_existing_identical_bytes_with_wrong_metadata(self):
        self.pack()
        path = self.root / self.names[0]
        path.chmod(0o600)
        with self.assertRaises(records.ArchiveError): archive.materialise(self.root, self.store, self.sha)
        path.unlink(); path.symlink_to(self.root / self.names[1])
        with self.assertRaises(OSError): archive.materialise(self.root, self.store, self.sha)

    def test_atomic_restore_refuses_target_created_after_preflight(self):
        self.pack(); path = self.root / self.names[0]; path.unlink()
        real = files._rename
        def race(directory, temporary, destination):
            path.write_bytes(b"concurrent writer")
            return real(directory, temporary, destination)
        with mock.patch.object(files, "_rename", side_effect=race):
            with self.assertRaises(FileExistsError): archive.materialise(self.root, self.store, self.sha)
        self.assertEqual(path.read_bytes(), b"concurrent writer")
        self.assertEqual(list(path.parent.glob(".oteleq-restore-*")), [])

    def test_partial_restore_and_eviction_are_recoverable_without_rerunning_apps(self):
        self.pack(); real = files.remove
        def stop_second(root, item, expected):
            if item["path"] == self.names[1]: raise OSError("simulated I/O failure")
            return real(root, item, expected)
        with mock.patch.object(files, "remove", side_effect=stop_second):
            with self.assertRaises(OSError): archive.evict(self.root, self.store, self.sha, cold=True)
        self.assertEqual(archive.status(self.root, self.store, self.sha)["archived"], self.names[:1])
        self.assertEqual(archive.materialise(self.root, self.store, self.sha)["restored"], 1)
        self.assertEqual(len(list(self.store.glob("eviction-*.jsonl"))), 1)

    def test_pack_failure_preserves_originals_and_retains_partial_storage(self):
        with mock.patch.object(archive, "_verified", side_effect=OSError("verification failed")):
            with self.assertRaises(OSError): self.pack()
        self.assertTrue((self.store / archive.INDEX).exists())
        for name, expected in self.originals.items(): self.assertEqual(files.read(self.root,name)[0],expected)

    def test_exclusive_lock_and_store_permissions_are_enforced(self):
        self.pack()
        with (self.store / "operation.lock").open("rb") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError): archive.verify(self.root,self.store,self.sha)
        self.store.chmod(0o755)
        with self.assertRaises(records.ArchiveError): archive.verify(self.root,self.store,self.sha)

    def test_selection_paths_roles_schema_and_duplicates_are_closed(self):
        for paths in ([], self.names*2, ["/node-runtime/node-launch.json"],
                      ["a/../node-runtime/node-launch.json"], ["a//node-runtime/node-launch.json"],
                      ["snapshot/node-runtime/node-launch.json"], ["node-runtime/source.py"],
                      ["node-runtime\\node-launch.json"], ["node-runtime/\nnode-launch.json"], [False]):
            self.selection["paths"]=paths; self.write_selection()
            with self.subTest(paths=paths), self.assertRaises(records.ArchiveError):
                records.selection(self.plan,self.root)
        self.selection["paths"]=self.names; self.selection["schema_version"]=True; self.write_selection()
        with self.assertRaises(records.ArchiveError): records.selection(self.plan,self.root)

    def test_json_duplicates_nonfinite_and_byte_budget_refuse(self):
        for content in ('{"x":1,"x":2}', '{"x":NaN}', '[]', '['*2000+']'*2000):
            self.plan.write_text(content)
            with self.assertRaises(records.ArchiveError): records.load(self.plan)
        self.write_selection()
        with mock.patch.object(records,"MAX_INDEX_BYTES",1):
            with self.assertRaises(records.ArchiveError): records.load(self.plan)

    def test_long_pax_names_and_empty_receipts_round_trip(self):
        name = "long-" + "x"*120 + "/node-runtime/node-plain-launch.json"
        path = self.root/name
        path.parent.mkdir(parents=True)
        path.write_bytes(b"")
        self.selection["paths"]=[name]; self.write_selection(); self.pack()
        expected=files.read(self.root,name)[0]
        archive.evict(self.root,self.store,self.sha,cold=True)
        archive.materialise(self.root,self.store,self.sha)
        self.assertEqual(files.read(self.root,name)[0],expected)

    def test_attributes_are_reproduced_and_unwanted_user_attributes_removed(self):
        path=self.root/self.names[0]
        descriptor=os.open(path,os.O_RDWR)
        try:
            original=attributes.read(descriptor)
            expected={**original, b"user.oteleq".hex(): b"\x00\xff".hex()}
            attributes.write(descriptor,expected)
            self.assertEqual(attributes.read(descriptor),expected)
            attributes.write(descriptor,original)
            self.assertEqual(attributes.read(descriptor),original)
        finally: os.close(descriptor)
        self.pack()
        before=files.read(self.root,self.names[0])[0]
        archive.evict(self.root,self.store,self.sha,cold=True)
        archive.materialise(self.root,self.store,self.sha)
        self.assertEqual(files.read(self.root,self.names[0])[0],before)

    def test_attribute_failure_and_size_limits_are_explicit(self):
        with self.assertRaises(OSError): attributes._checked(-1)
        with self.assertRaises(records.ArchiveError): attributes._checked(attributes.LIMIT+1)
        with mock.patch.object(attributes.sys,"platform","unsupported"):
            with self.assertRaises(records.ArchiveError): attributes._native("unused",[])
        with mock.patch.object(attributes.os,"listxattr",return_value=["user.test"],create=True), \
             mock.patch.object(attributes.os,"getxattr",return_value=b"x",create=True):
            self.assertEqual(attributes.read(1),{b"user.test".hex():"78"})
        with mock.patch.object(attributes.os,"listxattr",return_value=["same"]*65,create=True):
            with self.assertRaises(records.ArchiveError): attributes.read(1)

    def test_inode_replacement_before_eviction_is_not_an_original(self):
        item, content, identity=files.read(self.root,self.names[0])
        (self.root/self.names[0]).unlink()
        files.install(self.root,item,content)
        with self.assertRaisesRegex(records.ArchiveError,"identity changed"):
            files.remove(self.root,item,identity)
        self.assertEqual(files.read(self.root,self.names[0])[0],item)

    def test_wrong_root_nested_storage_and_optimised_python_refuse(self):
        with self.assertRaises(records.ArchiveError): archive.pack(self.root,self.plan,self.root/"archive")
        alias=self.directory/"alias"; alias.symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(records.ArchiveError): records.root_path(alias)
        self.pack()
        run=subprocess.run([sys.executable,"-O","-m","ci.qualification_archive","verify",
            "--root",str(self.root),"--store",str(self.store),"--index-sha256",self.sha],
            cwd=Path(__file__).resolve().parents[1],capture_output=True,check=False)
        self.assertEqual(run.returncode,2); self.assertIn(b"optimised Python",run.stderr)

    def test_install_failure_removes_private_temporary_file(self):
        item, content, _=files.read(self.root,self.names[0]); (self.root/self.names[0]).unlink()
        with mock.patch.object(files.os,"fsync",side_effect=OSError("disk failure")):
            with self.assertRaises(OSError): files.install(self.root,item,content)
        self.assertFalse((self.root/self.names[0]).exists())
        self.assertEqual(list((self.root/self.names[0]).parent.glob(".oteleq-restore-*")),[])
        with mock.patch.object(files.sys,"platform","unsupported"):
            with self.assertRaises(records.ArchiveError): files.install(self.root,item,content)

    def test_cli_operations_and_refusals_return_reviewable_json(self):
        common=["--root",str(self.root),"--store",str(self.store)]
        def invoke(args):
            output,error=io.StringIO(),io.StringIO()
            with redirect_stdout(output),redirect_stderr(error): result=main(args)
            return result,output.getvalue(),error.getvalue()
        code,output,_=invoke(["pack",*common,"--selection",str(self.plan)])
        self.assertEqual(code,0); self.sha=json.loads(output)["index_sha256"]
        for operation in ("verify","status","restore","evict"):
            args=[operation,*common,"--index-sha256",self.sha]
            if operation=="evict": args.append("--confirm-cold")
            self.assertEqual(invoke(args)[0],0)
        self.assertEqual(invoke(["verify",*common,"--index-sha256","wrong"])[0],2)
        for args in (["pack",*common],["verify",*common],
                     ["status",*common,"--index-sha256",self.sha,"--confirm-cold"]):
            with self.assertRaises(SystemExit): invoke(args)


if __name__ == "__main__":
    unittest.main()
