import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


# See Section 7 of the semantic-map-analysis spec. Every status an
# analysis can be in — the background worker and the API routes are the
# only things allowed to move a document between these states.
AnalysisStatus = Literal[
    "queued",
    "processing",
    "completed",
    "invalid_output",
    "failed",
    "configuration_required",
    "superseded",
    "cancelled",
]

ScopeType = Literal["map", "map_group"]

ReviewStatus = Literal["pending", "in_progress", "reviewed", "published"]


class LocalValidationResult(dict):
    """Plain-dict shape kept intentionally loose (not a StrictModel) since
    it stores {"valid": bool, "errors": [...], "warnings": [...]} produced
    by semantic_analysis_service's local Pydantic validation pass — never
    itself sent to or parsed as AI output."""


class SemanticMapAnalysis(Document):
    """
    AI Extraction Draft — Layer (A) of the three-layer architecture (see
    Section 2). Stores exactly what the AI returned (`ai_result`, never
    mutated after the analysis completes), plus whatever the admin has
    edited so far (`reviewed_result`, a separate, independently-evolving
    document). This collection is never read by the routing graph
    (RoutePoints/RouteEdges) directly — only an explicit publish action
    (see SemanticMapPublication) can make reviewed data available for
    RoutePoint naming, and even then never as graph data.
    """

    analysis_id: str = Field(default_factory=lambda: uuid.uuid4().hex)

    scope_type: ScopeType = "map"

    # Single-map analysis: map_id is the one Map being analysed.
    # Map-group analysis: map_id is None, map_group_id + source_map_ids
    # describe every floor Map included in this one combined analysis.
    map_id: Optional[str] = None
    map_group_id: Optional[str] = None
    building_id: Optional[str] = None
    source_map_ids: List[str] = Field(default_factory=list)

    source_filenames: List[str] = Field(default_factory=list)
    # SHA-256 of the concatenated source file bytes used for this
    # analysis — see Section 8 (Source Fingerprint and Idempotency).
    source_fingerprint: str

    prompt_version: str
    prompt_sha256: str
    model: str

    status: AnalysisStatus = "queued"
    progress: int = Field(default=0, ge=0, le=100)
    attempt_count: int = 0

    # Which AI provider produced (or will produce) ai_result. Provider-
    # neutral by design — new code should never need to special-case a
    # provider string outside this field and the error-mapping table in
    # semantic_analysis_service.py.
    provider: Optional[str] = "anthropic"

    # Provider-neutral message/request id, kept for support/debugging
    # only — never exposed to normal users (Section 19). Populated from
    # Anthropic's Message.id since the migration to Claude.
    provider_response_id: Optional[str] = None

    # DEPRECATED — kept only for backward compatibility with analysis
    # records created before the Anthropic migration, which stored the
    # OpenAI Responses API response id here. No longer written by any
    # current code path; new records use provider_response_id instead.
    openai_response_id: Optional[str] = None

    # Raw AI JSON exactly as returned and locally validated. Never
    # rewritten once status becomes "completed".
    ai_result: Optional[Dict[str, Any]] = None

    # Admin-edited copy. Starts as None; the first successful
    # PUT .../reviewed-result call initializes it. Never overwrites
    # ai_result.
    reviewed_result: Optional[Dict[str, Any]] = None
    review_revision: int = 0
    review_status: ReviewStatus = "pending"

    local_validation: Optional[Dict[str, Any]] = None

    error_code: Optional[str] = None
    error_message: Optional[str] = None

    created_by: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Set when this analysis has been published (see
    # SemanticMapPublication) — points at the publication document, not
    # the other way around, so an analysis always knows its own
    # publication history without a reverse query.
    published_analysis_id: Optional[str] = None
    published_at: Optional[datetime] = None

    # Worker bookkeeping: which "processing" claim owns this job right
    # now, and when that claim was made — used to detect and safely
    # requeue stale/crashed jobs (Section 10).
    worker_claim_id: Optional[str] = None
    processing_started_at: Optional[datetime] = None

    class Settings:
        name = "semantic_map_analyses"
        indexes = [
            IndexModel("analysis_id", unique=True),
            IndexModel("map_id"),
            IndexModel("map_group_id"),
            IndexModel("status"),
            IndexModel("source_fingerprint"),
            IndexModel("prompt_sha256"),
            IndexModel("created_at"),
        ]
