from collections.abc import Iterator
from uuid import UUID

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from reckon_core.persistence import Base, ExternalIdentity, User
from reckon_core.repositories import SqlAlchemyIdentityProvisioningRepository


@pytest.fixture
def identity_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        yield session
    engine.dispose()


def test_provisioned_identity_is_idempotent(
    identity_session: Session,
) -> None:
    repository = SqlAlchemyIdentityProvisioningRepository(identity_session)

    with identity_session.begin():
        first_user_id, created = repository.provision(
            "https://issuer.example.test/",
            "subject-123",
        )
        replayed_user_id, created_on_replay = repository.provision(
            "https://issuer.example.test/",
            "subject-123",
        )

    assert isinstance(first_user_id, UUID)
    assert created is True
    assert replayed_user_id == first_user_id
    assert created_on_replay is False
    assert identity_session.scalar(select(func.count()).select_from(User)) == 1
    assert (
        identity_session.scalar(
            select(func.count()).select_from(ExternalIdentity)
        )
        == 1
    )


def test_different_subjects_are_provisioned_as_separate_users(
    identity_session: Session,
) -> None:
    repository = SqlAlchemyIdentityProvisioningRepository(identity_session)

    with identity_session.begin():
        first_user_id, _ = repository.provision(
            "https://issuer.example.test/",
            "subject-123",
        )
        second_user_id, created = repository.provision(
            "https://issuer.example.test/",
            "subject-456",
        )

    assert second_user_id != first_user_id
    assert created is True
    assert identity_session.scalar(select(func.count()).select_from(User)) == 2


@pytest.mark.parametrize(
    ("issuer", "subject"),
    [
        ("", "subject-123"),
        ("https://issuer.example.test/", ""),
        (" https://issuer.example.test/", "subject-123"),
        ("https://issuer.example.test/", " " * 513),
    ],
)
def test_invalid_identity_claims_are_rejected(
    identity_session: Session,
    issuer: str,
    subject: str,
) -> None:
    repository = SqlAlchemyIdentityProvisioningRepository(identity_session)

    with pytest.raises(ValueError, match="Verified identity claims are invalid"):
        repository.provision(issuer, subject)

    assert identity_session.scalar(select(func.count()).select_from(User)) == 0
