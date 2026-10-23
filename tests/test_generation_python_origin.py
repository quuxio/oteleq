"""Independent J2 wire fixtures validate relations, never authentic capture."""

import copy
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import python_code
import python_journal as inputs
import python_origin as origin
from test_generation_python_code import fixture as function_graph

PID = 1234
VERSION = 0x030c0ff0
PATH = b"/tmp/entry.py"


def encoded(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def module_graph() -> dict:
    value = function_graph()
    child = copy.deepcopy(value["nodes"][0])
    child["id"] = 9
    child["fields"].update(co_consts=11, co_name=10, co_qualname=10)
    value["nodes"][0]["metadata"]["co_flags"] = 0
    value["nodes"][1]["items"] = [9]
    value["nodes"][3]["value"] = "<module>"
    value["nodes"].extend([child, {"id": 10, "type": "unicode", "value": "workload"},
                           {"id": 11, "type": "tuple", "items": [7]}])
    return value


def fixture(*, plain: bool = False, loader: bool = False) -> list[tuple[int, bytes, bytes]]:
    source = b"synthetic source bytes\0not executed"
    root = encoded(module_graph())
    selected = encoded(function_graph())
    rows = [(3 if loader else 1, PATH, inputs.SOURCE.pack(PID, 2, 3, len(source), -2, 17,
                                                        stat.S_IFREG | 0o600) + source),
            (5, PATH, origin.ROOT.pack(PID, 77, 90, 12 if loader else 0, 1, 2 if loader else 1,
                                      VERSION, 2, 0, 0) + root),
            (6, PATH, origin.EXECUTION.pack(PID, 91, 77, 0, VERSION, 1, 0) + origin.EDGE.pack(0))]
    if not plain:
        rows.extend([(4, PATH, inputs.CODE.pack(PID, 1, 0, VERSION, 2, len(selected), 0) + selected),
                     (7, PATH, origin.JOIN.pack(PID, 1, 91, 0, 0, 0, 0))])
    return rows


def wire(rows: list[tuple[int, bytes, bytes]], *, capture: int = 0, lost: int = 0,
         finalized: int = 1, expected: int = 1) -> bytes:
    size = sum(len(payload) - origin.WIDTHS[kind] for kind, _, payload in rows)
    final = inputs.FINAL.pack(PID, len(rows), size, capture, lost, finalized, expected)
    return b"".join(inputs.HEADER.pack(origin.MAGIC, kind, 0, 0, sequence, len(path), len(payload)) + path + payload
                    for sequence, (kind, path, payload) in enumerate([*rows, (2, b"", final)], 1))


def metadata(rows: list, index: int, field: int, value: int) -> list:
    result = copy.deepcopy(rows)
    kind, path, payload = result[index]
    layout = {1: inputs.SOURCE, 3: inputs.SOURCE, 4: inputs.CODE,
              5: origin.ROOT, 6: origin.EXECUTION, 7: origin.JOIN}[kind]
    fields = list(layout.unpack_from(payload))
    fields[field] = value
    result[index] = kind, path, layout.pack(*fields) + payload[layout.size:]
    return result


class PythonOriginTests(unittest.TestCase):
    def test_both_source_routes_and_plain_lane_preserve_ordered_relations(self) -> None:
        for plain in (False, True):
            for loader in (False, True):
                with self.subTest(plain=plain, loader=loader):
                    journal = origin.decode(wire(fixture(plain=plain, loader=loader)), PID)
                    self.assertTrue(journal.capture_complete)
                    self.assertEqual(journal.pid, PID)
                    self.assertEqual([row.sequence for row in journal.records], list(range(1, len(journal.records) + 1)))
                    source, root, execution, *_ = journal.records
                    self.assertEqual(source.content, b"synthetic source bytes\0not executed")
                    self.assertEqual(source.mtime_ns, -2 * 10 ** 9 + 17)
                    self.assertEqual((root.identity, root.transaction, root.input_sequence), (77, 90, 1))
                    self.assertEqual((execution.identity, execution.root, execution.edges, execution.member), (91, 77, (0,), 9))
                    self.assertEqual(root.route, 2 if loader else 1)
                    self.assertEqual(journal.comparison_steps > 0, not plain)
                    if not plain:
                        self.assertEqual((journal.records[-1].sdk, journal.records[-1].origin), (1, 91))

    def test_private_file_and_explicit_versions_are_separate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "origin.journal"
            path.write_bytes(wire(fixture()))
            path.chmod(0o600)
            self.assertTrue(origin.read(path, PID).capture_complete)
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                origin.read(path, PID)
            path.chmod(0o600)
            link = path.with_name("link")
            link.symlink_to(path)
            with self.assertRaises((ValueError, OSError)):
                origin.read(link, PID)
        data = wire(fixture())
        with self.assertRaises(ValueError):
            inputs.decode(data, PID)
        with self.assertRaises(ValueError):
            origin.decode(data.replace(origin.MAGIC, inputs.MAGIC), PID)
        position = data.index(origin.MAGIC, 1)
        with self.assertRaises(ValueError):
            origin.decode(data[:position] + inputs.MAGIC + data[position + 8:], PID)

    def test_no_compilation_or_application_execution_and_missing_relations_do_not_appear(self) -> None:
        with patch("builtins.compile", side_effect=AssertionError("must not compile")):
            journal = origin.decode(wire(fixture()), PID)
        self.assertTrue(journal.capture_complete)
        # Raw final health is deliberately separate from selection coverage.
        for rows in ([], fixture()[:1], fixture(plain=True), fixture()[:-1]):
            journal = origin.decode(wire(rows), PID)
            self.assertTrue(journal.capture_complete)
            self.assertFalse(any(type(row) is origin.Join for row in journal.records))

    def test_loss_finalisation_and_entry_expectation_are_not_silently_repaired(self) -> None:
        for kwargs in ({"capture": 1}, {"lost": 1}, {"finalized": 0}):
            with self.subTest(kwargs=kwargs):
                journal = origin.decode(wire(fixture(), **kwargs), PID)
                self.assertFalse(journal.capture_complete)
        journal = origin.decode(wire(fixture(loader=True), expected=0), PID)
        self.assertFalse(journal.entry_expected)
        self.assertTrue(journal.capture_complete)

    def test_envelope_kinds_flags_sequence_paths_lengths_truncation_and_eof_refuse(self) -> None:
        data = wire(fixture())
        for cut in (0, 1, 35, 36, len(data) - inputs.FINAL.size, len(data) - 1):
            with self.subTest(cut=cut), self.assertRaises(ValueError):
                origin.decode(data[:cut], PID)
        header = list(inputs.HEADER.unpack_from(data))
        for index, values in {0: [b"badmagic"], 1: [0, 8], 2: [1], 3: [1],
                              4: [0, 2, 4097], 5: [65536], 6: [0, inputs.MAX_PAYLOAD + 100]}.items():
            for value in values:
                fields = header.copy(); fields[index] = value
                with self.subTest(index=index, value=value), self.assertRaises(ValueError):
                    origin.decode(inputs.HEADER.pack(*fields) + data[inputs.HEADER.size:], PID)
        for rows in ([(kind, b"" if i == 0 else path, payload) for i, (kind, path, payload) in enumerate(fixture())],
                     [(kind, b"nul\0path" if i == 0 else path, payload) for i, (kind, path, payload) in enumerate(fixture())]):
            with self.assertRaises(ValueError):
                origin.decode(wire(rows), PID)
        with self.assertRaises(ValueError):
            origin.decode(data + b"trailing", PID)
        for invalid in (bytearray(data), None):
            with self.assertRaises(ValueError):
                origin.decode(invalid, PID)
        for pid in (True, 0, -1, 2 ** 64, PID + 1):
            with self.assertRaises(ValueError):
                origin.decode(data, pid)
        with patch.object(inputs, "MAX_BYTES", 1), self.assertRaises(ValueError):
            origin.decode(data, PID)
        with patch.object(inputs, "MAX_RECORDS", 2), self.assertRaises(ValueError):
            origin.decode(data, PID)

    def test_terminal_pid_counts_data_flags_and_exact_final_width_refuse(self) -> None:
        data = wire(fixture())
        values = list(inputs.FINAL.unpack_from(data, len(data) - inputs.FINAL.size))
        for field in (0, 1, 2, 5, 6):
            changed = values.copy(); changed[field] += 2
            with self.subTest(field=field), self.assertRaises(ValueError):
                origin.decode(data[:-inputs.FINAL.size] + inputs.FINAL.pack(*changed), PID)
        position = len(data) - inputs.FINAL.size - inputs.HEADER.size
        header = list(inputs.HEADER.unpack_from(data, position)); header[5] = 1
        with self.assertRaises(ValueError):
            origin.decode(data[:position] + inputs.HEADER.pack(*header) + b"x" + data[-inputs.FINAL.size:], PID)
        header[5], header[6] = 0, inputs.FINAL.size + 1
        with self.assertRaises(ValueError):
            origin.decode(data[:position] + inputs.HEADER.pack(*header) + data[-inputs.FINAL.size:] + b"x", PID)

    def test_root_foreign_pid_zero_ids_forward_token_route_schema_flags_and_reuse_refuse(self) -> None:
        rows = fixture()
        for field, values in {0: [PID + 1], 1: [0], 2: [0], 3: [1], 4: [0, 2, 99],
                              5: [0, 2, 3], 6: [VERSION + 0x10000], 7: [1, 3],
                              8: [2 ** 31], 9: [3]}.items():
            for value in values:
                # A different valid version alone is detected by later records.
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    origin.decode(wire(metadata(rows, 1, field, value)), PID)
        variants = []
        for graph in (function_graph(), module_graph()):
            if graph["nodes"][3]["value"] == "<module>":
                graph["nodes"][2]["value"] = "/tmp/other.py"
            changed = copy.deepcopy(rows)
            changed[1] = (5, PATH, rows[1][2][:origin.ROOT.size] + encoded(graph))
            variants.append(changed)
        variants.append([rows[1], rows[0], *rows[2:]])
        for fields in ((1, 78), (2, 92), (4, 1)):
            duplicate = metadata(rows, 1, *fields)[1]
            variants.append([*rows[:2], duplicate, *rows[2:]])
        for changed in variants:
            with self.assertRaises(ValueError):
                origin.decode(wire(changed), PID)
        for field, value in ((3, 0), (5, 1)):
            with self.assertRaises(ValueError):
                origin.decode(wire(metadata(fixture(loader=True), 1, field, value)), PID)
        changed = fixture(loader=True)
        changed = [(kind, path.replace(b".py", b".pyc"), payload) for kind, path, payload in changed]
        with self.assertRaises(ValueError):
            origin.decode(wire(changed), PID)

    def test_execution_edges_identity_membership_paths_offsets_and_metadata_refuse(self) -> None:
        rows = fixture()
        for field, values in {0: [PID + 1], 1: [0], 2: [0, 78], 3: [1, 6],
                              4: [VERSION + 0x10000], 5: [0, 2, 129], 6: [1]}.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    origin.decode(wire(metadata(rows, 2, field, value)), PID)
        for index in (1, 2 ** 64 - 1):
            changed = rows.copy()
            changed[2] = 6, PATH, rows[2][2][:origin.EXECUTION.size] + origin.EDGE.pack(index)
            with self.assertRaises(ValueError):
                origin.decode(wire(changed), PID)
        changed = metadata(rows, 2, 5, 2)
        changed[2] = 6, PATH, changed[2][2] + origin.EDGE.pack(0)
        with self.assertRaisesRegex(ValueError, "not code"):
            origin.decode(wire(changed), PID)
        changed = rows.copy(); changed[2] = 6, b"/tmp/other.py", rows[2][2]
        with self.assertRaises(ValueError):
            origin.decode(wire(changed), PID)
        for extra in (rows[2], metadata(rows, 2, 1, 92)[2]):
            with self.assertRaises(ValueError):
                origin.decode(wire([*rows[:3], extra, *rows[3:]]), PID)
        # Aliased constant paths cannot assign another execution identity.
        graph = module_graph(); graph["nodes"][1]["items"] = [9, 9]
        changed = rows.copy(); changed[1] = 5, PATH, rows[1][2][:origin.ROOT.size] + encoded(graph)
        extra = metadata(changed, 2, 1, 92)[2]
        extra = 6, PATH, extra[2][:origin.EXECUTION.size] + origin.EDGE.pack(1)
        with self.assertRaisesRegex(ValueError, "member"):
            origin.decode(wire([*changed[:3], extra, *changed[3:]]), PID)

    def test_module_root_execution_with_zero_edges_and_descendant_filename_are_valid(self) -> None:
        rows = fixture(plain=True)
        row = metadata(rows, 2, 5, 0)[2]
        rows[2] = 6, PATH, row[2][:origin.EXECUTION.size]
        self.assertEqual(origin.decode(wire(rows), PID).records[2].member, 1)
        graph = module_graph()
        graph["nodes"].append({"id": 12, "type": "unicode", "value": "/tmp/member.py"})
        graph["nodes"][8]["fields"]["co_filename"] = 12
        rows = fixture(plain=True)
        rows[1] = 5, PATH, rows[1][2][:origin.ROOT.size] + encoded(graph)
        rows[2] = 6, b"/tmp/member.py", rows[2][2]
        self.assertEqual(origin.decode(wire(rows), PID).records[2].path, b"/tmp/member.py")
        graph["filesystem"]["errors"] = "strict"
        graph["nodes"][11]["value"] = "/tmp/\udcff.py"
        rows[1] = 5, PATH, rows[1][2][:origin.ROOT.size] + encoded(graph)
        with self.assertRaisesRegex(ValueError, "filename codec"):
            origin.decode(wire(rows), PID)

    def test_sdk_join_foreign_or_forward_ids_reserved_fields_duplicate_and_graph_mismatch_refuse(self) -> None:
        rows = fixture()
        for field, values in {0: [PID + 1], 1: [0, 2], 2: [0, 92], 3: [1, 2], 4: [1], 5: [1], 6: [1]}.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    origin.decode(wire(metadata(rows, 4, field, value)), PID)
        for changed in ([*rows, rows[-1]], [*rows[:3], rows[-1], rows[3]],
                        [*rows[:3], rows[3], rows[3], rows[-1]],
                        [*rows[:-1], (7, PATH, rows[-1][2] + b"x")],
                        [*rows[:-1], (7, b"/tmp/other.py", rows[-1][2])]):
            with self.assertRaises(ValueError):
                origin.decode(wire(changed), PID)
        graph = function_graph(); graph["nodes"][0]["metadata"]["co_firstlineno"] = 2
        changed = rows.copy()
        raw = encoded(graph)
        changed[3] = 4, PATH, inputs.CODE.pack(PID, 1, 0, VERSION, 2, len(raw), 0) + raw
        with self.assertRaisesRegex(ValueError, "graph differs"):
            origin.decode(wire(changed), PID)

    def test_shared_comparison_budget_and_mixed_descriptor_profiles_refuse(self) -> None:
        rows = fixture()
        for limit in (0, True, 1, 1_000_001):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                origin.decode(wire(rows), PID, comparison_limit=limit)
        graph = function_graph(); graph["filesystem"]["errors"] = "strict"
        raw = encoded(graph)
        changed = rows.copy(); changed[3] = 4, PATH, inputs.CODE.pack(PID, 1, 0, VERSION, 2, len(raw), 0) + raw
        with self.assertRaisesRegex(ValueError, "profile"):
            origin.decode(wire(changed), PID)
        # Two distinct roots/executions with independent read tokens and SDK IDs.
        first = fixture()
        second = fixture()
        second = metadata(second, 1, 1, 78)
        second = metadata(second, 1, 2, 92)
        second = metadata(second, 1, 4, 6)
        second = metadata(second, 2, 1, 93)
        second = metadata(second, 2, 2, 78)
        second = metadata(second, 3, 1, 2)
        second = metadata(second, 4, 1, 2)
        second = metadata(second, 4, 2, 93)
        single_steps = origin.decode(wire(first), PID).comparison_steps
        both = wire([*first, *second])
        self.assertEqual(origin.decode(both, PID).comparison_steps, single_steps * 2)
        with self.assertRaisesRegex(ValueError, "budget exceeded"):
            origin.decode(both, PID, comparison_limit=single_steps)

    def test_sparse_sdk_ids_require_declared_loss_and_join_bijection_is_enforced(self) -> None:
        rows = fixture()
        changed = metadata(rows, 3, 1, 2)
        changed = metadata(changed, 4, 1, 2)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            origin.decode(wire(changed), PID)
        self.assertFalse(origin.decode(wire(changed, capture=1), PID).capture_complete)
        sdk = metadata(rows, 3, 1, 2)[3]
        join = metadata(rows, 4, 1, 2)[4]
        with self.assertRaises(ValueError):
            origin.decode(wire([*rows, sdk, join]), PID)


if __name__ == "__main__":
    unittest.main()
