# Blueprint: BMAD × beads

How the two tools are joined, what each owns, and where the seams are. Verified against
BMAD Method 6.11.0 and beads 1.2.2 (Dolt backend), August 2026.

## 1. The problem this solves

BMAD is a method for *deciding* — it makes product and architecture decisions explicit and
carries them forward as documents. Its implementation loop (`bmad-build` → `bmad-code-review`)
tracks state in one flat file, `sprint-status.yaml`, with a linear notion of order: stories are
listed per epic, and the next `ready-for-dev` story is "the next one".

That is fine for one person on one epic. It is not fine for a project that runs for months with
several people and several agents, where the questions are: *what can start now that nothing
blocks it?*, *who has it?*, *what did we find along the way that is not anybody's story yet?*,
and *what did we learn last month that this session must not forget?* Those are graph and memory
questions, and beads is a graph with memory.

The failure mode to avoid is adopting beads as a second status board. Then `sprint-status.yaml`
and `.beads/` disagree within a week and both get ignored. The design below prevents that by
giving every fact exactly one writer.

## 2. Ownership contract

| Fact | Writer | Readers | Carried by |
|---|---|---|---|
| Brief, PRD, UX, architecture | BMAD skills | everyone | `_bmad-output/planning-artifacts/**` |
| Epics, stories, acceptance criteria | `bmad-create-epics-and-stories` (+ `correct-course`) | bridge `import` | `epics.md` |
| Story dependencies | the PM, in `epics.md` (`**Depends on:**`) | bridge `import` → beads `blocks` edges | beads |
| Story lifecycle `in-progress`, `review`, `done` | `bmad-build`, `bmad-code-review` (via BMAD's `sync-sprint-status.md`) | bridge `sync` → beads | `sprint-status.yaml` |
| `ready-for-dev` vs `backlog` | **bridge `sync`, from `bd ready`** | BMAD (`bmad-build` step-01, `sprint_plan.py status`) | `sprint-status.yaml` (derived) |
| Epic rows `epic-N` | bridge `sync`, derived from story rows with BMAD's own rules | BMAD | `sprint-status.yaml` |
| Retrospective rows, `action_items` | BMAD | — | `sprint-status.yaml` (bridge never touches) |
| Claims / assignees | beads (`bd update --claim`) | agents, `status` | beads only |
| Discovered work, deferred findings, decisions | beads (`discovered-from`, `-t decision`) | `bd ready` | beads only |
| Durable insights | beads (`bd remember`) | `bd prime` at session start | beads only |
| Unknown statuses (e.g. bmad-loop `awaiting-operator`) | whoever wrote them | — | passed through untouched |

Two rules make the sync trivially safe:

1. **Monotonic within the BMAD vocabulary.** Story status only moves forward
   (`backlog → ready-for-dev → in-progress → review → done`), in both stores, with one
   documented exception: `ready-for-dev → backlog` when a *new* blocker appears in the graph. That
   demotion is the whole point of the graph, and BMAD itself never reads `ready-for-dev` as a
   promise.
2. **Idempotent, stateless.** `sync` computes a fixed point from the two current states. It keeps
   no cursor, no last-sync timestamp, and no conflict log. Running it twice is a no-op; running it
   after a crash is safe.

## 3. Data mapping

### 3.1 `epics.md` → beads (`import`)

| BMAD | beads |
|---|---|
| `## Epic N: Title` | issue `type=epic`, title `Epic N: Title`, labels `bmad-epic, epic-N`, metadata `{bmad_epic_key: "epic-N", bmad_epic: N}` |
| `### Story N.M: Title` | child `type=task` under the epic (hierarchical id `prefix-xxxx.M`), labels `story, epic-N`, description = *As a / I want / So that*, `acceptance_criteria` = the Given/When/Then block, metadata `{bmad_story_key: "N-M-slug", bmad_ref: "N.M"}` |
| `**Depends on:** A.B, C.D` under a story | `bd dep add <story> <A.B>` (type `blocks`) |
| `**Depends on:** Epic K` under an epic | a milestone task **"Epic K complete"** (label `epic-gate`, metadata `bmad_epic_gate`) blocked by every story of K; every story of this epic is blocked by the milestone. (beads only lets tasks block tasks — an epic cannot be a blocker.) `sync` closes the milestone when K's stories are all closed. |

The story key uses BMAD's exact slug rule (`sprint_plan.py::_slug`: lowercase, `\W+ → -`,
60 chars), so `sprint-status.yaml` keys and bead metadata line up byte-for-byte. Matching on
re-import is by metadata key, never by title, so retitling a story in beads is harmless; retitling
it in `epics.md` forks the key (BMAD forks it too — this is BMAD's behaviour, not the bridge's).
`doctor` reports the drift.

`import` adds and retitles; it never deletes. Removed stories are closed by hand with a reason
(`bd close <id> --reason "cut in correct-course"`), which keeps the audit trail.

### 3.2 `sprint-status.yaml` ↔ beads (`sync`)

Order of operations inside one run:

1. BMAD → beads. For each story row: `in-progress → in_progress`, `review → review` (a beads
   custom status, `status.custom review:wip`, so it is visible but not claimable), `done → closed`.
   Only forward moves.
2. Milestones and epic beads close when every story of the epic is closed.
3. `bd ready --type task --label story` is read **after** step 2, so a freshly unblocked epic is
   visible in the same run.
4. beads → BMAD. `closed → done`, `in_progress → in-progress` (someone claimed it in beads),
   `review → review`; and for `open` beads, `backlog ↔ ready-for-dev` from readiness.
5. Epic rows: `backlog → in-progress` when any story has started (BMAD's own lift rule);
   `→ done` when all stories are done (BMAD's own STATUS DEFINITIONS).
6. `tracking_system: beads`, `last_updated` refreshed; file written atomically, comments and
   `action_items` preserved verbatim (the editor is line-based and touches only the keys it owns).

BMAD's `sprint_plan.py status` reads the result without complaint and its `recommendation`
becomes "start the next *ready* story", which is now graph-aware.

### 3.3 Where the bridge is invoked

All through BMAD's supported customization surface (`_bmad/custom/<skill>.toml`, three-layer TOML
merge, survives `bmad-method install --action update`):

| Skill | `activation_steps_append` | `persistent_facts` | `on_complete` |
|---|---|---|---|
| `bmad-create-epics-and-stories` | — | the `Depends on:` convention; keys are stable | `import --dry-run`, confirm, `import` |
| `bmad-sprint-planning` | — | `ready-for-dev` is derived, never hand-set | `import` + `sync` + `status` |
| `bmad-build` / `bmad-build-auto` | claim the bead (`--claim`; stop if held by someone else) | discovered work → beads; insights → `bd remember` | `sync`, `bd dolt push` |
| `bmad-code-review` | — | `[Defer]` findings → beads | `sync` |
| `bmad-retrospective` | — | — | `sync`; action items → chores; lessons → `bd remember` |
| `bmad-correct-course` | — | keep `Depends on:` lines true; close, don't delete | `import` + `doctor` |

`on_complete` is an *instruction to the agent*, not a shell hook — BMAD's SKILL.md reads
"treat a string scalar as one instruction". So the bridge is only as reliable as the agent
following it; `doctor` exists to catch a skipped step, and `sync` is safe to run by hand at any
time. There is no shell-level hook in BMAD 6.11 that fires on workflow completion.

Session-level: Claude Code's `SessionStart` runs `bd prime --hook-json` (beads' own recommended
hook; it re-fires after compaction, so no `PreCompact` hook is needed or installed).

## 4. Planning as a molecule

`.beads/formulas/bmad-planning.formula.toml` turns BMAD phases 1–3 into a beads workflow:
`brief → prd → [human gate: PRD sign-off] → architecture → epics → sprint-plan → beads-import`.
Pour one per initiative. The value is small but real: `bd ready` now answers "what is the next
planning move" the same way it answers "what is the next story", and the human sign-off is a
gate the graph knows about rather than a memory in somebody's head. Phase 4 is deliberately not
in the formula — real stories come from `import`.

## 5. Team modes

**Embedded (default).** One Dolt database per clone under `.beads/embeddeddolt/` (gitignored).
`bd init` records the git remote as `sync.remote`; `bd dolt push` / `bd dolt pull` move the Dolt
history through `refs/dolt/data` on the same remote — invisible to branch protection, merged at
the cell level. Single writer per clone, which is right for one human plus one agent.

**Server (`bootstrap.sh --server`).** Every clone and every parallel agent talks to one
`dolt sql-server`. Needed when several agents on one machine write concurrently (worktrees, a
swarm). The trade is infrastructure and a network dependency for `bd ready`.

Both modes use the same bridge, the same overrides, the same protocol. `.beads/issues.jsonl` is
an *export* for viewers and migration, not the source of truth; the template does not enable it.

## 6. Known seams and how they fail

- **`on_complete` is advisory.** An agent that exits early skips the sync. Mitigation: `sync` is
  idempotent, `status`/`doctor` are one command, and the `SessionStart` hook means the next
  session sees the true graph regardless.
- **Retitled stories fork keys** — in BMAD as much as in beads. Edit bodies, not titles, after
  import; `doctor` lists keys present in one store but not the other.
- **`review` is a custom beads status.** If a clone is initialised without
  `bd config set status.custom review:wip`, `sync` fails loudly on the first `review` story.
  `doctor` checks it; `bootstrap.sh` sets it; the setting lives in the Dolt DB so it syncs.
- **beads JSON envelope.** beads 2.0 will wrap `--json` output in `{"schema_version","data"}`;
  the bridge already unwraps it.
- **bmad-loop** (unattended epic runner) is out of scope here but not designed out: it becomes
  the sole writer of `sprint-status.yaml` during a run and adds `awaiting-operator`. The bridge
  treats unknown statuses as pass-through and never regresses, so running `sync` around a loop
  is safe. Wiring it fully (a `.bmad-loop/plugins/` stage hook calling `sync`) is a later step.
- **Epic-level dependencies cost edges.** "Epic 2 depends on Epic 1" is |E1| + |E2| edges via
  the milestone, not |E1|×|E2|. Fine at tens of stories; revisit if an epic has hundreds.

## 7. What to standardise next

The bridge is 700 lines of stdlib Python because the contract is the product, not the code. The
things worth hardening in order: a `bmad-beads` custom BMAD module (so `npx bmad-method install
--custom-source` ships the overrides instead of the template copying them), the bmad-loop plugin
hook, and a `bd` label convention for routing stories to people versus agents
(`bd ready --label human`).
