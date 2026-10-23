"""Enforce separate compiled Java observer and compiler frontend coverage."""
import argparse
import hashlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
import zipfile


REPO = Path(__file__).resolve().parents[1]
CACHE = REPO / "ci/java-coverage"
URL = "https://github.com/jacoco/jacoco/releases/download/v0.8.15/jacoco-0.8.15.zip"
ARCHIVE_SHA256 = "5b3f6ddb724e761d25c937d68b0189a3a23f3e220e3282575ee0b53359e8110e"
TOOLS = {"jacocoagent.jar": "fb5b0036a0899ea97edfa0fc2c7985b55f3f7c5695028163e5e60d4f3cf6075d",
         "jacococli.jar": "d2b74b20b415163c1f53261e7c5ef4445b788327094208ff821e0c2baf9bc8f1"}


def digest(data: bytes) -> str:
    """Use the published release digest and separately pinned extracted products."""
    return hashlib.sha256(data).hexdigest()


def verified(cache: Path) -> bool:
    """Never execute an unverified local coverage agent or CLI."""
    return all((cache / name).is_file() and digest((cache / name).read_bytes()) == expected
               for name, expected in TOOLS.items())


def install(cache: Path) -> None:
    """Download only the fixed release and extract the two named, hashed files."""
    if verified(cache):
        return
    request = urllib.request.Request(URL, headers={"User-Agent": "oteleq-validation"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read(16 * 1024 * 1024)
    if digest(data) != ARCHIVE_SHA256:
        raise ValueError("JaCoCo release digest mismatch")
    products = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name, expected in TOOLS.items():
            product = archive.read("lib/" + name)
            if digest(product) != expected:
                raise ValueError("JaCoCo product digest mismatch: " + name)
            products[name] = product
    cache.mkdir(parents=True, exist_ok=True)
    for name, product in products.items():
        (cache / name).write_bytes(product)


def coverage(path: Path, name: str = "OteleqGraph", *, nested: bool = False) -> float:
    """Require one exact product class, optionally including its nested classes."""
    root = ET.parse(path).getroot()
    classes = [node for node in root.findall("./package/class")
               if node.attrib["name"] == name or nested and node.attrib["name"].startswith(name + "$")]
    names = [node.attrib["name"] for node in classes]
    groups = [node.findall("./counter[@type='LINE']") for node in classes]
    if names.count(name) != 1 or len(names) != len(set(names)) or any(len(group) != 1 for group in groups):
        raise ValueError("Java product coverage is missing or ambiguous: " + name)
    counters = [group[0] for group in groups]
    values = [int(counter.attrib[key]) for counter in counters for key in ("covered", "missed")]
    covered, missed = sum(values[::2]), sum(values[1::2])
    if min(values) < 0 or covered + missed == 0 or covered / (covered + missed) < 0.8:
        raise ValueError("Java product line coverage is below 80%: " + name)
    return 100 * covered / (covered + missed)


def compiler_probe(cache: Path, repo: Path, folder: Path, classes: Path, execution: Path) -> None:
    """Measure compiler bookkeeping separately from application/SDK execution."""
    compiled = folder / "compiler-probe"
    compiled.mkdir()
    javac = os.environ.get("OTELC_JAVAC", "javac")
    java = os.environ.get("OTELC_JAVA", "java")
    subprocess.run([javac, "-g", "-d", str(compiled), str(repo / "adapters/generation/OteleqCompile.java"),
                    str(repo / "tests/JavaCompilerProbe.java")], cwd=repo, check=True, timeout=30)
    agent = f"-javaagent:{cache / 'jacocoagent.jar'}=destfile={execution},append=true,includes=OteleqCompile*"
    subprocess.run([java, agent, "-cp", str(compiled), "JavaCompilerProbe",
                    str(folder / "probe-source"), str(folder / "probe-products")], cwd=repo, check=True, timeout=30)
    for source in compiled.glob("OteleqCompile*.class"):
        (classes / source.name).write_bytes(source.read_bytes())


def archive_probe(cache: Path, repo: Path, folder: Path, classes: Path, execution: Path) -> None:
    """Measure offline archive resolution without instrumenting any application."""
    compiled = folder / "archive-probe"
    compiled.mkdir()
    javac = os.environ.get("OTELC_JAVAC", "javac")
    java = os.environ.get("OTELC_JAVA", "java")
    subprocess.run([javac, "-g", "-d", str(compiled), str(repo / "adapters/generation/OteleqArchives.java"),
                    str(repo / "tests/JavaArchiveProbe.java")], cwd=repo, check=True, timeout=30)
    agent = f"-javaagent:{cache / 'jacocoagent.jar'}=destfile={execution},append=true,includes=OteleqArchives"
    subprocess.run([java, agent, "-cp", str(compiled), "JavaArchiveProbe", str(folder / "archive-inputs")],
                   cwd=repo, check=True, timeout=30)
    source = compiled / "OteleqArchives.class"
    (classes / source.name).write_bytes(source.read_bytes())


def check(cache: Path, repo: Path) -> None:
    """Collect product probes; production SDK qualification uses no JaCoCo."""
    if not verified(cache):
        raise ValueError("run make setup: pinned Java coverage tools are unavailable")
    build = repo / "build"
    build.mkdir(exist_ok=True)
    report = build / "java-observer-coverage.xml"
    report.unlink(missing_ok=True)
    java = os.environ.get("OTELC_JAVA", "java")
    with tempfile.TemporaryDirectory(prefix="java-coverage-", dir=build) as temporary:
        folder = Path(temporary)
        classes, execution = folder / "classes", folder / "jacoco.exec"
        classes.mkdir()
        environment = {**os.environ, "OTELEQ_JAVA_COVERAGE_CLASSES": str(classes),
                       "OTELEQ_JAVA_COVERAGE_AGENT": str(cache / "jacocoagent.jar"),
                       "OTELEQ_JAVA_COVERAGE_EXEC": str(execution)}
        for pattern in ("test_generation_java_receivers.py", "test_generation_java_action.py"):
            subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", pattern, "-v"],
                           cwd=repo, env=environment, check=True, timeout=120)
        compiler_probe(cache, repo, folder, classes, execution)
        archive_probe(cache, repo, folder, classes, execution)
        subprocess.run([java, "-jar", str(cache / "jacococli.jar"), "report", str(execution),
                        "--classfiles", str(classes), "--sourcefiles", str(repo / "adapters/generation"), "--xml", str(report)],
                       cwd=repo, check=True, timeout=30)
    print(f"Java observer line coverage: {coverage(report):.2f}%")
    print(f"Java compiler frontend line coverage: {coverage(report, 'OteleqCompile', nested=True):.2f}%")
    print(f"Java runtime archive resolver line coverage: {coverage(report, 'OteleqArchives'):.2f}%")
    print(f"Java private action rendezvous line coverage: {coverage(report, 'OteleqRendezvous'):.2f}%")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("setup", "check"))
    args = parser.parse_args()
    if args.action == "setup":
        install(CACHE)
    else:
        check(CACHE, REPO)


if __name__ == "__main__":
    main()
