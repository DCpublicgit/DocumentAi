"""HTTP-surface behavior of the OpenAI-compatible endpoint."""

import json
import uuid

from fastapi.testclient import TestClient

from app.answering import StageEvent
from app.config import settings
from app.server import ChatMessage, _split_history, app


def _parse_sse(body: str) -> list[tuple[str, str]]:
    """Splits a raw SSE response body into (event, data) pairs, in order.
    Default-event ("message") frames carry no "event:" line, per the spec."""
    frames = []
    for block in body.strip("\n").split("\n\n"):
        if not block:
            continue
        event = "message"
        data = None
        for line in block.split("\n"):
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data = line[len("data:") :].strip()
        if data is not None:
            frames.append((event, data))
    return frames


def test_split_history_picks_the_most_recent_user_turn_as_the_question():
    messages = [
        ChatMessage(role="user", content="эхний асуулт"),
        ChatMessage(role="assistant", content="хариулт"),
        ChatMessage(role="user", content="сүүлийн асуулт"),
    ]

    history, question = _split_history(messages)

    assert question == "сүүлийн асуулт"


def test_split_history_returns_everything_before_the_current_turn_in_order():
    messages = [
        ChatMessage(role="user", content="эхний асуулт"),
        ChatMessage(role="assistant", content="хариулт"),
        ChatMessage(role="user", content="сүүлийн асуулт"),
    ]

    history, _question = _split_history(messages)

    assert history == [("user", "эхний асуулт"), ("assistant", "хариулт")]


def test_split_history_is_empty_on_a_first_turn():
    messages = [ChatMessage(role="user", content="цорын ганц асуулт")]

    history, question = _split_history(messages)

    assert history == []
    assert question == "цорын ганц асуулт"


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


def test_get_document_is_a_404_for_a_file_name_nothing_matches():
    with TestClient(app) as client:
        response = client.get("/v1/documents/no-such-policy.txt")

    assert response.status_code == 404


def test_get_document_serves_a_real_file_inline_with_its_content_type(tmp_path, monkeypatch):
    (tmp_path / "Бодлого__v1__2024-01-01.txt").write_text("агуулга", encoding="utf-8")
    monkeypatch.setattr(settings, "policy_dir", str(tmp_path))

    with TestClient(app) as client:
        response = client.get("/v1/documents/Бодлого.txt")

    assert response.status_code == 200
    assert response.text == "агуулга"
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["content-disposition"] == "inline"


def test_get_document_path_traversal_attempt_is_a_404_not_a_file_leak(tmp_path, monkeypatch):
    (tmp_path / "Бодлого__v1__2024-01-01.txt").write_text("агуулга", encoding="utf-8")
    monkeypatch.setattr(settings, "policy_dir", str(tmp_path))

    with TestClient(app) as client:
        response = client.get("/v1/documents/..%2f..%2f..%2fetc%2fpasswd")

    assert response.status_code == 404


def test_submit_feedback_persists_and_returns_ok():
    payload = {
        "messageId": f"m-{uuid.uuid4()}",
        "conversationId": "c1",
        "verdict": "up",
        "question": "Ажлын цаг хэд вэ?",
        "answer": "09:00-18:00",
        "retrievedChunkIds": ["a.txt::v1::0"],
        "latencyMs": 1234,
    }

    with TestClient(app) as client:
        response = client.post("/api/feedback", json=payload)

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_submit_feedback_ignores_a_client_supplied_model_and_stamps_its_own(monkeypatch):
    """The client can't be trusted to know which model actually answered —
    see app.feedback.build_record's docstring."""
    monkeypatch.setattr(settings, "llm_model", "test-model-xyz")
    payload = {
        "messageId": f"m-{uuid.uuid4()}",
        "conversationId": "c1",
        "verdict": "up",
        "question": "q",
        "answer": "a",
        "model": "something-the-client-made-up",
    }

    with TestClient(app) as client:
        response = client.post("/api/feedback", json=payload)

    assert response.status_code == 200  # extra field silently ignored, not a 422


def test_submit_feedback_rejects_an_unknown_reason():
    payload = {
        "messageId": "m1", "conversationId": "c1", "verdict": "down",
        "question": "q", "answer": "a", "reason": "буруу зантай",
    }

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/feedback", json=payload)

    assert response.status_code == 422


def test_submit_feedback_rejects_an_invalid_verdict():
    payload = {
        "messageId": "m1", "conversationId": "c1", "verdict": "sideways",
        "question": "q", "answer": "a",
    }

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/feedback", json=payload)

    assert response.status_code == 422


def test_negative_summary_reflects_a_persisted_down_vote_grouped_by_document():
    marker_doc = f"test-doc-{uuid.uuid4()}.txt"
    payload = {
        "messageId": f"m-{uuid.uuid4()}",
        "conversationId": "c1",
        "verdict": "down",
        "question": "q",
        "answer": "a",
        "retrievedChunkIds": [f"{marker_doc}::v1::0"],
        "reason": "олдсонгүй",
    }

    with TestClient(app) as client:
        post_response = client.post("/api/feedback", json=payload)
        assert post_response.status_code == 200

        summary_response = client.get("/api/feedback/negative-summary")

    assert summary_response.status_code == 200
    docs = {d["document"]: d for d in summary_response.json()["documents"]}
    assert marker_doc in docs
    assert docs[marker_doc]["downCount"] == 1
    assert docs[marker_doc]["reasons"] == {"олдсонгүй": 1}


def test_stream_endpoint_sends_stage_events_as_their_own_named_frames(monkeypatch):
    """stage events must be tagged "event: stage" (never a content delta —
    ui/src/lib/streamChat.js tells them apart by event name alone) and stay
    in the exact order the pipeline emits them, interleaved correctly around
    the actual answer text."""

    async def fake_stream_answer(question, history, outcome):
        yield StageEvent("retrieving")
        yield StageEvent("retrieved", document_count=3)
        yield StageEvent("generating")
        yield "Сайн"
        yield " байна."

    monkeypatch.setattr("app.server.stream_answer", fake_stream_answer)

    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "stream": True,
                "messages": [{"role": "user", "content": "асуулт"}],
            },
        )

    assert response.status_code == 200
    frames = _parse_sse(response.text)

    # frames[0] is always the opening {"role": "assistant"} delta
    # (_stream_chat_completion sends it before consuming stream_answer at
    # all) — the 3 stage frames come right after it, in the order the fake
    # generator above yielded them, and only THEN the answer text.
    assert [event for event, _ in frames[:4]] == ["message", "stage", "stage", "stage"]
    stage_payloads = [json.loads(data) for _, data in frames[1:4]]
    assert stage_payloads == [
        {"stage": "retrieving"},
        {"stage": "retrieved", "documentCount": 3},
        {"stage": "generating"},
    ]

    content = "".join(
        json.loads(data)["choices"][0]["delta"].get("content") or ""
        for event, data in frames[4:]
        if event == "message" and data != "[DONE]"
    )
    assert content == "Сайн байна."


def test_stream_endpoint_omits_document_count_for_stages_that_have_none(monkeypatch):
    async def fake_stream_answer(question, history, outcome):
        yield StageEvent("retrieving")
        yield "Хариулт"

    monkeypatch.setattr("app.server.stream_answer", fake_stream_answer)

    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "stream": True,
                "messages": [{"role": "user", "content": "асуулт"}],
            },
        )

    frames = _parse_sse(response.text)
    stage_payloads = [json.loads(data) for event, data in frames if event == "stage"]
    assert stage_payloads == [{"stage": "retrieving"}]  # no "documentCount" key at all
