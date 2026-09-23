from typing import Any

from sqlalchemy import Enum, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, empty_json, json_type
from app.models.enums import RelationType


class DocumentRelation(Base, TimestampMixin):
    __tablename__ = "document_relations"
    __table_args__ = (
        UniqueConstraint(
            "from_document_id",
            "to_document_id",
            "relation_type",
            name="uq_document_relations_edge",
        ),
        Index("ix_document_relations_from", "from_document_id"),
        Index("ix_document_relations_to", "to_document_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    from_document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    to_document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    relation_type: Mapped[RelationType] = mapped_column(
        Enum(RelationType, native_enum=False, length=32), nullable=False
    )
    relation_metadata: Mapped[dict[str, Any]] = mapped_column(json_type, default=empty_json, nullable=False)

    from_document = relationship(
        "Document", back_populates="outgoing_relations", foreign_keys=[from_document_id]
    )
    to_document = relationship(
        "Document", back_populates="incoming_relations", foreign_keys=[to_document_id]
    )
