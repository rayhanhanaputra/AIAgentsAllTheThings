# Contributing

Thank you for helping build AIAgentsAllTheThings. The Web Workbench is the user-facing
product: it encodes an input channel, delivers it to an authorized AI-agent target,
captures the response, and evaluates deterministic evidence. The knowledge base
documents reusable techniques and mitigations.

Contributions normally improve one of three areas: the Workbench UI/API, a channel
adapter or connector, or a knowledge-base technique.

## Improving the Web Workbench

- UI code lives under `web/`; keep target setup, Workbench, Campaigns, and History
  usable across desktop and narrow viewports.
- The local API, target profiles, input mapper, connectors, evidence analysis, and
  SQLite history live under `harness/api/`.
- A channel adapter describes how user-controlled input is encoded. A connector
  describes how that encoded input reaches a target. Do not couple a connector to one
  scenario when it can remain channel-agnostic.
- Add loopback-only connector coverage under `tests/fixtures/connector_targets/` and extend
  `tools/test_workbench_e2e.py` for every supported adapter/connector path.
- Never store credential values in target profiles, browser state, previews, or run
  history. Profiles may reference server-side environment-variable names only.

Run backend, connector, and browser checks before opening a pull request:

```bash
python3 -m pytest -q
make connector-fixtures               # terminal 1
make workbench-e2e                    # terminal 2
npm --prefix web run lint
npm --prefix web run build
npm --prefix web run test:ui
```

## Adding a knowledge-base technique

1. Copy [`kb/_template/technique.md`](kb/_template/technique.md) into the folder for
   its channel, for example `kb/C2-data-field/`.
2. Name the file with its slug, for example `C2-I3-smartfarm-note-override.md`. The
   slug encodes the channel and primary intent.
3. Fill in the front matter and the body sections.
4. Leave `registry_id` as `AAT-XXXX`; a maintainer assigns the next number on merge.
5. Open a pull request with just that file (plus images under an `Images/` subfolder
   if needed).

### Mandatory rules

- **A falsifiable `success` field is required.** It must be a predicate over a
  privileged action in the target's action log. An entry whose success is vague,
  subjective, or decided only by an LLM judgment is not accepted. This is the rule
  that separates a technique from a description.
- **Cite only known mapping ids.** Values in `mappings` and `tags` must already exist
  in the files under [`mappings/`](mappings/). To use a new one, add it there in the
  same pull request.
- **Document reproducibility.** A `reproduced` entry must describe a controlled,
  authorized setup and a falsifiable observation that a reviewer can repeat through
  the Workbench or an equivalent lab target.

### Sanitization rules

Use placeholder, non-routable, non-real values only.

- Domains: `example.com`, `example.org`, or `attacker.example`.
- Addresses: documentation ranges (`192.0.2.0/24`, `198.51.100.0/24`,
  `203.0.113.0/24`) and `10.0.0.0/8` for lab networks.
- Credentials: obvious placeholders such as `P@ssw0rd-EXAMPLE`; never real secrets.
- No real personal data, no real PII or PHI, no real customer identifiers, and no data
  from a system you are not authorized to test.

## Before you open a pull request

Run the full local check (validation, tests, and Markdown lint):

```bash
python3 -m pip install --upgrade "pip>=23"
python3 -m pip install ".[dev,workbench]"
make all        # build_registry --check + pytest + markdownlint
```

Or individually:

```bash
python tools/build_registry.py --check    # validate the knowledge base
python tools/build_registry.py            # regenerate registry/ if you changed entries
python -m pytest -q                        # run the test suite
```

Continuous integration runs the same checks, plus the connector matrix, frontend
lint/format/build, browser tests, and production dependency audits; a pull request that
fails any of these will not merge.

## Licensing of contributions

By contributing you agree that your knowledge-base contributions are licensed under
CC BY 4.0 and your code contributions under Apache-2.0, matching the repository's
dual license. See [`LICENSE-DOCS`](LICENSE-DOCS) and [`LICENSE-CODE`](LICENSE-CODE).

Authorship is tracked through git commit history. Do not add author names to entry
front matter or documentation; a normal push records attribution automatically.

## Code of conduct and authorized use

This project is for defenders and researchers testing systems they own or are
explicitly authorized to test. Do not contribute material derived from unauthorized
access to third-party systems. See [`SECURITY.md`](SECURITY.md).
