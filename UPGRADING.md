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
