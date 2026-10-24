"""Independent bounded client for the source Node SDK's live metric endpoint."""

from pathlib import Path
import re
import time
from typing import cast

import node_source as provider
from live_control import endpoint, exchange

COMMANDS = {"status", "flush", "collection on", "collection off", "emission on", "emission off"}
MAX_REPLY = 4096
MAX_STATUSES = 512
CONTROL_FILE = "control.json"
RUNTIME_LOSSES = {"function_capacity", "active_call_capacity", "invalid", "async_origin", "incomplete"}


def status(value: object, pid: int) -> dict:
    """An actual application owns a separate healthy SDK while calls are paused."""
    provider.require(type(value) is dict, "missing live control status")
    value = cast(dict, value)
    provider.require(type(value.get("schema_version")) is int and value["schema_version"] == 1
                     and type(value.get("pid")) is int and value["pid"] == pid and pid > 1
                     and type(value.get("sdk_pid")) is int and value["sdk_pid"] > 1 and value["sdk_pid"] != pid
                     and value.get("phase") == "running"
                     and type(value.get("language")) is str and value["language"] in provider.LANGUAGES
                     and type(value.get("launch_id")) is str and re.fullmatch("[a-f0-9]{32}", value["launch_id"]),
                     "live control process or launch identity differs")
    provider.require(all(type(value.get(key)) is bool for key in ("collection", "emission", "effective_emission_off")),
                     "invalid live metric flags")
    counters = {"function_completions", "active_functions", "in_flight_exports", "export_started", "export_succeeded",
                "export_failed", "native_callback_failures", "lifetime_lost", "handoff_incomplete"}
    provider.require(all(type(value.get(key)) is int and 0 <= value[key] < 2**63 for key in counters),
                     "missing or invalid live control counters")
    provider.require(value["effective_emission_off"] == (not value["emission"] and value["in_flight_exports"] == 0)
                     and value["export_started"] == value["export_succeeded"] + value["export_failed"] + value["in_flight_exports"],
                     "live exporter barrier or accounting differs")
    losses = value.get("runtime_losses")
    provider.require(type(losses) is dict and set(losses) == RUNTIME_LOSSES
                     and all(type(count) is int and count == 0 for count in losses.values())
                     and all(value[key] == 0 for key in ("active_functions", "native_callback_failures", "lifetime_lost",
                                                       "handoff_incomplete", "export_failed")),
                     "live checkpoint is active or reports lost observations")
    handoff = value.get("handoff")
    provider.require(type(handoff) is dict and handoff.get("sdk_process_failed") is False
                     and all(type(handoff.get(key)) is int and handoff[key] >= 0 for key in ("attempted", "accepted", "lost"))
                     and handoff["attempted"] == handoff["accepted"] and handoff["lost"] == 0,
                     "live SDK handoff is incomplete")
    return value


def request(path: Path, command: str, pid: int, deadline: float) -> dict:
    """Validate the Node reply after the shared bounded control transport."""
    provider.require(command in COMMANDS, "unsupported live Node control command")
    return status(exchange(path, command, pid, deadline), pid)


def switch(path: Path, pid: int, requested: dict, deadline: float) -> list[dict]:
    """Set each flag independently and drain already admitted metric exports."""
    history = [{"command": "status", "status": request(path, "status", pid, deadline)}]
    completed = history[0]["status"]["function_completions"]
    for key, other in (("collection", "emission"), ("emission", "collection")):
        command = key + (" on" if requested[key] else " off")
        current = request(path, command, pid, deadline)
        provider.require(current[key] is requested[key] and current[other] is history[-1]["status"][other]
                         and current["function_completions"] == completed,
                         "live setter changed an independent state or selected calls ran while paused")
        history.append({"command": command, "status": current})
    while not requested["emission"] and not history[-1]["status"]["effective_emission_off"]:
        provider.require(len(history) < MAX_STATUSES and time.monotonic() < deadline,
                         "live export-off barrier exceeded its budget")
        time.sleep(min(.01, max(0., deadline - time.monotonic())))
        current = request(path, "status", pid, deadline)
        provider.require(all(current[key] is flag for key, flag in requested.items())
                         and current["function_completions"] == completed, "live state changed while draining exports")
        history.append({"command": "status", "status": current})
    return history
