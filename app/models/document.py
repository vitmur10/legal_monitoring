from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Document(Base, TimestampMixin):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("source_id", "identity_key", name="uq_documents_source_identity"),
        UniqueConstraint("source_id", "external_id", name="uq_documents_source_external_id"),
        UniqueConstraint("source_id", "canonical_url", name="uq_documents_source_canonical_url"),
        Index("ix_documents_source_seen", "source_id", "last_seen_at"),
        Index("ix_documents_type_published", "document_type", "published_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False)
    current_version_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "document_versions.id",
            name="fk_documents_current_version_id_document_versions",
            ondelete="SET NULL",
            use_alter=True,
        )
    )

    identity_key: Mapped[str] = mapped_column(String(512), nullable=False)
    identity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(512))
    canonical_url: Mapped[str | None] = mapped_column(String(2048))
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    document_type: Mapped[str | None] = mapped_column(String(128))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    source = relationship("Source", back_populates="documents")
    versions = relationship(
        "DocumentVersion",
        back_populates="document",
        foreign_keys="DocumentVersion.document_id",
        order_by="DocumentVersion.version_number",
        cascade="all, delete-orphan",
    )
    current_version = relationship("DocumentVersion", foreign_keys=[current_version_id], post_update=True)
    outgoing_relations = relationship(
        "DocumentRelation",
        back_populates="from_document",
        foreign_keys="DocumentRelation.from_document_id",
        cascade="all, delete-orphan",
    )
    incoming_relations = relationship(
        "DocumentRelation",
        back_populates="to_document",
        foreign_keys="DocumentRelation.to_document_id",
        cascade="all, delete-orphan",
    )
