"""Fast, network-free checks for the public metadata endpoints."""

from typing import Any, Coroutine

from app.api.routes import (
    get_classification_tags,
    get_supported_formats,
    health_check,
)


def _drive_no_await(coroutine: Coroutine[Any, Any, Any]) -> Any:
    """Drive a route coroutine whose body contains no ``await`` expression."""
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("metadata route unexpectedly suspended")


def test_health_metadata() -> None:
    response = _drive_no_await(health_check())

    assert response.status == "healthy"
    assert response.version == "1.0.0"
    assert response.service


def test_tag_metadata() -> None:
    response = _drive_no_await(get_classification_tags())

    assert response["version"] == "v1"
    assert len(response["tags"]) == 13
    assert {"标题", "摘要", "其他"}.issubset(response["tags"])


def test_supported_format_metadata() -> None:
    response = _drive_no_await(get_supported_formats())

    assert set(response["supported_formats"]) == {".txt", ".pdf", ".doc", ".docx"}
    assert response["max_file_size_mb"] == 50

