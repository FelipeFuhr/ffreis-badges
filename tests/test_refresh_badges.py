"""Tests for refresh_badges.py — shields.io endpoint generation from GitHub API data."""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from typing import Any

import badge_id
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


# -- opaque badge-id resolution ----------------------------------------------


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def test_get_badge_id_returns_none_on_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(refresh_badges, "gh", lambda *_a, **_k: None)

    assert refresh_badges.get_badge_id("o", "r", "") is None


def test_get_badge_id_decodes_and_validates_content(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(refresh_badges, "gh", lambda *_a, **_k: {"content": _b64("0123456789ab\n")})

    assert refresh_badges.get_badge_id("o", "r", "") == "0123456789ab"


def test_get_badge_id_returns_none_for_malformed_content(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(refresh_badges, "gh", lambda *_a, **_k: {"content": _b64("not-an-id")})

    assert refresh_badges.get_badge_id("o", "r", "") is None


def test_provision_badge_id_returns_new_id_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def _fake_urlopen(req: urllib.request.Request, timeout: int = 30) -> _FakeResponse:
        captured["method"] = req.get_method()
        captured["url"] = req.full_url
        return _FakeResponse({"content": {}})

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    monkeypatch.setattr(badge_id, "generate_id", lambda: "0123456789ab")

    new_id = refresh_badges.provision_badge_id("o", "r", "token")

    assert new_id == "0123456789ab"
    assert captured["method"] == "PUT"
    assert captured["url"].endswith("/repos/o/r/contents/.github/badge-id")


@pytest.mark.parametrize("status", [403, 404, 422])
def test_provision_badge_id_returns_none_when_write_not_possible(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    def _raise(*_a: object, **_k: object) -> None:
        raise urllib.error.HTTPError("url", status, "nope", Message(), None)

    monkeypatch.setattr(urllib.request, "urlopen", _raise)

    assert refresh_badges.provision_badge_id("o", "r", "token") is None


def test_provision_badge_id_reraises_unexpected_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_500(*_a: object, **_k: object) -> None:
        raise urllib.error.HTTPError("url", 500, "server error", Message(), None)

    monkeypatch.setattr(urllib.request, "urlopen", _raise_500)

    with pytest.raises(urllib.error.HTTPError):
        refresh_badges.provision_badge_id("o", "r", "token")


def test_resolve_badge_id_prefers_an_existing_id_over_provisioning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(refresh_badges, "get_badge_id", lambda *a, **k: "existing-id-")
    monkeypatch.setattr(
        refresh_badges,
        "provision_badge_id",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not provision")),
    )

    assert refresh_badges.resolve_badge_id("o", "r", "", provision=True) == "existing-id-"


def test_resolve_badge_id_does_not_provision_when_provision_is_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(refresh_badges, "get_badge_id", lambda *a, **k: None)
    monkeypatch.setattr(
        refresh_badges,
        "provision_badge_id",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not provision")),
    )

    assert refresh_badges.resolve_badge_id("o", "r", "", provision=False) is None


def test_resolve_badge_id_provisions_when_missing_and_provision_is_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(refresh_badges, "get_badge_id", lambda *a, **k: None)
    monkeypatch.setattr(refresh_badges, "provision_badge_id", lambda *a, **k: "new-id-value")

    assert refresh_badges.resolve_badge_id("o", "r", "", provision=True) == "new-id-value"


# -- main(): legacy name-keyed + new id-keyed dual write ---------------------


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
    monkeypatch.setattr(refresh_badges, "resolve_badge_id", lambda *a, **k: "abc123abc123")
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
    # the new index is id-keyed only, has exactly ok-repo's entry (broken-repo
    # errored out before ever reaching id resolution) — no name, no visibility.
    assert index["repos"] == [
        {"id": "abc123abc123", "ci": "success", "version": "-", "license": "none"}
    ]
    # legacy name-keyed file still written for the transition period.
    assert (out_dir / "ok-repo" / "ci.json").is_file()


def test_main_writes_both_legacy_name_keyed_and_new_id_keyed_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
                        "license": "MIT",
                    }
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
    monkeypatch.setattr(refresh_badges, "resolve_badge_id", lambda *a, **k: "0123456789ab")
    monkeypatch.setattr(
        "sys.argv", ["refresh_badges.py", "--manifest", str(manifest_path), "--out", str(out_dir)]
    )

    refresh_badges.main()

    assert json.loads((out_dir / "a" / "ci.json").read_text())["message"] == "success"
    assert json.loads((out_dir / "0123456789ab" / "ci.json").read_text())["message"] == "success"


def test_main_omits_repo_from_index_when_id_cannot_be_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "owner": "FelipeFuhr",
                "repos": [
                    {
                        "name": "no-write-access-repo",
                        "visibility": "private",
                        "default_branch": "main",
                        "license": "none",
                    }
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
    monkeypatch.setattr(refresh_badges, "resolve_badge_id", lambda *a, **k: None)
    monkeypatch.setattr(
        "sys.argv", ["refresh_badges.py", "--manifest", str(manifest_path), "--out", str(out_dir)]
    )

    refresh_badges.main()
    stderr = capsys.readouterr().err

    index = json.loads((out_dir / "index.json").read_text())
    assert index["repos"] == []  # never flooded with a nameless/idless placeholder
    assert (out_dir / "no-write-access-repo" / "ci.json").is_file()  # legacy write unaffected
    assert "no badge-id file and could not provision one" in stderr


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
    monkeypatch.setattr(refresh_badges, "resolve_badge_id", lambda *a, **k: "aaaaaaaaaaaa")
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

    assert [r["id"] for r in index["repos"]] == ["aaaaaaaaaaaa"]
    assert (out_dir / "a").exists()
    assert not (out_dir / "b").exists()


def test_main_defaults_to_not_provisioning_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A local, ad-hoc run (no --provision-ids) must stay read-only against
    every OTHER repo — it must never silently start writing .github/badge-id
    files across the fleet just because someone ran this to preview output."""
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
                    }
                ],
            }
        )
    )
    out_dir = tmp_path / "badges"
    captured_provision: dict[str, Any] = {}

    def _fake_resolve(owner: str, name: str, token: str, *, provision: bool) -> str | None:
        captured_provision["provision"] = provision
        return None

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
    monkeypatch.setattr(refresh_badges, "resolve_badge_id", _fake_resolve)
    monkeypatch.setattr(
        "sys.argv", ["refresh_badges.py", "--manifest", str(manifest_path), "--out", str(out_dir)]
    )

    refresh_badges.main()

    assert captured_provision["provision"] is False
