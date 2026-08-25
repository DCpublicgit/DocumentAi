"""HTTP-surface behavior of the OpenAI-compatible endpoint."""

from fastapi.testclient import TestClient

from app.server import ChatMessage, _last_user_message, app


def test_last_user_message_picks_the_most_recent_user_turn():
    messages = [
        ChatMessage(role="user", content="эхний асуулт"),
        ChatMessage(role="assistant", content="хариулт"),
        ChatMessage(role="user", content="сүүлийн асуулт"),
    ]
    assert _last_user_message(messages) == "сүүлийн асуулт"


def test_request_with_no_user_message_is_a_400_not_a_500():
    """A conversation with no user turn is the caller's mistake — it used to
    raise ValueError and surface as an unhandled 500."""
    # raise_server_exceptions=False so an unhandled error would show as a 500
    # response rather than propagating and failing the test ambiguously.
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "assistant", "content": "hi"}],
            },
        )

    assert response.status_code == 400
    assert response.status_code != 500


def test_models_endpoint_reports_the_backend_configured_model():
    with TestClient(app) as client:
        body = client.get("/v1/models").json()

    assert body["object"] == "list"
    assert len(body["data"]) == 1, "model is fixed by backend env, not caller-selectable"
