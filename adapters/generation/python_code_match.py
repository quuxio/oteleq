"""Compare validated code subgraphs without constructing or executing code."""

from dataclasses import dataclass
from typing import Iterator

from python_code import Descriptor, Node
from python_provider import require

MAX_STEPS = 1_000_000
CONTAINERS = {"code", "tuple", "frozenset", "slice"}


@dataclass
class Budget:
    """One finite work allowance is shared by every join in a journal."""

    limit: int = MAX_STEPS
    steps: int = 0

    def __post_init__(self) -> None:
        require(type(self.limit) is int and 1 <= self.limit <= MAX_STEPS
                and self.steps == 0, "invalid code comparison budget")

    def spend(self, count: int = 1) -> None:
        """Exhausted matching is refusal, never equality from a partial search."""
        self.steps += count
        require(self.steps <= self.limit, "code graph comparison budget exceeded")


@dataclass(frozen=True)
class _Pending:
    left: int
    right: int | tuple[int, ...]
    remaining: "_Pending | None"
    members: frozenset[int] | None = None


@dataclass
class _Choice:
    left: int
    candidates: Iterator[int]
    remaining: _Pending | None
    checkpoint: int


def _label(node: Node) -> tuple:
    if node.kind in CONTAINERS:
        return (node.kind, node.metadata, tuple(name for name, _ in node.fields), len(node.references))
    return node.kind, node.value


class _Search:
    def __init__(self, left: Descriptor, right: Descriptor, budget: Budget):
        self.left, self.right, self.budget = left, right, budget
        self.forward: dict[int, int] = {}
        self.reverse: dict[int, int] = {}
        self.trail: list[tuple[int, int]] = []

    def same_label(self, left: int, right: int) -> bool:
        return _label(self.left.nodes[left - 1]) == _label(self.right.nodes[right - 1])

    def next_choice(self, choice: _Choice) -> _Pending | None:
        for candidate in choice.candidates:
            self.budget.spend()
            if candidate not in self.reverse and self.same_label(choice.left, candidate):
                return _Pending(choice.left, candidate, choice.remaining)
        return None

    def retry(self, choices: list[_Choice]) -> _Pending | None:
        while choices:
            choice = choices[-1]
            while len(self.trail) > choice.checkpoint:
                left, right = self.trail.pop()
                del self.forward[left]
                del self.reverse[right]
            pending = self.next_choice(choice)
            if pending is not None:
                return pending
            choices.pop()
        return None

    def expand(self, left: int, right: int, remaining: _Pending | None) -> _Pending | None:
        a, b = self.left.nodes[left - 1], self.right.nodes[right - 1]
        self.budget.spend(len(a.references))
        if a.kind == "frozenset":
            members = frozenset(b.references)
            for child in reversed(a.references):
                remaining = _Pending(child, b.references, remaining, members)
        else:
            for child, counterpart in reversed(tuple(zip(a.references, b.references))):
                remaining = _Pending(child, counterpart, remaining)
        return remaining

    def step(self, task: _Pending, choices: list[_Choice]) -> tuple[bool, _Pending | None]:
        self.budget.spend()
        if task.members is not None:
            if task.left in self.forward:
                return self.forward[task.left] in task.members, task.remaining
            choice = _Choice(task.left, iter(task.right), task.remaining, len(self.trail))
            choices.append(choice)
            candidate = self.next_choice(choice)
            return candidate is not None, candidate
        if task.left in self.forward:
            return self.forward[task.left] == task.right, task.remaining
        if task.right in self.reverse or not self.same_label(task.left, task.right):
            return False, task.remaining
        self.forward[task.left] = task.right
        self.reverse[task.right] = task.left
        self.trail.append((task.left, task.right))
        return True, self.expand(task.left, task.right, task.remaining)

    def run(self, left: int, right: int) -> bool:
        # Persistent pending links keep outer constraints in each choice. A
        # later alias can therefore undo an earlier unordered assignment.
        pending = _Pending(left, right, None)
        choices: list[_Choice] = []
        while pending is not None:
            valid, pending = self.step(pending, choices)
            if not valid:
                pending = self.retry(choices)
                if pending is None:
                    return False
        return True


def equivalent(left: Descriptor, member: int, right: Descriptor, budget: Budget) -> bool:
    """Preserve values, ordered slots and aliases; frozensets are unordered.

    Inputs must already have passed the independent descriptor decoder. The
    left root may be a selected descendant of a larger compiler-root graph.
    Equality checks consistency of an explicit origin relation; it cannot
    supply a missing compiler or execution observation.
    """
    require(type(left) is Descriptor and type(right) is Descriptor and type(budget) is Budget
            and type(member) is int and 1 <= member <= len(left.nodes)
            and left.nodes[member - 1].kind == "code", "invalid code comparison input")
    if left.filesystem != right.filesystem or left.record.python_version != right.record.python_version:
        return False
    return _Search(left, right, budget).run(member, right.root)
