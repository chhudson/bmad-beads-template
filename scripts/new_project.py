#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
new_project.py — start a project from bmad-beads-template, choosing where it lives.

It lists your GitHub account, each organization you're an active member of, and "Local only"
(no GitHub repo), and you pick one with the arrow keys (#73). Then it creates the repo from the
template and clones it (`gh repo create OWNER/NAME --template … --private --clone`), or, for local
only, copies the template without its history. Last, it runs `scripts/bootstrap.sh` in the new
folder, with `--local-only` for a local project. Nothing is committed or pushed: bootstrap ends by
printing those steps.

  uv run https://raw.githubusercontent.com/chhudson/bmad-beads-template/<tag>/scripts/new_project.py my-project
      … new_project.py my-org/my-project            owner named: no picker
      … new_project.py my-project --local           no GitHub repo; beads stays on this machine
      … new_project.py my-project --dry-run         pick, then print the commands instead of running them
      … new_project.py my-project -- --no-metrics   everything after -- goes to bootstrap.sh

`gh repo create` has an owner picker of its own, but it can't be used here: it only prompts when
given no flags at all, and then it offers only templates owned by the owner you picked. With no
terminal to pick in (CI, a pipe), this script lists the owners it found and stops, rather than
choose one for you.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import select
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

DEFAULT_TEMPLATE = "chhudson/bmad-beads-template"
# What GitHub accepts in a repository name (it rewrites anything else to '-').
NAME_RE = re.compile(r"[A-Za-z0-9._-]+")
VISIBILITIES = ("private", "public", "internal")
# An organization's base permission applies to every repo in it, a new one included.
BASE_PERMISSION = {
    "read": "every org member can read it",
    "write": "every org member can push to it",
    "admin": "every org member is an admin of it",
}
INSTALL_HINT = {"gh": "https://cli.github.com, then `gh auth login` (or use --local)"}


class Abort(Exception):
    """Stop with this message and exit code."""

    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Choice:
    owner: str | None  # None: local only, no GitHub repo
    label: str
    note: str = ""


LOCAL_CHOICE = Choice(None, "Local only", "no GitHub repo; beads stays on this machine")


@dataclass(frozen=True)
class Step:
    cmd: tuple[str, ...]
    cwd: str = "."  # relative to the folder the script runs in

    def __str__(self) -> str:
        line = shlex.join(self.cmd)
        return line if self.cwd == "." else f"(cd {shlex.quote(self.cwd)} && {line})"


def parse_target(target: str) -> tuple[str | None, str]:
    """`NAME` or `OWNER/NAME`, the way gh takes it."""
    parts = target.split("/")
    if len(parts) > 2 or not all(parts):
        raise Abort(f"{target!r}: give NAME or OWNER/NAME", 2)
    owner, name = (None, parts[0]) if len(parts) == 1 else (parts[0], parts[1])
    if not NAME_RE.fullmatch(name) or name in (".", ".."):
        raise Abort(f"{name!r} isn't a name GitHub accepts for a repo: use letters, digits, '.', '-' and '_'", 2)
    return owner, name


# ----------------------------------------------------------------------------
# owners
# ----------------------------------------------------------------------------

def gh_api(path: str):
    try:
        r = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    except FileNotFoundError:
        raise Abort(f"gh (the GitHub CLI) isn't installed: {INSTALL_HINT['gh']}") from None
    if r.returncode:
        raise Abort(f"gh api {path} failed: {r.stderr.strip()}")
    return json.loads(r.stdout)


def org_note(role: str, org: dict, visibility: str) -> str:
    """What this org's settings mean for a new repo, in a few words."""
    notes = []
    # Org owners can always create repos; members only where the org allows that visibility.
    if role != "admin" and org.get(f"members_can_create_{visibility}_repositories") is False:
        notes.append(f"members can't create {visibility} repos here")
    if org.get("default_repository_permission") in BASE_PERMISSION:
        notes.append(BASE_PERMISSION[org["default_repository_permission"]])
    return "; ".join(notes) or "organization"


def build_choices(login: str, memberships: list[dict], orgs: dict[str, dict], visibility: str) -> list[Choice]:
    """Your account first, then your orgs by name, then local only. Nothing is left out for its
    settings: GitHub has the last word when the repo is created, and its error says why."""
    org_choices = [
        Choice(m["organization"]["login"], m["organization"]["login"],
               org_note(m.get("role", ""), orgs.get(m["organization"]["login"], {}), visibility))
        for m in memberships if m.get("state") == "active"
    ]
    return [Choice(login, login, "your account"), *sorted(org_choices, key=lambda c: c.label.lower()), LOCAL_CHOICE]


def owner_choices(visibility: str) -> list[Choice]:
    login = gh_api("user")["login"]
    memberships = gh_api("user/memberships/orgs?state=active&per_page=100")
    orgs = {}
    for m in memberships:
        name = m["organization"]["login"]
        try:
            orgs[name] = gh_api(f"orgs/{name}")
        except Abort:
            pass  # the note is a courtesy; without the details the org is still a choice
    return build_choices(login, memberships, orgs, visibility)


def no_terminal_message(choices: list[Choice]) -> str:
    flags = [f"--owner {c.owner}" if c.owner else "--local" for c in choices]
    width = max(len(f) for f in flags)
    return "\n".join(["no terminal to pick in, so name where the repo goes:",
                      *(f"  {f.ljust(width)}  {c.note}" for f, c in zip(flags, choices))])


# ----------------------------------------------------------------------------
# the picker
# ----------------------------------------------------------------------------

UP = {b"\x1b[A", b"\x1bOA", b"k"}
DOWN = {b"\x1b[B", b"\x1bOB", b"j"}
ENTER = {b"\r", b"\n"}
CANCEL = {b"\x1b", b"q"}


def move(index: int, count: int, key: bytes) -> tuple[int, str | None]:
    """One keypress: the new index, and "pick" or "cancel" once the picker is done."""
    if key in UP:
        return (index - 1) % count, None
    if key in DOWN:
        return (index + 1) % count, None
    if key in ENTER:
        return index, "pick"
    if key in CANCEL:
        return index, "cancel"
    return index, None


def read_key(fd: int) -> bytes:
    """One keypress. An arrow key is an escape sequence (ESC [ A); Esc alone is just ESC, told
    apart by nothing following it. Reads one sequence only, so keys typed fast aren't merged."""
    key = os.read(fd, 1)
    if key != b"\x1b" or not select.select([fd], [], [], 0.05)[0]:
        return key
    key += os.read(fd, 1)
    if key[-1:] in (b"[", b"O"):
        while True:  # parameter bytes, then one final byte in @..~
            b = os.read(fd, 1)
            key += b
            if not b or 0x40 <= b[0] <= 0x7E:
                break
    return key


def can_pick() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def pick(choices: list[Choice], title: str, fd: int | None = None, out: TextIO | None = None) -> Choice | None:
    """Arrow-key menu: Enter chooses, Esc or q cancels (None). Keys typed before it shows are
    discarded (setcbreak flushes input), so an Enter pressed while gh was loading picks nothing."""
    import termios
    import tty

    keys: int = sys.stdin.fileno() if fd is None else fd
    screen: TextIO = out or sys.stdout
    cols = shutil.get_terminal_size().columns
    width = max(len(c.label) for c in choices)

    def draw(index: int) -> None:
        for i, c in enumerate(choices):
            # Cut to the terminal's width: a wrapped line would throw off the redraw.
            text = f"{'❯' if i == index else ' '} {c.label.ljust(width)}  {c.note}"[: cols - 1]
            screen.write("\r\x1b[2K" + (f"\x1b[1m{text}\x1b[0m" if i == index else text) + "\n")
        screen.flush()

    saved = termios.tcgetattr(keys)
    index = 0
    screen.write(f"{title}  (↑/↓ to move, Enter to choose, Esc to cancel)\n\x1b[?25l")
    try:
        tty.setcbreak(keys)
        draw(index)
        while True:
            index, done = move(index, len(choices), read_key(keys))
            if done:
                return choices[index] if done == "pick" else None
            screen.write(f"\x1b[{len(choices)}A")
            draw(index)
    finally:
        termios.tcsetattr(keys, termios.TCSADRAIN, saved)
        screen.write("\x1b[?25h")
        screen.flush()


# ----------------------------------------------------------------------------
# the plan
# ----------------------------------------------------------------------------

def clone_url(template: str) -> str:
    # OWNER/REPO is on GitHub; a URL is used as it is (the tests clone a file:// fixture).
    return template if "://" in template else f"https://github.com/{template}.git"


def plan(owner: str | None, name: str, template: str, visibility: str, bootstrap: list[str] | None) -> list[Step]:
    """The commands, in order. owner None: local only. bootstrap None: leave it to the user."""
    if owner is None:
        steps = [Step(("git", "clone", "-q", "--depth", "1", clone_url(template), name)),
                 # A history of its own: the template's commits go, and with them its origin,
                 # which bootstrap refuses since beads would sync there (#49).
                 Step(("rm", "-rf", ".git"), name),
                 Step(("git", "init", "-q"), name)]
        if bootstrap is not None and "--local-only" not in bootstrap:
            bootstrap = ["--local-only", *bootstrap]
    else:
        steps = [Step(("gh", "repo", "create", f"{owner}/{name}", "--template", template,
                       f"--{visibility}", "--clone"))]
    if bootstrap is not None:
        steps.append(Step(("bash", "scripts/bootstrap.sh", *bootstrap), name))
    return steps


def run(steps: list[Step], owner: str | None, name: str) -> None:
    missing = sorted({s.cmd[0] for s in steps if not shutil.which(s.cmd[0])})
    if missing:
        raise Abort("missing: " + ", ".join(f"{m} ({INSTALL_HINT[m]})" if m in INSTALL_HINT else m for m in missing))
    for i, step in enumerate(steps):
        print(f"\n$ {step}", flush=True)
        rc = subprocess.run(step.cmd, cwd=step.cwd).returncode
        if rc:
            lines = [f"failed (exit {rc}): {step}"]
            if step.cmd[0] == "gh":
                lines.append(f"If GitHub made the repo but the clone failed (`gh repo view {owner}/{name}`), "
                             f"don't create it again: `gh repo clone {owner}/{name}` instead.")
            lines += ["Once the cause is fixed, what's left to run, in order (bootstrap is safe to re-run):",
                      *(f"  {s}" for s in steps[i:])]
            raise Abort("\n".join(lines))


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    # Split at -- by hand. In older patch releases (3.11.9, and 3.12.3, which ubuntu-latest runs) a
    # nargs="*" positional after NAME is matched, empty, along with NAME, and argparse then rejects
    # whatever follows the -- as unrecognized.
    cut = argv.index("--") if "--" in argv else len(argv)
    argv, bootstrap_args = argv[:cut], argv[cut + 1:]
    p = argparse.ArgumentParser(prog="new_project", description=__doc__,
                                usage="%(prog)s [options] [OWNER/]NAME [-- BOOTSTRAP_ARG ...]",
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("target", metavar="[OWNER/]NAME", help="the new repo and folder; with OWNER/ there is no picker")
    where = p.add_mutually_exclusive_group()
    where.add_argument("--owner", help="GitHub account or organization to create the repo in (no picker)")
    where.add_argument("--local", action="store_true",
                       help="no GitHub repo: copy the template without its history; beads stays on this machine")
    p.add_argument("--visibility", choices=VISIBILITIES, default="private", help="of the GitHub repo (default: private)")
    p.add_argument("--template", default=DEFAULT_TEMPLATE, help=f"template repo, OWNER/REPO (default: {DEFAULT_TEMPLATE})")
    p.add_argument("--no-bootstrap", action="store_true", help="create and clone only; run scripts/bootstrap.sh yourself")
    p.add_argument("--dry-run", action="store_true", help="print the commands instead of running them")
    args, extra = p.parse_known_args(argv)

    try:
        if extra:
            raise Abort(f"unexpected {' '.join(extra)!r}: arguments for bootstrap go after --", 2)
        owner, name = parse_target(args.target)
        if owner and (args.owner or args.local):
            raise Abort(f"{args.target!r} names the owner already: drop --owner / --local", 2)
        owner = owner or args.owner
        if Path(name).exists():
            raise Abort(f"./{name} exists already: choose another name, or run this from another folder")
        if owner is None and not args.local:
            choices = owner_choices(args.visibility)
            if not can_pick():
                raise Abort(no_terminal_message(choices), 2)
            chosen = pick(choices, f"Where should {name} live?")
            if chosen is None:
                raise Abort("cancelled: nothing was created")
            owner = chosen.owner
        bootstrap = None if args.no_bootstrap else bootstrap_args
        steps = plan(owner, name, args.template, args.visibility, bootstrap)
        where_to = (f"./{name}, local only: no GitHub repo, and beads stays on this machine" if owner is None
                    else f"github.com/{owner}/{name} ({args.visibility}), cloned to ./{name}")
        if args.dry_run:
            print(f"{where_to}\nwould run:")
            print("\n".join(f"  {s}" for s in steps))
            return 0
        print(where_to)
        run(steps, owner, name)
    except Abort as e:
        print(f"error: {e}", file=sys.stderr)
        return e.code
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130

    nxt = f"cd {name}" + ("" if bootstrap is not None else
                          f" && bash scripts/bootstrap.sh{' --local-only' if owner is None else ''}")
    print(f"\nDone: {where_to}.\nNext: {nxt}" + (", then the steps bootstrap printed above." if bootstrap is not None else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
