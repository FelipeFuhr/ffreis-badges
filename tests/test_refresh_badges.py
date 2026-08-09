"""Tests for refresh_badges.py — shields.io endpoint generation from GitHub API data."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from typing import Any

import pytest
import refresh_badges


class _FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:  # pragma: no cover - json.load uses .read() internally
        return json.dumps(self._payload).encode("utf-8")


def test_gh_returns_none_on_404(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_404(*a: object, **k: object) -> None:
        raise urllib.error.HTTPError("url", 404, "not found", Message(), None)

    monkeypatch.setattr(urllib.request, "urlopen", _raise_404)

    assert refresh_badges.gh("/repos/x/y", "") is None


def test_gh_retries_on_rate_limit_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def _flaky(*a: object, **k: object) -> _FakeResponse:
        calls["n"] += 1
        if calls["n"] < 2:
            raise urllib.error.HTTPError("url", 403, "rate limited", Message(), None)
        return _FakeResponse({"ok": True})

    monkeypatch.setattr(urllib.request, "urlopen", _flaky)
    monkeypatch.setattr(time, "sleep", lambda *_a: None)

    assert refresh_badges.gh("/repos/x/y", "token") == {"ok": True}
    assert calls["n"] == 2


def test_gh_reraises_non_rate_limit_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_500(*a: object, **k: object) -> None:
        raise urllib.error.HTTPError("url", 500, "server error", Message(), None)

    monkeypatch.setattr(urllib.request, "urlopen", _raise_500)

    with pytest.raises(urllib.error.HTTPError):
        refresh_badges.gh("/repos/x/y", "")


def test_detect_ci_workflow_prefers_override(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_gh(path: str, token: str) -> dict[str, Any]:
        if "workflows?" in path:
            return {"workflows": [{"path": ".github/workflows/custom.yml"}]}
        if "custom.yml/runs" in path:
            return {"workflow_runs": [{"conclusion": "success"}]}
        return {"workflow_runs": []}

    monkeypatch.setattr(refresh_badges, "gh", _fake_gh)

    wf, run = refresh_badges.detect_ci_workflow("o", "r", "main", "", override="custom.yml")

    assert wf == "custom.yml"
    assert run == {"conclusion": "success"}


def test_detect_ci_workflow_falls_back_to_priority_list(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_gh(path: str, token: str) -> dict[str, Any]:
        if "workflows?" in path:
            return {"workflows": [{"path": ".github/workflows/ci.yml"}]}
        if "/ci.yml/runs" in path:
            return {"workflow_runs": [{"conclusion": "failure"}]}
        return {"workflow_runs": []}

    monkeypatch.setattr(refresh_badges, "gh", _fake_gh)

    wf, run = refresh_badges.detect_ci_workflow("o", "r", "main", "", override=None)

    assert wf == "ci.yml"
    assert run is not None
    assert run["conclusion"] == "failure"


def test_detect_ci_workflow_returns_none_when_nothing_has_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(refresh_badges, "gh", lambda *_a, **_k: {"workflows": []})

    wf, run = refresh_badges.detect_ci_workflow("o", "r", "main", "", override=None)

    assert wf is None
    assert run is None


def test_ci_badge_no_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(refresh_badges, "detect_ci_workflow", lambda *a, **k: (None, None))

    badge = refresh_badges.ci_badge("o", "r", "main", "", None)

    assert badge == {"schemaVersion": 1, "label": "CI", "message": "no runs", "color": "lightgrey"}


def test_ci_badge_success_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        refresh_badges,
        "detect_ci_workflow",
        lambda *a, **k: ("ci.yml", {"conclusion": "success", "status": "completed"}),
    )

    badge = refresh_badges.ci_badge("o", "r", "main", "", None)

    assert badge["message"] == "success"
    assert badge["color"] == "brightgreen"


def test_ci_badge_in_progress_run_reports_running(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        refresh_badges,
        "detect_ci_workflow",
        lambda *a, **k: ("ci.yml", {"conclusion": None, "status": "in_progress"}),
    )

    badge = refresh_badges.ci_badge("o", "r", "main", "", None)

    assert badge["message"] == "running"


def test_version_badge_prefers_latest_release(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(refresh_badges, "gh", lambda path, token: {"tag_name": "v1.2.3"})

    badge = refresh_badges.version_badge("o", "r", "")

    assert badge == {"schemaVersion": 1, "label": "version", "message": "v1.2.3", "color": "blue"}


def test_version_badge_falls_back_to_latest_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_gh(path: str, token: str) -> Any:
        if "releases/latest" in path:
            return None
        return [{"name": "v0.9.0"}]

    monkeypatch.setattr(refresh_badges, "gh", _fake_gh)

    badge = refresh_badges.version_badge("o", "r", "")

    assert badge is not None
    assert badge["message"] == "v0.9.0"


def test_version_badge_omitted_when_unreleased(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(refresh_badges, "gh", lambda path, token: None)

    assert refresh_badges.version_badge("o", "r", "") is None


@pytest.mark.parametrize(
    ("tier", "expected_label"),
    [
        ("AGPL-3.0", "AGPL v3"),
        ("MIT", "MIT"),
        ("Apache-2.0", "Apache 2.0"),
        ("Proprietary", "Proprietary"),
        ("other", "see LICENSE"),
        ("something-unrecognized", "see LICENSE"),
    ],
)
def test_license_badge_maps_known_and_unknown_tiers(tier: str, expected_label: str) -> None:
    badge = refresh_badges.license_badge(tier)

    assert badge is not None
    assert badge["message"] == expected_label


def test_license_badge_omitted_when_no_license(tmp_path: Path) -> None:
    assert refresh_badges.license_badge("none") is None


def test_write_creates_parent_dirs_and_trailing_newline(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "ci.json"

    refresh_badges.write(str(target), {"schemaVersion": 1})

    assert target.read_text().endswith("\n")
    assert json.loads(target.read_text()) == {"schemaVersion": 1}


def test_main_continues_past_a_single_repo_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "owner": "FelipeFuhr",
                "repos": [
                    {
                        "name": "broken-repo",
                        "visibility": "public",
                        "default_branch": "main",
                        "license": "MIT",
                    },
                    {
                        "name": "ok-repo",
                        "visibility": "public",
                        "default_branch": "main",
                        "license": "none",
                    },
                ],
            }
        )
    )
    out_dir = tmp_path / "badges"

    def _fake_ci_badge(
        owner: str, name: str, branch: str, token: str, override: object
    ) -> dict[str, Any]:
        if name == "broken-repo":
            raise RuntimeError("simulated API failure")
        return {"schemaVersion": 1, "label": "CI", "message": "success", "color": "brightgreen"}

    monkeypatch.setattr(refresh_badges, "ci_badge", _fake_ci_badge)
    monkeypatch.setattr(refresh_badges, "version_badge", lambda *a, **k: None)
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    monkeypatch.setattr(
        "sys.argv",
        ["refresh_badges.py", "--manifest", str(manifest_path), "--out", str(out_dir)],
    )

    exit_code = refresh_badges.main()
    stderr = capsys.readouterr().err

    assert exit_code == 0
    assert "ERROR broken-repo" in stderr
    assert not (out_dir / "broken-repo").exists()
    index = json.loads((out_dir / "index.json").read_text())
    assert [r["name"] for r in index["repos"]] == ["ok-repo"]


def test_main_only_filter_restricts_to_named_repos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "owner": "FelipeFuhr",
                "repos": [
                    {
                        "name": "a",
                        "visibility": "public",
                        "default_branch": "main",
                        "license": "none",
                    },
                    {
                        "name": "b",
                        "visibility": "public",
                        "default_branch": "main",
                        "license": "none",
                    },
                ],
            }
        )
    )
    out_dir = tmp_path / "badges"

    monkeypatch.setattr(
        refresh_badges,
        "ci_badge",
        lambda *a, **k: {
            "schemaVersion": 1,
            "label": "CI",
            "message": "success",
            "color": "brightgreen",
        },
    )
    monkeypatch.setattr(refresh_badges, "version_badge", lambda *a, **k: None)
    monkeypatch.setattr(
        "sys.argv",
        [
            "refresh_badges.py",
            "--manifest",
            str(manifest_path),
            "--out",
            str(out_dir),
            "--only",
            "a",
        ],
    )

    refresh_badges.main()
    index = json.loads((out_dir / "index.json").read_text())

    assert [r["name"] for r in index["repos"]] == ["a"]
