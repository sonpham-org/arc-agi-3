# Agent Instructions

This file governs how AI agents (Claude Code, Cursor, Copilot, etc.) work in this codebase. These rules are non-negotiable and must be followed on every task, every session. They complement `CLAUDE.md` (project architecture) — read both before starting work.

---

## Before you touch any code

1. **Read the plan doc for the current task** in `docs/`. If one does not exist, create it and get it approved before writing any code. Plan doc naming: `docs/{YYYY-MM-DD}-{goal}-plan.md`.
2. **Read the relevant source files** before suggesting or making changes. Do not modify code you have not read.
3. **Search for existing utilities** before adding new ones. Grep and glob before writing anything new.
4. **For unfamiliar or recently updated libraries**, fetch documentation before coding. Ask the user to provide a URL if needed.

---

## Required: plan doc before coding

Every substantive task requires a plan doc in `docs/` **approved before implementation begins**.

Plan must include:
- **Scope** — what is in and out
- **Architecture** — which modules are touched, what is reused, where new code lives, why
- **TODOs** — ordered steps with explicit verification steps
- **Docs / Changelog touchpoints** — what docs and `CHANGELOG.md` entries are required

Do not start implementing until the user has approved the plan.

---

## Required: file headers

Every TypeScript, JavaScript, or Python file you **create or edit** must start with this header block. Update it every time you touch the file.

```
// Author: {Your Model Name}
// Date: {YYYY-MM-DD HH:MM}
// PURPOSE: Verbose description of what this file does, its integration points, and dependencies
// SRP/DRY check: Pass/Fail — did you verify no existing utility covers this?
```

For Python use `#`. For JS/TS use `//`. Do not add headers to JSON, SQL, YAML, or Markdown.

---

## Required: changelog

Any change that alters observable behaviour must have a `CHANGELOG.md` entry. Format:

```
## [version] — branch or tag
*Author: {name} | {YYYY-MM-DD}*

### Added / Fixed / Changed / Removed
- Description of what changed, why it changed, and how it was done.
```

If `CHANGELOG.md` does not exist, create it starting at `[1.0.0]` as the baseline.

---

## Workflow

1. **Analyse** — read existing code, understand the architecture, identify reuse opportunities
2. **Plan** — write a plan doc, get it approved
3. **Implement** — small focused changes; build on existing patterns
4. **Verify** — test with real services; no mocks or stubs in production code

---

## Code quality rules

- **Naming**: meaningful names everywhere; no single-letter variables outside tight loops
- **Error handling**: exhaustive and user-safe; handle every failure mode explicitly
- **Comments**: explain non-obvious logic and all integration boundaries, especially external API glue
- **No duplication**: if you are writing something twice, find and reuse the first instance
- **No over-engineering**: solve the current problem; do not build for hypothetical future requirements
- **No under-engineering**: fix root causes; do not paper over bugs with workarounds
- **Production only**: no mocks, stubs, fake data, `TODO` logic, or simulated responses in committed code

---

## Architecture rules (this project)

- **All game-playing and LLM logic runs client-side.** Do not add server-side LLM orchestration. See `CLAUDE.md` — Client-Side Architecture section.
- **Server role is limited**: static file serving, session persistence, model registry, proxying game steps only.
- **BYOK / local provider calls go browser → provider directly.** The Railway server must never be in the LLM call path for BYOK providers.
- **Game code must be fully deterministic.** No RNG. See `CLAUDE.md` — Game Design Rules.
- **Model select fields** in `SCAFFOLDING_SCHEMAS` must be wired in three places: `loadModels()` populate, `loadModels()` restore, `attachSettingsListeners()` change listener. See `CLAUDE.md` — Model Select Checklist.

---

## Git and deployment
- **Avoid destructive operations** like `git reset --hard`, `git push --force`, or `git rm` without explicit instruction.
- **Run the pre-push QC checks** before every push (see `CLAUDE.md` — Pre-Push QC).
- **Never skip hooks** (`--no-verify`), force-push to master, or amend published commits without explicit instruction.

---

## Communication rules

- Keep responses tight. Lead with the action or answer, not the reasoning.
- Do not dump chain-of-thought. If the logic is complex, put it in a plan doc or inline comment.
- Do not give time estimates.
- Do not celebrate completion. Nothing is done until the user has tested it.
- If something is blocked or ambiguous, state what you checked and ask one focused question.
- Call out when a web search would surface important up-to-date information (e.g. API changes).

---

## Prohibited

- Guessing at API behaviour without reading docs
- Writing code before a plan is approved
- Committing without being asked
- File headers missing from edited files
- Changelog entries missing for behaviour changes
- Mocks, stubs, placeholder logic, or fake data in committed code
- Time estimates
- Premature celebration or declaring something fixed before it is tested
