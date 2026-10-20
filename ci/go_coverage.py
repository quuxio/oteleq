"""Enforce statement coverage of the compiled private Go observer."""
import os
from pathlib import Path
import subprocess
import tempfile


REPO = Path(__file__).resolve().parents[1]
PRODUCT = "example.test/oteleqobserver/observer.go"


def coverage(path: Path) -> float:
    """Count only instrumented statements in the actual observer product."""
    lines = path.read_text().splitlines()
    if not lines or lines[0] != "mode: count":
        raise ValueError("Go observer coverage is missing")
    covered = total = 0
    seen = set()
    for line in lines[1:]:
        location, statements, hits = line.split()
        filename, span = location.rsplit(":", 1)
        count, runs = int(statements), int(hits)
        if filename != PRODUCT or span in seen or min(count, runs) < 0:
            raise ValueError("Go observer coverage is ambiguous or invalid")
        seen.add(span)
        total += count
        if runs:
            covered += count
    if not total or covered / total < 0.8:
        raise ValueError("Go observer statement coverage is below 80%")
    return 100 * covered / total


def check(repo: Path) -> None:
    """Compile the maintained observer and probes outside application sources."""
    build = repo / "build"
    build.mkdir(exist_ok=True)
    report = build / "go-observer-coverage.out"
    report.unlink(missing_ok=True)
    go = os.environ.get("OTELC_GO", "go")
    environment = {**os.environ, "GOTOOLCHAIN": "local", "GOWORK": "off", "GOENV": "off",
                   "GOFLAGS": "", "CGO_ENABLED": "0", "GOCACHE": str(build / "go-observer-cache")}
    with tempfile.TemporaryDirectory(prefix="go-observer-", dir=build) as temporary:
        folder = Path(temporary)
        (folder / "go.mod").write_text("module example.test/oteleqobserver\n\ngo 1.20\n")
        (folder / "observer.go").write_bytes((repo / "adapters/generation/go_observe.go").read_bytes())
        (folder / "observer_test.go").write_bytes((repo / "tests/go_observer_test.go").read_bytes())
        subprocess.run([go, "test", "-covermode=count", "-coverprofile", str(report), "."],
                       cwd=folder, env=environment, check=True, timeout=120)
        subprocess.run([go, "vet", "."], cwd=folder, env=environment, check=True, timeout=120)
    print(f"Go observer statement coverage: {coverage(report):.2f}%")


if __name__ == "__main__":
    check(REPO)
