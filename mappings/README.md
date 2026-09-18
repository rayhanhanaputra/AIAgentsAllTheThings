# Mappings (controlled vocabularies)

These files define the only valid identifiers a knowledge-base entry may cite in its
`mappings` and `tags` front matter. `tools/build_registry.py` validates every entry
against them, so coverage claims stay honest and mapping ids never drift into free
text.

| File | Vocabulary |
| --- | --- |
| `owasp-llm.yaml` | OWASP Top 10 for LLM Applications |
| `owasp-agentic.yaml` | OWASP Agentic AI threats and mitigations (T1-T17) |
| `mitre-atlas.yaml` | MITRE ATLAS techniques |
| `mitre-attack-ics.yaml` | MITRE ATT&CK for ICS (cyber-physical control channels) |
| `tags.yaml` | Free-form-but-controlled tags (channel, domain, protocol) |

To cite a new id, add it here first (with a short description and a reference), then
use it in an entry. Adding an id is a normal pull request.
