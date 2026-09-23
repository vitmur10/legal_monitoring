from app.diff import ChangeType, DocumentDiffEngine


def test_diff_engine_detects_no_change() -> None:
    result = DocumentDiffEngine().build(
        document_id=1,
        previous_version_id=10,
        current_version_id=11,
        previous_text="Пункт 1. Стара норма.\n\nПункт 2. Без змін.",
        current_text="Пункт 1. Стара норма.\n\nПункт 2. Без змін.",
    )

    assert result.changed is False
    assert result.summary_stats.added_blocks == 0
    assert result.changes == []


def test_diff_engine_detects_added_removed_and_modified_blocks() -> None:
    result = DocumentDiffEngine().build(
        document_id=1,
        previous_version_id=10,
        current_version_id=11,
        previous_text="Пункт 1. Декларація подається до 20 числа.\n\nПункт 2. Скасувати форму.",
        current_text=(
            "Пункт 1. Декларація подається до 25 числа.\n\n"
            "Пункт 3. Додати новий додаток до декларації."
        ),
    )

    assert result.changed is True
    assert result.summary_stats.changed_blocks == 1
    assert result.summary_stats.added_blocks == 1
    assert result.summary_stats.removed_blocks == 1
    assert [change.change_type for change in result.changes] == [
        ChangeType.MODIFIED,
        ChangeType.REMOVED,
        ChangeType.ADDED,
    ]
    assert "20 числа" in (result.changes[0].previous_text or "")
    assert "25 числа" in (result.changes[0].current_text or "")


def test_diff_engine_ignores_obvious_technical_noise() -> None:
    result = DocumentDiffEngine().build(
        document_id=1,
        previous_version_id=10,
        current_version_id=11,
        previous_text="Оновлено: 01.01.2026\n\nПункт 1. Без змін.",
        current_text="Оновлено: 02.01.2026\n\nПункт 1. Без змін.",
    )

    assert result.changed is False
