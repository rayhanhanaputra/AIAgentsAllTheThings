.PHONY: install check registry test lint all demo

install:
	pip install -r requirements-dev.txt

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
	npx -y markdownlint-cli2@0.13.0 "**/*.md" "!LICENSE-CODE" "!LICENSE-DOCS"

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
