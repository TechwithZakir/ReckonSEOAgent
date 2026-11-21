import json
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from reckon_core.persistence import SeoActionProposal
from reckon_core.wordpress_executor import (
    TargetVersionMismatch,
    UnsupportedWordPressAction,
    WordPressActionExecutor,
    WordPressExecutionError,
    WordPressVerificationFailed,
)


class PublicResolver:
    def addresses(self, host: str) -> tuple[str, ...]:
        assert host == "staging.example.com"
        return ("93.184.216.34",)


class PrivateResolver:
    def addresses(self, host: str) -> tuple[str, ...]:
        return ("169.254.169.254",)


class FakeWordPress:
    def __init__(self, title: str = "Old title", ignore_writes: bool = False) -> None:
        self.title = title
        self.version = "2026-01-01T00:00:00"
        self.ignore_writes = ignore_writes
        self.calls: list[tuple[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        assert request.url.host == "93.184.216.34"
        assert request.headers["host"] == "staging.example.com"
        assert request.headers["authorization"].startswith("Basic ")
        if request.url.path != "/wp-json/wp/v2/posts/42":
            return httpx.Response(404)
        if request.method == "POST" and not self.ignore_writes:
            self.title = json.loads(request.content)["title"]
            self.version = "2026-01-02T00:00:00"
        return httpx.Response(
            200,
            json={"title": {"raw": self.title}, "modified_gmt": self.version},
        )


def executor(wordpress: FakeWordPress, resolver: object = None) -> WordPressActionExecutor:
    return WordPressActionExecutor(
        "https://staging.example.com",
        "fixture-user",
        SecretStr("fixture-app-password"),
        transport=httpx.MockTransport(wordpress),
        resolver=resolver or PublicResolver(),
    )


def proposal(**overrides: object) -> SeoActionProposal:
    values: dict[str, object] = {
        "id": uuid4(),
        "action_type": "heading",
        "target_url": "https://staging.example.com/post",
        "target_version": "2026-01-01T00:00:00",
        "status": "approved",
        "before_state": {"wp_type": "posts", "wp_id": "42", "value": "Old title"},
        "proposed_state": {"value": "New title"},
    }
    values.update(overrides)
    return SeoActionProposal(**values)


def test_execute_verify_and_rollback_are_confirmed_by_read_back() -> None:
    wordpress = FakeWordPress()
    wp = executor(wordpress)
    item = proposal()

    item.executed_state = wp.execute(item)
    assert item.executed_state["execution"] == "wordpress-confirmed"
    assert wordpress.title == "New title"
    assert wp.verify(item)["verification"] == "wordpress-independent-read"

    restored = wp.rollback(item)
    assert restored["rollback"] == "wordpress-confirmed"
    assert wordpress.title == "Old title"


def test_stale_target_version_blocks_the_write() -> None:
    wordpress = FakeWordPress()
    wordpress.version = "2026-01-03T00:00:00"

    with pytest.raises(TargetVersionMismatch):
        executor(wordpress).execute(proposal())

    assert all(method == "GET" for method, _ in wordpress.calls)
    assert wordpress.title == "Old title"


def test_unconfirmed_write_is_not_reported_as_success() -> None:
    with pytest.raises(WordPressVerificationFailed):
        executor(FakeWordPress(ignore_writes=True)).execute(proposal())


def test_rollback_refuses_to_overwrite_later_edits() -> None:
    wordpress = FakeWordPress()
    wp = executor(wordpress)
    item = proposal()
    item.executed_state = wp.execute(item)
    wordpress.title = "Edited by a human"

    with pytest.raises(TargetVersionMismatch):
        wp.rollback(item)

    assert wordpress.title == "Edited by a human"


@pytest.mark.parametrize(
    "overrides",
    [
        {"target_url": "https://other.example.com/post"},
        {"target_url": "http://staging.example.com/post"},
        {"before_state": {"wp_type": "users", "wp_id": "42", "value": "Old title"}},
        {"before_state": {"wp_type": "posts", "wp_id": "../42", "value": "Old title"}},
    ],
)
def test_targets_outside_the_configured_site_or_resource_are_rejected(
    overrides: dict[str, object],
) -> None:
    wordpress = FakeWordPress()

    with pytest.raises(WordPressExecutionError):
        executor(wordpress).execute(proposal(**overrides))

    assert wordpress.calls == []


def test_unmapped_action_types_and_unapproved_proposals_fail_closed() -> None:
    wordpress = FakeWordPress()
    with pytest.raises(UnsupportedWordPressAction):
        executor(wordpress).execute(proposal(action_type="redirect"))
    with pytest.raises(WordPressExecutionError):
        executor(wordpress).execute(proposal(status="proposed"))
    assert wordpress.calls == []


def test_private_dns_answers_block_requests() -> None:
    wordpress = FakeWordPress()

    with pytest.raises(WordPressExecutionError):
        executor(wordpress, PrivateResolver()).execute(proposal())

    assert wordpress.calls == []


def test_invalid_configuration_is_rejected() -> None:
    with pytest.raises(ValueError):
        WordPressActionExecutor("http://staging.example.com", "u", SecretStr("p"))
    with pytest.raises(ValueError):
        WordPressActionExecutor("https://staging.example.com", "u", SecretStr("a b"))
    with pytest.raises(ValueError):
        WordPressActionExecutor(
            "https://staging.example.com", "u", SecretStr("p"), field_map={"heading": "status"}
        )
