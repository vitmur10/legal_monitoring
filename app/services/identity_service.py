from dataclasses import dataclass

from app.sources.base import NormalizedDocument
from app.utils.hashing import sha256_text


@dataclass(frozen=True)
class DocumentIdentity:
    identity_type: str
    identity_key: str


class DocumentIdentityService:
    def identify(self, document: NormalizedDocument, content_hash: str) -> DocumentIdentity:
        if document.external_id:
            return DocumentIdentity("external_id", f"external_id:{document.external_id}")
        if document.canonical_url:
            return DocumentIdentity("canonical_url", f"canonical_url:{document.canonical_url}")

        published = document.published_at.isoformat() if document.published_at else ""
        fallback_base = "|".join(
            [
                document.source_code,
                document.title.strip(),
                document.document_type or "",
                published,
                content_hash,
            ]
        )
        return DocumentIdentity("fallback_content", f"fallback:{sha256_text(fallback_base)}")
