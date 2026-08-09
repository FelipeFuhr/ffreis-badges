"""Tests for render_block.render() — the curated badge-block templating logic."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import render_block


def _touch(badges_dir: Path, repo: str, metric: str) -> None:
    outdir = badges_dir / repo
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / f"{metric}.json").write_text("{}")


def test_render_emits_only_badges_with_existing_endpoint_files(tmp_path: Path) -> None:
    badges_dir = tmp_path / "badges"
    _touch(badges_dir, "my-repo", "ci")

    block = render_block.render("my-repo", "main", badges_dir=str(badges_dir))

    assert block.startswith(render_block.START)
    assert block.endswith(render_block.END)
    assert "CI" in block
    assert "version" not in block.lower()
    assert "license" not in block.lower()


def test_render_emits_all_three_in_fixed_order(tmp_path: Path) -> None:
    badges_dir = tmp_path / "badges"
    for metric in ("license", "ci", "version"):  # deliberately out of ORDER
        _touch(badges_dir, "my-repo", metric)

    block = render_block.render("my-repo", "main", badges_dir=str(badges_dir))
    lines = block.splitlines()
    body = lines[1]

    # ORDER is ci, version, license — assert that relative ordering held even
    # though the endpoint files were created license/ci/version.
    assert body.index("CI") < body.index("version") < body.index("license")


def test_render_links_use_requested_default_branch(tmp_path: Path) -> None:
    badges_dir = tmp_path / "badges"
    _touch(badges_dir, "my-repo", "license")

    block = render_block.render("my-repo", "develop", badges_dir=str(badges_dir))

    assert "/blob/develop/LICENSE" in block


def test_render_with_no_endpoint_files_emits_only_markers(tmp_path: Path) -> None:
    badges_dir = tmp_path / "badges"
    badges_dir.mkdir()

    block = render_block.render("unreleased-repo", "main", badges_dir=str(badges_dir))

    assert block == f"{render_block.START}\n\n{render_block.END}"


def test_main_prints_rendered_block(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    badges_dir = tmp_path / "badges"
    _touch(badges_dir, "my-repo", "ci")
    monkeypatch.chdir(tmp_path)

    argv = ["render_block.py", "my-repo", "--badges-dir", str(badges_dir)]
    monkeypatch.setattr(sys, "argv", argv)

    exit_code = render_block.main()

    out = capsys.readouterr().out
    assert exit_code == 0
    assert render_block.START in out
    assert "CI" in out


def test_cli_smoke_via_subprocess(tmp_path: Path) -> None:
    """One end-to-end smoke test through the real CLI entry point."""
    badges_dir = tmp_path / "badges"
    _touch(badges_dir, "my-repo", "ci")
    script = Path(__file__).resolve().parent.parent / "scripts" / "render_block.py"

    result = subprocess.run(
        [sys.executable, str(script), "my-repo", "--badges-dir", str(badges_dir)],
        capture_output=True,
        text=True,
        check=True,
    )

    assert render_block.START in result.stdout
    # sanity: output is markdown, not JSON.
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stdout)
