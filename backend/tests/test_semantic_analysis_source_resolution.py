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


# =====================================================================
# 9. LOCAL UPLOAD DURABILITY (the actual root cause of the reported bug).
#
#    Every test above happens to pass even WITHOUT the durability fix,
#    because Starlette's TestClient runs BackgroundTasks to completion
#    inside the same call before returning control to the test — which
#    masks exactly the timing window a real uvicorn server exposes. The
#    tests below remove that safety net by stubbing the background
#    callback out entirely, so they fail on the pre-fix code and pass
#    only when the upload endpoint itself persists a durable,
#    analysis-readable source before answering 201.
#
#    Zero AI calls: nothing here touches Anthropic or OpenAI. The upload
#    path is exercised with use_openai=false, and the semantic-analysis
#    side is only ever asked to RESOLVE a source file, never to send one.
# =====================================================================


def _make_test_jpeg_bytes(width: int = 320, height: int = 240) -> bytes:
    image = np.full((height, width, 3), 240, dtype=np.uint8)
    cv2.rectangle(image, (15, 15), (width - 15, height - 15), (30, 30, 30), thickness=4)
    success, encoded = cv2.imencode(".jpg", image)
    assert success
    return encoded.tobytes()


def _disable_background_processing(monkeypatch):
    """
    Simulates the background task never running at all — killed by a dev
    server reload, a crashed/restarted process, or an unrelated error
    raised before its own persistence step. The durable-source guarantee
    must hold entirely without it.
    """

    from routes import map_groups_routes as map_groups_routes_module
    from routes import map_routes as map_routes_module

    async def _never_runs(*args, **kwargs):
        return None

    monkeypatch.setattr(
        map_routes_module, "process_map_in_background", _never_runs
    )
    monkeypatch.setattr(
        map_groups_routes_module, "process_map_in_background", _never_runs
    )


async def _assert_durable_source(map_id: str, *, expected_type: str) -> Path:
    map_item = await Map.get(map_id)
    assert map_item is not None

    # The durable pointer must already be set — this must never depend on
    # the background task having run.
    assert map_item.analysis_source_path
    assert map_item.analysis_source_type == expected_type

    resolved_path = map_image_service.from_storage_relative_path(
        map_item.analysis_source_path
    )
    assert resolved_path.exists()
    assert resolved_path.stat().st_size > 0

    # The ONE canonical resolver every analysis-start path shares must
    # find the exact same file, even though processing_status never
    # advanced past "pending".
    resolved = map_image_service.resolve_analysis_source_path(map_item)
    assert resolved is not None
    assert resolved.path == resolved_path

    return resolved_path


@pytest.mark.asyncio
async def test_png_upload_is_durable_without_background_processing(
    client, monkeypatch
):
    _disable_background_processing(monkeypatch)
    token, _ = create_admin_and_get_token(client, email="durable-png@example.com")

    map_summary = _upload_map(
        client,
        token,
        filename="floorplan.png",
        content=_make_test_png_bytes(),
        content_type="image/png",
        title="Durable PNG Map",
    )

    await _assert_durable_source(
        map_summary["id"], expected_type="original_image"
    )


@pytest.mark.asyncio
async def test_jpeg_upload_is_durable_without_background_processing(
    client, monkeypatch
):
    _disable_background_processing(monkeypatch)
    token, _ = create_admin_and_get_token(client, email="durable-jpeg@example.com")

    map_summary = _upload_map(
        client,
        token,
        filename="floorplan.jpg",
        content=_make_test_jpeg_bytes(),
        content_type="image/jpeg",
        title="Durable JPEG Map",
    )

    await _assert_durable_source(
        map_summary["id"], expected_type="original_image"
    )


@pytest.mark.asyncio
async def test_pdf_upload_is_durable_without_background_processing(
    client, monkeypatch
):
    _disable_background_processing(monkeypatch)
    token, _ = create_admin_and_get_token(client, email="durable-pdf@example.com")

    map_summary = _upload_map(
        client,
        token,
        filename="floorplan.pdf",
        content=_make_test_pdf_bytes(),
        content_type="application/pdf",
        title="Durable PDF Map",
    )

    await _assert_durable_source(map_summary["id"], expected_type="original_pdf")


@pytest.mark.asyncio
async def test_worker_resolver_finds_source_without_background_processing(
    client, monkeypatch
):
    """
    The direct regression test for the reported symptom: this is exactly
    what semantic_analysis_worker._process_job calls before deciding
    whether to fail a job with "No source file could be located on disk
    for this analysis". It must return real bytes for a freshly uploaded
    map even when the background task never ran.
    """

    _disable_background_processing(monkeypatch)
    token, _ = create_admin_and_get_token(client, email="durable-worker@example.com")

    map_summary = _upload_map(
        client,
        token,
        filename="floorplan.pdf",
        content=_make_test_pdf_bytes(),
        content_type="application/pdf",
        title="Durable Worker Resolver Map",
    )

    files = await svc.resolve_source_files_for_map(map_summary["id"])

    assert len(files) == 1
    assert len(files[0].file_bytes) > 0


@pytest.mark.asyncio
async def test_successful_upload_never_yields_source_file_unavailable(
    client, monkeypatch
):
    """
    A successful upload (HTTP 201) must never be followed by a
    source_file_unavailable failure — neither from the manual start
    endpoint nor from the worker's own resolution — even with the
    background task removed entirely.
    """

    _disable_background_processing(monkeypatch)
    token, _ = create_admin_and_get_token(client, email="durable-nofail@example.com")

    map_summary = _upload_map(
        client,
        token,
        filename="floorplan.png",
        content=_make_test_png_bytes(),
        content_type="image/png",
        title="Durable No Failure Map",
    )

    response = client.post(
        f"/api/maps/{map_summary['id']}/semantic-analysis/start",
        json={"force": True},
        headers=auth_headers(token),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] != "failed"
    assert body["error_code"] != "source_file_unavailable"

    # And the worker's own resolution agrees.
    assert await svc.resolve_source_files_for_map(map_summary["id"])


@pytest.mark.asyncio
async def test_upload_returns_real_error_when_durable_persistence_fails(
    client, monkeypatch
):
    """
    The inverse guarantee: if the durable write genuinely cannot succeed,
    the endpoint must return an actual backend error and must never leave
    behind a Map record pointing at a nonexistent local file.
    """

    from routes import map_routes as map_routes_module

    monkeypatch.setattr(
        map_routes_module,
        "preserve_original_source_file",
        lambda *args, **kwargs: None,
    )

    token, _ = create_admin_and_get_token(
        client, email="durable-upload-fail@example.com"
    )

    response = client.post(
        "/api/maps/upload",
        data={"title": "Should Never Persist", "use_openai": "false"},
        files={
            "file": (
                "floorplan.pdf",
                _make_test_pdf_bytes(),
                "application/pdf",
            )
        },
        headers=auth_headers(token),
    )

    assert response.status_code == 500, response.text

    orphaned = await Map.find({"title": "Should Never Persist"}).to_list()
    assert orphaned == []


# ---------------------------------------------------------------------
# 10. Unicode / Hebrew filesystem paths.
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hebrew_upload_filename_still_persists_a_durable_source(
    client, monkeypatch
):
    """
    Uploading a file whose ORIGINAL name is Hebrew must work: the stored
    filename is always "{map_id}{ext}" (ASCII), while the Hebrew name is
    preserved only as Map.source_filename metadata. This pins that the
    Hebrew name never leaks into a filesystem path and never breaks the
    durable copy.
    """

    _disable_background_processing(monkeypatch)
    token, _ = create_admin_and_get_token(client, email="hebrew-name@example.com")

    map_summary = _upload_map(
        client,
        token,
        filename="מפה קומה 1.pdf",
        content=_make_test_pdf_bytes(),
        content_type="application/pdf",
        title="מפת קומת קרקע",
    )

    resolved_path = await _assert_durable_source(
        map_summary["id"], expected_type="original_pdf"
    )

    # The on-disk name is the ASCII map id, never the Hebrew upload name.
    assert resolved_path.name == f"{map_summary['id']}.pdf"

    map_item = await Map.get(map_summary["id"])
    assert map_item.source_filename == "מפה קומה 1.pdf"


def test_storage_relative_path_round_trips_a_hebrew_path():
    """
    Should the whole storage root ever live under a Hebrew directory (a
    Windows user folder, a synced drive), the POSIX-relative persistence
    format must still round-trip exactly and must never contain a
    backslash.
    """

    map_image_service.ensure_map_directories()
    destination = map_image_service.ORIGINALS_DIR / "מפה-בדיקה.png"
    destination.write_bytes(b"fake-bytes")

    try:
        relative = map_image_service.to_storage_relative_path(destination)

        assert "\\" not in relative
        assert relative == "originals/מפה-בדיקה.png"
        assert (
            map_image_service.from_storage_relative_path(relative) == destination
        )
        assert map_image_service.from_storage_relative_path(relative).exists()
    finally:
        destination.unlink(missing_ok=True)


# ---------------------------------------------------------------------
# 11. Multi-floor map-group upload has the same durability guarantee.
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_map_group_upload_is_durable_without_background_processing(
    client, monkeypatch
):
    import json as _json

    _disable_background_processing(monkeypatch)
    token, _ = create_admin_and_get_token(client, email="durable-group@example.com")

    floors = [
        {"title": "Ground Floor", "floor": 0, "scale": 1.0, "use_openai": False},
        {"title": "First Floor", "floor": 1, "scale": 1.0, "use_openai": False},
    ]

    response = client.post(
        "/api/map-groups",
        data={"name": "Durable Group", "floors_json": _json.dumps(floors)},
        files=[
            ("files", ("floor-0.png", _make_test_png_bytes(), "image/png")),
            ("files", ("floor-1.pdf", _make_test_pdf_bytes(), "application/pdf")),
        ],
        headers=auth_headers(token),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert len(body["floors"]) == 2

    by_floor = {floor["floor"]: floor for floor in body["floors"]}

    await _assert_durable_source(
        by_floor[0]["id"], expected_type="original_image"
    )
    await _assert_durable_source(by_floor[1]["id"], expected_type="original_pdf")

    # Both floors resolve for the worker too.
    for floor in body["floors"]:
        assert await svc.resolve_source_files_for_map(floor["id"])


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
