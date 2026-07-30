"""
Loader for the ONE fixed, versioned semantic-map-analysis prompt.

This module deliberately does very little: it reads exactly one file from
disk (backend/prompts/quickroute_semantic_map_import_v2.txt), verifies it is
non-empty, and exposes its exact text plus a stable version string and a
SHA-256 hash of the exact bytes on disk.

Non-negotiable rules this module exists to enforce (see the task spec):
  - The prompt text lives ONLY in this backend file. It is never accepted
    from an API request body, never stored in `.env`, never editable from
    the browser, and never silently appended to.
  - Every analysis record must persist the prompt_version and prompt_sha256
    that were actually used, so a later edit to the prompt file produces a
    new hash (and therefore a new, distinguishable analysis revision)
    instead of silently changing the meaning of old, already-stored
    analyses.
  - If the file is missing or empty, loading must fail loudly and safely
    (never fall back to some other in-memory/default prompt text).
"""

import hashlib
from functools import lru_cache
from pathlib import Path

PROMPT_VERSION = "quickroute_semantic_map_import_v2"

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROMPT_FILE_PATH = (
    BACKEND_DIR / "prompts" / "quickroute_semantic_map_import_v2.txt"
)


class SemanticPromptLoadError(RuntimeError):
    """
    Raised when the fixed semantic-analysis prompt file cannot be safely
    loaded (missing, unreadable, or empty). Callers must treat this as a
    configuration problem, not an AI-provider/analysis failure — see
    error_code "prompt_unavailable" in semantic_analysis_service.py.
    """


@lru_cache(maxsize=1)
def _read_prompt_file_bytes() -> bytes:
    # Deliberately read raw bytes (not `Path.read_text`, which performs
    # universal-newline translation and would silently rewrite CRLF line
    # endings to LF — changing the exact bytes that get hashed/sent to
    # the AI provider even though the *visible* text looks identical).
    # The prompt file must be hashed and transmitted exactly as it sits
    # on disk.
    try:
        data = PROMPT_FILE_PATH.read_bytes()
    except FileNotFoundError as error:
        raise SemanticPromptLoadError(
            "The fixed semantic-analysis prompt file is missing: "
            f"{PROMPT_FILE_PATH}"
        ) from error
    except OSError as error:
        raise SemanticPromptLoadError(
            "The fixed semantic-analysis prompt file could not be read: "
            f"{PROMPT_FILE_PATH} ({error})"
        ) from error

    if not data.strip():
        raise SemanticPromptLoadError(
            "The fixed semantic-analysis prompt file is empty: "
            f"{PROMPT_FILE_PATH}"
        )

    return data


@lru_cache(maxsize=1)
def _read_prompt_file() -> str:
    data = _read_prompt_file_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SemanticPromptLoadError(
            "The fixed semantic-analysis prompt file is not valid UTF-8: "
            f"{PROMPT_FILE_PATH} ({error})"
        ) from error


def clear_prompt_cache() -> None:
    """
    Test/dev-only helper: forces the next load to re-read the file from
    disk (e.g. after a test writes a temporary prompt file, or to observe
    a hash change after editing the real prompt file without restarting
    the process).
    """

    _read_prompt_file.cache_clear()
    _read_prompt_file_bytes.cache_clear()


def get_prompt_text() -> str:
    """
    Returns the exact, unmodified prompt text. Raises
    SemanticPromptLoadError if the file is missing or empty. Never
    shortens, rewrites, or otherwise alters the text.
    """

    return _read_prompt_file()


def get_prompt_version() -> str:
    return PROMPT_VERSION


def get_prompt_sha256() -> str:
    """
    SHA-256 hex digest of the exact prompt file bytes (UTF-8 encoded text,
    matching what is actually sent to the AI provider). A single-character
    edit to the prompt file changes this hash, which is exactly what lets callers
    detect "the prompt changed since this analysis was created" and treat
    it as a new revision rather than silently reusing stale results.
    """

    data = _read_prompt_file_bytes()
    return hashlib.sha256(data).hexdigest()


def get_prompt_info() -> dict:
    """
    Safe-to-expose-to-admins bundle: version + hash only. Never includes
    the prompt text itself in this summary (admins can view the full text
    via a dedicated, explicitly-authorised endpoint if needed — see
    Section 19's "normal users must never see... prompt text" rule, which
    this helper's shape makes easy to respect by default).
    """

    return {
        "prompt_version": get_prompt_version(),
        "prompt_sha256": get_prompt_sha256(),
    }
