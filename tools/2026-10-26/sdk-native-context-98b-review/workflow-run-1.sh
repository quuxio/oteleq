mkdir -p build/native-context
git rev-parse HEAD > build/native-context/head.txt
python3 -c 'import shutil; assert shutil.disk_usage(".").free >= 8 * 1024**3, "at least 8 GiB required"'
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes --only-binary=:all: -r requirements-dev.txt -r requirements.txt
