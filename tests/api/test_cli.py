import pytest

from reckon_api.cli import MAX_ACCESS_TOKEN_LENGTH, read_access_token


def test_read_access_token_strips_file_whitespace(tmp_path) -> None:
    token_file = tmp_path / "access-token.txt"
    token_file.write_text("  signed-token\r\n", encoding="utf-8")

    assert read_access_token(token_file) == "signed-token"


def test_read_access_token_rejects_empty_file(tmp_path) -> None:
    token_file = tmp_path / "access-token.txt"
    token_file.write_text(" \n", encoding="utf-8")

    with pytest.raises(ValueError, match="token file is empty"):
        read_access_token(token_file)


def test_read_access_token_rejects_oversized_file(tmp_path) -> None:
    token_file = tmp_path / "access-token.txt"
    token_file.write_text("x" * (MAX_ACCESS_TOKEN_LENGTH + 1), encoding="utf-8")

    with pytest.raises(ValueError, match="maximum supported size"):
        read_access_token(token_file)
