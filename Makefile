.PHONY: install check registry test lint all demo workbench-api workbench-web dummy-targets workbench-e2e

install:
	python3 -m pip install --upgrade "pip>=23"
	python3 -m pip install ".[dev,workbench]"

# Validate the knowledge base and declarative tests against the registry.
check:
	python3 tools/build_registry.py --check

# Regenerate the machine-readable registry from knowledge-base front matter.
registry:
	python3 tools/build_registry.py

# Run the deterministic test suite.
test:
	python3 -m pytest -q

# Lint Markdown with the same tool and version CI uses.
lint:
	npx -y markdownlint-cli2@0.13.0 "**/*.md" "!web/node_modules/**" "!web/dist/**" "!web/test-results/**" "!web/playwright-report/**" "!LICENSE-CODE" "!LICENSE-DOCS"

# Everything CI runs.
all: check test lint

# Run all eight flagship demonstrations.
demo:
	@for t in C1-I3-process-tank-sensor-spoof C2-I3-smartfarm-note-override \
	          C3-I2-facility-morse-actuation C4-I4-callcenter-voice-override \
	          C5-I2-logistics-scan-injection C6-I2-smarthome-rf-access \
	          C7-I2-supportdesk-inter-agent-injection C8-I3-hvac-replay-flood; do \
	    python3 -m harness.cli demo $$t ; \
	done

# Start the local-only workbench services in separate terminals.
workbench-api:
	python3 -m harness.api

workbench-web:
	npm --prefix web run dev

dummy-targets:
	python3 -m sims.workbench_targets.server

# Run in another terminal while dummy-targets is active.
workbench-e2e:
	python3 -m tools.test_workbench_e2e
