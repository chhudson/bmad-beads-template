# bmad-beads-template

A GitHub template repo that wires **[BMAD Method v6](https://github.com/bmad-code-org/BMAD-METHOD)**
(ideation → PRD → architecture → epics) to **[beads](https://github.com/gastownhall/beads)**
(a Dolt-backed dependency graph and memory for coding agents), so a long-running project keeps
its *thinking* in BMAD's documents and its *execution state* in a graph that agents can query.

Neither tool is forked. BMAD is extended only through its sanctioned `_bmad/custom/*.toml`
overrides; beads is driven only through `bd --json`. Both upgrade independently.

## Why both

| Need | BMAD alone | beads alone | Together |
|---|---|---|---|
| Decide what to build, explicitly | ✅ brief/PRD/architecture | ✗ | BMAD |
| Stories with acceptance criteria | ✅ `epics.md` | ✗ | BMAD → imported |
| Which story can start *now*, across epics | ✗ (linear order per epic) | ✅ `bd ready` | beads → derived into `sprint-status.yaml` |
| Several people/agents without collisions | ✗ | ✅ `--claim`, hash IDs, Dolt merge | beads |
| Work discovered mid-story, not lost | prose in a spec | ✅ `discovered-from` | beads |
| Context that survives compaction/sessions | re-read documents | ✅ `bd prime`, `bd remember` | beads |
| Unattended per-story build with review | ✅ `bmad-build` / `code-review` | ✗ | BMAD, status mirrored |

The bridge gives every fact exactly one owner (see `AGENTS.md`), which is what keeps this from
becoming two status boards that disagree.

## Quick start

```bash
gh repo create my-project --template chhudson/bmad-beads-template --private --clone
cd my-project
bash scripts/bootstrap.sh         # installs BMAD + beads, wires hooks, runs doctor
git add -A && git commit -m "bootstrap BMAD×beads"
```

Prerequisites: git, Node ≥ 20.12, [uv](https://docs.astral.sh/uv/), and [Task](https://taskfile.dev)
for the `task …` shortcuts (optional: each task wraps one command you can run directly). `bd` is
installed by the bootstrap if missing (`npm i -g @beads/bd` or `brew install beads`).

Then in Claude Code:

```
/bmad-help                                  # BMAD tells you the next step
bd mol pour bmad-planning --var initiative="my thing"   # optional: planning steps as beads
```

## The loop

```mermaid
flowchart TB
    PB["/bmad-product-brief"] --> PRD["/bmad-prd"]
    PRD --> ARCH["/bmad-architecture"]
    ARCH --> EP["/bmad-create-epics-and-stories<br/>stories carry <b>Depends on:</b> lines"]
    EP -- "bmad_beads.py import" --> G[("beads graph<br/>epic + story beads, blocks edges,<br/>epic milestone gates")]
    G -- "bd ready" --> SYNC["bmad_beads.py sync"]
    SYNC -- "ready-for-dev / backlog derived" --> SS["sprint-status.yaml"]
    EP --> SP["/bmad-sprint-planning"]
    SP --> SS
    SS --> BUILD["/bmad-build story-key<br/>claim guard — halts if blocked or held"]
    BUILD -- "in-progress → review<br/>discovered-from beads" --> SYNC
    BUILD --> CR["/bmad-code-review"]
    CR -- "done ⇒ bead closed<br/>milestone closes ⇒ next epic unblocks" --> SYNC
    SYNC <--> G
```

The skill→bridge arrows are `on_complete` lines in `_bmad/custom/<skill>.toml` running
`scripts/bmad_beads.py`. Run `task status` (or `uv run scripts/bmad_beads.py status`) any time.

### Story lifecycle

```mermaid
stateDiagram-v2
    direction LR
    state "backlog" as b
    state "ready-for-dev" as rfd
    state "in-progress" as ip
    state "review" as rv
    state "done" as d
    [*] --> b : import
    b --> rfd : sync — blockers closed (bd ready)
    rfd --> b : sync — a new blocker appeared
    rfd --> ip : /bmad-build claims the bead
    ip --> rv : build complete
    rv --> ip : code-review leaves patches — claim kept
    rv --> d : code-review passes
    d --> [*] : sync closes the bead — downstream unblocks
```

Status only moves forward, with exactly two sanctioned reversals: `ready-for-dev → backlog`
(a blocker appeared) and `review → in-progress` (code-review sent the story back). Both
directions are mirrored by `sync`; nothing else ever demotes a story. A story bead is never
closed by hand: `sync` closes it from the `done` code-review writes. The one exception is a
story cut in correct-course, closed with `bd close <id> --reason "…"`.

## What's in the template

```
AGENTS.md                      operating protocol for any agent (Claude Code, Codex, humans)
CLAUDE.md                      points at AGENTS.md; project facts go below the line
.claude/settings.json          SessionStart → bd prime; read-only bd + bridge commands pre-allowed
_bmad/custom/*.toml            BMAD overrides: dependency convention, claim-on-start, sync-on-complete
.beads/formulas/bmad-planning.formula.toml   planning phases as a beads molecule
scripts/bmad_beads.py          the bridge: import | sync | claim | status | doctor  (stdlib only)
scripts/test_bmad_beads.py     unit tests for the parser, status mapping, and the sprint-status editor
scripts/bootstrap.sh           idempotent setup
Taskfile.yml                   task status | ready | import | sync | doctor | push | pull | plan
docs/BLUEPRINT.md              the design: ownership, data flow, failure modes, team modes
docs/references/               vendored standards + library docs; README.md is the manifest (anti-AI-slop shipped)
.github/workflows/bmad-beads-bridge.yml      CI for the BRIDGE only — add your project's own workflow
```

`_bmad/` (skills, config) and `.beads/` (database) are created by the bootstrap, not shipped —
so the template never pins a stale BMAD or beads version.

## Team modes

- **Default — per-clone embedded Dolt.** Each clone has its own `.beads/embeddeddolt/`;
  `bd dolt push` / `bd dolt pull` sync through the normal git remote under `refs/dolt/data`.
  No infrastructure; conflicts merge at the cell level.
- **Shared server — `scripts/bootstrap.sh --server`.** Points every clone (and every parallel
  agent on one machine) at one `dolt sql-server`. Use when many agents write concurrently;
  embedded mode is single-writer per clone.

See `docs/BLUEPRINT.md` for the full design and the things that will bite you.

## Status

Validated against BMAD Method **6.12.0** and beads **1.3.0** (Sep 2026) by the upstream
canary (`scripts/canary.py`): a fresh bootstrap, BMAD's own `sprint_plan.py` writing
`sprint-status.yaml`, then import → claim guard → review → done → milestone cascade, with
BMAD's `validate` accepting the result. That run caught one bd 1.3 change (a bead can only be
closed by its assignee), which the bridge now handles. The full dogfood cycles, two of them on a
real project with a cold agent in round two, ran in Aug 2026 on BMAD 6.11.0 / beads 1.2.2.

`bootstrap.sh` installs `@latest` of both unless you pin them
(`BMAD_VERSION=6.12.0 BD_VERSION=1.3.0 bash scripts/bootstrap.sh`), and `doctor` warns when the
installed pair differs from the validated one. The canary re-runs weekly in CI against
`@latest` and opens an issue when it fails. The bridge reads only the public shapes of
`epics.md`, `sprint-status.yaml`, and `bd --json`; when either tool changes those, the canary,
`scripts/test_bmad_beads.py` and `bmad_beads.py doctor` are where it shows first.

## License

[MIT](LICENSE)
