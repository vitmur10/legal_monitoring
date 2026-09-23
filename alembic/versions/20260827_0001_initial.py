"""initial schema

Revision ID: 20260827_0001
Revises:
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260827_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("base_url", sa.String(length=2048), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("check_interval_minutes", sa.Integer(), server_default="60", nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sources")),
        sa.UniqueConstraint("code", name="uq_sources_code"),
    )
    op.create_index(op.f("ix_sources_code"), "sources", ["code"], unique=False)

    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("current_version_id", sa.Integer(), nullable=True),
        sa.Column("identity_key", sa.String(length=512), nullable=False),
        sa.Column("identity_type", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=512), nullable=True),
        sa.Column("canonical_url", sa.String(length=2048), nullable=True),
        sa.Column("title", sa.String(length=1024), nullable=False),
        sa.Column("document_type", sa.String(length=128), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], name=op.f("fk_documents_source_id_sources"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint("source_id", "canonical_url", name="uq_documents_source_canonical_url"),
        sa.UniqueConstraint("source_id", "external_id", name="uq_documents_source_external_id"),
        sa.UniqueConstraint("source_id", "identity_key", name="uq_documents_source_identity"),
    )
    op.create_index("ix_documents_source_seen", "documents", ["source_id", "last_seen_at"], unique=False)
    op.create_index("ix_documents_type_published", "documents", ["document_type", "published_at"], unique=False)

    op.create_table(
        "document_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("raw_content", sa.Text(), nullable=False),
        sa.Column("normalized_content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("version_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], name=op.f("fk_document_versions_document_id_documents"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_versions")),
        sa.UniqueConstraint("document_id", "content_hash", name="uq_document_versions_hash"),
        sa.UniqueConstraint("document_id", "version_number", name="uq_document_versions_number"),
    )
    op.create_index("ix_document_versions_content_hash", "document_versions", ["content_hash"], unique=False)
    op.create_index("ix_document_versions_document_detected", "document_versions", ["document_id", "detected_at"], unique=False)
    op.create_foreign_key(
        op.f("fk_documents_current_version_id_document_versions"),
        "documents",
        "document_versions",
        ["current_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "document_relations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("from_document_id", sa.Integer(), nullable=False),
        sa.Column("to_document_id", sa.Integer(), nullable=False),
        sa.Column("relation_type", sa.Enum("AMENDS", "AMENDED_BY", "EXPLAINS", "EXPLAINED_BY", "IMPLEMENTS", "IMPLEMENTED_BY", "RELATED_TO", "SUPERSEDES", "SUPERSEDED_BY", native_enum=False, length=32), nullable=False),
        sa.Column("relation_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["from_document_id"], ["documents.id"], name=op.f("fk_document_relations_from_document_id_documents"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_document_id"], ["documents.id"], name=op.f("fk_document_relations_to_document_id_documents"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_relations")),
        sa.UniqueConstraint("from_document_id", "to_document_id", "relation_type", name="uq_document_relations_edge"),
    )
    op.create_index("ix_document_relations_from", "document_relations", ["from_document_id"], unique=False)
    op.create_index("ix_document_relations_to", "document_relations", ["to_document_id"], unique=False)

    op.create_table(
        "monitoring_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Enum("RUNNING", "COMPLETED", "FAILED", native_enum=False, length=32), nullable=False),
        sa.Column("items_found", sa.Integer(), server_default="0", nullable=False),
        sa.Column("new_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("changed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("unchanged_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], name=op.f("fk_monitoring_runs_source_id_sources"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_monitoring_runs")),
    )


def downgrade() -> None:
    op.drop_table("monitoring_runs")
    op.drop_index("ix_document_relations_to", table_name="document_relations")
    op.drop_index("ix_document_relations_from", table_name="document_relations")
    op.drop_table("document_relations")
    op.drop_constraint(op.f("fk_documents_current_version_id_document_versions"), "documents", type_="foreignkey")
    op.drop_index("ix_document_versions_document_detected", table_name="document_versions")
    op.drop_index("ix_document_versions_content_hash", table_name="document_versions")
    op.drop_table("document_versions")
    op.drop_index("ix_documents_type_published", table_name="documents")
    op.drop_index("ix_documents_source_seen", table_name="documents")
    op.drop_table("documents")
    op.drop_index(op.f("ix_sources_code"), table_name="sources")
    op.drop_table("sources")
