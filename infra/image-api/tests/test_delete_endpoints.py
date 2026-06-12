"""End-to-end tests for the deletion side of the contract (2026-06-11).

Ownership-based cleanup, no retention timers: the orchestrator deletes each staging
file the moment its /media copy is persisted, and wipe-all empties the whole staging
dir. These drive the real DELETE routes through the TestClient against the tmp staging
dir the conftest wires up (config.COMFY_OUTPUT_DIR). No ComfyUI involved - core ComfyUI
has no delete API, which is exactly why these routes touch the filesystem.
"""

import os
from pathlib import Path

from fastapi.testclient import TestClient

from app import config
from app.main import app

client = TestClient(app)

PNG_BYTES = b"\x89PNG\r\n\x1a\n-fake-png-body-"


def _plant(root: Path, *parts: str) -> Path:
    """Drop a fake png at root/parts..., creating subfolders like ComfyUI would."""
    target = root.joinpath(*parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(PNG_BYTES)
    return target


# --- DELETE /image/file ------------------------------------------------------------


def test_delete_existing_file_returns_true_and_only_removes_that_file(output_dir):
    victim = _plant(output_dir, "gamentic_00001_.png")
    bystander = _plant(output_dir, "gamentic_00002_.png")

    resp = client.delete("/image/file", params={"filename": "gamentic_00001_.png"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": True}
    assert not victim.exists()
    assert bystander.exists()  # deletion is surgical, never a sweep


def test_delete_addresses_subfolder_exactly_like_the_get(output_dir):
    victim = _plant(output_dir, "g1", "scene_00001_.png")

    resp = client.delete(
        "/image/file",
        params={"filename": "scene_00001_.png", "subfolder": "g1", "type": "output"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": True}
    assert not victim.exists()
    # The directory structure ComfyUI expects stays intact, only the file dies.
    assert (output_dir / "g1").is_dir()


def test_delete_missing_file_is_false_not_500(output_dir):
    resp = client.delete("/image/file", params={"filename": "never-rendered.png"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": False}


def test_delete_is_idempotent(output_dir):
    _plant(output_dir, "once.png")
    first = client.delete("/image/file", params={"filename": "once.png"})
    second = client.delete("/image/file", params={"filename": "once.png"})
    assert first.json() == {"deleted": True}
    assert second.status_code == 200
    assert second.json() == {"deleted": False}  # a retried delete is a non-event


def test_delete_traversal_filename_is_400_and_target_survives(output_dir, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("not yours")
    escape = os.path.relpath(secret, output_dir)  # ../../...-style climb out
    assert escape.startswith("..")

    resp = client.delete("/image/file", params={"filename": escape})
    assert resp.status_code == 400, resp.text
    assert secret.exists()


def test_delete_traversal_subfolder_is_400(output_dir):
    resp = client.delete(
        "/image/file", params={"filename": "x.png", "subfolder": "../.."}
    )
    assert resp.status_code == 400


def test_delete_absolute_path_is_400(output_dir, tmp_path):
    secret = tmp_path / "absolute-secret.txt"
    secret.write_text("not yours either")

    resp = client.delete("/image/file", params={"filename": str(secret)})
    assert resp.status_code == 400, resp.text
    assert secret.exists()


def test_delete_empty_filename_is_400(output_dir):
    resp = client.delete("/image/file", params={"filename": ""})
    assert resp.status_code == 400


def test_delete_null_byte_filename_is_400(output_dir):
    # %00 reaches pathlib as an embedded null; resolve() raises ValueError, which must
    # surface as a 400 reject, not an unhandled 500.
    resp = client.delete("/image/file", params={"filename": "a\x00b.png"})
    assert resp.status_code == 400


def test_delete_symlink_escaping_the_root_is_400_and_target_survives(output_dir, tmp_path):
    # A symlink planted inside the staging dir pointing outside: the RESOLVED path is
    # what gets containment-checked, so the delete must refuse to follow it out.
    secret = tmp_path / "linked-secret.txt"
    secret.write_text("still not yours")
    link = output_dir / "sneaky.png"
    link.symlink_to(secret)

    resp = client.delete("/image/file", params={"filename": "sneaky.png"})
    assert resp.status_code == 400, resp.text
    assert secret.exists()


def test_delete_non_output_type_is_400(output_dir):
    # Only the staging (output) dir is mounted into the adapter; temp/input belong to
    # the ComfyUI container.
    resp = client.delete(
        "/image/file", params={"filename": "x.png", "type": "temp"}
    )
    assert resp.status_code == 400


def test_delete_directory_target_is_false_and_dir_survives(output_dir):
    _plant(output_dir, "g2", "keep.png")

    resp = client.delete("/image/file", params={"filename": "g2"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": False}
    assert (output_dir / "g2" / "keep.png").exists()


# --- DELETE /image/files (wipe-all) --------------------------------------------------


def test_purge_without_confirm_is_400_and_nothing_deleted(output_dir):
    survivor = _plant(output_dir, "still-here.png")

    resp = client.delete("/image/files")
    assert resp.status_code == 400
    assert survivor.exists()


def test_purge_with_wrong_confirm_is_400(output_dir):
    survivor = _plant(output_dir, "still-here.png")

    resp = client.delete("/image/files", params={"confirm": "ALL"})
    assert resp.status_code == 400  # the exact lowercase token, nothing fuzzy
    assert survivor.exists()


def test_purge_with_confirm_empties_subfolders_but_keeps_the_tree(output_dir):
    _plant(output_dir, "top.png")
    _plant(output_dir, "g1", "a.png")
    _plant(output_dir, "g1", "deep", "b.png")

    resp = client.delete("/image/files", params={"confirm": "all"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": 3}
    # Every file gone, every directory ComfyUI made still standing.
    assert not any(p.is_file() for p in output_dir.rglob("*"))
    assert (output_dir / "g1").is_dir()
    assert (output_dir / "g1" / "deep").is_dir()


def test_purge_twice_second_pass_counts_zero(output_dir):
    _plant(output_dir, "once.png")
    first = client.delete("/image/files", params={"confirm": "all"})
    second = client.delete("/image/files", params={"confirm": "all"})
    assert first.json() == {"deleted": 1}
    assert second.status_code == 200
    assert second.json() == {"deleted": 0}


def test_missing_staging_mount_degrades_never_500s(monkeypatch, tmp_path):
    # The default /comfy/output only exists inside the container; a dev box without the
    # mount must get polite no-ops, because a game delete may never fail on media.
    monkeypatch.setattr(config, "COMFY_OUTPUT_DIR", tmp_path / "not-mounted")

    single = client.delete("/image/file", params={"filename": "x.png"})
    assert single.status_code == 200
    assert single.json() == {"deleted": False}

    purge = client.delete("/image/files", params={"confirm": "all"})
    assert purge.status_code == 200
    assert purge.json() == {"deleted": 0}
