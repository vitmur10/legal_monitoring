import datetime as dt
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, field_validator


class RelevanceCategory(StrEnum):
    VAT = "VAT"
    CORPORATE_INCOME_TAX = "CORPORATE_INCOME_TAX"
    PIT = "PIT"
    MILITARY_TAX = "MILITARY_TAX"
    SSC = "SSC"
    EXCISE = "EXCISE"
    SINGLE_TAX = "SINGLE_TAX"
    TRANSFER_PRICING = "TRANSFER_PRICING"
    CFC = "CFC"
    INTERNATIONAL_TAX = "INTERNATIONAL_TAX"
    CRS = "CRS"
    BEPS = "BEPS"
    TAX_AUDIT = "TAX_AUDIT"
    PENALTIES = "PENALTIES"
    TAX_REPORTING = "TAX_REPORTING"
    PN_RK = "PN_RK"
    SMKOR = "SMKOR"
    RRO_PRRO = "RRO_PRRO"
    SAF_T_UA = "SAF_T_UA"
    E_AUDIT = "E_AUDIT"
    ACCOUNTING = "ACCOUNTING"
    FINANCIAL_REPORTING = "FINANCIAL_REPORTING"
    PRIMARY_DOCUMENTS = "PRIMARY_DOCUMENTS"
    IFRS = "IFRS"
    EU_TAX_INTEGRATION = "EU_TAX_INTEGRATION"
    DAC = "DAC"
    E_INVOICING = "E_INVOICING"
    OTHER_RELEVANT = "OTHER_RELEVANT"


class DocumentStatus(StrEnum):
    DRAFT = "DRAFT"
    ADOPTED = "ADOPTED"
    SIGNED = "SIGNED"
    PUBLISHED = "PUBLISHED"
    EFFECTIVE = "EFFECTIVE"
    EXPIRED = "EXPIRED"
    NON_CURRENT = "NON_CURRENT"
    EXPLANATION = "EXPLANATION"
    OTHER = "OTHER"
    NOT_DETERMINED = "NOT_DETERMINED"


class AffectedEntity(StrEnum):
    ALL_TAXPAYERS = "ALL_TAXPAYERS"
    LEGAL_ENTITIES = "LEGAL_ENTITIES"
    VAT_PAYERS = "VAT_PAYERS"
    CORPORATE_INCOME_TAX_PAYERS = "CORPORATE_INCOME_TAX_PAYERS"
    FOP = "FOP"
    EMPLOYERS = "EMPLOYERS"
    TAX_AGENTS = "TAX_AGENTS"
    SINGLE_TAX_PAYERS = "SINGLE_TAX_PAYERS"
    LARGE_TAXPAYERS = "LARGE_TAXPAYERS"
    FINANCIAL_INSTITUTIONS = "FINANCIAL_INSTITUTIONS"
    INTERNATIONAL_BUSINESS = "INTERNATIONAL_BUSINESS"
    CONTROLLED_TRANSACTION_PARTICIPANTS = "CONTROLLED_TRANSACTION_PARTICIPANTS"
    CFC_OWNERS = "CFC_OWNERS"
    SPECIFIC_INDUSTRY = "SPECIFIC_INDUSTRY"
    OTHER = "OTHER"


class Importance(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class RiskType(StrEnum):
    financial = "financial"
    tax = "tax"
    penalty = "penalty"
    reporting = "reporting"
    operational = "operational"
    other = "other"


class DecisionMetadata(BaseModel):
    decision: str
    confidence_band: str


class RelevanceResult(BaseModel):
    relevant: bool
    categories: list[RelevanceCategory] = Field(default_factory=list)
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    decision_metadata: DecisionMetadata | None = None

    @field_validator("categories")
    @classmethod
    def categories_must_be_list(cls, value: list[RelevanceCategory]) -> list[RelevanceCategory]:
        return value or []


class Evidence(BaseModel):
    version_id: int | None = None
    text_excerpt: str
    source_url: str | None = None


class AnalyzedChange(BaseModel):
    provision: str | None = None
    before: str | None = None
    after: str | None = None
    explanation: str
    evidence: list[Evidence] = Field(default_factory=list)


class Deadline(BaseModel):
    date: dt.date | None = None
    description: str


class Risk(BaseModel):
    type: RiskType
    description: str


class KnowledgeBaseRecommendation(StrEnum):
    RECOMMENDED = "RECOMMENDED"
    OPTIONAL = "OPTIONAL"
    NOT_RECOMMENDED = "NOT_RECOMMENDED"


class KnowledgeBaseRecommendationResult(BaseModel):
    recommendation: KnowledgeBaseRecommendation = KnowledgeBaseRecommendation.OPTIONAL
    reason: str = "Рекомендацію не сформовано; рішення приймає користувач"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class FullAnalysisResult(BaseModel):
    knowledge_base_recommendation: KnowledgeBaseRecommendationResult = Field(default_factory=KnowledgeBaseRecommendationResult)
    relevant: bool = True
    categories: list[RelevanceCategory] = Field(default_factory=list)
    document_status: DocumentStatus
    document_date: dt.date | None = None
    effective_date: dt.date | None = None
    application_date: dt.date | None = None
    document_number: str | None = None
    document_type: str | None = None
    issuing_authority: str | None = None
    topics: list[str] = Field(default_factory=list)
    summary: str
    changes: list[AnalyzedChange] = Field(default_factory=list)
    affected_entities: list[AffectedEntity] = Field(default_factory=list)
    affected_entities_explanation: str
    practical_impact: str
    required_actions: list[str] = Field(default_factory=list)
    deadlines: list[Deadline] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)
    importance: Importance
    importance_reason: str
    official_source_url: str | None = None
    missing_information: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class ContentGenerationResult(BaseModel):
    knowledge_base_recommendation: KnowledgeBaseRecommendationResult = Field(default_factory=KnowledgeBaseRecommendationResult)
    knowledge_base_article: str = Field(min_length=80)
    telegram_post: str = Field(min_length=40)
    content_warnings: list[str] = Field(default_factory=list)


class Stage2Input(BaseModel):
    source_code: str
    document_id: int
    current_version_id: int
    previous_version_id: int | None = None
    title: str
    document_type: str | None = None
    normalized_text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    official_url: HttpUrl | str | None = None
    document_status: DocumentStatus | None = None
