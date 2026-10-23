"""Literal live Node status fixtures for consumer protocol regressions."""


def status(completed=0, collection=True, emission=True):
    return {"schema_version": 1, "pid": 101, "sdk_pid": 102, "language": "javascript", "launch_id": "a" * 32,
            "phase": "running", "collection": collection, "emission": emission,
            "effective_emission_off": not emission, "function_completions": completed, "active_functions": 0,
            "in_flight_exports": 0, "export_started": 0, "export_succeeded": 0, "export_failed": 0,
            "native_callback_failures": 0, "lifetime_lost": 0, "handoff_incomplete": 0,
            "runtime_losses": dict.fromkeys(("function_capacity", "active_call_capacity", "invalid", "async_origin", "incomplete"), 0),
            "handoff": {"attempted": 1, "accepted": 1, "lost": 0, "sdk_process_failed": False}}
