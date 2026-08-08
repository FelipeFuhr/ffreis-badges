"""Tests for gen_manifest.py — license-tier detection and fleet-roster generation."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import gen_manifest
import pytest


@pytest.mark.parametrize(
    ("license_head", "expected_tier"),
    [
        ("                    GNU AFFERO GENERAL PUBLIC LICENSE\n", "AGPL-3.0"),
        ("MIT License\n\nCopyright (c) 2026\n", "MIT"),
        ("                                 Apache License\n", "Apache-2.0"),
        ("All Rights Reserved.\n", "Proprietary"),
        ("Some bespoke license text nobody recognizes.\n", "other"),
    ],
)
def test_license_tier_detects_known_tiers(
    tmp_path: Path, license_head: str, expected_tier: str
) -> None:
    (tmp_path / "LICENSE").write_text(license_head)

    assert gen_manifest.license_tier(str(tmp_path)) == expected_tier


def test_license_tier_returns_none_when_no_license_file(tmp_path: Path) -> None:
    assert gen_manifest.license_tier(str(tmp_path)) == "none"


def test_remote_name_strips_dot_git_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "check_output",
        lambda *a, **k: "git@github.com:FelipeFuhr/ffreis-badges.git\n",
    )

    assert gen_manifest.remote_name("/some/repo") == "ffreis-badges"


def test_remote_name_handles_url_without_dot_git(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "check_output",
        lambda *a, **k: "https://github.com/FelipeFuhr/ffreis-badges\n",
    )

    assert gen_manifest.remote_name("/some/repo") == "ffreis-badges"


def test_remote_name_returns_none_when_git_command_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(*a: object, **k: object) -> str:
        raise subprocess.CalledProcessError(1, "git")

    monkeypatch.setattr(subprocess, "check_output", _raise)

    assert gen_manifest.remote_name("/some/repo") is None


def test_remote_name_returns_none_for_empty_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **k: "\n")

    assert gen_manifest.remote_name("/some/repo") is None


def test_iter_repos_finds_top_level_repo_and_skips_its_internals(tmp_path: Path) -> None:
    repo = tmp_path / "my-repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "src").mkdir()
    (repo / "src" / ".git").mkdir()  # a vendored/nested repo copy — must not surface separately

    found = list(gen_manifest.iter_repos(str(tmp_path)))

    assert found == [str(repo)]


def test_iter_repos_skips_orphaned_and_worktree_dirs(tmp_path: Path) -> None:
    for skip_dir in ("old", "_orphaned", ".worktrees"):
        nested = tmp_path / skip_dir / "some-repo"
        (nested / ".git").mkdir(parents=True)

    real_repo = tmp_path / "real-repo"
    (real_repo / ".git").mkdir(parents=True)

    found = list(gen_manifest.iter_repos(str(tmp_path)))

    assert found == [str(real_repo)]


def test_main_writes_manifest_for_known_repos_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path / "workspace"
    known_repo = workspace / "known-repo"
    unknown_repo = (
        workspace / "unknown-repo"
    )  # has a remote, but gh doesn't know it (fork/archived)
    for repo_dir in (known_repo, unknown_repo):
        (repo_dir / ".git").mkdir(parents=True)

    def _fake_check_output(cmd: list[str], **kwargs: object) -> str:
        repo_dir = cmd[cmd.index("-C") + 1]
        if repo_dir == str(known_repo):
            return "git@github.com:FelipeFuhr/known-repo.git\n"
        return "git@github.com:someoneelse/unknown-repo.git\n"

    monkeypatch.setattr(subprocess, "check_output", _fake_check_output)

    (known_repo / "LICENSE").write_text("MIT License\n")

    gh_repos = tmp_path / "repos.json"
    gh_repos.write_text(
        json.dumps(
            [
                {
                    "name": "known-repo",
                    "visibility": "PUBLIC",
                    "defaultBranchRef": {"name": "main"},
                    "isArchived": False,
                },
                {
                    "name": "archived-repo",
                    "visibility": "PUBLIC",
                    "isArchived": True,
                },
            ]
        )
    )

    monkeypatch.setattr("sys.argv", ["gen_manifest.py", str(workspace), str(gh_repos)])

    exit_code = gen_manifest.main()
    manifest = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert manifest["owner"] == "FelipeFuhr"
    names = [r["name"] for r in manifest["repos"]]
    assert names == ["known-repo"]  # unknown-repo has no gh entry, archived-repo has no dir
    assert manifest["repos"][0]["license"] == "MIT"
    assert manifest["repos"][0]["visibility"] == "public"
