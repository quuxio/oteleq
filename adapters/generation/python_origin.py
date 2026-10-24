"""Independent explicit source/cache relations; framing is not runtime admission."""

from dataclasses import dataclass
from pathlib import Path
import struct

import python_code
from python_code_match import Budget, MAX_STEPS, equivalent
import python_journal as inputs
import python_prepared
from python_provider import require

MAGIC = b"OTLCPY2\0"
CACHE_MAGIC = b"OTLCPY3\0"
ROOT = struct.Struct("!10Q")
EXECUTION = struct.Struct("!7Q")
JOIN = struct.Struct("!7Q")
EDGE = struct.Struct("!Q")
WIDTHS = {1: inputs.SOURCE.size, 2: inputs.FINAL.size, 3: inputs.SOURCE.size,
          4: inputs.CODE.size, 5: ROOT.size, 6: EXECUTION.size, 7: JOIN.size}


@dataclass(frozen=True)
class Root:
    """A source compiler or cache return references one earlier consumed input."""

    sequence: int
    identity: int
    transaction: int
    loader: int
    input_sequence: int
    route: int
    compiler_flags: int
    optimisation: int
    descriptor: python_code.Descriptor


@dataclass(frozen=True)
class Execution:
    """One first execution names an actual code-valued constant descendant."""

    sequence: int
    path: bytes
    identity: int
    root: int
    offset: int
    python_version: int
    edges: tuple[int, ...]
    member: int


@dataclass(frozen=True)
class Join:
    """Keep the explicit one-to-one origin/SDK relation in record order."""

    sequence: int
    path: bytes
    sdk: int
    origin: int
    offset: int


Record = inputs.SourceRecord | inputs.CodeRecord | Root | Execution | Join


@dataclass(frozen=True)
class Journal:
    """Capture health alone does not prove selected-function coverage."""

    pid: int
    records: tuple[Record, ...]
    capture_failures: int
    journal_failures: int
    python_finalized: bool
    entry_expected: bool
    comparison_steps: int
    schema_version: int = 2

    @property
    def capture_complete(self) -> bool:
        """Report raw capture health separately from selection and application exit."""
        return self.python_finalized and not self.capture_failures and not self.journal_failures


def _field(descriptor: python_code.Descriptor, member: int, name: str) -> python_code.Node:
    return descriptor.nodes[dict(descriptor.nodes[member - 1].fields)[name] - 1]


def _root(sequence: int, path: bytes, payload: bytes, pid: int,
          sources: dict[int, inputs.SourceRecord], journal_version: int) -> Root:
    actual, identity, transaction, loader, token, route, version, schema, flags, optimisation = ROOT.unpack_from(payload)
    require(actual == pid and identity > 0 and transaction > 0 and token in sources
            and ((route in (1, 2) and flags <= 0x7fffffff and optimisation <= 2)
                 or (journal_version == 3 and route == 3 and flags == 0 and optimisation == 3)),
            "invalid Python compiler root metadata or input reference")
    source = sources[token]
    if route == 3:
        require(source.kind == 3 and loader > 0 and source.path.endswith(b".pyc")
                and path.endswith(b".py") and len(source.content) >= 16,
                "unsupported Python cache root input or code path")
    else:
        require(source.path == path and ((route == 1 and source.kind == 1 and loader == 0)
                or (route == 2 and source.kind == 3 and loader > 0 and path.endswith(b".py"))),
                "unsupported Python compiler root route or path")
    record = inputs.CodeRecord(sequence, path, payload[ROOT.size:], identity, 0, version, schema)
    descriptor = python_code.decode(record)
    require(_field(descriptor, descriptor.root, "co_name").value == "<module>",
            "Python compiler root is not a module")
    return Root(sequence, identity, transaction, loader, token, route, flags, optimisation, descriptor)


def _execution(sequence: int, path: bytes, payload: bytes, pid: int, roots: dict[int, Root]) -> Execution:
    actual, identity, root, offset, version, count, reserved = EXECUTION.unpack_from(payload)
    require(actual == pid and identity > 0 and root in roots and count <= python_code.MAX_DEPTH
            and reserved == 0 and len(payload) == EXECUTION.size + count * EDGE.size,
            "invalid Python origin execution metadata or root reference")
    descriptor = roots[root].descriptor
    require(version == descriptor.record.python_version, "Python origin execution interpreter differs")
    edges = tuple(value[0] for value in EDGE.iter_unpack(payload[EXECUTION.size:]))
    member = descriptor.root
    for index in edges:
        constants = _field(descriptor, member, "co_consts").references
        require(index < len(constants), "Python origin constant edge is outside the tuple")
        member = constants[index]
        require(descriptor.nodes[member - 1].kind == "code", "Python origin constant edge is not code")
    filename = _field(descriptor, member, "co_filename").value
    try:
        encoded = filename.encode(*descriptor.filesystem)
    except (UnicodeError, LookupError) as error:
        raise ValueError("Python prepared provider: unsupported origin filename codec") from error
    require(encoded == path and offset % 2 == 0
            and offset < len(_field(descriptor, member, "co_code").value),
            "Python origin execution filename or offset differs")
    return Execution(sequence, path, identity, root, offset, version, edges, member)


class _Reader:
    def __init__(self, pid: int, comparison_limit: int, version: int):
        self.pid = pid
        self.version = version
        self.records: list[Record] = []
        self.sources: dict[int, inputs.SourceRecord] = {}
        self.roots: dict[int, Root] = {}
        self.codes: dict[int, python_code.Descriptor] = {}
        self.executions: dict[int, Execution] = {}
        self.transactions: set[int] = set()
        self.consumed: set[int] = set()
        self.members: set[tuple[int, int]] = set()
        self.joined_sdk: set[int] = set()
        self.joined_origin: set[int] = set()
        self.profile: tuple | None = None
        self.data_bytes = 0
        self.budget = Budget(comparison_limit)

    def profile_matches(self, descriptor: python_code.Descriptor) -> None:
        profile = (descriptor.record.python_version, descriptor.filesystem)
        require(self.profile is None or self.profile == profile, "mixed Python journal interpreter or filesystem profile")
        self.profile = profile

    def add(self, kind: int, sequence: int, path: bytes, payload: bytes) -> None:
        if kind in (1, 3):
            row = inputs.source_record(sequence, kind, path, payload, self.pid)
            self.sources[sequence] = row
        elif kind == 4:
            row = inputs.code_record(sequence, path, payload, self.pid)
            require(row.identity not in self.codes, "duplicate Python SDK code identity")
            descriptor = python_code.decode(row)
            self.profile_matches(descriptor)
            self.codes[row.identity] = descriptor
        elif kind == 5:
            row = _root(sequence, path, payload, self.pid, self.sources, self.version)
            require(row.identity not in self.roots and row.transaction not in self.transactions
                    and row.input_sequence not in self.consumed, "reused Python compiler root, transaction or read token")
            self.profile_matches(row.descriptor)
            self.roots[row.identity] = row
            self.transactions.add(row.transaction)
            self.consumed.add(row.input_sequence)
        elif kind == 6:
            row = _execution(sequence, path, payload, self.pid, self.roots)
            member = row.root, row.member
            require(row.identity not in self.executions and member not in self.members,
                    "reused Python origin execution identity or member")
            self.executions[row.identity] = row
            self.members.add(member)
        else:
            row = self.join(sequence, path, payload)
        self.records.append(row)
        self.data_bytes += len(payload) - WIDTHS[kind]

    def join(self, sequence: int, path: bytes, payload: bytes) -> Join:
        require(len(payload) == JOIN.size, "Python SDK join has trailing data")
        actual, sdk, origin, offset, *reserved = JOIN.unpack(payload)
        require(actual == self.pid and not any(reserved) and sdk in self.codes and origin in self.executions
                and sdk not in self.joined_sdk and origin not in self.joined_origin,
                "invalid Python SDK join identity or reference")
        code, execution = self.codes[sdk], self.executions[origin]
        require(path == code.record.path == execution.path and offset == code.record.offset == execution.offset
                and code.record.python_version == execution.python_version, "Python SDK join path, offset or version differs")
        root = self.roots[execution.root].descriptor
        require(equivalent(root, execution.member, code, self.budget), "Python SDK join code graph differs")
        self.joined_sdk.add(sdk)
        self.joined_origin.add(origin)
        return Join(sequence, path, sdk, origin, offset)

    def final(self, payload: bytes) -> Journal:
        actual, count, size, capture, journal, finalized, expected = inputs.FINAL.unpack(payload)
        require(actual == self.pid and count == len(self.records) and size == self.data_bytes
                and finalized in (0, 1) and expected in (0, 1), "Python origin terminal counts differ")
        if capture == journal == 0:
            require(set(self.codes) == set(range(1, len(self.codes) + 1)), "Python origin SDK code identities are incomplete")
        return Journal(self.pid, tuple(self.records), capture, journal, bool(finalized), bool(expected),
                       self.budget.steps, self.version)


def decode(data: bytes, pid: int, *, comparison_limit: int = MAX_STEPS, version: int = 2) -> Journal:
    """Require caller-selected framing, backward references and terminal counts.

    This pure-data reader does not claim that a producer really observed its
    declared compiler/loader/VM relations. Authentic runtime qualification and
    selected-function coverage remain separate admission requirements.
    """
    require(type(version) is int and version in (2, 3), "unsupported explicit Python origin journal version")
    require(type(data) is bytes and len(data) <= inputs.MAX_BYTES and type(pid) is int and 0 < pid < 2 ** 64,
            "invalid Python origin journal size or PID")
    reader = _Reader(pid, comparison_limit, version)
    position, sequence = 0, 0
    while position < len(data):
        require(len(data) - position >= inputs.HEADER.size, "truncated Python origin record header")
        magic, kind, flags, reserved, current, path_size, size = inputs.HEADER.unpack_from(data, position)
        position += inputs.HEADER.size
        require(magic == (MAGIC if version == 2 else CACHE_MAGIC) and kind in WIDTHS and flags == reserved == 0
                and current == sequence + 1 and current <= inputs.MAX_RECORDS and path_size <= inputs.MAX_PATH,
                "invalid Python origin record framing")
        width = WIDTHS[kind]
        require(width <= size <= width + inputs.MAX_PAYLOAD and path_size + size <= len(data) - position,
                "invalid Python origin record width or length")
        path = data[position:position + path_size]
        position += path_size
        payload = data[position:position + size]
        position += size
        sequence = current
        if kind == 2:
            require(not path and size == inputs.FINAL.size and position == len(data),
                    "Python origin final record is not terminal")
            return reader.final(payload)
        require(bool(path) and b"\0" not in path, "invalid Python origin record path")
        reader.add(kind, sequence, path, payload)
    raise ValueError("Python prepared provider: origin journal lacks finalization evidence")


def read(path: Path, pid: int, *, comparison_limit: int = MAX_STEPS, version: int = 2) -> Journal:
    """Snapshot an owned bounded private file only after its owner has stopped."""
    return decode(python_prepared.read_bytes(path, inputs.MAX_BYTES), pid,
                  comparison_limit=comparison_limit, version=version)
