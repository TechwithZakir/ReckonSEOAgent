import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from uuid import uuid4

from reckon_api import cli
from reckon_api.cli import MAX_ACCESS_TOKEN_LENGTH, read_access_token
from reckon_api.config import Settings
from reckon_core.persistence import Base, NativeAccount, PlatformAdministrator, User


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


def test_bootstrap_admin_uses_private_prompt_and_refuses_replacement(tmp_path, monkeypatch, capsys) -> None:
    url = f"sqlite+pysqlite:///{tmp_path / 'auth.db'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    settings = Settings(_env_file=None, environment="local", database_url=SecretStr(url))
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "fixture-password-123")
    assert cli.bootstrap_admin("admin@example.com", settings) == 0
    assert cli.bootstrap_admin("another@example.com", settings) == 1
    output = capsys.readouterr()
    assert "fixture-password-123" not in output.out + output.err
    with Session(engine) as session:
        admin = session.get(PlatformAdministrator, 1)
        assert admin is not None
        account = session.get(NativeAccount, admin.user_id)
        assert account is not None and account.email == "admin@example.com"
        assert account.password_hash.startswith("$argon2id$")
        assert session.scalar(select(NativeAccount).where(NativeAccount.email == "another@example.com")) is None
    engine.dispose()


def test_bootstrap_admin_rejects_noninteractive_and_nonlocal(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    assert cli.bootstrap_admin("admin@example.com", Settings(_env_file=None, environment="local")) == 1
    assert cli.bootstrap_admin("admin@example.com", Settings(_env_file=None, environment="staging")) == 1
    assert "interactive terminal" in capsys.readouterr().err


def test_bootstrap_does_not_promote_an_existing_account(tmp_path, monkeypatch) -> None:
    url = f"sqlite+pysqlite:///{tmp_path / 'auth.db'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(id=uuid4())
        session.add(user)
        session.flush()
        session.add(NativeAccount(user_id=user.id, email="existing@example.com", password_hash="fixture"))
        session.commit()
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "fixture-password-123")
    settings = Settings(_env_file=None, environment="local", database_url=SecretStr(url))
    assert cli.bootstrap_admin("existing@example.com", settings) == 1
    with Session(engine) as session:
        assert session.get(PlatformAdministrator, 1) is None
    engine.dispose()
