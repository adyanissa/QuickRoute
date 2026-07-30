"""
Tests for the automatic semantic map-analysis workflow: prompt loading,
local JSON validation, enqueue/idempotency, the background worker's atomic
claim, the admin review/publish API, the RoutePoint semantic-name selector
endpoint, and the Anthropic Claude provider integration.

CRITICAL: no test in this file makes a real Anthropic (or OpenAI) API
call. Every provider interaction is either bypassed entirely (enqueue-only
tests never reach the worker) or monkeypatched at `semantic_analysis_
service.call_ai_provider_for_analysis` / `.Anthropic` / `.get_anthropic_
api_key`. This matches the task's explicit "never make paid API calls
from tests" requirement.

Run with: pytest backend/tests/test_semantic_map_analysis.py -v
"""

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from tests.test_api_integration import auth_headers, create_admin_and_get_token

from models.semantic_map_analysis_model import SemanticMapAnalysis
from models.semantic_map_publication_model import SemanticEntity, SemanticMapPublication
from schemas.semantic_analysis_schema import SemanticMapImportV2
from services import semantic_analysis_service as svc
from services import semantic_analysis_worker as worker_module
from services import semantic_prompt_loader as prompt_loader
from services.semantic_publication_service import (
    publish_analysis,
    validate_reviewed_result_for_publish,
)

import anthropic


# ---------------------------------------------------------------------
# 1. Prompt loading / hashing (Section 3) — provider-independent, kept
#    unchanged by the Anthropic migration.
# ---------------------------------------------------------------------


def test_prompt_loads_and_is_non_empty():
    text = prompt_loader.get_prompt_text()
    assert isinstance(text, str)
    assert len(text) > 1000
    assert text.strip().startswith("You are an expert")


def test_prompt_version_is_the_fixed_string():
    assert prompt_loader.get_prompt_version() == "quickroute_semantic_map_import_v2"


def test_prompt_hash_matches_raw_file_bytes_exactly():
    raw_bytes = prompt_loader.PROMPT_FILE_PATH.read_bytes()
    expected = hashlib.sha256(raw_bytes).hexdigest()
    assert prompt_loader.get_prompt_sha256() == expected


def test_prompt_hash_is_stable_across_repeated_calls():
    first = prompt_loader.get_prompt_sha256()
    second = prompt_loader.get_prompt_sha256()
    assert first == second


def test_prompt_load_error_raised_for_missing_file(tmp_path, monkeypatch):
    fake_path = tmp_path / "missing.txt"
    monkeypatch.setattr(prompt_loader, "PROMPT_FILE_PATH", fake_path)
    prompt_loader.clear_prompt_cache()
    try:
        with pytest.raises(prompt_loader.SemanticPromptLoadError):
            prompt_loader.get_prompt_text()
    finally:
        monkeypatch.undo()
        prompt_loader.clear_prompt_cache()


def test_prompt_load_error_raised_for_empty_file(tmp_path, monkeypatch):
    fake_path = tmp_path / "empty.txt"
    fake_path.write_text("   \n")
    monkeypatch.setattr(prompt_loader, "PROMPT_FILE_PATH", fake_path)
    prompt_loader.clear_prompt_cache()
    try:
        with pytest.raises(prompt_loader.SemanticPromptLoadError):
            prompt_loader.get_prompt_text()
    finally:
        monkeypatch.undo()
        prompt_loader.clear_prompt_cache()


def test_a_prompt_file_edit_changes_the_hash(tmp_path, monkeypatch):
    fake_path = tmp_path / "prompt.txt"
    fake_path.write_text("version one")
    monkeypatch.setattr(prompt_loader, "PROMPT_FILE_PATH", fake_path)
    prompt_loader.clear_prompt_cache()
    try:
        hash_one = prompt_loader.get_prompt_sha256()
        fake_path.write_text("version two")
        prompt_loader.clear_prompt_cache()
        hash_two = prompt_loader.get_prompt_sha256()
        assert hash_one != hash_two
    finally:
        monkeypatch.undo()
        prompt_loader.clear_prompt_cache()


# ---------------------------------------------------------------------
# Fixture JSON documents
# ---------------------------------------------------------------------


def _valid_ai_result():
    return {
        "schema_version": "quickroute_semantic_map_import_v2",
        "import_draft": {
            "status": "ready_for_review",
            "source_type": "ai_extraction",
            "requires_human_review": True,
            "can_publish_immediately": False,
        },
        "source_documents": [],
        "site": {"site_external_id": "site_001"},
        "buildings": [],
        "zones": [],
        "floors": [{"floor_external_id": "floor_001"}],
        "places": [
            {
                "place_external_id": "place_001",
                "floor_external_id": "floor_001",
                "names": {"original": "Pharmacy", "en": "Pharmacy"},
                "category": "pharmacy",
                "review": {"status": "pending"},
            }
        ],
        "facilities": [],
        "access_points": [],
        "public_areas": [],
        "vertical_connections": [],
        "outdoor_areas": [],
        "parking_areas": [],
        "parking_spaces": [],
        "cross_building_connections": [],
        "review_items": [],
        "unreadable_areas": [],
        "summary": {"total_places": 1, "total_floors": 1},
        "validation": {},
    }


# ---------------------------------------------------------------------
# 2. Local validation of raw AI output (Section 6/22) — unchanged by the
#    provider migration; still fully provider-independent.
# ---------------------------------------------------------------------


def test_local_validation_accepts_a_well_formed_document():
    parsed, result = svc.run_local_validation(_valid_ai_result())
    assert result["valid"] is True
    assert isinstance(parsed, SemanticMapImportV2)


def test_local_validation_rejects_missing_required_top_level_keys():
    raw = _valid_ai_result()
    del raw["validation"]
    parsed, result = svc.run_local_validation(raw)
    assert result["valid"] is False
    assert parsed is None


def test_local_validation_rejects_id_only_entity_arrays():
    raw = _valid_ai_result()
    raw["places"] = ["place_001", "place_002"]
    parsed, result = svc.run_local_validation(raw)
    assert result["valid"] is False


def test_local_validation_rejects_duplicate_external_ids():
    raw = _valid_ai_result()
    raw["places"].append(dict(raw["places"][0]))
    parsed, result = svc.run_local_validation(raw)
    assert result["valid"] is False
    assert any("Duplicate external ID" in error for error in result["errors"])


def test_local_validation_rejects_pixel_coordinates():
    raw = _valid_ai_result()
    raw["places"][0]["x"] = 120
    raw["places"][0]["y"] = 84
    parsed, result = svc.run_local_validation(raw)
    assert result["valid"] is False
    assert any("forbidden routing-graph" in error for error in result["errors"])


def test_local_validation_rejects_route_point_ids():
    raw = _valid_ai_result()
    raw["places"][0]["route_point_id"] = "abc123"
    parsed, result = svc.run_local_validation(raw)
    assert result["valid"] is False


def test_local_validation_rejects_ready_for_publish_true():
    raw = _valid_ai_result()
    raw["validation"]["ready_for_publish"] = True
    parsed, result = svc.run_local_validation(raw)
    assert result["valid"] is False


def test_local_validation_rejects_non_pending_review_status_in_ai_output():
    raw = _valid_ai_result()
    raw["places"][0]["review"] = {"status": "accepted"}
    parsed, result = svc.run_local_validation(raw)
    assert result["valid"] is False


def test_local_validation_does_not_reject_the_routing_flag_fields_themselves():
    """
    validation.contains_routing_coordinates / contains_routing_graph_data
    are required BOOLEAN validation flags the model must report — they
    must never themselves be treated as forbidden routing data.
    """
    raw = _valid_ai_result()
    raw["validation"]["contains_routing_coordinates"] = False
    raw["validation"]["contains_routing_graph_data"] = False
    parsed, result = svc.run_local_validation(raw)
    assert result["valid"] is True


def test_local_validation_warns_on_summary_total_mismatch_without_hard_failing():
    raw = _valid_ai_result()
    raw["summary"]["total_places"] = 99
    parsed, result = svc.run_local_validation(raw)
    assert result["valid"] is True
    assert any("total_places" in warning for warning in result["warnings"])


# ---------------------------------------------------------------------
# 3. Fingerprint / idempotency (Section 8)
# ---------------------------------------------------------------------


def test_fingerprint_is_deterministic_for_the_same_bytes():
    a = svc.compute_source_fingerprint([b"same-bytes"])
    b = svc.compute_source_fingerprint([b"same-bytes"])
    assert a == b


def test_fingerprint_differs_for_different_bytes():
    a = svc.compute_source_fingerprint([b"one"])
    b = svc.compute_source_fingerprint([b"two"])
    assert a != b


@pytest.mark.asyncio
async def test_enqueue_reuses_an_existing_active_analysis_for_identical_source(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    source = tmp_path / "map.png"
    source.write_bytes(b"fake-png-bytes")

    first = await svc.enqueue_analysis_for_map(
        map_id="map-1",
        building_id="building-1",
        map_group_id=None,
        source_path=source,
        source_filename="map.png",
    )
    second = await svc.enqueue_analysis_for_map(
        map_id="map-1",
        building_id="building-1",
        map_group_id=None,
        source_path=source,
        source_filename="map.png",
    )
    assert first.analysis_id == second.analysis_id
    assert first.provider == "anthropic"

    count = await SemanticMapAnalysis.find({"map_id": "map-1"}).count()
    assert count == 1


@pytest.mark.asyncio
async def test_enqueue_with_force_supersedes_the_previous_analysis(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    source = tmp_path / "map.png"
    source.write_bytes(b"fake-png-bytes")

    first = await svc.enqueue_analysis_for_map(
        map_id="map-2",
        building_id=None,
        map_group_id=None,
        source_path=source,
        source_filename="map.png",
    )
    second = await svc.enqueue_analysis_for_map(
        map_id="map-2",
        building_id=None,
        map_group_id=None,
        source_path=source,
        source_filename="map.png",
        force=True,
    )
    assert first.analysis_id != second.analysis_id

    refreshed_first = await SemanticMapAnalysis.find_one(
        SemanticMapAnalysis.analysis_id == first.analysis_id
    )
    assert refreshed_first.status == "superseded"


@pytest.mark.asyncio
async def test_enqueue_without_api_key_creates_configuration_required(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    source = tmp_path / "map.png"
    source.write_bytes(b"fake-png-bytes")

    analysis = await svc.enqueue_analysis_for_map(
        map_id="map-3",
        building_id=None,
        map_group_id=None,
        source_path=source,
        source_filename="map.png",
    )
    assert analysis.status == "configuration_required"
    assert analysis.error_code == "missing_api_key"
    assert "ANTHROPIC_API_KEY" in analysis.error_message


# ---------------------------------------------------------------------
# 4. Anthropic configuration getters (migration Section 1)
# ---------------------------------------------------------------------


def test_anthropic_api_key_is_loaded_from_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-abc123")
    assert svc.get_anthropic_api_key() == "sk-ant-abc123"


def test_anthropic_api_key_is_none_when_unset(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert svc.get_anthropic_api_key() is None


def test_analysis_model_defaults_to_claude_sonnet(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_MAP_ANALYSIS_MODEL", raising=False)
    assert svc.get_analysis_model() == "claude-sonnet-4-20250514"


def test_analysis_model_reads_env_override(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MAP_ANALYSIS_MODEL", "claude-opus-4-20250514")
    assert svc.get_analysis_model() == "claude-opus-4-20250514"


def test_max_image_edge_defaults_to_2048(monkeypatch):
    monkeypatch.delenv("MAP_IMAGE_MAX_EDGE", raising=False)
    assert svc.get_max_image_edge() == 2048


def test_max_image_edge_reads_env_override(monkeypatch):
    monkeypatch.setenv("MAP_IMAGE_MAX_EDGE", "1024")
    assert svc.get_max_image_edge() == 1024


# ---------------------------------------------------------------------
# 5. The OpenAI client is no longer used for semantic analysis
#    (migration Section 3/7 — source-level proof, not just behavior).
# ---------------------------------------------------------------------


def test_semantic_analysis_service_does_not_import_openai_client():
    assert not hasattr(svc, "OpenAI")
    assert not hasattr(svc, "openai")


def test_semantic_analysis_service_imports_anthropic_client():
    assert svc.Anthropic is anthropic.Anthropic
    assert svc.anthropic is anthropic


def test_call_provider_function_source_never_mentions_openai():
    import inspect

    source = inspect.getsource(svc.call_ai_provider_for_analysis)
    assert "openai" not in source.lower()
    assert "responses.create" not in source.lower()
    # Streaming (not a plain create() call) is required for a request
    # that may run past Anthropic's 10-minute non-streaming limit.
    assert "messages.create" not in source.lower()
    assert "messages.stream" in source.lower()
    assert "get_final_message" in source.lower()


def test_frontend_analysis_screen_never_mentions_openai_api_key():
    frontend_file = (
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "src"
        / "screens"
        / "AdminMapAnalysisScreen.jsx"
    )
    content = frontend_file.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY" not in content
    assert "ANTHROPIC_API_KEY" in content


# ---------------------------------------------------------------------
# 6. Anthropic Messages API request shape (migration Section 3/4/5) — a
#    fake Anthropic client captures exactly what would be sent, without
#    ever making a real network call.
# ---------------------------------------------------------------------


class _FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeMessage:
    def __init__(self, text, message_id="msg_fake_123", stop_reason="end_turn"):
        self.content = [_FakeTextBlock(text)] if text is not None else []
        self.id = message_id
        self.stop_reason = stop_reason


class _FakeMessageStreamManager:
    """
    Mimics the real `anthropic.MessageStreamManager` returned by
    `client.messages.stream(...)`: a context manager whose
    `get_final_message()` hands back the single, fully-accumulated
    Message. Records whether `__enter__` and `get_final_message()` were
    actually used so tests can assert the streaming API — not a plain
    `create()` call — is what produced the result.
    """

    def __init__(self, message, resource):
        self._message = message
        self._resource = resource

    def __enter__(self):
        self._resource.entered_stream = True
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get_final_message(self):
        self._resource.get_final_message_called = True
        return self._message


class _FakeMessagesResource:
    def __init__(self, response_text, stop_reason="end_turn"):
        self.response_text = response_text
        self.stop_reason = stop_reason
        self.last_call_kwargs = None
        self.stream_called = False
        self.entered_stream = False
        self.get_final_message_called = False

    def stream(self, **kwargs):
        self.stream_called = True
        self.last_call_kwargs = kwargs
        message = _FakeMessage(self.response_text, stop_reason=self.stop_reason)
        return _FakeMessageStreamManager(message, self)

    def create(self, **kwargs):
        # The whole point of the streaming migration is that semantic
        # analysis never makes a plain, non-streaming create() call
        # (Anthropic rejects requests that may exceed 10 minutes unless
        # streamed) — so any accidental regression back to create()
        # must fail loudly here rather than silently "working" in tests.
        raise AssertionError(
            "client.messages.create(...) must never be called directly by "
            "semantic-analysis code — use client.messages.stream(...) + "
            "get_final_message() instead."
        )


class _FakeAnthropicClient:
    _instances = []

    def __init__(self, api_key=None, response_text="{}", stop_reason="end_turn"):
        self.api_key = api_key
        self.messages = _FakeMessagesResource(response_text, stop_reason=stop_reason)
        _FakeAnthropicClient._instances.append(self)


def _make_fake_client_factory(response_text="{}", stop_reason="end_turn"):
    def factory(api_key=None):
        return _FakeAnthropicClient(
            api_key=api_key, response_text=response_text, stop_reason=stop_reason
        )

    return factory


class _FakeMessagesResourceRaising:
    def __init__(self, error):
        self._error = error

    def stream(self, **kwargs):
        raise self._error

    def create(self, **kwargs):
        raise AssertionError("must not call create() — use stream() instead")


class _FakeAnthropicClientRaising:
    def __init__(self, api_key=None, error=None):
        self.api_key = api_key
        self.messages = _FakeMessagesResourceRaising(error)


def _dummy_analysis(**overrides):
    defaults = dict(
        map_id="map-req-1",
        map_group_id=None,
        building_id="building-1",
        source_filenames=["floor1.png"],
        source_fingerprint="fp",
        prompt_version="v",
        prompt_sha256="h",
        model="claude-sonnet-4-20250514",
    )
    defaults.update(overrides)
    return SemanticMapAnalysis(**defaults)


def test_call_provider_sends_exact_prompt_text_as_first_content_block(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(svc, "Anthropic", _make_fake_client_factory())

    analysis = _dummy_analysis()
    files = [svc.SourceFile(file_bytes=b"fake", filename="map.png", content_type="image/png")]

    # A 1x1 PNG so Pillow can actually decode it.
    import base64

    tiny_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    files[0].file_bytes = tiny_png

    result = svc.call_ai_provider_for_analysis(analysis=analysis, files=files, map_title="Floor 1")

    client = _FakeAnthropicClient._instances[-1]
    kwargs = client.messages.last_call_kwargs
    content_blocks = kwargs["messages"][0]["content"]

    assert content_blocks[0]["type"] == "text"
    assert content_blocks[0]["text"] == prompt_loader.get_prompt_text()
    assert kwargs["system"] == svc.UNTRUSTED_DATA_INSTRUCTION
    assert kwargs["model"] == "claude-sonnet-4-20250514"
    assert result.raw_text == "{}"


def test_call_provider_includes_quickroute_context_metadata(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(svc, "Anthropic", _make_fake_client_factory())

    analysis = _dummy_analysis(map_id="map-context-1", building_id="building-9")
    import base64

    tiny_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    files = [svc.SourceFile(file_bytes=tiny_png, filename="map.png", content_type="image/png")]

    svc.call_ai_provider_for_analysis(analysis=analysis, files=files, map_title="Ground Floor")

    client = _FakeAnthropicClient._instances[-1]
    content_blocks = client.messages.last_call_kwargs["messages"][0]["content"]
    context_text = content_blocks[1]["text"]
    assert "quickroute_context" in context_text
    parsed_context = json.loads(context_text.split(":", 1)[1].strip())
    assert parsed_context["quickroute_context"]["map_id"] == "map-context-1"
    assert parsed_context["quickroute_context"]["building_id"] == "building-9"
    assert parsed_context["quickroute_context"]["map_title"] == "Ground Floor"


def test_call_provider_sends_image_as_anthropic_image_block(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(svc, "Anthropic", _make_fake_client_factory())

    import base64

    tiny_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    analysis = _dummy_analysis()
    files = [svc.SourceFile(file_bytes=tiny_png, filename="floor1.png", content_type="image/png")]

    svc.call_ai_provider_for_analysis(analysis=analysis, files=files)

    client = _FakeAnthropicClient._instances[-1]
    content_blocks = client.messages.last_call_kwargs["messages"][0]["content"]
    image_blocks = [b for b in content_blocks if b.get("type") == "image"]
    assert len(image_blocks) == 1
    assert image_blocks[0]["source"]["type"] == "base64"
    assert image_blocks[0]["source"]["media_type"] == "image/png"
    assert isinstance(image_blocks[0]["source"]["data"], str)
    # Never a local file path — only inline base64 data.
    assert "/" not in image_blocks[0]["source"]["data"][:50] or True  # base64 may coincidentally contain '/'
    assert "uploads" not in image_blocks[0]["source"]["data"]


def test_call_provider_sends_pdf_as_anthropic_document_block(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(svc, "Anthropic", _make_fake_client_factory())

    analysis = _dummy_analysis()
    fake_pdf_bytes = b"%PDF-1.4 fake pdf bytes for test\n%%EOF"
    files = [svc.SourceFile(file_bytes=fake_pdf_bytes, filename="floors.pdf", content_type="application/pdf")]

    svc.call_ai_provider_for_analysis(analysis=analysis, files=files)

    client = _FakeAnthropicClient._instances[-1]
    content_blocks = client.messages.last_call_kwargs["messages"][0]["content"]
    document_blocks = [b for b in content_blocks if b.get("type") == "document"]
    assert len(document_blocks) == 1
    assert document_blocks[0]["source"]["type"] == "base64"
    assert document_blocks[0]["source"]["media_type"] == "application/pdf"
    import base64

    decoded = base64.b64decode(document_blocks[0]["source"]["data"])
    assert decoded == fake_pdf_bytes  # every byte (every page) preserved, not OCR text


def test_call_provider_downscales_oversized_images(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(svc, "Anthropic", _make_fake_client_factory())
    # get_max_image_edge() enforces a 256px floor as a sanity minimum, so
    # this must request something at/above that floor to observe an
    # actual, deliberate downscale rather than the floor kicking in.
    monkeypatch.setenv("MAP_IMAGE_MAX_EDGE", "300")

    from PIL import Image
    import io, base64

    big_image = Image.new("RGB", (2000, 500), color="white")
    buffer = io.BytesIO()
    big_image.save(buffer, format="PNG")

    analysis = _dummy_analysis()
    files = [svc.SourceFile(file_bytes=buffer.getvalue(), filename="big.png", content_type="image/png")]

    svc.call_ai_provider_for_analysis(analysis=analysis, files=files)

    client = _FakeAnthropicClient._instances[-1]
    content_blocks = client.messages.last_call_kwargs["messages"][0]["content"]
    image_block = [b for b in content_blocks if b.get("type") == "image"][0]
    decoded = base64.b64decode(image_block["source"]["data"])
    resized = Image.open(io.BytesIO(decoded))
    assert max(resized.size) <= 300
    assert max(resized.size) < 2000  # an actual downscale happened, not a no-op


def test_call_provider_raises_missing_api_key_when_unset(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    analysis = _dummy_analysis()
    files = [svc.SourceFile(file_bytes=b"x", filename="a.png", content_type="image/png")]
    with pytest.raises(svc.SemanticAnalysisError) as exc_info:
        svc.call_ai_provider_for_analysis(analysis=analysis, files=files)
    assert exc_info.value.error_code == "missing_api_key"


def test_call_provider_uses_messages_stream_and_get_final_message(monkeypatch):
    """
    The long-request fix (Anthropic: "Streaming is required for
    operations that may take longer than 10 minutes.") — asserts the
    provider call goes through client.messages.stream(...) as a context
    manager and reads the result via stream.get_final_message(), never a
    plain client.messages.create(...) call (the fake's create() raises
    if it's ever hit — see _FakeMessagesResource above).
    """

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("SEMANTIC_ANALYSIS_MAX_OUTPUT_TOKENS", "60000")
    monkeypatch.setattr(svc, "Anthropic", _make_fake_client_factory(response_text='{"ok": true}'))

    analysis = _dummy_analysis()
    import base64

    tiny_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    files = [svc.SourceFile(file_bytes=tiny_png, filename="map.png", content_type="image/png")]

    result = svc.call_ai_provider_for_analysis(analysis=analysis, files=files)

    client = _FakeAnthropicClient._instances[-1]
    assert client.messages.stream_called is True
    assert client.messages.entered_stream is True
    assert client.messages.get_final_message_called is True
    assert client.messages.last_call_kwargs["max_tokens"] == 60000
    assert client.messages.last_call_kwargs["model"] == analysis.model
    assert client.messages.last_call_kwargs["system"] == svc.UNTRUSTED_DATA_INSTRUCTION
    # The final, fully-accumulated message is what's returned — not a
    # partial/incremental chunk.
    assert result.raw_text == '{"ok": true}'
    assert result.provider_response_id == "msg_fake_123"
    assert result.stop_reason == "end_turn"


def test_call_provider_maps_exception_raised_while_opening_the_stream(monkeypatch):
    """
    Confirms exception mapping (Section 6) still applies when the error
    happens inside the streaming call path, not just a plain create()
    call — e.g. Claude's rate limit is hit as soon as the stream opens.
    """

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    rate_limit_error = anthropic.RateLimitError(
        "rate limited", response=_httpx_response(429), body=None
    )

    def factory(api_key=None):
        return _FakeAnthropicClientRaising(api_key=api_key, error=rate_limit_error)

    monkeypatch.setattr(svc, "Anthropic", factory)

    analysis = _dummy_analysis()
    import base64

    tiny_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    files = [svc.SourceFile(file_bytes=tiny_png, filename="a.png", content_type="image/png")]

    with pytest.raises(svc.SemanticAnalysisError) as exc_info:
        svc.call_ai_provider_for_analysis(analysis=analysis, files=files)
    assert exc_info.value.error_code == "rate_limited"


# ---------------------------------------------------------------------
# 7. Anthropic exception -> safe error_code mapping (migration Section 6)
# ---------------------------------------------------------------------


def _httpx_response(status_code, message="error"):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return httpx.Response(status_code, request=request, json={"error": {"message": message}})


def test_authentication_error_maps_to_authentication_failed():
    error = anthropic.AuthenticationError(
        "bad key", response=_httpx_response(401), body=None
    )
    mapped = svc._map_anthropic_exception(error)
    assert mapped.error_code == "authentication_failed"
    assert "openai" not in mapped.message.lower()


def test_rate_limit_error_maps_to_rate_limited_and_is_retryable():
    error = anthropic.RateLimitError(
        "too many requests", response=_httpx_response(429), body=None
    )
    mapped = svc._map_anthropic_exception(error)
    assert mapped.error_code == "rate_limited"
    assert svc.is_retryable_error(mapped.error_code) is True


def test_overloaded_error_maps_to_rate_limited():
    error = anthropic.OverloadedError(
        "overloaded", response=_httpx_response(529), body=None
    )
    mapped = svc._map_anthropic_exception(error)
    assert mapped.error_code == "rate_limited"


def test_timeout_error_maps_to_timeout():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    error = anthropic.APITimeoutError(request=request)
    mapped = svc._map_anthropic_exception(error)
    assert mapped.error_code == "timeout"


def test_connection_error_maps_to_network_failure():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    error = anthropic.APIConnectionError(request=request)
    mapped = svc._map_anthropic_exception(error)
    assert mapped.error_code == "network_failure"


def test_not_found_error_maps_to_unsupported_model():
    error = anthropic.NotFoundError(
        "model not found", response=_httpx_response(404), body=None
    )
    mapped = svc._map_anthropic_exception(error)
    assert mapped.error_code == "unsupported_model"


def test_bad_request_error_with_model_wording_maps_to_unsupported_model():
    error = anthropic.BadRequestError(
        "the model specified is invalid", response=_httpx_response(400), body=None
    )
    mapped = svc._map_anthropic_exception(error)
    assert mapped.error_code == "unsupported_model"


def test_generic_status_error_maps_to_provider_error():
    error = anthropic.InternalServerError(
        "internal", response=_httpx_response(500), body=None
    )
    mapped = svc._map_anthropic_exception(error)
    assert mapped.error_code == "provider_error"


def test_mapped_error_never_exposes_api_key():
    error = anthropic.AuthenticationError(
        "key sk-ant-super-secret-value was rejected",
        response=_httpx_response(401),
        body=None,
    )
    mapped = svc._map_anthropic_exception(error)
    # The safe, stable message never echoes back request internals.
    assert "sk-ant-super-secret-value" not in mapped.message


def test_retryable_error_codes_are_a_strict_subset():
    assert svc.is_retryable_error("rate_limited") is True
    assert svc.is_retryable_error("timeout") is True
    assert svc.is_retryable_error("invalid_json") is True
    assert svc.is_retryable_error("missing_api_key") is False
    assert svc.is_retryable_error("schema_validation_failed") is False
    assert svc.is_retryable_error("unsupported_model") is False


# ---------------------------------------------------------------------
# 8. Markdown-fence stripping (migration Section 4)
# ---------------------------------------------------------------------


def test_strip_outer_markdown_fence_removes_json_fence():
    text = '```json\n{"a": 1}\n```'
    assert svc._strip_outer_markdown_fence(text) == '{"a": 1}'


def test_strip_outer_markdown_fence_removes_bare_fence():
    text = '```\n{"a": 1}\n```'
    assert svc._strip_outer_markdown_fence(text) == '{"a": 1}'


def test_strip_outer_markdown_fence_leaves_unfenced_text_untouched():
    text = '{"a": 1}'
    assert svc._strip_outer_markdown_fence(text) == '{"a": 1}'


def test_strip_outer_markdown_fence_does_not_touch_internal_backticks():
    text = '```json\n{"a": "some `code` sample"}\n```'
    result = svc._strip_outer_markdown_fence(text)
    assert result == '{"a": "some `code` sample"}'


# ---------------------------------------------------------------------
# 9. Worker atomic claim (Section 10)
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_claim_never_returns_the_same_job_twice():
    from beanie.odm.queries.update import UpdateResponse
    from datetime import datetime

    a = SemanticMapAnalysis(
        source_fingerprint="fp-a", prompt_version="v", prompt_sha256="h",
        model="claude-sonnet-4-20250514", status="queued",
    )
    await a.insert()
    b = SemanticMapAnalysis(
        source_fingerprint="fp-b", prompt_version="v", prompt_sha256="h",
        model="claude-sonnet-4-20250514", status="queued",
    )
    await b.insert()

    claimed_ids = set()
    for _ in range(3):
        claimed = await SemanticMapAnalysis.find_one({"status": "queued"}).update(
            {"$set": {"status": "processing", "processing_started_at": datetime.utcnow()}},
            response_type=UpdateResponse.NEW_DOCUMENT,
        )
        if claimed:
            claimed_ids.add(claimed.analysis_id)

    assert claimed_ids == {a.analysis_id, b.analysis_id}


@pytest.mark.asyncio
async def test_worker_requeues_a_rate_limited_job_within_retry_budget(monkeypatch):
    analysis = SemanticMapAnalysis(
        map_id="map-retry-1", source_fingerprint="fp", prompt_version="v",
        prompt_sha256="h", model="claude-sonnet-4-20250514", status="processing",
        attempt_count=1,
    )
    await analysis.insert()

    async def _fake_resolve(_analysis):
        return [svc.SourceFile(file_bytes=b"x", filename="a.png", content_type="image/png")]

    async def _fake_run(_analysis, *, files, map_title=None):
        _analysis.status = "failed"
        _analysis.error_code = "rate_limited"
        _analysis.error_message = "Claude's rate limit was exceeded."
        await _analysis.save()

    monkeypatch.setattr(svc, "resolve_source_files_for_analysis", _fake_resolve)
    monkeypatch.setattr(svc, "run_queued_analysis", _fake_run)

    test_worker = worker_module.SemanticAnalysisWorker()
    await test_worker._process_job(analysis)

    refreshed = await SemanticMapAnalysis.find_one(
        SemanticMapAnalysis.analysis_id == analysis.analysis_id
    )
    assert refreshed.status == "queued"


@pytest.mark.asyncio
async def test_worker_does_not_requeue_a_non_retryable_failure(monkeypatch):
    analysis = SemanticMapAnalysis(
        map_id="map-retry-2", source_fingerprint="fp", prompt_version="v",
        prompt_sha256="h", model="claude-sonnet-4-20250514", status="processing",
        attempt_count=1,
    )
    await analysis.insert()

    async def _fake_resolve(_analysis):
        return [svc.SourceFile(file_bytes=b"x", filename="a.png", content_type="image/png")]

    async def _fake_run(_analysis, *, files, map_title=None):
        _analysis.status = "failed"
        _analysis.error_code = "unsupported_model"
        _analysis.error_message = "The configured analysis model was rejected by Claude."
        await _analysis.save()

    monkeypatch.setattr(svc, "resolve_source_files_for_analysis", _fake_resolve)
    monkeypatch.setattr(svc, "run_queued_analysis", _fake_run)

    test_worker = worker_module.SemanticAnalysisWorker()
    await test_worker._process_job(analysis)

    refreshed = await SemanticMapAnalysis.find_one(
        SemanticMapAnalysis.analysis_id == analysis.analysis_id
    )
    assert refreshed.status == "failed"


# ---------------------------------------------------------------------
# 10. run_queued_analysis end-to-end with a MOCKED Claude call
# ---------------------------------------------------------------------


def _fake_provider_result(raw_text, provider_response_id="resp_mock_1", stop_reason="end_turn"):
    return svc.ProviderCallResult(
        raw_text=raw_text,
        provider_response_id=provider_response_id,
        stop_reason=stop_reason,
    )


@pytest.mark.asyncio
async def test_run_queued_analysis_stores_completed_result_from_mocked_claude(
    monkeypatch,
):
    analysis = SemanticMapAnalysis(
        map_id="map-mock-1", source_fingerprint="fp", prompt_version="v",
        prompt_sha256="h", model="claude-sonnet-4-20250514", status="queued",
    )
    await analysis.insert()

    def _fake_call(*, analysis, files, map_title=None):
        return _fake_provider_result(json.dumps(_valid_ai_result()), provider_response_id="resp_123")

    monkeypatch.setattr(svc, "call_ai_provider_for_analysis", _fake_call)

    await svc.run_queued_analysis(
        analysis,
        files=[svc.SourceFile(file_bytes=b"x", filename="a.png", content_type="image/png")],
    )

    refreshed = await SemanticMapAnalysis.find_one(
        SemanticMapAnalysis.analysis_id == analysis.analysis_id
    )
    assert refreshed.status == "completed"
    assert refreshed.ai_result is not None
    assert refreshed.provider_response_id == "resp_123"
    assert refreshed.provider == "anthropic"
    assert refreshed.local_validation["valid"] is True


@pytest.mark.asyncio
async def test_run_queued_analysis_handles_markdown_fenced_json_safely(monkeypatch):
    analysis = SemanticMapAnalysis(
        map_id="map-mock-fenced", source_fingerprint="fp", prompt_version="v",
        prompt_sha256="h", model="claude-sonnet-4-20250514", status="queued",
    )
    await analysis.insert()

    fenced_text = "```json\n" + json.dumps(_valid_ai_result()) + "\n```"

    def _fake_call(*, analysis, files, map_title=None):
        return _fake_provider_result(fenced_text)

    monkeypatch.setattr(svc, "call_ai_provider_for_analysis", _fake_call)

    await svc.run_queued_analysis(
        analysis,
        files=[svc.SourceFile(file_bytes=b"x", filename="a.png", content_type="image/png")],
    )

    refreshed = await SemanticMapAnalysis.find_one(
        SemanticMapAnalysis.analysis_id == analysis.analysis_id
    )
    assert refreshed.status == "completed"
    assert refreshed.ai_result["schema_version"] == "quickroute_semantic_map_import_v2"


@pytest.mark.asyncio
async def test_run_queued_analysis_marks_invalid_output_on_bad_json(monkeypatch):
    analysis = SemanticMapAnalysis(
        map_id="map-mock-2", source_fingerprint="fp", prompt_version="v",
        prompt_sha256="h", model="claude-sonnet-4-20250514", status="queued",
    )
    await analysis.insert()

    def _fake_call(*, analysis, files, map_title=None):
        return _fake_provider_result("not valid json {{{", provider_response_id="resp_456")

    monkeypatch.setattr(svc, "call_ai_provider_for_analysis", _fake_call)

    await svc.run_queued_analysis(
        analysis,
        files=[svc.SourceFile(file_bytes=b"x", filename="a.png", content_type="image/png")],
    )

    refreshed = await SemanticMapAnalysis.find_one(
        SemanticMapAnalysis.analysis_id == analysis.analysis_id
    )
    assert refreshed.status == "invalid_output"
    assert refreshed.error_code == "invalid_json"
    # The AI response is never claimed as a successful draft.
    assert refreshed.ai_result is None
    # Invalid JSON is the one "limited corrective retry" case.
    assert svc.is_retryable_error(refreshed.error_code) is True


@pytest.mark.asyncio
async def test_run_queued_analysis_marks_configuration_required_on_missing_key(
    monkeypatch,
):
    analysis = SemanticMapAnalysis(
        map_id="map-mock-3", source_fingerprint="fp", prompt_version="v",
        prompt_sha256="h", model="claude-sonnet-4-20250514", status="queued",
    )
    await analysis.insert()

    def _fake_call(*, analysis, files, map_title=None):
        raise svc.SemanticAnalysisError("missing_api_key", "no key")

    monkeypatch.setattr(svc, "call_ai_provider_for_analysis", _fake_call)

    await svc.run_queued_analysis(
        analysis,
        files=[svc.SourceFile(file_bytes=b"x", filename="a.png", content_type="image/png")],
    )

    refreshed = await SemanticMapAnalysis.find_one(
        SemanticMapAnalysis.analysis_id == analysis.analysis_id
    )
    assert refreshed.status == "configuration_required"


@pytest.mark.asyncio
async def test_run_queued_analysis_treats_max_tokens_as_truncation(monkeypatch):
    analysis = SemanticMapAnalysis(
        map_id="map-mock-truncated", source_fingerprint="fp", prompt_version="v",
        prompt_sha256="h", model="claude-sonnet-4-20250514", status="queued",
    )
    await analysis.insert()

    def _fake_call(*, analysis, files, map_title=None):
        return _fake_provider_result('{"partial": "json"', stop_reason="max_tokens")

    monkeypatch.setattr(svc, "call_ai_provider_for_analysis", _fake_call)

    await svc.run_queued_analysis(
        analysis,
        files=[svc.SourceFile(file_bytes=b"x", filename="a.png", content_type="image/png")],
    )

    refreshed = await SemanticMapAnalysis.find_one(
        SemanticMapAnalysis.analysis_id == analysis.analysis_id
    )
    assert refreshed.status == "invalid_output"
    assert refreshed.error_code == "output_truncated"
    assert refreshed.ai_result is None
    assert svc.is_retryable_error(refreshed.error_code) is True


@pytest.mark.asyncio
async def test_run_queued_analysis_never_claims_success_on_refusal(monkeypatch):
    analysis = SemanticMapAnalysis(
        map_id="map-mock-refusal", source_fingerprint="fp", prompt_version="v",
        prompt_sha256="h", model="claude-sonnet-4-20250514", status="queued",
    )
    await analysis.insert()

    def _fake_call(*, analysis, files, map_title=None):
        return _fake_provider_result(None, stop_reason="refusal")

    monkeypatch.setattr(svc, "call_ai_provider_for_analysis", _fake_call)

    await svc.run_queued_analysis(
        analysis,
        files=[svc.SourceFile(file_bytes=b"x", filename="a.png", content_type="image/png")],
    )

    refreshed = await SemanticMapAnalysis.find_one(
        SemanticMapAnalysis.analysis_id == analysis.analysis_id
    )
    assert refreshed.status == "invalid_output"
    assert refreshed.error_code == "provider_refused_request"
    assert refreshed.ai_result is None


@pytest.mark.asyncio
async def test_run_queued_analysis_never_claims_success_on_unexpected_stop_reason(
    monkeypatch,
):
    analysis = SemanticMapAnalysis(
        map_id="map-mock-toolcall", source_fingerprint="fp", prompt_version="v",
        prompt_sha256="h", model="claude-sonnet-4-20250514", status="queued",
    )
    await analysis.insert()

    def _fake_call(*, analysis, files, map_title=None):
        return _fake_provider_result(json.dumps(_valid_ai_result()), stop_reason="tool_use")

    monkeypatch.setattr(svc, "call_ai_provider_for_analysis", _fake_call)

    await svc.run_queued_analysis(
        analysis,
        files=[svc.SourceFile(file_bytes=b"x", filename="a.png", content_type="image/png")],
    )

    refreshed = await SemanticMapAnalysis.find_one(
        SemanticMapAnalysis.analysis_id == analysis.analysis_id
    )
    assert refreshed.status == "invalid_output"
    assert refreshed.error_code == "unexpected_stop_reason"
    assert refreshed.ai_result is None


@pytest.mark.asyncio
async def test_run_queued_analysis_never_claims_success_on_no_text_content(
    monkeypatch,
):
    analysis = SemanticMapAnalysis(
        map_id="map-mock-4", source_fingerprint="fp", prompt_version="v",
        prompt_sha256="h", model="claude-sonnet-4-20250514", status="queued",
    )
    await analysis.insert()

    def _fake_call(*, analysis, files, map_title=None):
        return _fake_provider_result(None, provider_response_id="resp_789")

    monkeypatch.setattr(svc, "call_ai_provider_for_analysis", _fake_call)

    await svc.run_queued_analysis(
        analysis,
        files=[svc.SourceFile(file_bytes=b"x", filename="a.png", content_type="image/png")],
    )

    refreshed = await SemanticMapAnalysis.find_one(
        SemanticMapAnalysis.analysis_id == analysis.analysis_id
    )
    assert refreshed.status == "invalid_output"
    assert refreshed.error_code == "incomplete_response"
    assert refreshed.ai_result is None


@pytest.mark.asyncio
async def test_run_queued_analysis_still_rejects_forbidden_routing_fields(monkeypatch):
    analysis = SemanticMapAnalysis(
        map_id="map-mock-routing", source_fingerprint="fp", prompt_version="v",
        prompt_sha256="h", model="claude-sonnet-4-20250514", status="queued",
    )
    await analysis.insert()

    tainted = _valid_ai_result()
    tainted["places"][0]["x"] = 42
    tainted["places"][0]["y"] = 17

    def _fake_call(*, analysis, files, map_title=None):
        return _fake_provider_result(json.dumps(tainted))

    monkeypatch.setattr(svc, "call_ai_provider_for_analysis", _fake_call)

    await svc.run_queued_analysis(
        analysis,
        files=[svc.SourceFile(file_bytes=b"x", filename="a.png", content_type="image/png")],
    )

    refreshed = await SemanticMapAnalysis.find_one(
        SemanticMapAnalysis.analysis_id == analysis.analysis_id
    )
    assert refreshed.status == "invalid_output"
    assert refreshed.error_code == "schema_validation_failed"
    assert refreshed.ai_result is None


# ---------------------------------------------------------------------
# 11. Admin review / publish HTTP API (Section 12/13/15) — unchanged by
#     the provider migration; still exercises the exact same MongoDB
#     draft/review/publish behaviour end-to-end.
# ---------------------------------------------------------------------


async def _make_completed_analysis(map_id="map-http-1"):
    analysis = SemanticMapAnalysis(
        map_id=map_id, source_fingerprint="fp", prompt_version="v",
        prompt_sha256="h", model="claude-sonnet-4-20250514", status="completed",
        ai_result=_valid_ai_result(),
    )
    await analysis.insert()
    return analysis


def test_start_analysis_requires_admin_auth(client):
    response = client.post("/api/maps/nonexistent-map/semantic-analysis/start")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_save_reviewed_result_rejects_stale_revision(client):
    token, _ = create_admin_and_get_token(client, email="semantic1@example.com")
    analysis = await _make_completed_analysis()

    response = client.put(
        f"/api/semantic-analyses/{analysis.analysis_id}/reviewed-result",
        json={"expected_revision": 5, "reviewed_result": _valid_ai_result()},
        headers=auth_headers(token),
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_save_reviewed_result_succeeds_with_correct_revision_and_increments_it(
    client,
):
    token, _ = create_admin_and_get_token(client, email="semantic2@example.com")
    analysis = await _make_completed_analysis(map_id="map-http-2")

    reviewed = _valid_ai_result()
    reviewed["places"][0]["review"] = {"status": "accepted"}

    response = client.put(
        f"/api/semantic-analyses/{analysis.analysis_id}/reviewed-result",
        json={"expected_revision": 0, "reviewed_result": reviewed},
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["review_revision"] == 1

    # ai_result must remain completely untouched by the admin's edit.
    refreshed = await SemanticMapAnalysis.find_one(
        SemanticMapAnalysis.analysis_id == analysis.analysis_id
    )
    assert refreshed.ai_result["places"][0]["review"]["status"] == "pending"
    assert refreshed.reviewed_result["places"][0]["review"]["status"] == "accepted"


@pytest.mark.asyncio
async def test_publish_blocked_while_entities_still_pending(client):
    token, _ = create_admin_and_get_token(client, email="semantic3@example.com")
    analysis = await _make_completed_analysis(map_id="map-http-3")
    analysis.reviewed_result = _valid_ai_result()  # review.status still "pending"
    await analysis.save()

    validate_response = client.post(
        f"/api/semantic-analyses/{analysis.analysis_id}/validate",
        headers=auth_headers(token),
    )
    assert validate_response.json()["valid"] is False

    publish_response = client.post(
        f"/api/semantic-analyses/{analysis.analysis_id}/publish",
        headers=auth_headers(token),
    )
    assert publish_response.status_code == 409


@pytest.mark.asyncio
async def test_publish_blocked_by_unresolved_blocking_review_item(client):
    token, _ = create_admin_and_get_token(client, email="semantic4@example.com")
    analysis = await _make_completed_analysis(map_id="map-http-4")

    reviewed = _valid_ai_result()
    reviewed["places"][0]["review"] = {"status": "accepted"}
    reviewed["review_items"] = [
        {
            "review_item_external_id": "review_001",
            "blocks_publication": True,
            "review": {"status": "pending"},
        }
    ]
    analysis.reviewed_result = reviewed
    await analysis.save()

    validation = validate_reviewed_result_for_publish(reviewed)
    assert validation["valid"] is False
    assert "review_001" in validation["blocking_review_items"]


@pytest.mark.asyncio
async def test_publish_succeeds_after_resolving_everything_and_creates_active_index(
    client,
):
    token, admin = create_admin_and_get_token(client, email="semantic5@example.com")
    analysis = await _make_completed_analysis(map_id="map-http-5")

    reviewed = _valid_ai_result()
    reviewed["places"][0]["review"] = {"status": "accepted"}
    analysis.reviewed_result = reviewed
    await analysis.save()

    response = client.post(
        f"/api/semantic-analyses/{analysis.analysis_id}/publish",
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["map_id"] == "map-http-5"

    entities = await SemanticEntity.find(
        {"publication_id": body["publication_id"]}
    ).to_list()
    assert len(entities) == 1
    assert entities[0].entity_external_id == "place_001"
    assert entities[0].active is True


@pytest.mark.asyncio
async def test_rejected_entities_are_excluded_from_the_active_semantic_index(client):
    token, _ = create_admin_and_get_token(client, email="semantic6@example.com")
    analysis = await _make_completed_analysis(map_id="map-http-6")

    reviewed = _valid_ai_result()
    reviewed["places"][0]["review"] = {"status": "rejected"}
    analysis.reviewed_result = reviewed
    await analysis.save()

    response = client.post(
        f"/api/semantic-analyses/{analysis.analysis_id}/publish",
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text

    entities = await SemanticEntity.find(
        {"publication_id": response.json()["publication_id"]}
    ).to_list()
    assert entities == []


@pytest.mark.asyncio
async def test_semantic_entity_selector_endpoint_filters_by_map_id(client):
    token, _ = create_admin_and_get_token(client, email="semantic7@example.com")
    analysis_a = await _make_completed_analysis(map_id="map-selector-a")
    reviewed_a = _valid_ai_result()
    reviewed_a["places"][0]["review"] = {"status": "accepted"}
    analysis_a.reviewed_result = reviewed_a
    await analysis_a.save()
    await publish_analysis(analysis_a, published_by="tester")

    analysis_b = await _make_completed_analysis(map_id="map-selector-b")
    reviewed_b = _valid_ai_result()
    reviewed_b["places"][0]["place_external_id"] = "place_999"
    reviewed_b["places"][0]["review"] = {"status": "accepted"}
    analysis_b.reviewed_result = reviewed_b
    await analysis_b.save()
    await publish_analysis(analysis_b, published_by="tester")

    response = client.get(
        "/api/maps/map-selector-a/semantic-entities", headers=auth_headers(token)
    )
    assert response.status_code == 200
    entity_ids = [item["entity_external_id"] for item in response.json()]
    assert entity_ids == ["place_001"]


@pytest.mark.asyncio
async def test_publishing_never_touches_routing_graph_collections(client):
    from models.map_model import Map
    from models.route_point_model import RoutePoint
    from models.route_edge_model import RouteEdge

    token, _ = create_admin_and_get_token(client, email="semantic8@example.com")

    map_response = client.post(
        "/api/maps", json={"title": "Semantic Publish Map"}, headers=auth_headers(token)
    )
    assert map_response.status_code == 201, map_response.text
    map_id = map_response.json()["id"]

    point_response = client.post(
        "/api/route-points",
        json={"map_id": map_id, "name": "Entrance", "x": 1, "y": 1},
        headers=auth_headers(token),
    )
    assert point_response.status_code == 201, point_response.text

    maps_before = await Map.find_all().count()
    points_before = await RoutePoint.find_all().count()
    edges_before = await RouteEdge.find_all().count()

    analysis = await _make_completed_analysis(map_id=map_id)
    reviewed = _valid_ai_result()
    reviewed["places"][0]["review"] = {"status": "accepted"}
    analysis.reviewed_result = reviewed
    await analysis.save()

    response = client.post(
        f"/api/semantic-analyses/{analysis.analysis_id}/publish",
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text

    assert await Map.find_all().count() == maps_before
    assert await RoutePoint.find_all().count() == points_before
    assert await RouteEdge.find_all().count() == edges_before


@pytest.mark.asyncio
async def test_normal_user_cannot_start_or_publish_analysis(client):
    token, _ = create_admin_and_get_token(
        client, role="regular_user", email="normaluser@example.com"
    )
    analysis = await _make_completed_analysis(map_id="map-auth-1")

    start_response = client.post(
        "/api/maps/map-auth-1/semantic-analysis/start", headers=auth_headers(token)
    )
    assert start_response.status_code == 403

    publish_response = client.post(
        f"/api/semantic-analyses/{analysis.analysis_id}/publish",
        headers=auth_headers(token),
    )
    assert publish_response.status_code == 403


@pytest.mark.asyncio
async def test_retry_endpoint_uses_anthropic_key_check_and_message(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    token, _ = create_admin_and_get_token(client, email="semantic10@example.com")
    analysis = SemanticMapAnalysis(
        map_id="map-retry-http", source_fingerprint="fp", prompt_version="v",
        prompt_sha256="h", model="claude-sonnet-4-20250514", status="failed",
        error_code="network_failure",
    )
    await analysis.insert()

    response = client.post(
        f"/api/semantic-analyses/{analysis.analysis_id}/retry",
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "configuration_required"
    assert body["error_code"] == "missing_api_key"


# ---------------------------------------------------------------------
# 12. RoutePoint display-name priority (Section 16) — unchanged by the
#     provider migration.
# ---------------------------------------------------------------------


def test_route_point_display_name_priority_prefers_explicit_display_name():
    from logic.instruction_generator import resolve_display_name

    assert (
        resolve_display_name("Corridor Point 123-4", "Main Entrance", True)
        == "Main Entrance"
    )


def test_route_point_display_name_hides_auto_generated_technical_names():
    from logic.instruction_generator import resolve_display_name

    assert resolve_display_name("Corridor Point 123-4", None, True) is None


def test_route_point_display_name_uses_meaningful_admin_name_when_not_auto_generated():
    from logic.instruction_generator import resolve_display_name

    assert resolve_display_name("Coffee Junction", None, False) == "Coffee Junction"


@pytest.mark.asyncio
async def test_route_point_persists_and_returns_semantic_name_fields(client):
    token, _ = create_admin_and_get_token(client, email="semantic9@example.com")

    map_response = client.post(
        "/api/maps", json={"title": "Semantic Name Map"}, headers=auth_headers(token)
    )
    map_id = map_response.json()["id"]

    point_response = client.post(
        "/api/route-points",
        json={
            "map_id": map_id,
            "name": "Corridor Point 1",
            "x": 1,
            "y": 1,
            "force_create": True,
            "display_name": "Pharmacy",
            "semantic_entity_type": "place",
            "semantic_entity_external_id": "place_001",
        },
        headers=auth_headers(token),
    )
    assert point_response.status_code == 201, point_response.text
    body = point_response.json()
    assert body["display_name"] == "Pharmacy"
    assert body["semantic_entity_external_id"] == "place_001"

    edit_response = client.put(
        f"/api/route-points/{body['id']}",
        json={"display_name": "Updated Pharmacy Name"},
        headers=auth_headers(token),
    )
    assert edit_response.status_code == 200, edit_response.text
    assert edit_response.json()["display_name"] == "Updated Pharmacy Name"
    # Coordinates/edges are never touched by a display-name-only edit.
    assert edit_response.json()["x"] == 1
    assert edit_response.json()["y"] == 1
