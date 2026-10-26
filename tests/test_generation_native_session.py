"""Native pre-exec ownership, publication races, budgets and separate-group cleanup."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]

import native_execution as execution
import native_prepared as prepared
import native_session as session
from test_generation_native_execution import complete, start, write


def setup(root: Path, *, plain: bool = False):
    launch, _ = start(root, plain=plain)
    records = [(launch.intent.runtime / name, json.loads((launch.intent.runtime / name).read_bytes()))
               for name in prepared.START_FILES]
    for path, _ in records: path.unlink()
    controller = session.Session(launch)
    records[0][1]['parent_pid'] = os.getpid()
    for path, value in records: write(path, value)
    process = SimpleNamespace(pid=22, args=prepared.command(launch.intent), poll=lambda: None, returncode=0)
    identities = {22: {'pid': 22, 'parent_pid': os.getpid(), 'process_group': 22, 'session': 22},
                  23: {'pid': 23, 'parent_pid': 22, 'process_group': 23, 'session': 23}}
    return controller, process, identities


class NativeSessionTests(unittest.TestCase):
    def test_waiting_child_is_bound_before_release_and_success_is_retained(self):
        with tempfile.TemporaryDirectory() as temporary:
            controller, process, identities = setup(Path(temporary).resolve())
            root = controller.launch.intent.runtime
            staged = root / 'native-application-start.json.staging'
            os.link(root / prepared.START_FILES[1], staged)
            with patch.object(session, 'kernel', side_effect=lambda pid, deadline: identities[pid]) as query:
                controller.poll(process, time.monotonic() + 10)
                self.assertEqual(query.call_count, 0)
                self.assertFalse((root / execution.RELEASE).exists())
                staged.unlink()
                controller.poll(process, time.monotonic() + 10)
                self.assertEqual(query.call_count, 2)
                controller.poll(process, time.monotonic() + 10)
                self.assertEqual(query.call_count, 2)
            self.assertEqual(controller.child, 23)
            self.assertEqual(json.loads((root / execution.RELEASE).read_bytes())['pid'], 23)
            complete(controller.started)
            controller.finish(process)
            self.assertEqual(len(controller.records), 3)
            controller.execution.verify()
            with patch.object(os, 'killpg') as kill:
                with session.retained(controller): pass
            kill.assert_called_once_with(23, signal.SIGKILL)

    def test_wrong_kernel_parent_group_session_and_dead_supervisor_cannot_release(self):
        for kind in ('parent', 'group', 'session', 'dead', 'command', 'early', 'metadata'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                controller, process, identities = setup(Path(temporary).resolve())
                root = controller.launch.intent.runtime
                if kind == 'parent': identities[23]['parent_pid'] = 99
                elif kind == 'group': identities[23]['process_group'] = 22
                elif kind == 'session': identities[23]['session'] = 22
                elif kind == 'dead': process.poll = lambda: 1
                elif kind == 'command': process.args = ['foreign-program']
                elif kind == 'early': write(root / execution.RELEASE, {})
                else:
                    path = root / prepared.START_FILES[1]; value = json.loads(path.read_bytes())
                    value['pid'] = True; write(path, value)
                with patch.object(session, 'kernel', side_effect=lambda pid, deadline: identities[pid]), self.assertRaises(ValueError):
                    controller.poll(process, time.monotonic() + 10)
                self.assertIsNone(controller.started)
                if kind != 'early': self.assertFalse((root / execution.RELEASE).exists())

    def test_start_missing_records_timeout_and_used_runtime_refuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            controller, process, identities = setup(Path(temporary).resolve())
            path = controller.launch.intent.runtime / prepared.START_FILES[1]; raw = path.read_bytes(); path.unlink()
            controller.poll(process, time.monotonic() + 10)
            self.assertIsNone(controller.started)
            write(path, json.loads(raw))
            with self.assertRaises(ValueError): session.Session(controller.launch)
            with self.assertRaises(ValueError): session.Session(None)
            with patch.object(session, 'kernel', side_effect=lambda pid, deadline: identities[pid]), self.assertRaises(ValueError):
                controller.poll(process, time.monotonic() - 1)

    def test_kernel_query_is_fixed_bounded_ascii_and_checked_against_native_syscalls(self):
        result = subprocess.CompletedProcess([], 0, b'23 22 23\n', b'')
        with patch.object(subprocess, 'run', return_value=result) as run, patch.object(os, 'getpgid', return_value=23), patch.object(os, 'getsid', return_value=23):
            self.assertEqual(session.kernel(23, time.monotonic() + 5),
                {'pid': 23, 'parent_pid': 22, 'process_group': 23, 'session': 23})
            self.assertEqual(run.call_args.args[0], ['/bin/ps', '-p', '23', '-o', 'pid=,ppid=,pgid='])
            for raw in (b'23 22 23 extra', b'24 22 24', b'23 +22 23', b'23 22 00', b'x' * 257):
                run.return_value = subprocess.CompletedProcess([], 0, raw, b'')
                with self.subTest(raw=raw), self.assertRaises(ValueError): session.kernel(23, time.monotonic() + 5)
        with self.assertRaises(ValueError): session.kernel(True, time.monotonic() + 5)
        with self.assertRaises(ValueError): session.kernel(23, time.monotonic() - 1)

    def test_publication_never_replaces_files_and_original_facts_remain_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); path = root / 'host.json'
            value = session.publish(path, {'literal': '$value'})
            value.verify(); self.assertFalse(path.with_name(path.name + '.staging').exists())
            with self.assertRaises(FileExistsError): session.publish(path, {})
            value.verify()
            with patch.object(os, 'link', side_effect=OSError('link failed')), self.assertRaises(OSError):
                session.publish(root / 'failed.json', {})
            self.assertFalse((root / 'failed.json.staging').exists())

    def test_child_cleanup_keeps_primary_errors_and_denied_live_group_is_not_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            controller, _, _ = setup(Path(temporary).resolve()); controller.child = 23
            with patch.object(os, 'killpg', side_effect=ProcessLookupError): controller.close()
            with patch.object(os, 'killpg', side_effect=PermissionError), patch('generation.live_process_group', return_value=False):
                controller.close()
            with patch.object(os, 'killpg', side_effect=PermissionError), patch('generation.live_process_group', return_value=True), self.assertRaises(ValueError):
                controller.close()
            error = ValueError('original execution failure')
            with patch.object(controller, 'close', side_effect=OSError('cleanup failed')):
                with self.assertRaisesRegex(ValueError, 'original execution failure'):
                    with session.retained(controller): raise error
            self.assertIn('cleanup also failed', error.__notes__[0])
            with self.assertRaises(ValueError):
                with session.retained(None): pass


if __name__ == '__main__':
    unittest.main()
