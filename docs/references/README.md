# docs/references

Static copies of the standards this project has adopted (style guides, ADR templates, API
conventions, security baselines). Copies, not plugins or submodules: a reader of this repo — human
or agent — should never need network access or a tool install to see what "the standard" is.

Conventions:

- One file per standard, named for what it governs: `python-style.md`, `adr-template.md`.
- First line of each file: the upstream source URL and the date it was copied.
- BMAD picks these up through `persistent_facts` in `_bmad/custom/<skill>.toml`
  (e.g. `"file:{project-root}/docs/references/python-style.md"`).
- Updating a standard is a normal PR, reviewed like code.
