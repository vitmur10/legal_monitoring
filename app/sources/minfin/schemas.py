from __future__ import annotations

from datetime import date as Date
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class MinfinDocumentType(StrEnum):
    NEWS = "NEWS"
    TAX_POLICY = "TAX_POLICY"
    GENERAL_TAX_CONSULTATION = "GENERAL_TAX_CONSULTATION"
    ORDER = "ORDER"
    ACCOUNTING = "ACCOUNTING"
    FINANCIAL_REPORTING = "FINANCIAL_REPORTING"
    CRS = "CRS"
    OTHER = "OTHER"


class MinfinAttachment(BaseModel):
    label: str
    url: str
    extension: str
    content_type: str | None = None
    source_context: str


class MinfinDocumentReference(BaseModel):
    kind: str
    number: str | None = None
    date: Date | None = None
    url: str | None = None
    text: str


class MinfinDocumentStub(BaseModel):
    external_id: str
    title: str
    source_url: str
    canonical_url: str
    document_type: MinfinDocumentType = MinfinDocumentType.OTHER
    published_at: datetime | None = None
    metadata: dict = Field(default_factory=dict)


class MinfinOrderStub(BaseModel):
    external_id: str
    row_date: Date | None = None
    order_date: Date
    order_number: str
    title: str
    source_url: str
    canonical_url: str
    attachments: list[MinfinAttachment] = Field(default_factory=list)
    references: list[MinfinDocumentReference] = Field(default_factory=list)
    document_type: MinfinDocumentType = MinfinDocumentType.ORDER


class MinfinConsultationStub(BaseModel):
    external_id: str
    row_date: Date | None = None
    order_date: Date
    order_number: str
    title: str
    source_url: str
    canonical_url: str
    attachments: list[MinfinAttachment] = Field(default_factory=list)
    references: list[MinfinDocumentReference] = Field(default_factory=list)
    tax_code_references: list[str] = Field(default_factory=list)
    document_type: MinfinDocumentType = MinfinDocumentType.GENERAL_TAX_CONSULTATION


class MinfinParsedPage(BaseModel):
    external_id: str
    title: str
    canonical_url: str
    source_url: str
    document_type: MinfinDocumentType
    body: str
    published_at: datetime | None = None
    effective_at: datetime | None = None
    attachments: list[MinfinAttachment] = Field(default_factory=list)
    references: list[MinfinDocumentReference] = Field(default_factory=list)
