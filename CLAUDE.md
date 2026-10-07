# STATOP — notes for AI agents

Full documentation: README.md

## Working with an AI agent

The repo ships `CLAUDE.md` / `AGENTS.md`, so an agent reads the rules on entry.
Tell it:

```
This repo is STATOP, a local statistics validation tool.
- Environment: conda activate statop
- rules/*.yaml decides what may be used and why not. Do not hand-edit it —
  schema/registry-*.md is the source, python -m statop.rules.build regenerates it.
- Flow: session new → select → types --confirm → analyze plan --apply → analyze run
- Data cells are never stored; the session log holds operations only.
```

| you want | ask for |
|---|---|
| a first look | `statop columns my.csv`, then "flag columns whose inferred type looks wrong" |
| choosing a test | `statop analyze plan ...`, then "keep only the ✅ ones and say why the ⚠ are ⚠" |
| why something is blocked | "quote the reason from `rules/tests.yaml`" |
| reproducibility | `statop report`, then "build a replay script from the session log" |

**Let STATOP judge; let the agent explain.** Every verdict has written grounds in
`rules/`, so an agent can cite them instead of inventing a justification.

---

