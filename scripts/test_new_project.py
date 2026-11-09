#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Tests for new_project.py: the owner list and its notes, the picker's keys on a real pty, the
commands it plans, and whole runs against a fake `gh` and a throwaway template repo.
Run: uv run scripts/test_new_project.py"""
from __future__ import annotations

import contextlib
import io
import json
import os
import pty
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import new_project as newp  # noqa: E402

# Answers `gh api` from a table and logs every call; `gh repo create` clones the --template URL
# into ./NAME, which is what the real one does with --clone once GitHub has made the repo.
FAKE_GH = r'''#!PYTHON
import json, os, subprocess, sys
args = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a") as f:
    f.write(json.dumps(args) + "\n")
api = {
    "user": {"login": "me"},
    "user/memberships/orgs?state=active&per_page=100": [
        {"organization": {"login": "zeta"}, "role": "admin", "state": "active"},
        {"organization": {"login": "acme"}, "role": "member", "state": "active"},
    ],
    "orgs/acme": {"default_repository_permission": "write", "members_can_create_private_repositories": False},
    "orgs/zeta": {"default_repository_permission": "none", "members_can_create_private_repositories": False},
}
if args[:1] == ["api"]:
    if args[1] not in api:
        sys.exit("gh: Not Found (HTTP 404)")
    print(json.dumps(api[args[1]]))
elif args[:2] == ["repo", "create"]:
    if os.environ.get("FAKE_GH_CREATE_FAILS"):
        sys.exit("GraphQL: Name already exists on this account (createRepository)")
    template = args[args.index("--template") + 1]
    subprocess.run(["git", "clone", "-q", template, args[2].split("/")[1]], check=True)
else:
    sys.exit("fake gh: unexpected " + " ".join(args))
'''

# Records its arguments in the folder it runs in, which is the new project's.
FAKE_BOOTSTRAP = 'printf "%s\\n" "$@" > bootstrap-args.txt\nexit "${FAKE_BOOTSTRAP_EXIT:-0}"\n'


def sh(*cmd: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def make_template(root: Path) -> str:
    tpl = root / "template"
    (tpl / "scripts").mkdir(parents=True)
    (tpl / "scripts" / "bootstrap.sh").write_text(FAKE_BOOTSTRAP, encoding="utf-8")
    (tpl / "README.md").write_text("# bmad-beads-template\n", encoding="utf-8")
    for cmd in (("git", "init", "-q", "-b", "main"), ("git", "add", "-A"),
                ("git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "template")):
        sh(*cmd, cwd=tpl).check_returncode()
    return tpl.as_uri()  # file://, so `git clone --depth 1` really is shallow


class ParseTargetTests(unittest.TestCase):
    def test_name_and_owner_name(self):
        self.assertEqual(newp.parse_target("my-project"), (None, "my-project"))
        self.assertEqual(newp.parse_target("my-org/my.project_2"), ("my-org", "my.project_2"))

    def test_rejects_what_github_would_not_take(self):
        for bad in ("", "a/", "/a", "a/b/c", "has space", "..", "x/."):
            with self.subTest(bad), self.assertRaises(newp.Abort) as cm:
                newp.parse_target(bad)
            self.assertEqual(cm.exception.code, 2)


class ChoicesTests(unittest.TestCase):
    MEMBERSHIPS = [
        {"organization": {"login": "zeta"}, "role": "admin", "state": "active"},
        {"organization": {"login": "Acme"}, "role": "member", "state": "active"},
        {"organization": {"login": "invited"}, "role": "member", "state": "pending"},
        {"organization": {"login": "quiet"}, "role": "member", "state": "active"},
    ]
    ORGS = {
        "Acme": {"default_repository_permission": "write", "members_can_create_private_repositories": False},
        "zeta": {"default_repository_permission": "read", "members_can_create_private_repositories": False},
        # "quiet": details unreadable, so no note beyond what it is
    }

    def choices(self, visibility="private"):
        return newp.build_choices("me", self.MEMBERSHIPS, self.ORGS, visibility)

    def test_order_account_orgs_by_name_then_local(self):
        self.assertEqual([c.owner for c in self.choices()], ["me", "Acme", "quiet", "zeta", None])

    def test_pending_invitation_is_not_a_choice(self):
        self.assertNotIn("invited", [c.owner for c in self.choices()])

    def test_notes(self):
        notes = {c.owner: c.note for c in self.choices()}
        self.assertEqual(notes["me"], "your account")
        self.assertEqual(notes["Acme"], "members can't create private repos here; every org member can push to it")
        # An org owner can create repos whatever the members' setting says.
        self.assertEqual(notes["zeta"], "every org member can read it")
        self.assertEqual(notes["quiet"], "organization")
        self.assertIn("beads stays on this machine", notes[None])

    def test_note_follows_the_visibility_asked_for(self):
        notes = {c.owner: c.note for c in self.choices("public")}
        self.assertEqual(notes["Acme"], "every org member can push to it")

    def test_no_terminal_message_names_a_flag_per_choice(self):
        msg = newp.no_terminal_message(self.choices())
        for flag in ("--owner me", "--owner Acme", "--owner quiet", "--owner zeta", "--local"):
            self.assertIn(flag, msg)


class MoveTests(unittest.TestCase):
    def test_keys(self):
        self.assertEqual(newp.move(0, 3, b"\x1b[B"), (1, None))
        self.assertEqual(newp.move(0, 3, b"\x1bOB"), (1, None))
        self.assertEqual(newp.move(1, 3, b"k"), (0, None))
        self.assertEqual(newp.move(0, 3, b"\x1b[A"), (2, None))  # wraps
        self.assertEqual(newp.move(2, 3, b"j"), (0, None))
        self.assertEqual(newp.move(1, 3, b"\r"), (1, "pick"))
        self.assertEqual(newp.move(1, 3, b"\n"), (1, "pick"))
        self.assertEqual(newp.move(1, 3, b"\x1b"), (1, "cancel"))
        self.assertEqual(newp.move(1, 3, b"q"), (1, "cancel"))
        self.assertEqual(newp.move(1, 3, b"x"), (1, None))
        self.assertEqual(newp.move(1, 3, b"\x1b[1;5C"), (1, None))  # ctrl-right: ignored


class PickerTests(unittest.TestCase):
    """The real termios path, on a pseudo-terminal."""

    CHOICES = [newp.Choice("me", "me", "your account"), newp.Choice("acme", "acme", "organization"), newp.LOCAL_CHOICE]

    def pick_with(self, keys: bytes):
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        # After a pause: the picker flushes whatever was typed before it showed. A picker that
        # misreads the keys would wait forever, so a late `q` turns that hang into a failure.
        for delay, data in ((0.3, keys), (3.0, b"q")):
            timer = threading.Timer(delay, os.write, (master, data))
            timer.start()
            self.addCleanup(timer.cancel)
        out = io.StringIO()
        return newp.pick(self.CHOICES, "Where?", fd=slave, out=out), out.getvalue()

    def test_arrows_then_enter(self):
        chosen, screen = self.pick_with(b"\x1b[B\x1b[B\x1b[A\r")  # three keys in one burst
        self.assertEqual(chosen.owner, "acme")
        self.assertIn("Local only", screen)
        self.assertTrue(screen.endswith("\x1b[?25h"))  # cursor shown again

    def test_up_from_the_top_reaches_local(self):
        chosen, _ = self.pick_with(b"\x1b[A\r")
        self.assertIsNone(chosen.owner)

    def test_escape_cancels(self):
        chosen, _ = self.pick_with(b"\x1b")
        self.assertIsNone(chosen)

    def test_terminal_settings_restored(self):
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        import termios

        def attrs():
            a = termios.tcgetattr(slave)
            # PENDIN is the kernel's own: macOS sets it when a tty goes back to line mode.
            a[3] &= ~getattr(termios, "PENDIN", 0)
            return a

        before = attrs()
        threading.Timer(0.3, os.write, (master, b"q")).start()
        newp.pick(self.CHOICES, "Where?", fd=slave, out=io.StringIO())
        self.assertEqual(attrs(), before)


class PlanTests(unittest.TestCase):
    def lines(self, *args, **kw):
        return [str(s) for s in newp.plan(*args, **kw)]

    def test_github(self):
        self.assertEqual(self.lines("acme", "proj", "o/t", "private", []), [
            "gh repo create acme/proj --template o/t --private --clone",
            "(cd proj && bash scripts/bootstrap.sh)",
        ])

    def test_local(self):
        self.assertEqual(self.lines(None, "proj", "o/t", "private", ["--no-metrics"]), [
            "git clone -q --depth 1 https://github.com/o/t.git proj",
            "(cd proj && rm -rf .git)",
            "(cd proj && git init -q)",
            "(cd proj && bash scripts/bootstrap.sh --local-only --no-metrics)",
        ])

    def test_local_only_not_doubled(self):
        self.assertEqual(self.lines(None, "p", "o/t", "private", ["--local-only"])[-1],
                         "(cd p && bash scripts/bootstrap.sh --local-only)")

    def test_no_bootstrap(self):
        self.assertEqual(self.lines("acme", "proj", "o/t", "public", None),
                         ["gh repo create acme/proj --template o/t --public --clone"])


class RunTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.template = make_template(root)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text(FAKE_GH.replace("PYTHON", sys.executable), encoding="utf-8")
        gh.chmod(0o755)
        self.log = root / "gh.log"
        self.work = root / "work"
        self.work.mkdir()
        env = mock.patch.dict(os.environ, {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                                           "FAKE_GH_LOG": str(self.log)})
        env.start()
        self.addCleanup(env.stop)
        cwd = os.getcwd()
        os.chdir(self.work)
        self.addCleanup(os.chdir, cwd)
        # The tests may run in a terminal; only the ones that say so get a picker.
        tty = mock.patch.object(newp, "can_pick", return_value=False)
        tty.start()
        self.addCleanup(tty.stop)

    def main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = newp.main(["--template", self.template, *argv])
        return code, out.getvalue(), err.getvalue()

    def gh_calls(self):
        return [json.loads(ln) for ln in self.log.read_text().splitlines()] if self.log.exists() else []

    def bootstrap_args(self, name="proj"):
        f = self.work / name / "bootstrap-args.txt"
        return [ln for ln in f.read_text().splitlines() if ln] if f.exists() else None

    def test_owner_in_the_name(self):
        code, out, _ = self.main("acme/proj")
        self.assertEqual(code, 0)
        self.assertEqual(self.gh_calls(), [["repo", "create", "acme/proj", "--template", self.template,
                                            "--private", "--clone"]])  # no lookups: the owner was given
        self.assertTrue((self.work / "proj" / "README.md").is_file())
        self.assertEqual(self.bootstrap_args(), [])
        self.assertIn("Next: cd proj", out)

    def test_owner_flag_and_visibility(self):
        code, _, _ = self.main("proj", "--owner", "acme", "--visibility", "public")
        self.assertEqual(code, 0)
        self.assertEqual(self.gh_calls()[0][2:], ["acme/proj", "--template", self.template, "--public", "--clone"])

    def test_local_has_no_template_history_and_bootstraps_local_only(self):
        code, _, _ = self.main("proj", "--local", "--", "--no-metrics")
        self.assertEqual(code, 0)
        self.assertEqual(self.gh_calls(), [])  # never touches GitHub
        proj = self.work / "proj"
        self.assertTrue((proj / "README.md").is_file())
        self.assertNotEqual(sh("git", "rev-parse", "--verify", "-q", "HEAD", cwd=proj).returncode, 0)  # no commits
        self.assertEqual(sh("git", "remote", cwd=proj).stdout, "")  # no origin
        self.assertEqual(self.bootstrap_args(), ["--local-only", "--no-metrics"])

    def test_no_terminal_lists_owners_and_creates_nothing(self):
        code, _, err = self.main("proj")
        self.assertEqual(code, 2)
        for flag in ("--owner me", "--owner acme", "--owner zeta", "--local"):
            self.assertIn(flag, err)
        self.assertIn("every org member can push to it", err)
        self.assertNotIn(["repo", "create"], [c[:2] for c in self.gh_calls()])
        self.assertFalse((self.work / "proj").exists())

    def test_picked_org(self):
        with mock.patch.object(newp, "can_pick", return_value=True), \
             mock.patch.object(newp, "pick", side_effect=lambda choices, title: choices[1]) as picker:
            code, _, _ = self.main("proj")
        self.assertEqual(code, 0)
        self.assertEqual([c.owner for c in picker.call_args.args[0]], ["me", "acme", "zeta", None])
        self.assertEqual(self.gh_calls()[-1][:3], ["repo", "create", "acme/proj"])

    def test_picked_local(self):
        with mock.patch.object(newp, "can_pick", return_value=True), \
             mock.patch.object(newp, "pick", return_value=newp.LOCAL_CHOICE):
            code, _, _ = self.main("proj")
        self.assertEqual(code, 0)
        self.assertNotIn(["repo", "create"], [c[:2] for c in self.gh_calls()])
        self.assertEqual(self.bootstrap_args(), ["--local-only"])

    def test_cancelled_creates_nothing(self):
        with mock.patch.object(newp, "can_pick", return_value=True), mock.patch.object(newp, "pick", return_value=None):
            code, _, err = self.main("proj")
        self.assertEqual(code, 1)
        self.assertIn("nothing was created", err)
        self.assertFalse((self.work / "proj").exists())

    def test_existing_folder_refused_before_anything(self):
        (self.work / "proj").mkdir()
        code, _, err = self.main("acme/proj")
        self.assertEqual(code, 1)
        self.assertIn("exists already", err)
        self.assertEqual(self.gh_calls(), [])

    def test_dry_run_creates_nothing(self):
        code, out, _ = self.main("acme/proj", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn(f"gh repo create acme/proj --template {self.template} --private --clone", out)
        self.assertIn("(cd proj && bash scripts/bootstrap.sh)", out)
        self.assertEqual(self.gh_calls(), [])
        self.assertFalse((self.work / "proj").exists())

    def test_no_bootstrap(self):
        code, out, _ = self.main("acme/proj", "--no-bootstrap")
        self.assertEqual(code, 0)
        self.assertIsNone(self.bootstrap_args())
        self.assertIn("cd proj && bash scripts/bootstrap.sh", out)

    def test_failed_bootstrap_says_what_is_left(self):
        with mock.patch.dict(os.environ, {"FAKE_BOOTSTRAP_EXIT": "3"}):
            code, _, err = self.main("acme/proj")
        self.assertEqual(code, 1)
        self.assertIn("failed (exit 3)", err)
        self.assertIn("  (cd proj && bash scripts/bootstrap.sh)", err)
        self.assertNotIn("  gh repo create", err)  # that part is done
        self.assertTrue((self.work / "proj").is_dir())

    def test_failed_create_says_not_to_create_again(self):
        with mock.patch.dict(os.environ, {"FAKE_GH_CREATE_FAILS": "1"}):
            code, _, err = self.main("acme/proj")
        self.assertEqual(code, 1)
        self.assertIn("gh repo clone acme/proj", err)
        self.assertFalse((self.work / "proj").exists())

    def test_stray_argument_refused(self):
        for stray in ("extra", "--no-metrics"):  # a bootstrap flag without the -- in front of it
            with self.subTest(stray):
                code, _, err = self.main("proj", "--local", stray)
                self.assertEqual(code, 2)
                self.assertIn("after --", err)
                self.assertFalse((self.work / "proj").exists())

    def test_owner_twice_refused(self):
        code, _, _ = self.main("acme/proj", "--owner", "zeta")
        self.assertEqual(code, 2)
        self.assertEqual(self.gh_calls(), [])

    def test_missing_gh_named_before_anything_runs(self):
        with mock.patch.object(newp.shutil, "which", side_effect=lambda c: None if c == "gh" else "/bin/" + c):
            code, _, err = self.main("acme/proj")
        self.assertEqual(code, 1)
        self.assertIn("missing: gh", err)
        self.assertEqual(self.gh_calls(), [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
