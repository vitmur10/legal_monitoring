from difflib import SequenceMatcher
import re

from app.diff.schemas import ChangeType, DiffBlock, DiffSummaryStats, DocumentDiffResult


TECHNICAL_NOISE_PATTERNS = (
    re.compile(r"^\s*(оновлено|дата\s+оновлення|last\s+updated)\s*[:：]", re.IGNORECASE),
    re.compile(r"^\s*(print|share|версія для друку)\s*$", re.IGNORECASE),
)


class DocumentDiffEngine:
    def __init__(
        self, context_blocks: int = 1, max_changes: int = 250, modified_similarity_floor: float = 0.45
    ) -> None:
        self.context_blocks = context_blocks
        self.max_changes = max_changes
        self.modified_similarity_floor = modified_similarity_floor

    def build(
        self,
        *,
        document_id: int,
        previous_version_id: int | None,
        current_version_id: int,
        previous_text: str | None,
        current_text: str,
    ) -> DocumentDiffResult:
        previous_blocks = self._split_blocks(previous_text or "")
        current_blocks = self._split_blocks(current_text)
        matcher = SequenceMatcher(a=previous_blocks, b=current_blocks, autojunk=False)
        changes: list[DiffBlock] = []
        truncated = False

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            if len(changes) >= self.max_changes:
                truncated = True
                break
            if tag == "insert":
                for offset, block in enumerate(current_blocks[j1:j2]):
                    changes.append(
                        self._block(
                            ChangeType.ADDED,
                            f"block:{j1 + offset + 1}",
                            None,
                            block,
                            previous_blocks,
                            current_blocks,
                            i1,
                            j1 + offset,
                        )
                    )
            elif tag == "delete":
                for offset, block in enumerate(previous_blocks[i1:i2]):
                    changes.append(
                        self._block(
                            ChangeType.REMOVED,
                            f"block:{i1 + offset + 1}",
                            block,
                            None,
                            previous_blocks,
                            current_blocks,
                            i1 + offset,
                            j1,
                        )
                    )
            elif tag == "replace":
                changes.extend(
                    self._modified_blocks(previous_blocks, current_blocks, i1, i2, j1, j2)
                )
            if len(changes) > self.max_changes:
                changes = changes[: self.max_changes]
                truncated = True
                break

        stats = DiffSummaryStats(
            added_blocks=sum(1 for item in changes if item.change_type == ChangeType.ADDED),
            removed_blocks=sum(1 for item in changes if item.change_type == ChangeType.REMOVED),
            changed_blocks=sum(1 for item in changes if item.change_type == ChangeType.MODIFIED),
        )
        return DocumentDiffResult(
            document_id=document_id,
            previous_version_id=previous_version_id,
            current_version_id=current_version_id,
            changed=bool(changes),
            summary_stats=stats,
            changes=changes,
            truncated=truncated,
        )

    def _modified_blocks(
        self,
        previous_blocks: list[str],
        current_blocks: list[str],
        i1: int,
        i2: int,
        j1: int,
        j2: int,
    ) -> list[DiffBlock]:
        previous_slice = previous_blocks[i1:i2]
        current_slice = current_blocks[j1:j2]
        changes: list[DiffBlock] = []
        paired = min(len(previous_slice), len(current_slice))
        for offset in range(paired):
            previous_text = previous_slice[offset]
            current_text = current_slice[offset]
            similarity = SequenceMatcher(None, previous_text, current_text, autojunk=False).ratio()
            if similarity < self.modified_similarity_floor:
                changes.append(
                    self._block(
                        ChangeType.REMOVED,
                        f"block:{i1 + offset + 1}",
                        previous_text,
                        None,
                        previous_blocks,
                        current_blocks,
                        i1 + offset,
                        j1 + offset,
                    )
                )
                changes.append(
                    self._block(
                        ChangeType.ADDED,
                        f"block:{j1 + offset + 1}",
                        None,
                        current_text,
                        previous_blocks,
                        current_blocks,
                        i1 + offset,
                        j1 + offset,
                    )
                )
                continue
            changes.append(
                self._block(
                    ChangeType.MODIFIED,
                    f"block:{j1 + offset + 1}",
                    previous_text,
                    current_text,
                    previous_blocks,
                    current_blocks,
                    i1 + offset,
                    j1 + offset,
                    similarity,
                )
            )
        for offset, block in enumerate(previous_slice[paired:]):
            changes.append(
                self._block(
                    ChangeType.REMOVED,
                    f"block:{i1 + paired + offset + 1}",
                    block,
                    None,
                    previous_blocks,
                    current_blocks,
                    i1 + paired + offset,
                    j2,
                )
            )
        for offset, block in enumerate(current_slice[paired:]):
            changes.append(
                self._block(
                    ChangeType.ADDED,
                    f"block:{j1 + paired + offset + 1}",
                    None,
                    block,
                    previous_blocks,
                    current_blocks,
                    i2,
                    j1 + paired + offset,
                )
            )
        return changes

    def _block(
        self,
        change_type: ChangeType,
        locator: str,
        previous_text: str | None,
        current_text: str | None,
        previous_blocks: list[str],
        current_blocks: list[str],
        previous_index: int,
        current_index: int,
        similarity_score: float | None = None,
    ) -> DiffBlock:
        return DiffBlock(
            locator=locator,
            previous_text=previous_text,
            current_text=current_text,
            change_type=change_type,
            similarity_score=similarity_score,
            previous_context=self._context(previous_blocks, previous_index),
            current_context=self._context(current_blocks, current_index),
        )

    def _context(self, blocks: list[str], index: int) -> str | None:
        if not blocks:
            return None
        start = max(index - self.context_blocks, 0)
        end = min(index + self.context_blocks + 1, len(blocks))
        context = "\n".join(blocks[start:end]).strip()
        return context or None

    def _split_blocks(self, text: str) -> list[str]:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        raw_blocks = re.split(r"\n\s*\n|(?<=\.)\s*\n(?=[А-ЯA-ZІЇЄҐ0-9])", normalized)
        blocks = []
        for block in raw_blocks:
            cleaned = re.sub(r"[ \t\xa0]+", " ", block).strip()
            if not cleaned or any(pattern.search(cleaned) for pattern in TECHNICAL_NOISE_PATTERNS):
                continue
            blocks.append(cleaned)
        return blocks
