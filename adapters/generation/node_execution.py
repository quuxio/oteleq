"""Check Node body-entry witnesses independently of returned loader emissions."""

from pathlib import Path

import node_source as provider

ORIGIN = ("path", "url", "logical_source")
FINAL = {"loaded", "instrumented"}
ENTRY_FIELDS = {"kind", "path", "load_id", "pid", "url", "logical_source", "source_sha256",
                "emission_kind", "emission_sha256", "format", "execution_protocol"}
REENTRY_FIELDS = {"kind", "path", "load_id", "previous_load_id", "logical_source", "url"}


def observer(emission: dict, root: Path) -> str:
    """Only the pinned helper and a concrete parsing goal describe this delta."""
    value = emission.get("body_entry")
    provider.require(type(value) is dict and set(value) == {"schema_version", "goal", "helper"}
                     and type(value["schema_version"]) is int and value["schema_version"] == 1
                     and value["goal"] in ("commonjs", "module")
                     and value["helper"] == str(root / "adapters/node/src/source-inputs.ts"),
                     "invalid module body observation helper")
    provider.require(emission.get("format") in ("node-detected", value["goal"]),
                     "returned module format contradicts its body observation goal")
    return value["goal"]


def body_entry(record: dict, emission: dict, value: dict, pid: int) -> None:
    """Bind the real process and original source to already returned bytes."""
    provider.require(set(record) == ENTRY_FIELDS and type(record["execution_protocol"]) is int
                     and record["execution_protocol"] == provider.PROTOCOLS["execution"],
                     "invalid module execution protocol")
    goal = observer(emission, Path(value["provider"]))
    provider.require(type(record["pid"]) is int and record["pid"] == pid
                     and all(record[key] == emission[key] for key in (*ORIGIN, "source_sha256"))
                     and record["emission_kind"] == emission["kind"]
                     and record["emission_sha256"] == emission["sha256"] and record["format"] == goal,
                     "module body entry differs from actual process, source or returned bytes")


def reentry(record: dict, requests: dict, emissions: dict, entries: dict,
            successors: dict, previous: dict, last_request: int | None) -> None:
    """A reentry names the preceding same-URL attempt, without a causal claim."""
    provider.require(set(record) == REENTRY_FIELDS, "invalid module reentry fields")
    load, earlier = record["load_id"], record["previous_load_id"]
    provider.require(type(earlier) is int and earlier in requests and earlier < load
                     and previous[load] == earlier and earlier not in successors
                     and load == last_request and load not in emissions,
                     "module reentry has no unique preceding same-URL attempt")
    provider.require(all(record[key] == requests[load][key] == requests[earlier][key] for key in ORIGIN)
                     and earlier in emissions and earlier not in entries,
                     "module reentry lacks a complete unentered preceding emission")
    successors[earlier] = load


def later_entry(load: int, entries: dict, successors: dict) -> int:
    """Only a complete increasing same-URL chain can reach an observed body."""
    later = load
    while later in successors and later not in entries:
        later = successors[later]
    provider.require(later != load and later in entries, "module body entry is unverified")
    return later


def outcomes(requests: dict, emissions: dict, entries: dict, successors: dict, value: dict) -> list[dict]:
    """Unentered attempts need a complete retained chain to a later actual entry."""
    result = []
    for load, request in requests.items():
        emission = emissions.get(load)
        expected = "instrumented" if not value["plain"] and request["path"] == value["entry"] else "loaded"
        provider.require(emission is not None and emission["kind"] == expected,
                         "module execution lacks its required returned emission")
        required = expected == "instrumented" or request["module_type"] == "typescript"
        if required or "body_entry" in emission:
            observer(emission, Path(value["provider"]))
        outcome = {"load_id": load, **{key: request[key] for key in ORIGIN},
                   "returned_format": emission["format"], "resolved_format": None, "outcome": "not_observed"}
        if load in entries:
            outcome.update(outcome="body_entered", resolved_format=entries[load]["format"])
        elif required:
            later = later_entry(load, entries, successors)
            outcome.update(outcome="unentered_before_same_url_entry", reentered_by=successors[load],
                           later_entry_load_id=later)
        result.append(outcome)
    return result


def verify(records: list, value: dict, pid: int) -> list[dict]:
    """Reconstruct execution1 outcomes from the independently verified raw journal."""
    requests, emissions, entries, successors, previous, last_urls = {}, {}, {}, {}, {}, {}
    last_request = None
    for record in records:
        kind = record["kind"]
        if kind not in {"module_requested", "module_reentered", "execution_started"} | FINAL:
            last_request = None
            continue
        load = record.get("load_id")
        provider.require(type(load) is int and load > 0, "invalid module execution load identity")
        if kind == "module_requested":
            provider.require(load == len(requests) + 1, "module execution request order is incomplete")
            requests[load] = record
            previous[load] = last_urls.get(record["url"])
            last_urls[record["url"]] = last_request = load
            continue
        provider.require(load in requests and all(record.get(key) == requests[load][key] for key in ORIGIN),
                         "module execution changed its requested origin")
        if kind == "module_reentered":
            reentry(record, requests, emissions, entries, successors, previous, last_request)
        elif kind in FINAL:
            provider.require(load not in emissions and load not in entries, "duplicate returned module emission")
            emissions[load] = record
        else:
            provider.require(load in emissions and load not in entries, "module entry precedes its emission or is duplicated")
            body_entry(record, emissions[load], value, pid)
            entries[load] = record
        last_request = None
    return outcomes(requests, emissions, entries, successors, value)
