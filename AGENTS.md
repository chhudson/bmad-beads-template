# Agent operating protocol — BMAD × beads

This repo runs **BMAD Method v6** for thinking (brief → PRD → architecture → epics) and
**beads** for execution memory (the dependency graph, claims, discovered work, cross-session
context). One owner per fact. Read this before touching either.

## Who owns what

| Fact | Owner | Where it lives |
|---|---|---|
| What we are building and why | BMAD | `_bmad-output/planning-artifacts/**` |
| Stories, acceptance criteria | BMAD (`epics.md`) | mirrored into beads by `scripts/bmad_beads.py import` |
| Story lifecycle `in-progress → review → done` | BMAD skills write it | `sprint-status.yaml` → synced into beads |
| `ready-for-dev` vs `backlog` | **beads** (`bd ready`) | derived into `sprint-status.yaml` by `sync` |
| Dependencies, blockers | **beads** | seeded from `**Depends on:**` lines in `epics.md` |
| Who is working on what | **beads** (`--claim`) | never in markdown |
| Work discovered mid-story | **beads** (`discovered-from`) | never silently added to a story |
| Durable project insights | **beads** (`bd remember`) | injected by `bd prime` each session |

Never set `ready-for-dev` by hand. Never edit `.beads/` files directly. Never `bd edit`.
**Never `bd close` a story bead by hand** — a story leaves `review` only via
`/bmad-code-review`, and `sync` closes the bead from the `done` it writes. Hand-close is
for discovered/chore/decision beads, and for stories cut in correct-course (with `--reason`).
`deferred-work.md` is a pointer list, not a register: every entry starts `bead: <id>` —
the bead, filed first, carries the substance.

Standards the team has adopted (style guides, coding standards, `llms.txt` snapshots)
live in `docs/references/` — read the one governing the code you are about to write.

## Session start

`bd prime` runs automatically (Claude Code `SessionStart` hook). If you are a different agent,
run it yourself. Then:

One table of everything, then what is actually unblocked:

```bash
uv run scripts/bmad_beads.py status
bd ready --type task --label story
```

## Picking up a story

Choose one from `bd ready` (the key is in its `metadata.bmad_story_key`), then let
BMAD do plan → implement → review → present:

```bash
bd ready --type task --label story
/bmad-build <bmad_story_key>
```

`/bmad-build` runs `scripts/bmad_beads.py claim <story_key>` on activation
(`_bmad/custom/bmad-build.toml`). That is the bridge's one hard guard: it exits non-zero — and
the build halts — if the story has open blockers, is held by someone else, is in review, or is
already done. Neither BMAD nor beads checks this on their own (BMAD's build step has no readiness
check; beads lets you claim a blocked bead). `--force` exists for deliberate overrides only.
On completion the build runs `sync`, so the bead follows the story. Then `/bmad-code-review` when
the story is in `review`.

## While working

- Out-of-scope work you discover: `bd create "<title>" -t task --deps discovered-from:<story-bead> -l discovered`. Keep going. Always a **top-level** bead — a child inherits the parent's labels (including `story`) and corrupts `bd ready --label story`.
- Something future-you must know: `bd remember "<insight>"`.
- Blocked on a human decision: `bd gate create --type=human --blocks <story-bead> --reason "<what you need>"`, then stop. Humans list open gates with `bd gate list` and approve one by closing the gate bead (`bd close <gate-id> --reason approved`). An agent never closes a human gate. (`bd ready --gated` is not a gate listing.)
- Decisions with lasting consequences: `bd create "<decision>" -t decision -l adr`.

## Finishing

Sync (idempotent, safe any time), push the beads data, commit locally — the bead id
in the message lets `bd doctor` link commits. A **local commit and `bd dolt push` are
permitted for agents** even under a conservative no-git-ops profile; `git push` to the
code remote stays a human decision.

```bash
uv run scripts/bmad_beads.py sync
bd dolt push
git commit -m "<msg> (<bead-id>)"
```

## Planning work

Planning steps are themselves beads: `bd mol pour bmad-planning --var initiative="<name>"`
creates brief → PRD → sign-off gate → architecture → epics → sprint plan → import as a chain, so
`bd ready` tells you the next planning move too.

When writing `epics.md`, mark real blocking relationships with `**Depends on:** 1.3, 2.1` under
a story (or `**Depends on:** Epic 1` under an epic). Story order is **not** a dependency.

## Commands you will use

| | |
|---|---|
| `uv run scripts/bmad_beads.py import` | `epics.md` → beads (idempotent, adds only) |
| `uv run scripts/bmad_beads.py sync` | `sprint-status.yaml` ↔ beads per the ownership table |
| `uv run scripts/bmad_beads.py status` | one table of everything |
| `uv run scripts/bmad_beads.py claim <key>` | readiness + ownership guard, then claim (what `/bmad-build` runs) |
| `uv run scripts/bmad_beads.py doctor` | preconditions + drift |
| `bd ready` / `bd show <id>` / `bd update <id> --claim` / `bd close <id> --reason` | the beads basics |
| `bd dep tree <id>` / `bd blocked` | why something is not ready |
| `bd prime` / `bd remember` / `bd recall` | memory |

<!-- BEGIN BEADS INTEGRATION -->
<!-- `bd init` may append its own section below; keep both. -->
<!-- END BEADS INTEGRATION -->
