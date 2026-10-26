"""Install the frozen reviewed CLI and inspect its installed command surface."""

import datetime
import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent
SOURCE = ROOT / "source-6ba15b2"


def main() -> None:
    assert json.loads((ROOT / "gate-6ba15b2.json").read_text()).get("exit_code") == 0
    assert not (ROOT / "installation-6ba15b2.json").exists()
    seal = json.loads((ROOT / "source-6ba15b2.json").read_text())
    environment = dict(os.environ)
    environment.update(
        PATH="/Users/sclarke/.rustup/toolchains/1.98.1-aarch64-apple-darwin/bin:/opt/homebrew/bin:/usr/bin:/bin",
        CARGO_NET_OFFLINE="true",
    )
    command = ["cargo", "install", "--locked", "--path", str(SOURCE),
               "--root", str(ROOT / "installed-6ba15b2"),
               "--target-dir", str(ROOT / "target-runtime-4593e82")]
    receipt = {"commit": seal["commit"], "command": command,
               "started_at": datetime.datetime.now(datetime.UTC).isoformat()}
    with (ROOT / "install-6ba15b2.log").open("w") as output:
        result = subprocess.run(command, env=environment, stdout=output,
                                stderr=subprocess.STDOUT)
    receipt["install_exit"] = result.returncode
    if result.returncode == 0:
        binary = ROOT / "installed-6ba15b2/bin/quux-oteleq"
        receipt["cli_sha256"] = hashlib.sha256(binary.read_bytes()).hexdigest()
        commands = ("plan", "generate", "run", "replay", "shrink",
                    "export-tests", "promote", "clean", "render-report")
        receipt["help"] = {}
        for command_name in commands:
            help_result = subprocess.run([str(binary), command_name, "--help"],
                                         capture_output=True, text=True)
            (ROOT / ("installed-help-" + command_name + ".txt")).write_text(
                help_result.stdout + help_result.stderr)
            receipt["help"][command_name] = help_result.returncode
    assert all(hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == value
               for name, value in seal["files"].items())
    receipt["source_files_preserved"] = len(seal["files"])
    receipt["finished_at"] = datetime.datetime.now(datetime.UTC).isoformat()
    (ROOT / "installation-6ba15b2.json").write_text(
        json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))
    assert receipt["install_exit"] == 0
    assert all(value == 0 for value in receipt["help"].values())


if __name__ == "__main__":
    main()
