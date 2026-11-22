from uuid import uuid4

import pytest

from reckon_api.config import Settings
from reckon_api.crawl_worker import CeleryCrawlQueue, create_celery_app


class _RecordingCelery:
    def __init__(self) -> None:
        self.sent: list[tuple[str, list[str]]] = []

    def send_task(self, name: str, args: list[str]) -> None:
        self.sent.append((name, args))


def test_celery_app_requires_enabled_worker_and_broker() -> None:
    with pytest.raises(ValueError):
        create_celery_app(Settings(_env_file=None, environment="test"))


def test_celery_app_is_json_only_bounded_and_scheduled() -> None:
    app = create_celery_app(
        Settings(
            _env_file=None,
            environment="test",
            crawl_worker_enabled=True,
            crawl_broker_url="memory://",
        )
    )
    assert app.conf.task_serializer == "json"
    assert list(app.conf.accept_content) == ["json"]
    assert app.conf.task_acks_late is True
    assert app.conf.task_soft_time_limit < app.conf.task_time_limit <= 30
    schedule = app.conf.beat_schedule["reckon-run-due-crawl-schedules"]
    assert schedule["task"] == "reckon.run_due_crawl_schedules"


def test_queue_sends_only_string_identifiers() -> None:
    celery = _RecordingCelery()
    ids = [uuid4() for _ in range(5)]
    CeleryCrawlQueue(celery).enqueue(*ids)  # type: ignore[arg-type]
    assert celery.sent == [("reckon.execute_crawl", [str(value) for value in ids])]
