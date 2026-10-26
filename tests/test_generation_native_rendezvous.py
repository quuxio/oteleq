"""Real private files expose publication ordering, replacement and framing defects."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]

import native_rendezvous as checkpoints


def private(path, raw):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
        stream.write(raw)


def ready(session, *, value=None, flag=True):
    phase = session.phases[session.position]
    private(session.flag(phase, 'ready.json'), (json.dumps(session.value() if value is None else value) + '\n').encode())
    if flag: session.flag(phase, 'ready').mkdir(mode=0o700)


class NativeRendezvousTests(unittest.TestCase):
    def session(self, base, steps=1):
        return checkpoints.Rendezvous(Path(base).resolve() / 'rendezvous', steps)

    def test_closed_data_precedes_ready_and_every_frame_acknowledgement_is_immutable(self):
        with tempfile.TemporaryDirectory() as base:
            session = self.session(base, 2)
            self.assertEqual(session.environment()[checkpoints.ROOT_ENV], str(session.root))
            self.assertEqual(len(session.environment()[checkpoints.TOKEN_ENV]), 32)
            self.assertIsNone(session.ready())
            for phase in session.phases:
                ready(session, flag=False)
                self.assertIsNone(session.ready())
                session.flag(phase, 'ready').mkdir(mode=0o700)
                self.assertEqual(session.ready().value(), session.value())
                if phase.startswith('after-'):
                    index = int(phase.split('-')[1])
                    private(session.root / ('step-' + str(index) + '.observation'), b'original\nafter\nbytes\x00')
                    self.assertEqual(session.frame(index).content, b'original\nafter\nbytes\x00')
                record = session.acknowledge()
                record.verify()
                self.assertEqual(record.value()['phase'], phase)
            session.finish()
            self.assertEqual(len(session.flags), 10)
            with self.assertRaises(ValueError): session.value()
            private(session.root / 'unexpected', b'x')
            with self.assertRaises(ValueError): session.finish()

    def test_early_future_nonce_and_nonempty_or_symlink_flags_refuse(self):
        for mode in ('future', 'nonce', 'extra', 'symlink', 'mode'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as base:
                session = self.session(base)
                if mode == 'future': session.flag('finish', 'ready').mkdir(mode=0o700)
                else:
                    value = session.value()
                    if mode == 'nonce': value['nonce'] = '0' * 32
                    ready(session, value=value, flag=mode != 'symlink')
                    flag = session.flag('before-0', 'ready')
                    if mode == 'extra': private(flag / 'extra', b'x')
                    elif mode == 'symlink': flag.symlink_to(session.root, target_is_directory=True)
                    elif mode == 'mode': flag.chmod(0o755)
                with self.assertRaises(ValueError): session.ready()

    def test_previously_accepted_flag_or_record_replacement_cannot_be_repaired(self):
        for kind in ('flag', 'data', 'root'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as base:
                session = self.session(base); ready(session); session.acknowledge()
                if kind == 'flag':
                    path = session.flag('before-0', 'ready'); path.rename(path.with_name('held')); path.mkdir(mode=0o700)
                elif kind == 'data':
                    path = session.flag('before-0', 'ready.json'); raw = path.read_bytes()
                    path.rename(path.with_name('held')); private(path, raw)
                else:
                    path = session.root; path.rename(path.with_name('held')); path.mkdir(mode=0o700)
                with self.assertRaises(ValueError): session.verify()

    def test_frames_require_the_right_phase_owned_single_link_complete_bytes_and_budget(self):
        for kind in ('wrong-phase', 'missing-ready', 'empty', 'large', 'mode', 'link', 'symlink'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as base:
                session = self.session(base)
                if kind != 'wrong-phase': ready(session); session.acknowledge()
                if kind != 'missing-ready': ready(session)
                path = session.root / 'step-0.observation'
                private(path, b'' if kind == 'empty' else b'12345')
                if kind == 'mode': path.chmod(0o644)
                elif kind == 'link': os.link(path, session.root / 'extra-link')
                elif kind == 'symlink': path.rename(path.with_name('held')); path.symlink_to(session.root / 'held')
                with patch.object(checkpoints, 'MAX_FRAME', 4 if kind == 'large' else 100), self.assertRaises(ValueError):
                    session.frame(0)

    def test_premature_ack_finish_invalid_counts_and_existing_root_refuse(self):
        with tempfile.TemporaryDirectory() as base:
            for count in (0, 33, True):
                with self.subTest(count=count), self.assertRaises(ValueError): self.session(base, count)
            session = self.session(base)
            with self.assertRaises(FileExistsError): self.session(base)
            with self.assertRaises(ValueError): session.acknowledge()
            with self.assertRaises(ValueError): session.finish()
        with self.assertRaises(ValueError): checkpoints.Rendezvous(Path('relative'), 1)


if __name__ == '__main__':
    unittest.main()
