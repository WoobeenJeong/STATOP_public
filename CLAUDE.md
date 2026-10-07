# STATOP — notes for AI agents

Full documentation: README.md

## With an AI agent

`CLAUDE.md` / `AGENTS.md` are in the repo; an agent picks them up on entry.

| you want | ask for |
|---|---|
| first look | `statop columns my.csv` → "flag columns whose type looks wrong" |
| pick a test | `statop analyze plan ...` → "keep only ✅, say why ⚠ is ⚠" |
| why blocked | "quote the reason from `rules/tests.yaml`" |
| compare runs | "read these two session files, name the step that differs" |

Let STATOP judge; let the agent explain. Every verdict has written grounds in
`rules/`, so the agent cites instead of inventing.