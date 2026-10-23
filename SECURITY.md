# Security

## Reporting a vulnerability

Report it privately through GitHub's private vulnerability reporting:
[Security → Report a vulnerability](https://github.com/chhudson/bmad-beads-template/security/advisories/new).
Please don't open a public issue for it.

This covers the template's own files: the bridge and updater scripts, `bootstrap.sh`, the
workflows, and the Claude Code and BMAD configuration it ships. Problems in BMAD Method or beads
themselves belong to [BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD) and
[beads](https://github.com/gastownhall/beads).

In a project made from this template, replace this section with your project's own policy. The
updater keeps your edits.

## What runs without asking

Everything below is in the repo, so review a change to any of these files the way you would
review code.

| What | Where | When it runs |
|---|---|---|
| `bd prime --hook-json` | `SessionStart` hook in `.claude/settings.json` | Every Claude Code session in this folder, once you have trusted the folder. Headless runs (`claude -p`, the Agent SDK) don't show the trust dialog, so there it runs in any checkout. The `disableAllHooks` setting turns hooks off. |
| `uv run scripts/bmad_beads.py …` and read-only `bd` commands (`ready`, `show`, `list`, `dep tree`, `prime`) | `permissions.allow` in `.claude/settings.json` | Whenever an agent calls them, with no permission prompt. The bridge script lives in this repo: once you accept an edit to it, the edited version also runs without a prompt. |
| Bridge calls (`claim`, `import`, `sync`), `bd` writes, a local `git commit` after build and code-review, `bd dolt push` (skipped in a project bootstrapped with `--local-only`) | `activation_steps_append` and `on_complete` in `_bmad/custom/*.toml` | When a BMAD skill starts or finishes. These are instructions to the agent, not hooks, so anything outside the allowlist above still asks first. None of them runs `git push`. |
| Git hooks: `pre-commit`, `post-merge`, `pre-push`, `post-checkout`, `prepare-commit-msg` | `.beads/hooks/`, committed. `bd init` installs them and points `core.hooksPath` there; in a clone, `scripts/bootstrap.sh` does it again (`bd hooks install --beads`), since that setting isn't cloned. | On each of those git operations, in every clone that has run bootstrap. Each hook calls `bd hooks run <name>`. `prepare-commit-msg` adds agent identity trailers for orchestrator agents only; ordinary commits get none. A hook the repo already had keeps running because `bd init` copies its body into the matching `.beads/hooks/` file, so review that file: a copied hook can contain paths from the machine it came from. |
| `npx bmad-method@…`, and `npm install -g @beads/bd@…` when `bd` is missing | `scripts/bootstrap.sh` | When you run it. Both install `@latest` unless `BMAD_VERSION` / `BD_VERSION` pin them. In a clone, or on a re-run, the BMAD installer is skipped when the committed `_bmad/` already has that version. |
| Bridge tests | `.github/workflows/bmad-beads-bridge.yml` | Every push to `main` and every PR, with a read-only token. |
| Upstream canary | `.github/workflows/upstream-canary.yml` | Weekly in the template repo. In a project, only when the repository variable `UPSTREAM_CANARY` is `on`. It has `issues: write` so it can file a failure issue. |
| Dependabot | `.github/dependabot.yml` | Weekly, opening PRs that bump the pinned actions. |

Agents also read `docs/references/` and `_bmad-output/` as working context. Text there can carry
instructions, so a re-vendored doc or an edited planning artifact deserves the same review.
