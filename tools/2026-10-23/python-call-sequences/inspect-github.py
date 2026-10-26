"""Retain authenticated repository, protection and exact-head delivery evidence."""

import concurrent.futures
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
WRAPPER = [
    "/Users/sclarke/github/otelc-qualification/2026-10-20/integrated-provider/d6d03b7/provider/.venv/bin/python",
    "/Users/sclarke/github/oteleq-qualification/2026-10-20/pause-for-reboot/quux-oteleq-gh.py",
]
EXPECTED = {
    "Documentation and design examples": 15368,
    "Rust comparator and 80% product coverage": 15368,
    "SonarCloud Code Analysis": 12526,
}


def api(arguments: list[str]) -> dict:
    environment = dict(os.environ,
                       XDG_CACHE_HOME="/Users/sclarke/github/oteleq-qualification/work/gh-cache")
    result = subprocess.run(WRAPPER + ["api", *arguments], env=environment,
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def main() -> None:
    head, label = sys.argv[1:]
    query = '''query { repository(owner:"quuxio", name:"oteleq") {
      pullRequest(number:72) { reviewDecision mergeStateStatus
        reviewThreads(first:100) { nodes { isResolved isOutdated }
          pageInfo { hasNextPage endCursor } } } } }'''
    requests = {
        "pr": ["repos/quuxio/oteleq/pulls/72"],
        "checks": [f"repos/quuxio/oteleq/commits/{head}/check-runs?per_page=100"],
        "rules": ["repos/quuxio/oteleq/rulesets/24784844"],
        "main": ["repos/quuxio/oteleq/branches/main"],
        "reviews": ["graphql", "-f", "query=" + query],
    }
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {name: pool.submit(api, arguments)
                   for name, arguments in requests.items()}
        values = {name: future.result() for name, future in futures.items()}
    for name, value in values.items():
        (ROOT / (label + "-" + name + ".json")).write_text(
            json.dumps(value, indent=2) + "\n")
    checks = values["checks"]
    assert checks["total_count"] == len(checks["check_runs"]), "check pagination required"
    selected = {}
    for name, app in EXPECTED.items():
        matches = [check for check in checks["check_runs"]
                   if check["name"] == name and check["app"]["id"] == app]
        assert len(matches) <= 1, (name, len(matches))
        if not matches:
            selected[name] = {"app": app, "status": "not_registered",
                              "conclusion": None, "id": None}
            continue
        check = matches[0]
        assert check["head_sha"] == head
        selected[name] = {"app": app, "status": check["status"],
                          "conclusion": check["conclusion"], "id": check["id"]}
    review = values["reviews"]["data"]["repository"]["pullRequest"]
    assert not review["reviewThreads"]["pageInfo"]["hasNextPage"]
    rules = values["rules"]
    parameters = {rule["type"]: rule.get("parameters", {}) for rule in rules["rules"]}
    required = parameters["required_status_checks"]
    assert rules["enforcement"] == "active"
    assert required["strict_required_status_checks_policy"] is True
    assert {item["context"]: item["integration_id"]
            for item in required["required_status_checks"]} == EXPECTED
    assert parameters["pull_request"]["required_approving_review_count"] == 0
    assert parameters["pull_request"]["required_review_thread_resolution"] is True
    pr = values["pr"]
    record = {
        "observed_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "head": head, "pr_head": pr["head"]["sha"], "pr_state": pr["state"],
        "pr_author": pr["user"]["login"], "merged": pr["merged"],
        "merge_commit": pr["merge_commit_sha"],
        "merged_by": (pr["merged_by"] or {}).get("login"),
        "main": values["main"]["commit"]["sha"],
        "main_protected": values["main"]["protected"],
        "merge_state": review["mergeStateStatus"],
        "unresolved_review_threads": sum(not row["isResolved"]
                                          for row in review["reviewThreads"]["nodes"]),
        "required_checks": selected,
        "all_required_success": all(item["status"] == "completed"
                                    and item["conclusion"] == "success"
                                    for item in selected.values()),
        "protection": "active strict app-bound checks; zero human approvals; conversations must resolve",
    }
    (ROOT / (label + "-summary.json")).write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record))


if __name__ == "__main__":
    main()
