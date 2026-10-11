"""Tests for badge_id.py -- the opaque per-repo ID scheme shared by the
other three scripts."""

from __future__ import annotations

from pathlib import Path

import badge_id


def test_generate_id_matches_the_published_pattern() -> None:
    generated = {badge_id.generate_id() for _ in range(50)}

    assert all(badge_id.ID_PATTERN.match(g) for g in generated)
    # secrets.token_hex(6) -- 12 lowercase hex chars, not derived from anything.
    assert all(len(g) == 12 for g in generated)


def test_generate_id_is_not_deterministic() -> None:
    first = badge_id.generate_id()
    second = badge_id.generate_id()

    assert first != second


def test_read_id_from_dir_returns_none_when_file_missing(tmp_path: Path) -> None:
    assert badge_id.read_id_from_dir(str(tmp_path)) is None


def test_read_id_from_dir_returns_none_for_malformed_content(tmp_path: Path) -> None:
    id_file = tmp_path / ".github" / "badge-id"
    id_file.parent.mkdir(parents=True)
    id_file.write_text("not-a-valid-id\n")

    assert badge_id.read_id_from_dir(str(tmp_path)) is None


def test_read_id_from_dir_returns_the_valid_id(tmp_path: Path) -> None:
    id_file = tmp_path / ".github" / "badge-id"
    id_file.parent.mkdir(parents=True)
    id_file.write_text("0123456789ab\n")

    assert badge_id.read_id_from_dir(str(tmp_path)) == "0123456789ab"


def test_read_id_from_dir_strips_whitespace(tmp_path: Path) -> None:
    id_file = tmp_path / ".github" / "badge-id"
    id_file.parent.mkdir(parents=True)
    id_file.write_text("  0123456789ab  \n")

    assert badge_id.read_id_from_dir(str(tmp_path)) == "0123456789ab"


def test_write_id_to_dir_creates_parent_dirs(tmp_path: Path) -> None:
    badge_id.write_id_to_dir(str(tmp_path), "0123456789ab")

    written = tmp_path / ".github" / "badge-id"
    assert written.read_text() == "0123456789ab\n"


def test_write_then_read_roundtrips(tmp_path: Path) -> None:
    new_id = badge_id.generate_id()
    badge_id.write_id_to_dir(str(tmp_path), new_id)

    assert badge_id.read_id_from_dir(str(tmp_path)) == new_id
