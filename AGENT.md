# SyllabAI Parser — Multi-Agent Rules

The project-wide multi-agent operating system is canonical in `SyllabAI/syllabai` (`AGENT.md` + `.syllabai/`).

Parser-specific rules:

1. Parser output is candidate educational representation until downstream validation accepts it.
2. Preserve source identity, provenance, asset references, unresolved references and deterministic output.
3. Parser/core bundle changes are a shared contract: update the contract fixtures and coordinate with core before changing semantics.
4. Educational-content fields must remain fail-loud when the consumer does not understand them; do not silently discard unknown fields.
5. Record task ID, base commit and contract impact before substantial work.
6. Label completion claims VERIFIED / INFERRED / REPORTED / UNVERIFIED and retain durable evidence for material milestones.
7. If main advances and touched parser/core contract files overlap, reconcile before completion and rerun parser + contract tests.
