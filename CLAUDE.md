# STATOP — notes for AI agents

Full documentation: README.md

## Working with an AI agent

The repo ships `CLAUDE.md` / `AGENTS.md`, so an agent picks up the rules on entry.
Tell it:

```
This repo is STATOP, a local statistics validation tool.
- Environment: conda activate statop
- rules/*.yaml decides what may be used and why. Do not hand-edit —
  schema/registry-*.md is the source, python -m statop.rules.build generates it.
- Flow: session new → select → types --confirm → analyze plan --apply → analyze run
- Data cells are never stored; the session log holds operations only.
```

| you want | ask the agent |
|---|---|
| a first look | "run `statop columns my.csv` and flag columns whose inferred type looks wrong" |
| pick a test | "run `statop analyze plan --question Q-01 --y y --group g`, keep only ✅" |
| why blocked | "find the reason in `rules/tests.yaml` and quote it" |
| reproducibility | "run `statop report`, then build a replay script from the session log" |

**Let STATOP judge, let the agent explain.** Every verdict has written grounds in
`rules/`, so the agent can cite instead of invent.

