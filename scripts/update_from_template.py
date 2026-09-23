#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
update_from_template.py — take a newer bmad-beads-template release into a project made from it.

A repo created with "Use this template" shares no git history with the template, so it cannot
`git merge` a new release. This script does a per-file three-way merge instead, using the
template release the project started from as the common base:

  untouched since the base        → replaced with the new version
  customised, template unchanged  → left alone
  customised, template changed    → merged (`git merge-file`; JSON merged structurally),
                                    kept only if the result still parses
  merge conflict                  → the local file is NOT touched; base / local / template
                                    versions are saved for review (`/update-template` in
                                    Claude Code resolves them)
  new in the template             → added
  removed from the template       → reported, never deleted

Never touched: README.md, CLAUDE.md (project-owned), anything listed in `.template-ignore`
(one glob per line) or passed with --skip. It refuses to run on a dirty working tree. Every
file it changes is backed up under `.template-update/<timestamp>/backup/`, next to a REPORT.md
of what it did and an undo.sh that puts back exactly those files and nothing else.

  uv run scripts/update_from_template.py                  # latest release
  uv run scripts/update_from_template.py --ref v0.3.0 --dry-run
  uv run https://raw.githubusercontent.com/chhudson/bmad-beads-template/main/scripts/update_from_template.py
                                                          # a project older than this script
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

DEFAULT_SOURCE = "https://github.com/chhudson/bmad-beads-template"
VERSION_FILE = ".template-version"
IGNORE_FILE = ".template-ignore"
WORK_DIR = ".template-update"
PROJECT_OWNED = {"README.md", "CLAUDE.md", VERSION_FILE}
# Line-set files: every line from both sides belongs in the result. `bd init` appends its own
# block to .gitignore, so a plain merge would conflict with any template addition at the end.
UNION_MERGE = {".gitignore"}
CONFLICT = object()  # sentinel from the JSON merge


# ----------------------------------------------------------------------------
# git helpers
# ----------------------------------------------------------------------------
def git(*args: str, cwd: Path, check: bool = True) -> str:
    res = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and res.returncode != 0:
        raise SystemExit(f"error: git {' '.join(args)}: {res.stderr.strip()}")
    return res.stdout


def semver_tags(repo: Path) -> list[str]:
    tags = [t for t in git("tag", "-l", cwd=repo).split() if re.fullmatch(r"v\d+\.\d+\.\d+", t)]
    return sorted(tags, key=_vkey)


def _vkey(tag: str) -> tuple[int, ...]:
    return tuple(int(x) for x in tag.lstrip("v").split("."))


class Tree:
    """File contents of the template at one ref, read lazily from the clone."""

    def __init__(self, repo: Path, ref: str):
        self.repo, self.ref = repo, ref
        self.paths = set(git("ls-tree", "-r", "--name-only", ref, cwd=repo).splitlines())

    def read(self, path: str) -> bytes | None:
        if path not in self.paths:
            return None
        return subprocess.run(["git", "show", f"{self.ref}:{path}"], cwd=self.repo, capture_output=True, check=True).stdout


# ----------------------------------------------------------------------------
# merging
# ----------------------------------------------------------------------------
def merge_text(base: bytes, local: bytes, new: bytes, union: bool = False) -> tuple[bytes, bool]:
    """git merge-file base local new → (result, clean). Needs no repository."""
    with tempfile.TemporaryDirectory() as d:
        p = {k: Path(d) / k for k in ("local", "base", "new")}
        p["local"].write_bytes(local)
        p["base"].write_bytes(base)
        p["new"].write_bytes(new)
        res = subprocess.run(["git", "merge-file", "-q", *(["--union"] if union else []), "-L", "local", "-L", "base",
                              "-L", "template", str(p["local"]), str(p["base"]), str(p["new"])], capture_output=True)
        return p["local"].read_bytes(), res.returncode == 0


def merge_json_value(base, local, new):
    """Three-way merge of parsed JSON. Objects merge per key; arrays keep local items, drop the
    ones the template removed, and append the ones it added. Returns CONFLICT when both sides
    changed one scalar differently. Objects are always merged key by key, in local's key order:
    dict equality ignores order, so an `==` shortcut would swap in the template's ordering
    (and `bd setup claude` rewrites settings.json with sorted keys)."""
    if isinstance(local, dict) and isinstance(new, dict):
        b = base if isinstance(base, dict) else {}
        out = {}
        for k in [*local, *(k for k in new if k not in local)]:
            miss = object()
            v = merge_json_value(b.get(k, miss), local.get(k, miss), new.get(k, miss))
            if v is CONFLICT:
                return CONFLICT
            if v is not miss:
                out[k] = v
        return out
    if local == new:
        return local
    if local == base:
        return new
    if new == base:
        return local
    if isinstance(local, list) and isinstance(new, list):
        b = base if isinstance(base, list) else []
        out = [x for x in local if not (x in b and x not in new)]
        out += [x for x in new if x not in b and x not in out]
        return out
    return CONFLICT


def merge_json(base: bytes, local: bytes, new: bytes) -> tuple[bytes, bool]:
    try:
        b, l, n = (json.loads(x.decode("utf-8")) if x else {} for x in (base, local, new))
    except (ValueError, UnicodeDecodeError):
        return local, False
    v = merge_json_value(b, l, n)
    if v is CONFLICT:
        return local, False
    newline = "\n" if local.endswith(b"\n") else ""  # keep the local file's style
    return (json.dumps(v, indent=2, ensure_ascii=False) + newline).encode("utf-8"), True


def _sq(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def _no_dupes(pairs):
    keys = [k for k, _ in pairs]
    dup = {k for k in keys if keys.count(k) > 1}
    if dup:
        raise ValueError(f"duplicate key(s) {sorted(dup)}")
    return dict(pairs)


def validate(path: str, data: bytes) -> str | None:
    """None if the file still parses; else why not. git's "clean" says nothing about validity:
    a line merge of JSON can produce two `permissions` keys and still exit 0."""
    try:
        text = data.decode("utf-8")
        if path.endswith(".json"):
            json.loads(text, object_pairs_hook=_no_dupes)
        elif path.endswith(".toml"):
            tomllib.loads(text)
        elif path.endswith(".py"):
            compile(text, path, "exec")
        elif path.endswith(".sh"):
            r = subprocess.run(["bash", "-n"], input=text, capture_output=True, text=True)
            if r.returncode:
                return r.stderr.strip()
        if "\n<<<<<<< " in "\n" + text:
            return "conflict markers left in the file"
    except (ValueError, SyntaxError, UnicodeDecodeError) as ex:
        return str(ex)
    return None


# ----------------------------------------------------------------------------
# planning the update
# ----------------------------------------------------------------------------
@dataclass
class Plan:
    write: dict[str, bytes] = field(default_factory=dict)  # path → new content
    actions: list[tuple[str, str]] = field(default_factory=list)  # (label, path)
    conflicts: dict[str, tuple[bytes | None, bytes, bytes]] = field(default_factory=dict)  # path → base, local, new
    skipped_upstream: list[str] = field(default_factory=list)  # ignored files the template changed

    def note(self, label: str, path: str) -> None:
        self.actions.append((label, path))


def plan_update(root: Path, base: Tree, new: Tree, ignore: list[str]) -> Plan:
    plan = Plan()
    for path in sorted(base.paths | new.paths):
        if path in PROJECT_OWNED:
            continue
        b, n = base.read(path), new.read(path)
        if b == n:
            continue  # the template did not change this file
        f = root / path
        local = f.read_bytes() if f.is_file() else None
        if any(fnmatch.fnmatch(path, g) for g in ignore):
            plan.skipped_upstream.append(path)
            plan.note("ignored (changed upstream)", path)
            continue
        if n is None:
            plan.note("removed upstream, kept", path)
            continue
        if local is None:
            if b is None:
                plan.write[path] = n
                plan.note("added", path)
            else:
                plan.note("deleted locally, not restored", path)
            continue
        if local == n:
            plan.note("already current", path)
            continue
        if local == b:
            plan.write[path] = n
            plan.note("updated", path)
            continue
        if path.endswith(".json"):
            merged, clean = merge_json(b or b"", local, n)
        elif b is None:
            merged, clean = local, False  # added upstream, but a different file already exists here
        else:
            merged, clean = merge_text(b, local, n, union=path in UNION_MERGE)
        problem = validate(path, merged) if clean else "overlapping edits"
        if problem:
            plan.conflicts[path] = (b, local, n)
            plan.note(f"CONFLICT ({problem})", path)
        else:
            plan.write[path] = merged
            plan.note("merged, local edits kept", path)
    return plan


def detect_base(root: Path, repo: Path, tags: list[str]) -> tuple[str, str]:
    """The template release this project was made from (or last updated to)."""
    vf = root / VERSION_FILE
    if vf.is_file():
        ref = vf.read_text(encoding="utf-8").split()[0]
        if git("rev-parse", "-q", "--verify", f"{ref}^{{commit}}", cwd=repo, check=False).strip():
            return ref, f"{VERSION_FILE}"
        print(f"! {VERSION_FILE} names {ref!r}, which the template does not have — guessing from file contents")
    # Score every template commit, not just releases: a project made from `main` between
    # releases matches that commit exactly. Blob ids make this one `ls-tree` per commit.
    commits = git("rev-list", "--reverse", "HEAD", *tags, cwd=repo).split()
    commits = list(dict.fromkeys(commits))  # oldest first; strictly-greater keeps the oldest on a tie
    paths: set[str] = set()
    trees = {}
    for c in commits:
        trees[c] = {}
        for line in git("ls-tree", "-r", c, cwd=repo).splitlines():
            meta, path = line.split("\t", 1)
            if path not in PROJECT_OWNED:
                trees[c][path] = meta.split()[2]
                paths.add(path)
    present = sorted(p for p in paths if (root / p).is_file())
    local_ids = dict(zip(present, git("hash-object", "--no-filters", "--", *present, cwd=root).split())) if present else {}
    best, best_n = None, 0
    for c in commits:
        n = sum(1 for p, blob in trees[c].items() if local_ids.get(p) == blob)
        if n > best_n:
            best, best_n = c, n
    if best is None:
        raise SystemExit("error: cannot tell which template release this project came from; pass --base <tag or commit>")
    tag = next((t for t in tags if git("rev-parse", f"{t}^{{commit}}", cwd=repo).strip() == best), None)
    if tag:
        return tag, f"guessed: {best_n} files match {tag} exactly"
    short = git("rev-parse", "--short=10", best, cwd=repo).strip()
    after = release_of(repo, short, tags)
    return short, f"guessed: {best_n} files match template commit {short}" + (f" (after {after})" if after else "") + " exactly"


def release_of(repo: Path, ref: str, tags: list[str]) -> str | None:
    """`ref` itself if it is a release tag, else the newest release tag it contains."""
    if ref in tags:
        return ref
    out = git("describe", "--tags", "--abbrev=0", "--match", "v[0-9]*", ref, cwd=repo, check=False).strip()
    return out if out in tags else None


def upgrading_notes(new: Tree, since: str | None, upto: str | None) -> str:
    """UPGRADING.md sections for releases after `since` up to and including `upto` (both release
    tags; None = no bound). Callers map a commit to its release with release_of()."""
    text = (new.read("UPGRADING.md") or b"").decode("utf-8")
    out = []
    for m in re.finditer(r"^## (v\d+\.\d+\.\d+)\b.*?(?=^## v\d|\Z)", text, re.M | re.S):
        v = _vkey(m.group(1))
        if (since is None or _vkey(since) < v) and (upto is None or v <= _vkey(upto)):
            out.append(m.group(0).strip())
    return "\n\n".join(out)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="update_from_template", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ref", help="template release to update to (default: the newest vX.Y.Z tag)")
    p.add_argument("--base", help="template release this project is on (default: .template-version, else guessed)")
    p.add_argument("--source", default=DEFAULT_SOURCE, help="template repository URL or local path")
    p.add_argument("--skip", action="append", default=[], metavar="GLOB", help="leave matching paths alone this run (repeatable)")
    p.add_argument("--dry-run", action="store_true", help="report what would happen; write nothing")
    p.add_argument("--allow-dirty", action="store_true", help="run even with uncommitted changes (git can then not undo the run)")
    p.add_argument("--no-checks", action="store_true", help="skip running the bridge tests afterwards")
    p.add_argument("--check", nargs="+", metavar="PATH", help="only check that these files still parse (after resolving a conflict), then exit")
    args = p.parse_args(argv)

    if args.check:
        bad = 0
        for path in args.check:
            problem = validate(path, Path(path).read_bytes())
            print(f"{'✗' if problem else '✓'} {path}" + (f": {problem}" if problem else ""))
            bad += bool(problem)
        return 1 if bad else 0

    root = Path(git("rev-parse", "--show-toplevel", cwd=Path.cwd()).strip())
    dirty = [ln for ln in git("status", "--porcelain", cwd=root).splitlines() if not ln[3:].startswith(WORK_DIR + "/")]
    if dirty and not (args.allow_dirty or args.dry_run):
        print("error: uncommitted changes. Commit or stash first, so `git checkout .` can undo this update.", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "template"
        print(f"fetching {args.source} …")
        res = subprocess.run(["git", "clone", "-q", "--no-checkout", args.source, str(repo)], capture_output=True, text=True)
        if res.returncode:
            print(f"error: could not clone {args.source}: {res.stderr.strip()}", file=sys.stderr)
            return 1
        tags = semver_tags(repo)
        ref = args.ref or (tags[-1] if tags else "HEAD")
        base_ref, how = (args.base, "--base") if args.base else detect_base(root, repo, tags)
        print(f"template: {base_ref} → {ref}  (base {how})")
        if git("rev-parse", f"{base_ref}^{{commit}}", cwd=repo) == git("rev-parse", f"{ref}^{{commit}}", cwd=repo):
            print("already up to date.")
            return 0
        ignore = [*args.skip]
        if (root / IGNORE_FILE).is_file():
            ignore += [ln.strip() for ln in (root / IGNORE_FILE).read_text(encoding="utf-8").splitlines()
                       if ln.strip() and not ln.lstrip().startswith("#")]
        new = Tree(repo, ref)
        # Record a tag as itself; anything else (a branch, HEAD) as its commit, which a later
        # clone can still resolve.
        recorded = ref if ref in tags else git("rev-parse", f"{ref}^{{commit}}", cwd=repo).strip()
        plan = plan_update(root, Tree(repo, base_ref), new, ignore)
        # A commit on main between releases has taken that release's steps already (its tag is
        # an ancestor) but not the next one's; a non-tag target gets every newer section.
        notes = upgrading_notes(new, release_of(repo, base_ref, tags), ref if ref in tags else None)

    width = max((len(label) for label, _ in plan.actions), default=0)
    for label, path in plan.actions:
        print(f"  {label.ljust(width)}  {path}")
    if args.dry_run:
        print(f"\ndry run: {len(plan.write)} file(s) would change, {len(plan.conflicts)} conflict(s). Nothing written.")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    work = root / WORK_DIR / stamp
    rel = f"{WORK_DIR}/{stamp}"
    undo = ["#!/usr/bin/env bash", f"# Undo the template update {base_ref} → {ref}: restore every file it changed,",
            "# delete the ones it added. Touches nothing else.", "set -euo pipefail", 'cd "$(git rev-parse --show-toplevel)"']
    # Conflicted files are backed up too: the updater leaves them alone, but /update-template
    # then writes a resolution into them, and undo must take that back as well.
    for path in [*plan.write, *plan.conflicts, VERSION_FILE]:
        if (root / path).is_file():
            dst = work / "backup" / path
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / path, dst)
            undo.append(f"cp {_sq(f'{rel}/backup/{path}')} {_sq(path)}")
        else:
            undo.append(f"rm -f {_sq(path)}")
    work.mkdir(parents=True, exist_ok=True)
    (work / "undo.sh").write_text("\n".join(undo) + '\necho "template update undone"\n', encoding="utf-8")
    for path, data in plan.write.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(data)
    if plan.conflicts:
        lines = [f"# Template update {base_ref} → {ref}: {len(plan.conflicts)} conflict(s)", "",
                 "Each local file below was left exactly as it was. Beside it here are three versions:",
                 "`.base` (the template as the project started from it), `.local` (the project's copy)",
                 "and `.template` (the new release). Write a version into the project that keeps the",
                 "project's own changes and takes the template's. `/update-template` in Claude Code does this.", ""]
        for path, (b, local, n) in plan.conflicts.items():
            for suffix, data in ((".base", b), (".local", local), (".template", n)):
                if data is not None:
                    dst = work / "conflicts" / (path + suffix)
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_bytes(data)
            lines.append(f"- [ ] `{path}`")
        (work / "CONFLICTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (root / VERSION_FILE).write_text(f"{recorded}\n", encoding="utf-8")
    width = max((len(label) for label, _ in plan.actions), default=0)
    report = [f"# Template update {base_ref} → {ref}", "", f"- base: {base_ref} ({how})", f"- {VERSION_FILE} now: {recorded}",
              f"- files changed: {len(plan.write)}; conflicts: {len(plan.conflicts)}",
              f"- undo: `bash {rel}/undo.sh`", "", "## Every file the template changed", "", "```",
              *(f"{label.ljust(width)}  {path}" for label, path in plan.actions), "```", ""]
    if notes:
        report += ["## Do these by hand (from UPGRADING.md)", "", notes, ""]
    (work / "REPORT.md").write_text("\n".join(report), encoding="utf-8")

    print(f"\n{len(plan.write)} file(s) changed; backups, REPORT.md and undo.sh in {rel}/. {VERSION_FILE} → {recorded}.")
    if plan.skipped_upstream:
        print(f"Ignored but changed upstream (review by hand): {', '.join(plan.skipped_upstream)}")
    ok = True
    if not args.no_checks and (root / "scripts" / "test_bmad_beads.py").is_file():
        r = subprocess.run(["uv", "run", "--quiet", "scripts/test_bmad_beads.py"], cwd=root, capture_output=True, text=True)
        ok = r.returncode == 0
        print("bridge tests: " + ("pass" if ok else "FAIL\n" + (r.stderr or r.stdout)[-2000:]))
    if notes:
        print("\n---- UPGRADING.md: do these by hand ----\n" + notes + "\n")
    if plan.conflicts:
        print(f"{len(plan.conflicts)} conflict(s): see {WORK_DIR}/{stamp}/CONFLICTS.md, or run /update-template in Claude Code.")
    print(f"Review with `git diff`; undo with `bash {rel}/undo.sh`.")
    return 0 if ok and not plan.conflicts else 2


if __name__ == "__main__":
    sys.exit(main())
