# docs/references

Static copies of the standards this project has adopted (style guides, ADR templates, API
conventions, security baselines) and of the documentation for the libraries it depends on.
Copies, not plugins or submodules: a reader of this repo — human or agent — should never need
network access or a tool install to see what "the standard" is or what an API actually accepts.

## Conventions

- **Standards** are one file each, named for what they govern: `python-style.md`,
  `adr-template.md`. First line: the upstream source URL and the date it was copied.
- **Vendored library docs** live in a `<tool>/` subfolder: `<tool>/llms-full.txt` (or one
  `<product>.llms-full.txt` per product for a large vendor), optionally the `llms.txt` index, and a
  `README.md` stating the upstream URL, version, fetch date, fetch method, size and licence.
  `docs/references/<tool>/*llms-full.txt` is the **source of record** for that library: grep it
  before asserting any API, binding, config key, limit or CLI flag. Search-derived API knowledge
  is the expensive kind of wrong, and training data is out of date by definition.
- **Style references** that are more than one file (a checklist plus the sources it cites) live
  under `style/<name>/` with the same `README.md` contract.
- Every subfolder README records licence and attribution. Vendored content keeps its own licence
  (this repo's MIT licence covers the template, not the copies).
- BMAD skills pick these up through `persistent_facts` in `_bmad/custom/<skill>.toml`. The
  shipped overrides load this manifest (`file:{project-root}/docs/references/README.md`) plus a
  rule telling the agent to grep the vendored docs; point a skill at a specific file with
  `"file:{project-root}/docs/references/<path>"`. A glob such as `docs/references/*.md` only
  matches this README, never the subfolders — name files explicitly.
- Updating a standard or re-vendoring a library is a normal PR, reviewed like code.
- Verify a skill sees what you intended:
  `uv run _bmad/scripts/resolve_customization.py --skill .claude/skills/<skill> --key workflow`.

## Manifest

| Path | What | Version / date | Source |
|---|---|---|---|
| `style/anti-ai-slop/` | "Wikipedia:Signs of AI writing" (CC BY-SA 4.0) + `tropes.md` AI-writing tropes catalogue (attribution-required), with a house checklist for reviewing prose | Wikipedia rev. 1370403579; both copied 2026-09-01 | en.wikipedia.org, gist.github.com/ossa-ma (tropes.fyi) |

Add one row per standard or vendored library, e.g.
`| \`cloudflare/\` | Cloudflare \`llms.txt\` index + per-product \`llms-full.txt\` | fetched YYYY-MM-DD | developers.cloudflare.com |`.
