#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Tests for update_from_template.py against a throwaway template repo with two releases.
Run: uv run scripts/test_update_from_template.py"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import update_from_template as uft  # noqa: E402

V1 = {
    "README.md": "# bmad-beads-template\n",
    "AGENTS.md": "# Agents\n\nRule one.\n\nPlanning line.\n\nRule three.\n",
    "Taskfile.yml": "tasks:\n  test:\n    cmds: [old]\n\n  push:\n    cmds: [bd dolt push]\n",
    ".claude/settings.json": json.dumps({"hooks": {"SessionStart": [{"matcher": "", "hooks": [
        {"type": "command", "command": "bd prime --hook-json"}]}]}}, indent=2) + "\n",
    "scripts/bridge.py": "PRIORITY = 2\n\n\ndef run():\n    return 'v1'\n",
    "_bmad/custom/bmad-prd.toml": 'persistent_facts = [\n  "fact a",\n]\n\non_complete = "v1"\n',
    "scripts/untouched.sh": "echo v1\n",
    "scripts/retired.py": "x = 1\n",
    "UPGRADING.md": "# Upgrading\n",
    "CLAUDE.md": "# Project instructions\n",
    ".gitignore": ".venv/\n",
}
V2 = {
    **{k: v for k, v in V1.items() if k != "scripts/retired.py"},
    "AGENTS.md": "# Agents\n\nRule one.\n\nPlanning line. Find steps by label.\n\nRule three.\n",
    "Taskfile.yml": "tasks:\n  test:\n    cmds: [new]\n\n  canary:\n    cmds: [canary]\n\n  push:\n    cmds: [bd dolt push]\n",
    ".claude/settings.json": json.dumps({"permissions": {"allow": ["Bash(bd ready:*)"]}, "hooks": {"SessionStart": [
        {"matcher": "", "hooks": [{"type": "command", "command": "bd prime --hook-json"}]}]}}, indent=2) + "\n",
    "scripts/bridge.py": "PRIORITY = 2\n\n\ndef run():\n    return 'v2'\n",
    "_bmad/custom/bmad-prd.toml": 'persistent_facts = [\n  "fact a",\n]\n\non_complete = "v2"\n',
    "scripts/untouched.sh": "echo v2\n",
    "scripts/canary.py": "print('new')\n",
    "README.md": "# bmad-beads-template\n\nNew template docs.\n",
    "CLAUDE.md": "# Project instructions\n\nNew template text.\n",
    ".gitignore": ".venv/\n.template-update/\n",
    "UPGRADING.md": "# Upgrading\n\n## v0.2.0\n\n- bump bd\n\n## v0.1.0\n\n- first\n",
}


def sh(*cmd: str, cwd: Path) -> str:
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout


def write_tree(root: Path, files: dict[str, str]) -> None:
    for path, text in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text, encoding="utf-8")


def init_repo(root: Path) -> None:
    sh("git", "init", "-q", "-b", "main", cwd=root)
    sh("git", "config", "user.email", "t@example.invalid", cwd=root)
    sh("git", "config", "user.name", "t", cwd=root)


def commit(root: Path, msg: str) -> None:
    sh("git", "add", "-A", cwd=root)
    sh("git", "commit", "-q", "-m", msg, cwd=root)


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        tmp = Path(self.tmp.name)
        self.tmpl, self.proj = tmp / "template", tmp / "project"
        self.tmpl.mkdir()
        self.proj.mkdir()
        init_repo(self.tmpl)
        write_tree(self.tmpl, V1)
        commit(self.tmpl, "v1")
        sh("git", "tag", "v0.1.0", cwd=self.tmpl)
        for path in set(V1) - set(V2):
            (self.tmpl / path).unlink()
        write_tree(self.tmpl, V2)
        commit(self.tmpl, "v2")
        sh("git", "tag", "v0.2.0", cwd=self.tmpl)

        # The project: made from v0.1.0, then customised (and bd reformatted settings.json).
        init_repo(self.proj)
        write_tree(self.proj, V1)
        write_tree(self.proj, {
            "README.md": "# acme\n",
            ".gitignore": ".venv/\n# added by bd init\n.dolt/\n",
            "AGENTS.md": V1["AGENTS.md"].replace("Planning line.", "Planning line. ACME: Jira keys."),
            "Taskfile.yml": V1["Taskfile.yml"] + "\n  dev:\n    cmds: [npm run dev]\n",
            ".claude/settings.json": json.dumps({"hooks": {"SessionStart": [{"hooks": [
                {"command": "bd prime --hook-json", "type": "command"}], "matcher": ""}]},
                "permissions": {"allow": ["Bash(npm test:*)"]}}, indent=2, sort_keys=True),
            "scripts/bridge.py": V1["scripts/bridge.py"].replace("PRIORITY = 2", "PRIORITY = 1  # ACME"),
            "_bmad/custom/bmad-prd.toml": V1["_bmad/custom/bmad-prd.toml"].replace('  "fact a",\n', '  "fact a",\n  "ACME fact",\n'),
        })
        commit(self.proj, "project")
        cwd = Path.cwd()
        os.chdir(self.proj)
        self.addCleanup(os.chdir, cwd)

    def run_update(self, *args: str) -> int:
        self.out = io.StringIO()
        with contextlib.redirect_stdout(self.out), contextlib.redirect_stderr(self.out):
            return uft.main(["--source", str(self.tmpl), "--no-checks", *args])

    def read(self, path: str) -> str:
        return (self.proj / path).read_text(encoding="utf-8")

    def work_dir(self) -> Path:
        return next((self.proj / uft.WORK_DIR).iterdir())

    def test_full_update(self):
        code = self.run_update()
        out = self.out.getvalue()
        self.assertIn("v0.1.0 → v0.2.0", out)
        # untouched → replaced; new → added; removed → kept
        self.assertEqual(self.read("scripts/untouched.sh"), "echo v2\n")
        self.assertEqual(self.read("scripts/canary.py"), "print('new')\n")
        self.assertEqual(self.read("scripts/retired.py"), "x = 1\n")
        self.assertIn("removed upstream, kept", out)
        # customised + changed elsewhere → merged, both sides kept
        self.assertIn("PRIORITY = 1  # ACME", self.read("scripts/bridge.py"))
        self.assertIn("return 'v2'", self.read("scripts/bridge.py"))
        self.assertIn('"ACME fact"', self.read("_bmad/custom/bmad-prd.toml"))
        self.assertIn('on_complete = "v2"', self.read("_bmad/custom/bmad-prd.toml"))
        self.assertIn("dev:", self.read("Taskfile.yml"))
        self.assertIn("canary:", self.read("Taskfile.yml"))
        # project-owned never touched
        self.assertEqual(self.read("README.md"), "# acme\n")
        self.assertEqual(self.read("CLAUDE.md"), "# Project instructions\n")  # even untouched
        self.assertEqual(self.read(uft.VERSION_FILE), "v0.2.0\n")
        # conflict: local file untouched, three versions saved, exit 2
        self.assertEqual(code, 2)
        self.assertIn("ACME: Jira keys.", self.read("AGENTS.md"))
        self.assertNotIn("<<<<<<<", self.read("AGENTS.md"))
        conflicts = self.work_dir() / "conflicts"
        self.assertTrue((conflicts / "AGENTS.md.base").is_file())
        self.assertIn("Find steps by label", (conflicts / "AGENTS.md.template").read_text())
        self.assertIn("ACME", (conflicts / "AGENTS.md.local").read_text())
        self.assertIn("`AGENTS.md`", (self.work_dir() / "CONFLICTS.md").read_text())
        # every changed file backed up
        self.assertIn("ACME", (self.work_dir() / "backup" / "scripts" / "bridge.py").read_text())
        # upgrade notes: only releases after the base
        self.assertIn("bump bd", out)
        self.assertNotIn("- first", out)

    def test_gitignore_union_merged(self):
        # bd init appends to .gitignore; so does the template. Both belong.
        self.run_update()
        self.assertEqual(set(self.read(".gitignore").splitlines()), {".venv/", "# added by bd init", ".dolt/", ".template-update/"})

    def test_second_run_not_blocked_by_its_own_backups(self):
        self.run_update()
        subprocess.run(["git", "checkout", "AGENTS.md"], cwd=self.proj)  # say the conflict is resolved
        (self.proj / ".gitignore").write_text(".venv/\n")  # and the team never ignored the work dir
        sh("git", "add", "-A", "--", ".", ":!" + uft.WORK_DIR, cwd=self.proj)
        sh("git", "commit", "-q", "-m", "update", cwd=self.proj)
        self.assertTrue((self.proj / uft.WORK_DIR).is_dir())
        self.run_update()
        self.assertIn("already up to date", self.out.getvalue())

    def test_undo_restores_exactly(self):
        before = {p: (self.proj / p).read_bytes() for p in sh("git", "ls-files", cwd=self.proj).split()}
        (self.proj / "notes.txt").write_text("mine, untracked\n")  # must survive the undo
        self.run_update("--allow-dirty")
        (self.proj / "AGENTS.md").write_text("resolved by hand\n")  # /update-template resolves the conflict
        sh("bash", str(self.work_dir() / "undo.sh"), cwd=self.proj)
        self.assertEqual({p: (self.proj / p).read_bytes() for p in before}, before)
        self.assertFalse((self.proj / "scripts" / "canary.py").exists())
        self.assertFalse((self.proj / uft.VERSION_FILE).exists())
        self.assertEqual(self.read("notes.txt"), "mine, untracked\n")

    def test_report_written(self):
        self.run_update()
        report = (self.work_dir() / "REPORT.md").read_text()
        self.assertIn("v0.1.0 → v0.2.0", report)
        self.assertIn("removed upstream, kept", report)
        self.assertIn("bump bd", report)
        self.assertIn("undo.sh", report)

    def test_non_tag_ref_recorded_as_commit(self):
        self.run_update("--ref", "main")
        sha = sh("git", "rev-parse", "main", cwd=self.tmpl).strip()
        self.assertEqual(self.read(uft.VERSION_FILE).strip(), sha)

    def test_check_flags_broken_files(self):
        (self.proj / "bad.json").write_text('{"a": 1, "a": 2}')
        self.assertEqual(self.run_update("--check", "bad.json"), 1)
        self.assertEqual(self.run_update("--check", ".claude/settings.json"), 0)

    def test_settings_json_merged_structurally(self):
        # A line merge of this file exits 0 but produces two `permissions` keys.
        self.run_update()
        data = json.loads(self.read(".claude/settings.json"), object_pairs_hook=uft._no_dupes)
        self.assertEqual(sorted(data["permissions"]["allow"]), ["Bash(bd ready:*)", "Bash(npm test:*)"])
        self.assertEqual(len(data["hooks"]["SessionStart"]), 1)

    def test_line_merge_of_json_is_caught(self):
        base, local, new = (V1[".claude/settings.json"].encode(), self.read(".claude/settings.json").encode(),
                            V2[".claude/settings.json"].encode())
        merged, clean = uft.merge_text(base, local, new)
        if clean:  # git calls it clean; validate() must not
            self.assertIsNotNone(uft.validate(".claude/settings.json", merged))

    def test_ignored_and_skipped_left_alone(self):
        (self.proj / uft.IGNORE_FILE).write_text("# ours\nscripts/untouched.sh\n")
        commit(self.proj, "ignore")
        self.run_update("--skip", "Taskfile.yml")
        self.assertEqual(self.read("scripts/untouched.sh"), "echo v1\n")
        self.assertNotIn("canary:", self.read("Taskfile.yml"))
        self.assertIn("changed upstream (review by hand)", self.out.getvalue())

    def test_dirty_tree_refused(self):
        (self.proj / "AGENTS.md").write_text("dirty\n")
        self.assertEqual(self.run_update(), 1)
        self.assertIn("uncommitted changes", self.out.getvalue())
        self.assertFalse((self.proj / "scripts" / "canary.py").exists())

    def test_dry_run_writes_nothing(self):
        before = sh("git", "status", "--porcelain", "--untracked-files=all", cwd=self.proj)
        self.assertEqual(self.run_update("--dry-run"), 0)
        self.assertEqual(sh("git", "status", "--porcelain", "--untracked-files=all", cwd=self.proj), before)
        self.assertIn("CONFLICT", self.out.getvalue())

    def test_version_file_wins_over_guessing(self):
        (self.proj / uft.VERSION_FILE).write_text("v0.2.0\n")
        commit(self.proj, "pin")
        self.run_update()
        self.assertIn("already up to date", self.out.getvalue())

    def test_second_run_is_a_noop(self):
        self.run_update()
        commit(self.proj, "update")
        self.run_update()
        self.assertIn("already up to date", self.out.getvalue())


class JsonMergeTests(unittest.TestCase):
    def test_list_union_with_removals(self):
        v = uft.merge_json_value(["a", "b"], ["a", "b", "mine"], ["a", "c"])
        self.assertEqual(v, ["a", "mine", "c"])

    def test_scalar_conflict(self):
        self.assertIs(uft.merge_json_value({"k": 1}, {"k": 2}, {"k": 3}), uft.CONFLICT)

    def test_local_key_deletion_respected(self):
        self.assertEqual(uft.merge_json_value({"a": 1, "b": 1}, {"a": 1}, {"a": 1, "b": 1, "c": 1}), {"a": 1, "c": 1})


if __name__ == "__main__":
    unittest.main(verbosity=1)
