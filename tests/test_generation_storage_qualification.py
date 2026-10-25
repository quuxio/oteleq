"""A low-disk refusal records no invented launch or terminal process result."""

import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import qualification_storage as storage
from qualify_project_tests import command


class QualificationStorageTests(unittest.TestCase):
    def test_low_space_refuses_before_process_marker_or_launch(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            with storage.budget(10), patch.object(storage.shutil, 'disk_usage', return_value=SimpleNamespace(free=9)), \
                    patch('qualify_project_tests.subprocess.run') as execute:
                with self.assertRaisesRegex(ValueError, 'headroom exhausted'):
                    command(['never-execute'], folder, 'run')
                execute.assert_not_called()
            receipt = json.loads((folder / 'run.storage-refusal.json').read_text())
            self.assertEqual(receipt['applications_started_by_operation'], 0)
            self.assertEqual((receipt['minimum_free_bytes'], receipt['observed_free_bytes']), (10, 9))
            self.assertEqual({p.name for p in folder.iterdir()}, {'run.storage-refusal.json'})

    def test_equal_headroom_runs_the_original_literal_command_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            result = subprocess.CompletedProcess(['tool'], 0, b' output\n', b'notes')
            with storage.budget(10), patch.object(storage.shutil, 'disk_usage', return_value=SimpleNamespace(free=10)), \
                    patch('qualify_project_tests.subprocess.run', return_value=result) as execute:
                self.assertEqual(command(['tool', '$literal; *'], folder, 'run'), 'output')
                self.assertEqual(execute.call_args.args[0], ['tool', '$literal; *'])
                execute.assert_called_once()
            self.assertEqual((folder / 'run.exit').read_text(), '0\n')
            self.assertEqual((folder / 'run.stderr').read_bytes(), b'notes')

    def test_nested_and_failed_contexts_restore_the_previous_floor(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            with patch.object(storage.shutil, 'disk_usage', return_value=SimpleNamespace(free=7)) as usage:
                with self.assertRaises(ValueError), storage.budget(10):
                    with storage.budget(5): storage.check(folder, 'inner')
                    storage.check(folder, 'outer')
                calls = usage.call_count
                storage.check(folder, 'unconfigured')
                self.assertEqual(usage.call_count, calls)
                with storage.budget(0): storage.check(folder, 'disabled')
                self.assertEqual(usage.call_count, calls)

    def test_invalid_limits_and_previous_start_or_refusal_are_not_overwritten(self):
        for value in (-1, True, 1.5, '10'):
            with self.subTest(value=value), self.assertRaises(ValueError), storage.budget(value):
                self.fail('invalid limit entered its context')
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            marker = folder / 'run.started.json'; marker.write_text('original')
            with storage.budget(10), patch.object(storage.shutil, 'disk_usage') as usage:
                with self.assertRaises(AssertionError): command(['never-execute'], folder, 'run')
                usage.assert_not_called()
            self.assertEqual(marker.read_text(), 'original')
            refused = folder / 'other.storage-refusal.json'; refused.write_text('original')
            with storage.budget(10), patch.object(storage.shutil, 'disk_usage', return_value=SimpleNamespace(free=0)):
                with self.assertRaises(FileExistsError): storage.check(folder, 'other')
            self.assertEqual(refused.read_text(), 'original')


if __name__ == '__main__':
    unittest.main()
