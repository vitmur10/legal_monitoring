from app.utils.hashing import sha256_text
from app.utils.normalization import normalize_legal_text


def test_normalization_deterministic() -> None:
    left = normalize_legal_text("  має   право\r\n\r\n\r\nзобов'язаний  ")
    right = normalize_legal_text("має право\n\nзобов'язаний")
    assert left == right
    assert left == "має право\n\nзобов'язаний"


def test_hash_deterministic() -> None:
    value = "Old legal rule"
    assert sha256_text(value) == sha256_text(value)
    assert sha256_text(value) != sha256_text("New legal rule")
