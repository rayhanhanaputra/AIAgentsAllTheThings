.PHONY: install check registry test lint all workbench-api workbench-web connector-fixtures workbench-e2e arduino-bridge-sim

install:
	python3 -m pip install --upgrade "pip>=23"
	python3 -m pip install ".[dev,workbench]"

# Validate the knowledge base against the generated registry.
check:
	python3 tools/build_registry.py --check

# Regenerate the machine-readable registry from knowledge-base front matter.
registry:
	python3 tools/build_registry.py

# Run backend and connector-unit tests.
test:
	python3 -m pytest -q

# Lint Markdown with the same tool and version CI uses.
lint:
	npx -y markdownlint-cli2@0.13.0 "**/*.md" "!web/node_modules/**" "!web/dist/**" "!web/test-results/**" "!web/playwright-report/**" "!LICENSE-CODE" "!LICENSE-DOCS"

# Everything CI runs.
all: check test lint

# Start the local-only workbench services in separate terminals.
workbench-api:
	python3 -m harness.api

workbench-web:
	npm --prefix web run dev

connector-fixtures:
	python3 -m tests.fixtures.connector_targets.server

# Run in another terminal while connector-fixtures is active.
workbench-e2e:
	python3 -m tools.test_workbench_e2e

arduino-bridge-sim:
	python3 -m harness.hardware.arduino_bridge --simulate
