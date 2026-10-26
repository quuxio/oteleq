python3 -c 'import shutil; assert shutil.disk_usage(".").free >= 8 * 1024**3, "at least 8 GiB required"'
make native-check PYTHON=.venv/bin/python 2>&1 | tee build/native-context/tests.log
.venv/bin/python -c 'from pathlib import Path; assert Path("build/native-sdk-tests.log").read_text().count("native owned context: 6 SDK groups passed") == 1'
.venv/bin/python -m coverage json --data-file=build/native-tooling.coverage -o build/native-context/python-coverage.json
