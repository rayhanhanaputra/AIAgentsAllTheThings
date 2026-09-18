# Contributing

Thank you for helping build AIAgentsAllTheThings. The project has two halves and two
contribution paths: adding a technique to the knowledge base, and adding or improving
harness code. Most contributions are a single-file knowledge-base pull request.

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
- **Simulator-first.** A bound test runs over the in-process `direct` transport
  against a simulator or reference target. The `hardware: true` field is reserved for
  future hardware channels and is never the default.

### Sanitization rules

Use placeholder, non-routable, non-real values only.

- Domains: `example.com`, `example.org`, or `attacker.example`.
- Addresses: documentation ranges (`192.0.2.0/24`, `198.51.100.0/24`,
  `203.0.113.0/24`) and `10.0.0.0/8` for lab networks.
- Credentials: obvious placeholders such as `P@ssw0rd-EXAMPLE`; never real secrets.
- No real personal data, no real PII or PHI, no real customer identifiers, and no data
  from a system you are not authorized to test.

## Adding harness code

Harness plugins live under [`harness/`](harness/) in the appropriate category
directory. A new channel is an encoder and a target (plus an oracle when the success
condition is new). Declarative tests go in
`harness/tests/<technique-slug>/` and must carry a stable `auto_generated_guid`,
referenced from the knowledge-base entry's `tests` list.

## Before you open a pull request

Run the full local check (validation, tests, and Markdown lint):

```bash
pip install -r requirements-dev.txt
make all        # build_registry --check + pytest + markdownlint
```

Or individually:

```bash
python tools/build_registry.py --check    # validate the knowledge base and tests
python tools/build_registry.py            # regenerate registry/ if you changed entries
python -m pytest -q                        # run the test suite
```

Continuous integration runs the same checks (the front-matter validation, the registry
rebuild, the test suite, and markdownlint); a pull request that fails any of these will
not merge.

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
