"""Selection coverage requires frozen inputs and actual declared origin relations."""

import copy
from dataclasses import replace
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / 'adapters/generation'), str(REPO / 'examples')]
import python_selection as selection
import python_origin as origin
from test_generation_python_origin import PATH, PID, VERSION, encoded, fixture, metadata, module_graph, wire
from test_generation_python_code import fixture as function_graph


def expected() -> selection.Selection:
    """Literal facts are independent of the retained wire fixture being checked."""
    source = selection.Source(PATH, b'synthetic source bytes\0not executed', 2, 3,
                              -2 * 10 ** 9 + 17, stat.S_IFREG | 0o600)
    return selection.Selection(source, 'workload', 1)


def check(rows: list | None = None, *, plain: bool = False, chosen: tuple | None = None,
          **options) -> tuple[selection.Coverage, ...]:
    journal = origin.decode(wire(fixture(plain=plain) if rows is None else rows), PID)
    return selection.verify(journal, (expected(),) if chosen is None else chosen,
                            python_version=VERSION, optimisation=0, plain=plain, **options)


class PythonSelectionTests(unittest.TestCase):
    def test_both_routes_and_lanes_require_the_selected_first_execution(self) -> None:
        for plain in (False, True):
            for loader in (False, True):
                with self.subTest(plain=plain, loader=loader):
                    rows = fixture(plain=plain, loader=loader)
                    if loader:
                        rows = metadata(rows, 1, 4, 2)
                        rows.insert(0, (1, b'/tmp/caller.py', rows[0][2]))
                    result, = check(rows, plain=plain)
                    self.assertEqual(result.selection, expected())
                    self.assertEqual(result.matches, (selection.Match(77, 91, 9, None if plain else 1),))

    def test_complete_empty_read_only_unexecuted_and_unjoined_journals_refuse(self) -> None:
        for rows in ([], fixture()[:1], fixture()[:2], fixture()[:-1]):
            with self.subTest(records=len(rows)), self.assertRaises(ValueError):
                check(rows)
        with self.assertRaises(ValueError):
            check(fixture(plain=True))
        with self.assertRaises(ValueError):
            check(fixture(), plain=True)

    def test_raw_loss_finalisation_and_missing_entry_expectation_refuse(self) -> None:
        for values in ({'capture': 1}, {'lost': 1}, {'finalized': 0}, {'expected': 0}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                selection.verify(origin.decode(wire(fixture(), **values), PID), (expected(),),
                                 python_version=VERSION, optimisation=0, plain=False)
        with self.assertRaises(ValueError):
            check(fixture(loader=True))

    def test_selected_name_line_source_bytes_and_open_file_identity_are_caller_owned(self) -> None:
        original = expected()
        variants = [replace(original, qualname='other'), replace(original, line=2)]
        for field, value in {'path': b'/tmp/other.py', 'content': b'changed source', 'device': 4,
                             'inode': 5, 'mtime_ns': 0, 'mode': stat.S_IFREG | 0o644}.items():
            variants.append(replace(original, source=replace(original.source, **{field: value})))
        for value in variants:
            with self.subTest(value=value), self.assertRaises(ValueError):
                check(chosen=(value,))

    def test_every_selected_callable_needs_coverage_and_duplicates_refuse(self) -> None:
        for chosen in ((), (expected(), expected()), (expected(), replace(expected(), qualname='unexecuted'))):
            with self.subTest(chosen=chosen), self.assertRaises(ValueError):
                check(chosen=chosen)
        other = replace(expected(), source=replace(expected().source, content=b'changed'), qualname='other')
        with self.assertRaises(ValueError):
            check(chosen=(expected(), other))

    def test_lane_interpreter_and_compiler_profile_are_independent_intent(self) -> None:
        journal = origin.decode(wire(fixture()), PID)
        defaults = {'python_version': VERSION, 'optimisation': 0, 'plain': False}
        for key, values in {'python_version': [True, -1, 2 ** 32, 0x030b0ff0, 0x030e08f0],
                            'optimisation': [True, -1, 3, 1], 'plain': [1, 'false']}.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    selection.verify(journal, (expected(),), **{**defaults, key: value})
        for field in (8, 9):
            with self.subTest(field=field), self.assertRaises(ValueError):
                check(metadata(fixture(), 1, field, 1))
        with self.assertRaises(ValueError):
            selection.verify(None, (expected(),), **defaults)

    def test_ordinary_class_method_names_are_checked_without_executing_descriptors(self) -> None:
        rows = fixture()
        root, code = module_graph(), function_graph()
        root['nodes'].append({'id': 12, 'type': 'unicode', 'value': 'Counter.workload'})
        root['nodes'][8]['fields']['co_qualname'] = 12
        code['nodes'].append({'id': 9, 'type': 'unicode', 'value': 'Counter.workload'})
        code['nodes'][0]['fields']['co_qualname'] = 9
        rows[1] = 5, PATH, rows[1][2][:origin.ROOT.size] + encoded(root)
        header = list(selection.inputs.CODE.unpack_from(rows[3][2]))
        header[5] = len(encoded(code))
        rows[3] = 4, PATH, selection.inputs.CODE.pack(*header) + encoded(code)
        with patch('builtins.compile', side_effect=AssertionError('must not compile')):
            result, = check(rows, chosen=(replace(expected(), qualname='Counter.workload'),))
        self.assertEqual(len(result.matches), 1)
        for flags in (0, 4, 8, 16, 32, 128, 512):
            changed_root, changed_code = copy.deepcopy(root), copy.deepcopy(code)
            changed_root['nodes'][8]['metadata']['co_flags'] = (3 | flags) if flags else 0
            changed_code['nodes'][0]['metadata']['co_flags'] = (3 | flags) if flags else 0
            changed = rows.copy()
            changed[1] = 5, PATH, rows[1][2][:origin.ROOT.size] + encoded(changed_root)
            header[5] = len(encoded(changed_code))
            changed[3] = 4, PATH, selection.inputs.CODE.pack(*header) + encoded(changed_code)
            with self.subTest(flags=flags), self.assertRaises(ValueError):
                check(changed, chosen=(replace(expected(), qualname='Counter.workload'),))

    def test_unaccounted_sdk_code_cannot_be_hidden_by_a_matching_selected_join(self) -> None:
        rows = fixture()
        extra = metadata(fixture(), 3, 1, 2)[3]
        rows.append(extra)
        with self.assertRaises(ValueError):
            check(rows)

    def test_repeated_compilations_keep_distinct_roots_and_execution_relations(self) -> None:
        second = fixture()
        for index, field, value in ((1, 1, 78), (1, 2, 91), (1, 4, 6), (2, 1, 92),
                                    (2, 2, 78), (3, 1, 2), (4, 1, 2), (4, 2, 92)):
            second = metadata(second, index, field, value)
        result, = check(fixture() + second)
        self.assertEqual(result.matches, (selection.Match(77, 91, 9, 1), selection.Match(78, 92, 9, 2)))

    def test_selection_shapes_paths_and_expected_source_budget_are_bounded(self) -> None:
        original = expected()
        for value in [None, [], (None,), (replace(original, source=None),),
                      *((replace(original, qualname=name),) for name in ('', '<module>', 'f.<locals>.g', 'a.b.c', 'class')),
                      (replace(original, line=True),), (replace(original, line=0),)]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                check(chosen=value if value is not None else (None,))
        for field, value in {'path': b'relative.py', 'content': 'text', 'device': True,
                             'inode': 0, 'mtime_ns': True, 'mode': stat.S_IFDIR | 0o700}.items():
            with self.subTest(field=field), self.assertRaises(ValueError):
                check(chosen=(replace(original, source=replace(original.source, **{field: value})),))
        with patch.object(selection.inputs, 'MAX_BYTES', 1), self.assertRaises(ValueError):
            check()

    def test_freeze_preserves_exact_file_facts_and_refuses_links_special_or_large_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = root / 'entry.py'
            path.write_bytes(b'original\0bytes')
            frozen = selection.freeze(path)
            info = path.stat()
            self.assertEqual((frozen.path, frozen.content, frozen.device, frozen.inode, frozen.mtime_ns, frozen.mode),
                             (os.fsencode(path), b'original\0bytes', info.st_dev, info.st_ino, info.st_mtime_ns, info.st_mode))
            self.assertEqual(len(frozen.sha256), 64)
            alias = root / 'alias.py'; alias.symlink_to(path)
            fifo = root / 'pipe.py'; os.mkfifo(fifo)
            for candidate in (alias, fifo, Path('entry.py')):
                with self.subTest(candidate=candidate), self.assertRaises((ValueError, OSError)):
                    selection.freeze(candidate)
            with path.open('wb') as stream:
                stream.truncate(selection.inputs.MAX_PAYLOAD + 1)
            with self.assertRaises(ValueError):
                selection.freeze(path)

    def test_freeze_refuses_an_input_replaced_during_its_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / 'entry.py'; path.write_text('original')
            actual, calls = os.fstat, 0
            def replaced(descriptor):
                nonlocal calls
                calls += 1
                if calls == 2:
                    path.unlink(); path.write_text('replaced')
                return actual(descriptor)
            with patch.object(selection.os, 'fstat', side_effect=replaced), self.assertRaises(ValueError):
                selection.freeze(path)


if __name__ == '__main__':
    unittest.main()
