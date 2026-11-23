from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field


JobStatus = Literal[
    "new",
    "shortlisted",
    "applied",
    "interviewing",
    "archived",
    "filtered_out",
]


class SourceUrl(BaseModel):
    source: str
    url: str


class RawJob(BaseModel):
    company: str
    title: str
    location_raw: str = ""
    description: str = ""
    source: str
    url: str


class LLMAnalysis(BaseModel):
    match_score: int = Field(ge=1, le=10)
    role_track: str = "Engineering Leadership"
    location_policy: str = "Unspecified"
    relocation_or_visa_note: str = ""
    summary: str = ""
    match_reasons: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    tailoring_angle: str = ""
    scored_by: str = "llm"


class TailoredPitch(BaseModel):
    cv_summary: str
    emphasized_bullets: list[str] = Field(default_factory=list)
    outreach_message: str
    generated_by: str = "llm"
    generated_at: datetime


class JobDocument(BaseModel):
    id: str
    dedup_hash: str
    company: str
    title: str
    location_raw: str = ""
    description: str = ""
    source_urls: list[SourceUrl] = Field(default_factory=list)
    status: JobStatus = "new"
    match_score: Optional[int] = None
    role_track: Optional[str] = None
    location_policy: Optional[str] = None
    llm_analysis: Optional[LLMAnalysis] = None
    tailored_pitch: Optional[TailoredPitch] = None
    notes: str = ""
    filter_reason: Optional[str] = None
    first_seen_at: datetime
    last_seen_at: datetime
    updated_at: datetime


class JobUpdateRequest(BaseModel):
    status: Optional[JobStatus] = None
    notes: Optional[str] = None


class ManualJobRequest(BaseModel):
    company: Optional[str] = None
    title: Optional[str] = None
    location_raw: Optional[str] = ""
    url: Optional[str] = ""
    description: Optional[str] = ""


class ScrapeRunDocument(BaseModel):
    id: str
    connector_name: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    status: Literal["running", "success", "failed", "skipped"] = "running"
    jobs_fetched: int = 0
    jobs_new: int = 0
    jobs_scored: int = 0
    jobs_filtered: int = 0
    tokens_used: int = 0
    error_message: Optional[str] = None


class IntegrationSettingsPayload(BaseModel):
    llm_base_url: str = "https://api.minimax.io/v1"
    llm_api_key: str = ""
    llm_model: str = "MiniMax-M1"
    llm_tailor_model: str = "MiniMax-M1"
    max_llm_scores_per_run: int = 50
    apify_token: str = ""
    serpapi_key: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    dashboard_public_url: str = "https://job-seeker.fluffy-oratrice.ts.net"


class AppConfigPayload(BaseModel):
    cv_markdown: str
    preferences_yaml: str
    companies_yaml: str
    integrations: Optional[IntegrationSettingsPayload] = None
