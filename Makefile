PYTHON ?= python3
MARKDOWNLINT ?= ./ci/markdownlint/node_modules/.bin/markdownlint

.PHONY: help setup lint examples check

help:
	@printf '%s\n' 'setup     Install locked documentation tools' 'lint      Validate repository Markdown' 'examples  Parse illustrative JSON and TOML' 'check     Run all design-repository checks'

setup:
	npm ci --ignore-scripts --prefix ci/markdownlint

lint:
	$(MARKDOWNLINT) '**/*.md' --ignore 'ci/markdownlint/node_modules/**'

examples:
	$(PYTHON) -c 'import json, pathlib, tomllib; files = list(pathlib.Path("examples").rglob("*.json")) + list(pathlib.Path(".badges").glob("*.json")); [json.loads(p.read_text()) for p in files]; tomllib.loads(pathlib.Path("examples/equivalence.toml").read_text()); print("JSON and TOML syntax valid")'

check: lint examples
