"""Private ordered native checkpoints with immutable data and readiness flags."""

import os
from pathlib import Path
import stat
import uuid

import native_inputs as inputs
from native_protocol import encoded, require, same

ROOT_ENV = 'OTELEQ_NATIVE_CONTROL_ROOT'
TOKEN_ENV = 'OTELEQ_NATIVE_CONTROL_TOKEN'
MAX_FRAME = 4 * 1024 * 1024


def directory(path: Path) -> tuple:
    """Directory timestamps/link counts change as new checkpoints are published."""
    info = path.lstat()
    require(path.is_absolute() and path.resolve(strict=True) == path and stat.S_ISDIR(info.st_mode)
            and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
            'unsafe native checkpoint directory')
    return info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid


def empty_directory(path: Path) -> tuple:
    """Empty flags keep write/link facts too, preventing inode-reuse substitutions."""
    directory(path)
    before = inputs.signature(path.lstat())
    require(not any(path.iterdir()) and before == inputs.signature(path.lstat()),
            'native checkpoint flag contains files or changed during inspection')
    return before


class Rendezvous:
    """Publish closed data before the atomic mkdir that makes it readable."""

    def __init__(self, root: Path, steps: int):
        require(type(steps) is int and 1 <= steps <= 32, 'native checkpoints require 1 to 32 calls')
        require(root.is_absolute() and root.resolve() == root,
                'native checkpoints require a canonical private path')
        self.root = root
        root.mkdir(mode=0o700)
        self.identity = directory(root)
        self.token = uuid.uuid4().hex
        self.phases = tuple(phase + '-' + str(index) for index in range(steps)
                            for phase in ('before', 'after')) + ('finish',)
        self.position = 0
        self.pending = None
        self.records = []
        self.frames = []
        self.flags: dict[Path, tuple] = {}

    def environment(self) -> dict:
        return {ROOT_ENV: str(self.root), TOKEN_ENV: self.token}

    def verify(self) -> None:
        """A later checkpoint cannot replace any previously accepted file."""
        require(directory(self.root) == self.identity, 'native checkpoint root changed')
        for record in self.records:
            record.verify()
        for frame in self.frames:
            frame.verify()
        for path, identity in self.flags.items():
            require(empty_directory(path) == identity,
                    'native checkpoint flag changed')

    def value(self) -> dict:
        require(self.position < len(self.phases), 'native checkpoints already finished')
        return {'nonce': self.token, 'phase': self.phases[self.position]}

    def flag(self, phase: str, suffix: str) -> Path:
        return self.root / (phase + '.' + suffix)

    def ready(self) -> inputs.Record | None:
        """A data file without its ready directory is still being published."""
        self.verify()
        value = self.value()
        phase = value['phase']
        allowed = {name + '.ready' for name in self.phases[:self.position + 1]}
        entries = list(self.root.iterdir())
        require(len(entries) <= 4 * len(self.phases) + 32
                and all(path.name in allowed for path in entries if path.name.endswith('.ready')),
                'native checkpoint appeared out of order or exceeded its file budget')
        flag = self.flag(phase, 'ready')
        if not flag.exists() and not flag.is_symlink():
            return None
        identity = empty_directory(flag)
        if self.pending is None:
            record = inputs.read(self.flag(phase, 'ready.json'), private=True, maximum=256)
            require(same(record.value(), value), 'native checkpoint nonce or phase differs')
            self.pending = record
            self.records.append(record)
            self.flags[flag] = identity
        self.pending.verify()
        return self.pending

    def frame(self, index: int) -> inputs.File:
        """Retain one complete original application frame at its paused boundary."""
        require(type(index) is int and index == len(self.frames)
                and self.phases[self.position] == 'after-' + str(index)
                and self.ready() is not None, 'native frame has no ordered after checkpoint')
        path = self.root / ('step-' + str(index) + '.observation')
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) and not path.is_symlink()
                and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o600
                and info.st_nlink == 1 and 0 < info.st_size <= MAX_FRAME,
                'unsafe or oversized native step frame')
        frame = inputs.capture(path, maximum=MAX_FRAME, private=True, keep=True)
        frame.verify()
        require(len(frame.content) == info.st_size, 'native frame changed while reading')
        self.frames.append(frame)
        return frame

    def acknowledge(self) -> inputs.Record:
        """Keep the acknowledgement inode stable before and after child reads."""
        require(self.ready() is not None, 'native acknowledgement has no ready checkpoint')
        value = self.value()
        path = self.flag(value['phase'], 'resume.json')
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write((encoded(value) + '\n').encode())
        record = inputs.read(path, private=True, maximum=256)
        require(same(record.value(), value), 'native acknowledgement changed')
        flag = self.flag(value['phase'], 'resume')
        flag.mkdir(mode=0o700)
        self.flags[flag] = empty_directory(flag)
        self.records.append(record)
        self.pending = None
        self.position += 1
        self.verify()
        return record

    def finish(self) -> None:
        """No missing, copied or extra frame can satisfy the completed schedule."""
        self.verify()
        require(self.position == len(self.phases) and self.pending is None
                and len(self.frames) * 2 + 1 == len(self.phases), 'native checkpoint sequence is incomplete')
        expected = {name + '.' + suffix for name in self.phases
                    for suffix in ('ready.json', 'ready', 'resume.json', 'resume')}
        expected.update('step-' + str(index) + '.observation' for index in range(len(self.frames)))
        require({path.name for path in self.root.iterdir()} == expected,
                'native checkpoint directory has an unexpected file denominator')
