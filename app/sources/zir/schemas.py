from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ZirStatus(StrEnum):
    CURRENT = "CURRENT"
    NON_CURRENT = "NON_CURRENT"
    UNKNOWN = "UNKNOWN"


class ZirCategory(BaseModel):
    id: str
    code: str | None = None
    title: str
    parent_id: str | None = None
    raw_label: str


class ZirNormativeReference(BaseModel):
    reference_type: str
    number: str | None = None
    article: str | None = None
    paragraph: str | None = None
    text: str


class ZirConsultationStub(BaseModel):
    id: str
    external_id: str
    question: str
    category: str | None = None
    status: ZirStatus = ZirStatus.UNKNOWN
    status_text: str | None = None
    canonical_url: str
    src: str = "ques"


class ZirSearchResult(BaseModel):
    count: int | None = None
    items: list[ZirConsultationStub] = Field(default_factory=list)


class ZirAnswer(BaseModel):
    short_answer: str | None = None
    full_answer: str | None = None
    comments: list[str] = Field(default_factory=list)
    raw_text: str


class ZirConsultation(BaseModel):
    id: str
    external_id: str
    canonical_url: str
    src: str = "ques"
    question: str
    short_answer: str | None = None
    full_answer: str | None = None
    status: ZirStatus = ZirStatus.UNKNOWN
    status_text: str | None = None
    category: str | None = None
    comments: list[str] = Field(default_factory=list)
    normative_references: list[ZirNormativeReference] = Field(default_factory=list)
