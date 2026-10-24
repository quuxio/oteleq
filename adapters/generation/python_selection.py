"""Bind selected ordinary Python callables to independently expected source facts.

This consumer checks decoded origin relations and selection coverage. Authentic
producer qualification, prepared transport, telemetry and per-action attribution
remain separate. First-execution identities are not invocation counts.
"""

from dataclasses import dataclass
import hashlib
import inspect
import keyword
import os
from pathlib import Path
import stat

import python_code
import python_journal as inputs
import python_origin as origin
from python_provider import require

FUNCTION_FLAGS = inspect.CO_OPTIMIZED | inspect.CO_NEWLOCALS
UNSUPPORTED_FLAGS = (inspect.CO_VARARGS | inspect.CO_VARKEYWORDS | inspect.CO_NESTED |
                     inspect.CO_GENERATOR | inspect.CO_COROUTINE | inspect.CO_ITERABLE_COROUTINE |
                     inspect.CO_ASYNC_GENERATOR)


@dataclass(frozen=True)
class Source:
    """Caller-owned file facts frozen before application launch."""

    path: bytes
    content: bytes
    device: int
    inode: int
    mtime_ns: int
    mode: int

    @property
    def sha256(self) -> str:
        """Identify the independently retained source bytes."""
        return hashlib.sha256(self.content).hexdigest()


def _signature(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_mode, info.st_uid, info.st_gid, info.st_nlink)


def freeze(path: Path) -> Source:
    """Read bounded canonical source without following a link or blocking on a FIFO."""
    require(path.is_absolute() and path == path.resolve(strict=True),
            "selected Python source must have a canonical absolute path")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode) and before.st_size <= inputs.MAX_PAYLOAD,
                "selected Python source is not a bounded regular file")
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            content = stream.read(inputs.MAX_PAYLOAD + 1)
        require(len(content) == before.st_size and
                _signature(before) == _signature(os.fstat(descriptor)) == _signature(path.lstat()),
                "selected Python source changed while freezing")
    finally:
        os.close(descriptor)
    return Source(os.fsencode(path), content, before.st_dev, before.st_ino,
                  before.st_mtime_ns, before.st_mode)


@dataclass(frozen=True)
class Selection:
    """The planner supplies an ordinary function or declared plain receiver method."""

    source: Source
    qualname: str
    line: int


@dataclass(frozen=True)
class Match:
    """One first-execution relation, with a separate optional SDK code identity."""

    root: int
    execution: int
    member: int
    sdk: int | None


@dataclass(frozen=True)
class Coverage:
    """Keep every selected callable and its actual matching relations visible."""

    selection: Selection
    matches: tuple[Match, ...]


def _selections(value: tuple[Selection, ...]) -> dict[tuple[bytes, str, int], Selection]:
    require(type(value) is tuple and 0 < len(value) <= inputs.MAX_RECORDS,
            "selected Python callables must be a non-empty bounded tuple")
    result, sources = {}, {}
    for selection in value:
        require(type(selection) is Selection and type(selection.source) is Source,
                "invalid caller-owned Python selection")
        source = selection.source
        require(type(source.path) is bytes and source.path.startswith(b'/') and
                0 < len(source.path) <= inputs.MAX_PATH and b'\0' not in source.path and
                os.path.normpath(source.path) == source.path and type(source.content) is bytes and
                len(source.content) <= inputs.MAX_PAYLOAD and type(source.device) is int and 0 <= source.device < 2 ** 64 and
                type(source.inode) is int and 0 < source.inode < 2 ** 64 and type(source.mtime_ns) is int and
                type(source.mode) is int and 0 <= source.mode <= 0xffffffff and stat.S_ISREG(source.mode),
                "invalid frozen Python source facts")
        require(source.path not in sources or sources[source.path] == source,
                "conflicting frozen Python sources")
        sources[source.path] = source
        require(type(selection.qualname) is str and 0 < len(selection.qualname) <= 1024 and
                len(selection.qualname.split('.')) <= 2 and
                all(part.isidentifier() and not keyword.iskeyword(part) for part in selection.qualname.split('.')) and
                type(selection.line) is int and 0 < selection.line <= 0x7fffffff,
                "selected Python callable needs an ordinary name and source line")
        key = source.path, selection.qualname, selection.line
        require(key not in result, "duplicate selected Python callable")
        result[key] = selection
    require(sum(len(source.content) for source in sources.values()) <= inputs.MAX_BYTES,
            "frozen selected Python sources exceed the byte budget")
    return result


def _label(descriptor: python_code.Descriptor, member: int) -> tuple[str, str, int, int]:
    node = descriptor.nodes[member - 1]
    fields, metadata = dict(node.fields), dict(node.metadata)
    return (descriptor.nodes[fields['co_qualname'] - 1].value,
            descriptor.nodes[fields['co_name'] - 1].value,
            metadata['co_firstlineno'], metadata['co_flags'])


def _source_matches(actual: inputs.SourceRecord, expected: Source) -> bool:
    return (actual.content, actual.device, actual.inode, actual.mtime_ns, actual.mode) == (
        expected.content, expected.device, expected.inode, expected.mtime_ns, expected.mode)


def verify(journal: origin.Journal, selected: tuple[Selection, ...], *,
           python_version: int, optimisation: int, plain: bool) -> tuple[Coverage, ...]:
    """Require selected execution in each lane; matching raw health is insufficient.

    The caller must first decode against its independently observed application
    PID. Expected file facts and selection never come from the journal. Only
    already qualified ordinary synchronous callable shapes belong here.
    """
    selections = _selections(selected)
    require(type(journal) is origin.Journal and journal.capture_complete and journal.entry_expected,
            "selected Python origin capture is incomplete")
    require(type(plain) is bool and type(python_version) is int and 0 <= python_version <= 0xffffffff and
            python_version >> 24 == 3 and (python_version >> 16 & 255) >= 12 and
            type(optimisation) is int and 0 <= optimisation <= 2,
            "invalid selected Python lane or interpreter")
    sources = {item.source.path: item.source for item in selected}
    reads, roots, codes, joins = {}, {}, set(), {}
    for row in journal.records:
        if type(row) is inputs.SourceRecord:
            if row.path in sources:
                require(_source_matches(row, sources[row.path]), "selected Python source read differs from frozen input")
                reads[row.sequence] = row
        elif type(row) is origin.Root:
            require(row.descriptor.record.python_version == python_version, "Python compiler root interpreter differs")
            roots[row.identity] = row
        elif type(row) is inputs.CodeRecord:
            require(row.python_version == python_version, "Python SDK code interpreter differs")
            codes.add(row.identity)
        elif type(row) is origin.Join:
            joins[row.origin] = row.sdk
    require(any(type(row) is inputs.SourceRecord and row.kind == 1 for row in journal.records),
            "selected Python capture lacks its native entry")
    require(not plain or not codes and not joins, "plain Python lane contains SDK code or joins")
    matches = {key: [] for key in selections}
    members = {}
    for row in journal.records:
        if type(row) is not origin.Execution:
            continue
        root = roots[row.root]
        if root.input_sequence not in reads:
            continue
        require(root.compiler_flags == 0 and root.optimisation == optimisation,
                "selected Python compiler inputs differ from the declared profile")
        qualname, name, line, flags = _label(root.descriptor, row.member)
        key = row.path, qualname, line
        if key not in selections:
            continue
        require(name == qualname.rsplit('.', 1)[-1] and flags & FUNCTION_FLAGS == FUNCTION_FLAGS and
                not flags & UNSUPPORTED_FLAGS,
                "selected Python callable is not an ordinary synchronous function")
        member_key = row.root, key
        require(member_key not in members or members[member_key] == row.member,
                "selected Python callable has ambiguous compiler members")
        members[member_key] = row.member
        require(plain or row.identity in joins, "selected Python execution lacks its SDK code join")
        matches[key].append(Match(row.root, row.identity, row.member, joins.get(row.identity)))
    require(all(matches.values()), "selected Python callable lacks source-bound execution")
    require(plain or codes == {match.sdk for group in matches.values() for match in group},
            "Python SDK code is outside the declared callable selection")
    return tuple(Coverage(selection, tuple(matches[key])) for key, selection in selections.items())
