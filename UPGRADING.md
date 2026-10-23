# Upgrading

How to take a newer template release into a project made from this template:

```bash
uv run scripts/update_from_template.py            # or /update-template in Claude Code
```

Projects made before v0.3.0 don't have the script yet. Run it straight from the template:

```bash
uv run https://raw.githubusercontent.com/chhudson/bmad-beads-template/v0.3.1/scripts/update_from_template.py
```

If Claude Code's auto mode blocks that ("Code from External"), run it yourself by typing it with a
leading `!` in the prompt, then run `/update-template` to resolve conflicts and finish.

It merges each file with the project's own changes, leaves conflicts untouched for review, and prints
the steps below for every release it crosses. See the README section "Updating from the template".

## Unreleased

- **Run `bd dolt push` once on the machine that bootstrapped the project**, if nobody has. In a
  fresh clone, `bootstrap.sh` now fetches the beads database with `bd bootstrap` (before, it stopped
  at `no beads database found`). With nothing pushed, it stops and says so.
- **Local-only projects made from `main` after v0.3.1** (bootstrapped with `--local-only`): the
  next bootstrap unsets `sync.remote` in `.beads/config.yaml`, and bd's section of `AGENTS.md` drops
  its `bd dolt push` lines to match. Commit both. `bd bootstrap` ignores `dolt.local-only`, so with
  `sync.remote` set a clone tries to fetch a database that was never pushed; without it, the clone
  starts its own.
- **`LICENSE` is now the project's**, like `README.md`: the updater never changes it, and a new
  project's first bootstrap removes the template's. If yours is still the template's MIT licence
  (copyright Charles Hudson) and that isn't right for the project, delete it or replace it.
- **bd's anonymous usage metrics are now in SECURITY.md's "What runs without asking".** bd sends
  them from every command unless they are off. Nothing changes unless you want them off: run
  `bd metrics off` (it applies to your user account on that machine, not to the project), or
  re-run `bash scripts/bootstrap.sh --no-metrics`. In CI, set `BD_DISABLE_METRICS=1`; the upstream
  canary now does. `doctor` shows the current state.
- **Add `@AGENTS.md` to your `CLAUDE.md`.** Claude Code reads `AGENTS.md` by itself only in a
  project with no `CLAUDE.md`, so until now the protocol reached the agent only when it chose to
  open the file. The updater never touches `CLAUDE.md`: replace the line
  "Read `AGENTS.md` first — …" with `@AGENTS.md` on a line of its own.
- **`.github/dependabot.yml` is new**: weekly PRs that bump the pinned actions. Delete it and list
  it in `.template-ignore` if you'd rather bump them by hand.
- **`SECURITY.md` is new.** Replace its reporting section with your project's own policy.
- **`doctor` now says where beads syncs**, and fails when a Dolt remote is the template repo
  (`bd dolt push` would publish your beads there). Run `uv run scripts/bmad_beads.py doctor` once.
  To keep beads off every remote from now on: `bd config set dolt.local-only true`, which is what the
  new `bootstrap.sh --local-only` sets.
- Nothing to do for the rest:
  - The updater now recognises a project made from `main` between releases even though
    `.template-version` names the release before. It also leaves alone a project that is newer
    than the newest release.
  - The canary creates its issue labels when they're missing.
  - `/bmad-build` skips the claim for a freeform change that has no story.
  - In a clone, bootstrap installs bd's git hooks (`core.hooksPath` isn't cloned) and sets
    `.beads/` back to 0700. It skips the BMAD installer when the committed `_bmad/` already has the
    wanted version, so a re-run leaves a clean tree.
  - `doctor` fails when there is no beads database, instead of printing `doctor: OK`.
  - `update_from_template.py --install` adds the template to a repo that wasn't made from it (README,
    "Add to an existing repo"), and `/update-template` knows how to resolve what it leaves.
  - On a first run, bootstrap takes back the commit `bd init` makes of its own and leaves the
    changes staged, so the whole bootstrap is one commit. It writes a README stub when there is no
    `README.md`, names any repo hooks bd copied into `.beads/hooks/`, and keeps the key order of
    `.claude/settings.json` (`bd setup claude` sorts it).
  - `doctor` warns when `core.hooksPath` isn't `.beads/hooks`, which is when bd's hooks stop running.
  - An `undo.sh` also removes directories its run created.
  - The upstream canary drops the project's beads state from its throwaway copy. In a project it
    failed on every PR that touched its paths, Dependabot's included.

## v0.3.1

- **The upstream canary's weekly run is now opt-in** outside the template repo. Nothing to do if you
  don't want it. To keep it, set the repository variable `UPSTREAM_CANARY` to `on`.
- Updater fixes only; nothing else to do. (A project made from template `main` between releases is
  now recognised, `--base <commit>` works, and `.claude/settings.json` keeps its key order.)

## v0.3.0

- **bd 1.3 or newer is required** (`claim` uses `bd update --if-assignee`). `brew upgrade beads` or
  `npm i -g @beads/bd@latest`. `doctor` now warns on anything older and prints the installed
  BMAD / bd pair against the validated one.
- **Planning molecules poured before v0.3.0 have no step labels**, and the planning skills now find
  their step only by label (`bmad-step:<id>`), so they skip an old molecule without a word. Re-pour it
  (`bd mol pour bmad-planning --var initiative="<name>"`), or close its remaining steps by hand.
- **PRD sign-off is two closes**: the human gate bead (`bd gate list`), then the "PRD sign-off" step it
  unblocks. Architecture waits on the second.
- **The `upstream canary` workflow is new** (`.github/workflows/upstream-canary.yml`). It bootstraps a
  throwaway project against the newest BMAD and bd and runs one story through the bridge. From v0.3.1
  its weekly run is opt-in (see above).
- Nothing to do for the rest (bridge fixes, stricter `Depends on:` parsing, the permission allowlist).
  After updating, run `uv run scripts/bmad_beads.py sync` once.
