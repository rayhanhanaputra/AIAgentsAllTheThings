<!-- Thank you for contributing to AIAgentsAllTheThings. -->

## What does this pull request add or change?

<!-- One or two sentences. -->

## Type

- [ ] New knowledge-base technique
- [ ] Change to an existing technique
- [ ] Harness code (plugin, test, or engine)
- [ ] Documentation or tooling

## Checklist for a knowledge-base technique

- [ ] Copied from `kb/_template/technique.md` into the correct channel folder.
- [ ] Filename equals the `id` slug.
- [ ] `registry_id` left as `AAT-XXXX` for a maintainer to assign.
- [ ] `success` is a falsifiable predicate over a privileged action (not vague, not
      LLM-judged).
- [ ] All `mappings` and `tags` ids already exist under `mappings/`.
- [ ] Any bound test defaults to a simulator (`hardware: false`).
- [ ] Values are sanitized (placeholder domains, addresses, and credentials only).

## Validation

- [ ] `python tools/build_registry.py --check` passes locally.

## Authorization

- [ ] This contribution is not derived from unauthorized access to any third-party
      system, and contains no real personal data.
