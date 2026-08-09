"""
Tests for the semantic-analysis source-file path bug fix.

Bug being regression-tested: a newly uploaded Map displayed correctly in
the frontend, but clicking "Analyze Floor Map" (or the automatic
post-upload analysis job the background worker picks up) failed with
"No source file could be located on disk for this analysis (the Map's
uploaded file may have been removed)." — even though the exact same file
had just been used to render the map the admin was looking at.

Root cause: three independent code paths (routes/semantic_analysis_
routes.py's start_map_semantic_analysis, its map-group sibling, and
services/semantic_analysis_service.resolve_source_files_for_map, called by
the background worker) each re-derived "where is this map's source file"
by filename convention instead of reading one persisted, reliable
pointer. This file exercises the fix: an explicit Map.analysis_source_path
/ analysis_source_type field, persisted once at upload time, and one
canonical resolver (services/map_image_service.resolve_analysis_source_
path / _async) every one of those three call sites now shares.

Run with: pytest backend/tests/test_semantic_analysis_source_resolution.py -v
"""

import tempfile
from pathlib import Path

import cv2
import fitz
import numpy as np
import pytest

from tests.test_api_integration import auth_headers, create_admin_and_get_token

from models.map_model import Map
from models.route_point_model import RoutePoint
from models.route_edge_model import RouteEdge
from services import map_image_service
from services import semantic_analysis_service as svc


# ---------------------------------------------------------------------
# Fixture file builders
# ---------------------------------------------------------------------


def _make_test_png_bytes(width: int = 300, height: int = 200) -> bytes:
    image = np.full((height, width, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (20, 20), (width - 20, height - 20), (0, 0, 0), thickness=3)
    success, encoded = cv2.imencode(".png", image)
    assert success
    return encoded.tobytes()


def _make_test_pdf_bytes(width: int = 400, height: int = 300) -> bytes:
    document = fitz.open()
    document.new_page(width=width, height=height)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_pdf_path = Path(temp_dir) / "fixture.pdf"
        document.save(str(temp_pdf_path))
        document.close()
        return temp_pdf_path.read_bytes()


def _upload_map(client, token, *, filename, content, content_type, title):
    response = client.post(
        "/api/maps/upload",
        data={"title": title, "use_openai": "false"},
        files={"file": (filename, content, content_type)},
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------
# 1. New image upload persists an existing source path.
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_image_upload_persists_analysis_source_path(client):
    token, _ = create_admin_and_get_token(client, email="imgupload@example.com")

    map_summary = _upload_map(
        client,
        token,
        filename="floorplan.png",
        content=_make_test_png_bytes(),
        content_type="image/png",
        title="PNG Source Map",
    )

    map_item = await Map.get(map_summary["id"])
    assert map_item is not None
    assert map_item.analysis_source_path
    assert map_item.analysis_source_type in ("original_image", "rendered_source_png")

    resolved_path = map_image_service.from_storage_relative_path(
        map_item.analysis_source_path
    )
    assert resolved_path.exists()
    assert resolved_path.stat().st_size > 0


# ---------------------------------------------------------------------
# 2. New PDF upload persists an existing source path.
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pdf_upload_persists_analysis_source_path(client):
    token, _ = create_admin_and_get_token(client, email="pdfupload@example.com")

    map_summary = _upload_map(
        client,
        token,
        filename="floorplan.pdf",
        content=_make_test_pdf_bytes(),
        content_type="application/pdf",
        title="PDF Source Map",
    )

    map_item = await Map.get(map_summary["id"])
    assert map_item is not None
    assert map_item.analysis_source_path
    # A PDF upload's true original is preservable (unlike some fonts/older
    # environments where preservation is best-effort), so this should be
    # the real PDF, not the flattened fallback PNG, in the normal case.
    assert map_item.analysis_source_type in ("original_pdf", "rendered_source_png")

    resolved_path = map_image_service.from_storage_relative_path(
        map_item.analysis_source_path
    )
    assert resolved_path.exists()
    assert resolved_path.stat().st_size > 0


# ---------------------------------------------------------------------
# 3. Semantic analysis can resolve the newly uploaded source — the direct
#    regression test for the reported bug (this is exactly what the
#    background worker calls before deciding whether to fail a job).
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_resolver_finds_the_newly_uploaded_source(client):
    token, _ = create_admin_and_get_token(client, email="resolver@example.com")

    map_summary = _upload_map(
        client,
        token,
        filename="floorplan.pdf",
        content=_make_test_pdf_bytes(),
        content_type="application/pdf",
        title="Resolver Regression Map",
    )

    files = await svc.resolve_source_files_for_map(map_summary["id"])

    assert len(files) == 1
    assert len(files[0].file_bytes) > 0


@pytest.mark.asyncio
async def test_start_analysis_endpoint_succeeds_without_a_second_upload(client):
    """
    End-to-end regression test for the exact reported symptom: uploading a
    Map must be sufficient — the admin must never need to upload the same
    file again through the analysis screen.
    """

    token, _ = create_admin_and_get_token(client, email="e2e@example.com")

    map_summary = _upload_map(
        client,
        token,
        filename="floorplan.png",
        content=_make_test_png_bytes(),
        content_type="image/png",
        title="End To End Map",
    )

    response = client.post(
        f"/api/maps/{map_summary['id']}/semantic-analysis/start",
        json={"force": True},
        headers=auth_headers(token),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    # Never the old failure — no source file was ever "removed", so this
    # must not be a source_file_unavailable failure.
    assert body["status"] != "failed"
    assert body["error_code"] != "source_file_unavailable"


# ---------------------------------------------------------------------
# 4. Windows path separators are handled correctly.
# ---------------------------------------------------------------------


def test_to_storage_relative_path_never_produces_backslashes(tmp_path):
    map_image_service.ensure_map_directories()
    destination = map_image_service.ORIGINALS_DIR / "windows_path_test.png"
    destination.write_bytes(b"fake-bytes")

    try:
        relative = map_image_service.to_storage_relative_path(destination)
        assert "\\" not in relative
        assert relative == "originals/windows_path_test.png"
    finally:
        destination.unlink(missing_ok=True)


def test_from_storage_relative_path_parses_forward_slash_string_safely():
    # Simulates a path persisted by a process running on Windows: always
    # forward-slash (see to_storage_relative_path), even though a naive
    # str(WindowsPath) would have produced backslashes.
    resolved = map_image_service.from_storage_relative_path(
        "originals/some-map-id.pdf"
    )
    assert resolved == map_image_service.ORIGINALS_DIR / "some-map-id.pdf"


# ---------------------------------------------------------------------
# 5. Relative storage paths resolve from the configured storage root, not
#    process CWD.
# ---------------------------------------------------------------------


def test_from_storage_relative_path_ignores_process_cwd(tmp_path, monkeypatch):
    unrelated_directory = tmp_path / "somewhere_else_entirely"
    unrelated_directory.mkdir()
    monkeypatch.chdir(unrelated_directory)

    resolved = map_image_service.from_storage_relative_path(
        "source/cwd-independence-test.png"
    )

    # Still anchored to the real MAPS_DIR constant, never to the process's
    # (now completely unrelated) current working directory.
    assert resolved == map_image_service.SOURCE_DIR / "cwd-independence-test.png"
    assert str(unrelated_directory) not in str(resolved)


# ---------------------------------------------------------------------
# 6. Preview/render generation does not delete the original source.
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_processing_does_not_delete_the_preserved_original(client):
    token, _ = create_admin_and_get_token(client, email="preserve@example.com")

    map_summary = _upload_map(
        client,
        token,
        filename="floorplan.pdf",
        content=_make_test_pdf_bytes(),
        content_type="application/pdf",
        title="Preservation Map",
    )

    map_item = await Map.get(map_summary["id"])
    assert map_item.analysis_source_type == "original_pdf", (
        "test setup assumption: PDF preservation should succeed in this "
        "environment so this test can verify it is never deleted"
    )

    preserved_path = map_image_service.get_preserved_original_path(
        map_summary["id"]
    )
    assert preserved_path is not None
    assert preserved_path.exists()

    # The display/preview pipeline (create_local_display_map, and the
    # optional OpenAI recolor step) has already run by the time the upload
    # endpoint's background task finished — nothing about it should have
    # touched the preserved original.
    assert preserved_path.read_bytes()  # still readable, non-empty


# ---------------------------------------------------------------------
# 7. A genuinely missing legacy source still returns a clear error.
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_map_with_missing_files_returns_clear_error(client):
    token, admin_user = create_admin_and_get_token(
        client, email="legacy@example.com"
    )

    # Simulates a pre-existing Map document whose files were removed from
    # disk some other way (never through this fix's normal flow) — no
    # analysis_source_path, no ORIGINALS_DIR entry, no SOURCE_DIR PNG.
    legacy_map = Map(
        title="Legacy Map With No Files",
        processing_status="completed",
        scale=1.0,
    )
    await legacy_map.insert()

    resolved = map_image_service.resolve_analysis_source_path(legacy_map)
    assert resolved is None

    response = client.post(
        f"/api/maps/{legacy_map.id}/semantic-analysis/start",
        json={},
        headers=auth_headers(token),
    )

    assert response.status_code == 409
    assert "no processed source file" in response.json()["detail"].lower()


# ---------------------------------------------------------------------
# 8. Upload and analysis create zero RoutePoints and zero RouteEdges.
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_and_start_analysis_create_zero_route_points_and_edges(client):
    token, _ = create_admin_and_get_token(client, email="zerograph@example.com")

    map_summary = _upload_map(
        client,
        token,
        filename="floorplan.png",
        content=_make_test_png_bytes(),
        content_type="image/png",
        title="Zero Graph Map",
    )

    client.post(
        f"/api/maps/{map_summary['id']}/semantic-analysis/start",
        json={"force": True},
        headers=auth_headers(token),
    )

    points = await RoutePoint.find({"map_id": map_summary["id"]}).to_list()
    edges = await RouteEdge.find({"map_id": map_summary["id"]}).to_list()

    assert points == []
    assert edges == []


# ---------------------------------------------------------------------
# Self-healing: a map that predates the explicit field (analysis_source_
# path is None) but still has a discoverable preserved original gets the
# field backfilled the first time resolution succeeds.
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_map_without_explicit_field_self_heals(client):
    token, _ = create_admin_and_get_token(client, email="selfheal@example.com")

    map_item = Map(
        title="Pre-Fix Map",
        processing_status="completed",
        scale=1.0,
    )
    await map_item.insert()

    map_image_service.ensure_map_directories()
    source_path = map_image_service.SOURCE_DIR / f"{map_item.id}.png"
    source_path.write_bytes(_make_test_png_bytes())

    try:
        assert map_item.analysis_source_path is None

        resolved = await map_image_service.resolve_analysis_source_path_async(
            map_item
        )
        assert resolved is not None
        assert resolved.source_type == "rendered_source_png"

        response = client.post(
            f"/api/maps/{map_item.id}/semantic-analysis/start",
            json={"force": True},
            headers=auth_headers(token),
        )
        assert response.status_code == 200, response.text

        refreshed = await Map.get(map_item.id)
        assert refreshed.analysis_source_path == "source/{}.png".format(map_item.id)
        assert refreshed.analysis_source_type == "rendered_source_png"
    finally:
        source_path.unlink(missing_ok=True)
