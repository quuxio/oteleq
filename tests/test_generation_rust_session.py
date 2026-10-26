"""Rust host release requires actual ownership; literal and controlled OS probes."""

import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import native_session as shared
import rust_execution as execution
import rust_prepared as prepared
import rust_session as session
import test_generation_rust_execution as literal_execution
import test_generation_rust_prepared as literal_preparation


class RustSessionTests(unittest.TestCase):
    def fixture(self, *, plain: bool = False):
        helper = literal_execution.RustExecutionTests('test_all_profiles_and_lanes_hold_start_release_completion_without_inventing_image_proof')
        self.addCleanup(helper.doCleanups)
        _, launch, _ = helper.fixture(plain=plain)
        records = [(launch.intent.runtime / name, json.loads((launch.intent.runtime / name).read_text()))
                   for name in execution.START_FILES]
        for path, _ in records: path.unlink()
        controller = session.Session(launch)
        records[0][1]['parent_pid'] = os.getpid()
        for path, value in records: literal_execution.publish(path, value)
        process = SimpleNamespace(pid=22, args=list(controller.command), poll=lambda: None, returncode=0)
        identities = {22: {'pid': 22, 'parent_pid': os.getpid(), 'process_group': 22, 'session': 22},
                      23: {'pid': 23, 'parent_pid': 22, 'process_group': 23, 'session': 23}}
        return helper, controller, process, identities

    def test_pending_publication_cannot_release_then_owned_completion_keeps_original_ack(self) -> None:
        helper, controller, process, identities = self.fixture()
        root = controller.launch.intent.runtime
        staged = root / '.staging'; os.link(root / execution.START_FILES[1], staged)
        with patch.object(shared, 'kernel', side_effect=lambda pid, deadline: identities[pid]) as query:
            controller.poll(process, time.monotonic() + 20)
            self.assertEqual(query.call_count, 0)
            self.assertFalse((root / execution.RELEASE).exists())
            staged.unlink()
            controller.poll(process, time.monotonic() + 20)
            self.assertEqual(query.call_count, 2)
            controller.poll(process, time.monotonic() + 20)
            self.assertEqual(query.call_count, 2)
        helper.complete(controller.started)
        controller.finish(process)
        self.assertEqual(len(controller.records), 3)
        controller.execution.verify()
        with patch.object(os, 'killpg') as kill:
            with session.retained(controller): pass
        kill.assert_called_once_with(23, signal.SIGKILL)

    def test_bad_kernel_ownership_deadline_or_supervisor_cannot_release(self) -> None:
        for kind in ('parent', 'group', 'session', 'dead', 'command', 'early', 'metadata', 'deadline'):
            _, controller, process, identities = self.fixture()
            root = controller.launch.intent.runtime
            if kind == 'parent': identities[23]['parent_pid'] = 99
            elif kind == 'group': identities[23]['process_group'] = 22
            elif kind == 'session': identities[23]['session'] = 22
            elif kind == 'dead': process.poll = lambda: 1
            elif kind == 'command': process.args = ['foreign']
            elif kind == 'early': literal_execution.publish(root / execution.RELEASE, {})
            elif kind == 'metadata':
                path = root / execution.START_FILES[1]; row = json.loads(path.read_text())
                row['pid'] = True; literal_execution.publish(path, row)
            deadline = time.monotonic() + (-1 if kind == 'deadline' else 20)
            with patch.object(shared, 'kernel', side_effect=lambda pid, deadline: identities[pid]), \
                    self.subTest(kind=kind), self.assertRaises(ValueError):
                controller.poll(process, deadline)
            self.assertIsNone(controller.started)
            if kind != 'early': self.assertFalse((root / execution.RELEASE).exists())

    def test_missing_used_and_changed_start_or_finish_records_stay_incomplete(self) -> None:
        _, controller, process, identities = self.fixture()
        root = controller.launch.intent.runtime
        path = root / execution.START_FILES[1]; raw = path.read_bytes(); path.unlink()
        controller.poll(process, time.monotonic() + 20)
        self.assertIsNone(controller.started)
        literal_execution.publish(path, json.loads(raw))
        with self.assertRaises(ValueError): session.Session(controller.launch)
        with self.assertRaises(ValueError): session.Session(None)
        with self.assertRaises(ValueError): controller.finish(process)
        with patch.object(shared, 'kernel', side_effect=lambda pid, deadline: identities[pid]):
            controller.poll(process, time.monotonic() + 20)
        process.pid = 24
        with self.assertRaises(ValueError): controller.poll(process, time.monotonic() + 20)
        with self.assertRaises(ValueError): controller.finish(process)

    def test_release_deadline_is_rechecked_after_binding_and_original_host_publication(self) -> None:
        _, controller, process, identities = self.fixture()
        with patch.object(shared, 'kernel', side_effect=lambda pid, deadline: identities[pid]), \
                patch.object(session.time, 'monotonic', side_effect=(0, 2)), self.assertRaises(ValueError):
            controller.poll(process, 1)
        self.assertEqual(controller.child, 23)
        self.assertIsNotNone(controller.started)
        self.assertFalse((controller.launch.intent.runtime / execution.RELEASE).exists())

    def test_shared_cleanup_preserves_primary_errors_and_denied_live_groups_refuse(self) -> None:
        _, controller, _, _ = self.fixture(); controller.child = 23
        with patch.object(os, 'killpg', side_effect=ProcessLookupError): controller.close()
        with patch.object(os, 'killpg', side_effect=PermissionError), patch('generation.live_process_group', return_value=False):
            controller.close()
        with patch.object(os, 'killpg', side_effect=PermissionError), patch('generation.live_process_group', return_value=True), \
                self.assertRaises(ValueError): controller.close()
        error = ValueError('original failure')
        with patch.object(controller, 'close', side_effect=OSError('cleanup failure')):
            with self.assertRaisesRegex(ValueError, 'original failure'):
                with session.retained(controller): raise error
        self.assertIn('cleanup also failed', error.__notes__[0])
        with self.assertRaises(ValueError):
            with session.retained(None): pass

    def test_real_python_gate_processes_verify_kernel_parent_groups_and_release_order(self) -> None:
        """Two controlled Python test helpers exercise OS ownership, not Rust/SDK code."""
        helper = literal_preparation.RustPreparedTests('test_both_source_profiles_and_lanes_hold_literal_arguments_without_processes')
        self.addCleanup(helper.doCleanups)
        fixture, original = helper.fixture(plain=True)
        source = fixture.sdk.root / 'otelc/rust_supervisor.py'
        source.write_text(PYTHON_GATE)
        intent = prepared.freeze(original.build, original.runtime, Path(sys.executable).absolute(),
            original.policy_file.path, original.policy(), plain=True, wait_ms=12345)
        helper.publish(intent); controller = session.Session(prepared.read(intent))
        process = subprocess.Popen(list(controller.command), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True)
        try:
            self.assertTrue(select.select([process.stdout], [], [], 10)[0])
            self.assertEqual(process.stdout.readline(), b'ready\n')
            marker = intent.runtime / 'released-marker'
            self.assertFalse(marker.exists())
            controller.poll(process, time.monotonic() + 20)
            self.assertEqual(controller.started.owner.pid, process.pid)
            self.assertNotEqual(controller.child, process.pid)
            out, err = process.communicate(timeout=15)
            self.assertEqual((process.returncode, out, err), (0, b'', b''))
            self.assertEqual(marker.read_text(), str(controller.child))
            controller.finish(process)
            controller.execution.verify()
        finally:
            if process.poll() is None:
                process.terminate()
            try: process.communicate(timeout=5)
            finally: controller.close()


PYTHON_GATE = '''import json, os, signal, subprocess, sys, time
from pathlib import Path
runtime=Path(sys.argv[1]);request=json.loads((runtime/'rust-request.json').read_text());plan=json.loads((runtime/'rust-plan.json').read_text())
def publish(name,row):
 path=runtime/name;path.write_text(json.dumps(row));path.chmod(0o600)
def stop(number,frame):raise SystemExit(128+number)
signal.signal(signal.SIGTERM,stop)
child_code="""import os,sys,time
from pathlib import Path
root=Path(sys.argv[1]);deadline=time.monotonic()+12
while not (root/'rust-host-release.json').exists():
 if time.monotonic()>deadline:raise SystemExit(78)
 time.sleep(.005)
(root/'released-marker').write_text(str(os.getpid()))
"""
child=subprocess.Popen([sys.executable,'-I','-S','-c',child_code,str(runtime)],start_new_session=True)
try:
 sup={'schema_version':1,'kind':'otelc.rust.supervisor','pid':os.getpid(),'parent_pid':os.getppid(),'process_group':os.getpgrp(),'session':os.getsid(0),'launch_id':request['launch_id']}
 app={'schema_version':1,'kind':'otelc.rust.application','pid':child.pid,'parent_pid':os.getpid(),'process_group':child.pid,'session':child.pid,'supervisor_pid':os.getpid(),'launch_id':request['launch_id'],'image':plan['image'],'phase':'waiting_exec','source_complete':False}
 publish('rust-supervisor-start.json',sup);publish('rust-application-start.json',app);print('ready',flush=True)
 code=child.wait(timeout=15)
 import hashlib
 digest=lambda x:hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':')).encode()).hexdigest()
 publish('rust-execution.json',{'schema_version':1,'kind':'otelc.rust.execution','profile':'rust1981-owned-standalone-v1','request_sha256':digest(request),'plan_sha256':digest(plan),'supervisor':sup,'application':app,'released':True,'process_exit_code':code,'supervisor_exit_code':code,'exec_verified':False,'sdk_health':None,'inputs_rechecked':True,'failures':{},'source_complete':False})
 raise SystemExit(code)
finally:
 if child.poll() is None:os.killpg(child.pid,signal.SIGKILL)
 child.wait()
'''


if __name__ == '__main__':
    unittest.main()
