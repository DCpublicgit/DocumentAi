"""Grounds a question in retrieved policy chunks and calls the LLM. Ties
together app.retrieve + app.llm + app.citations; used by the CLI (app.ask)
and by the FastAPI /v1/chat/completions endpoint (app.server).
"""

import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Literal

from app import timing, usage
from app.audit import build_record, write_audit
from app.citations import (
    citation_fields,
    extract_used_context,
    format_context_block,
    is_used_marker_line,
)
from app.contract import REFUSAL_STRING, is_refusal
from app.db import get_pool
from app.llm import get_client
from app.query_guard import is_gibberish
from app.retrieve import RetrievalResult, RetrievedChunk, retrieve, rewrite_standalone_query

SYSTEM_PROMPT = f"""Та компанийн дотоод бодлогын талаар ажилтнуудад Монгол хэлээр хариулдаг туслах юм.

Дүрэм:
1. Зөвхөн хэрэглэгчийн мессежинд өгөгдсөн бодлогын хэсгүүдэд үндэслэн хариул. Гадны мэдлэг бүү ашигла.
2. Бодлогын бичвэрээс өгүүлбэрийг шууд хуулж бичихгүй. Ажилтанд тайлбарлаж буй мэт өөрийн үгээр, байгалиан Монгол хэлээр найруул.
3. Асуултын хариулт байгаа тохиолдолд хариултаа Markdown-аар, яг доорх бүтцээр бич (гарчиг ба дараагийн агуулгын хооронд ЗААВАЛ хоосон мөр орхи):

**Товч хариулт**

1-2 өгүүлбэрээр асуултад шууд хариул.

**Дэлгэрэнгүй тайлбар**

Холбогдох дүрэм, нөхцөл, үл хамаарах зүйлсийг өөрийн үгээр 3-6 мөрөнд "- " тэмдэгтээр эхлүүлэн жагсаалт хэлбэрээр бич. Мөр бүр эх бичвэрээс хуулаагүй, өөрийн найруулгаар байх ёстой.

4. Хэрэв өгөгдсөн хэсгүүдэд асуултын хариулт олдохгүй бол дээрх бүтцийг АШИГЛАХГҮЙгээр, өөр юу ч нэмэлгүйгээр яг дараах өгүүлбэрийг гарга (энэ тохиолдолд 7, 8-р дүрмийн мөрийг бүү нэм):
"{REFUSAL_STRING}"
5. Хариултаа Монгол хэлээр бич.
6. Эх сурвалжийн жагсаалтыг өөрөө бүү нэмээрэй — үүнийг систем автоматаар хавсаргана.
7. Хэрэглэгчийн мессежинд өгөгдсөн бодлогын хэсэг бүр "[1]", "[2]" гэх мэт
   дугаартай. Хариултаа бичиж дуусаад, хоосон мөрийн дараа, ЗӨВХӨН
   бодитоор ашигласан хэсэг БҮРТ нэг мөр нэм (эдгээр мөрийг ажилтан
   харахгүй — систем дотооддоо ашиглаад хасна). Мөр бүрийн формат:
АШИГЛАСАН <хэсгийн дугаар>: <хэрэв тухайн хэсэгт хэд хэдэн заалтын дугаар
   (жишээ нь "4.1.", "4.2.") орсон бол, хариултдаа БОДИТООР ашигласан ЯГ
   НЭГ заалтын дугаар; заалтын дугаар зааж өгөх шаардлагагүй бол хоосон
   орхи>
   Жишээ нь, хэрэв 1, 3-р хэсгийг ашигласан бөгөөд 1-р хэсгээс яг 4.2
   дугаартай заалтыг ашигласан бол:
АШИГЛАСАН 1: 4.2
АШИГЛАСАН 3:
   Мөр бүрт ЗӨВХӨН НЭГ заалтын дугаар бич — хэд хэдэн дугаар бүү жагсаа,
   таслал, цэг таслалаар бүү холбо. Тухайн хэсэгт БАЙХГҮЙ заалтын дугаар
   бүү зохиож бич. Зөвхөн хариултдаа бодитоор тусгасан хэсгүүдийн мөрийг
   бич, бусдыг бүү оруул.
8. "Дэлгэрэнгүй тайлбар" хэсгийн мөр бүрийн төгсгөлд тухайн мэдээллийг аваасан
   хэсгийн дугаарыг "[N]" хэлбэрээр нэм (N нь 7-р дүрэмд дурдсан хэсгийн
   дугаартай ЯГ ТЭНЦҮҮ байх ёстой — өөрөө шинэ дугаар бүү зохио). Нэг мөр хэд
   хэдэн эх сурвалжаас бүрдсэн бол "[1][2]" гэх мэт дараалуулан бич. Жишээ нь:
- Ажилтан бүр жилд нэг удаа мэдээллийн аюулгүй байдлын сургалтад заавал
  хамрагдана.[1]
   "Товч хариулт" хэсэгт дугаар бүү нэм."""


class EmptyCompletionError(RuntimeError):
    """The provider returned no text at all.

    Surfaced as an error rather than silently becoming a refusal: a refusal
    tells the employee the answer is not in company policy, and an empty
    completion is evidence of a provider problem, not of policy content.
    Observed in practice with reasoning models whose thinking tokens consume
    the whole LLM_MAX_TOKENS budget, leaving nothing for the answer.
    """


@dataclass
class AnswerOutcome:
    """Out-of-band result metadata for one answer, filled in as it is produced.

    Exists because an answer's TEXT can't carry whether the provider truncated
    it. Reporting finish_reason="stop" on an answer cut off at LLM_MAX_TOKENS
    tells the client it is complete, while the citation block still asserts the
    policy documents back it — the completeness claim CONTRIBUTING.md rule 2 is
    about. Passed in by the caller rather than returned, since the streaming
    path is an async generator whose yields are answer text.
    """

    truncated: bool = False
    # Structured citations for the API response (choices[0].citations, or
    # the streaming "citations" SSE event) — populated once the used context
    # is resolved, same out-of-band reasoning as `truncated`: the streaming
    # path's yields are answer text only, never a place to also carry
    # structured data.
    citations: list[dict] = field(default_factory=list)

    @property
    def finish_reason(self) -> str:
        return "length" if self.truncated else "stop"


@dataclass(frozen=True)
class StageEvent:
    """A pipeline-progress marker interleaved with stream_answer's text
    yields (never sent to the LLM or audited — UI-only progress, gone once
    the outer generator finishes). app.server tells these apart from answer
    text with isinstance() and sends each as its own "stage" SSE event
    (ui/src/lib/streamChat.js's onStage) rather than a content delta.

    `document_count` is set only on "retrieved" (distinct source documents
    among result.cited_chunks — what will actually ground the answer, not
    the raw candidate count before the relevance bar). "retrieving" and
    "generating" carry no count.
    """

    stage: Literal["retrieving", "retrieved", "generating"]
    document_count: int | None = None


def compose_answer(result: RetrievalResult) -> str | None:
    """Returns the refusal string if retrieval says refuse, else None (caller
    should proceed to call the LLM). Split out from answer_question so the
    below-threshold refusal path is unit-testable without a DB or LLM call."""
    if result.refuse:
        return REFUSAL_STRING
    return None


async def _retrieve_and_prepare(
    question: str, history: list[tuple[str, str]]
) -> tuple[RetrievalResult | None, str | None]:
    """Runs retrieval; returns the RetrievalResult plus the grounded user
    message to send the LLM, or None for the message when the refusal gate
    trips.

    `history` ([(role, content), ...], oldest first, everything BEFORE the
    current turn — see app.server._split_history) feeds
    app.retrieve.query_rewrite.rewrite_standalone_query, which condenses a
    followup like "Тэгвэл цалинтай юу?" into a standalone question before
    ANYTHING else runs — retrieval, and the "Асуулт:" line the model itself
    sees, both use the rewritten form, not the raw pronoun-bearing one.
    `question` itself (the raw turn, unrewritten) is what gets audited —
    that's what the employee actually typed.

    The result comes back either way so the audit trail can record what was
    retrieved and what it scored even on a refusal — "why did it refuse this"
    is unanswerable without it. The one exception is app.query_guard's
    gibberish gate: it runs BEFORE retrieval (and before rewriting — no point
    spending an LLM call condensing a question that's about to be refused
    outright) specifically to skip the embedding/DB round trip entirely, so
    there is no RetrievalResult to return on that path —
    app.audit.build_record already treats `result=None` as "retrieval itself
    never produced one" for exactly this case."""
    if is_gibberish(question):
        timing.note(refused=True, gibberish=True)
        return None, None

    with timing.stage("query_rewrite"):
        standalone_question = await rewrite_standalone_query(question, history)
    timing.note(query_rewritten=standalone_question != question)

    pool = await get_pool()
    result = await retrieve(pool, standalone_question)

    if compose_answer(result) is not None:
        # The refusal path never reaches the LLM, so its stage set is
        # retrieval-only — worth flagging, or a run of refusals reads as
        # suspiciously fast generation.
        timing.note(refused=True)
        return result, None

    with timing.stage("prompt_assembly"):
        # cited_chunks, not chunks: a candidate that never cleared its own
        # relevance bar (app.retrieve.retriever.select_cited_chunks) must not
        # ground the answer either, or the answer and its citation list could
        # disagree about what the answer actually rests on. Each block is
        # numbered "[N]" so the model can name which ones it actually drew
        # from (SYSTEM_PROMPT rule 7) — retrieval can still hand over more
        # than the answer ends up using, see _resolve_used_context.
        context = "\n\n".join(
            f"[{i}] {format_context_block(c)}"
            for i, c in enumerate(result.cited_chunks, start=1)
        )
        user_message = f"Бодлогын хэсгүүд:\n\n{context}\n\nАсуулт: {standalone_question}"
    timing.note(refused=False, chunks=len(result.cited_chunks), prompt_chars=len(user_message))
    return result, user_message


def _resolve_used_context(
    cited_chunks: list[RetrievedChunk], used: list[tuple[int, str | None]] | None
) -> tuple[list[tuple[int, RetrievedChunk]], dict[tuple[str, str, int], str]]:
    """Narrows retrieval's cited_chunks (everything that individually cleared
    the score floor) down to what the model's answer actually drew from, per
    its trailing "АШИГЛАСАН:" marker (extract_used_context) — and, where the
    model named a specific clause within a chunk, returns that too, keyed by
    the chunk's PK, for citation_fields to cite under that clause instead of
    whichever one happens to appear first in the chunk's text.

    Returns (index, chunk) pairs, not bare chunks — `index` is the chunk's
    ORIGINAL 1-based position in `cited_chunks`, matching the "[N]" numbering
    shown to the model in the prompt (SYSTEM_PROMPT rule 7) and the inline
    "[N]" markers it places in its own prose (rule 8). That numbering must
    survive narrowing UNCHANGED: if only chunks 1 and 3 of 3 were used, this
    returns [(1, chunk1), (3, chunk3)], never renumbered to
    [(1, chunk1), (2, chunk3)] — a renumbered list would make the model's
    own inline "[3]" marker point at the wrong citation (or none at all).

    Falls back to (the full list, no clause preferences) — the pre-marker
    behavior — when the marker is missing, malformed, or names nothing
    valid: a parsing miss must never suppress a chunk that was genuinely
    used, only risk citing one extra, or under a less specific clause, than
    it should. Same fail-open shape as query_expansion's failure handling.
    """
    if used is None:
        return list(enumerate(cited_chunks, start=1)), {}
    selected: list[tuple[int, RetrievedChunk]] = []
    preferred_clauses: dict[tuple[str, str, int], str] = {}
    for index, clause in used:
        if not (1 <= index <= len(cited_chunks)):
            continue
        chunk = cited_chunks[index - 1]
        selected.append((index, chunk))
        if clause is not None:
            preferred_clauses[(chunk.file_name, chunk.policy_version, chunk.chunk_index)] = clause
    if not selected:
        return list(enumerate(cited_chunks, start=1)), {}
    return selected, preferred_clauses


async def _audit(
    *,
    question: str,
    answer: str,
    result: RetrievalResult | None,
    refused: bool,
    streamed: bool,
    outcome: AnswerOutcome,
    started: float,
    cited_chunks: list[RetrievedChunk] | None = None,
    preferred_clauses: dict[tuple[str, str, int], str] | None = None,
) -> None:
    await write_audit(
        build_record(
            question=question,
            answer=answer,
            result=result,
            refused=refused,
            streamed=streamed,
            finish_reason=outcome.finish_reason,
            latency_ms=int((time.perf_counter() - started) * 1000),
            cited_chunks=cited_chunks,
            preferred_clauses=preferred_clauses,
            # Always called inside the request's usage.collect() block below;
            # a request that never reached an LLM has an empty log, which
            # records as "0 tokens, $0" — measured, not unknown.
            usage_log=usage.current(),
        )
    )


async def answer_question(
    question: str,
    history: list[tuple[str, str]] | None = None,
    outcome: AnswerOutcome | None = None,
) -> str:
    outcome = outcome if outcome is not None else AnswerOutcome()
    started = time.perf_counter()

    with timing.request_timing("answer_question"), usage.collect():
        result, user_message = await _retrieve_and_prepare(question, history or [])
        if user_message is None:
            await _audit(
                question=question, answer=REFUSAL_STRING, result=result,
                refused=True, streamed=False, outcome=outcome, started=started,
            )
            return REFUSAL_STRING

        client = get_client()
        with timing.stage("llm_generate"):
            raw_answer = (await client.generate(SYSTEM_PROMPT, user_message)).strip()
        usage.require_answer_call()
        outcome.truncated = getattr(client, "truncated", False)

        if not raw_answer:
            # Deliberately not audited: no answer was served, and recording it
            # as one would put an empty "answer" in the compliance record.
            raise EmptyCompletionError(
                "The model returned no text"
                + (" (output truncated at LLM_MAX_TOKENS)" if outcome.truncated else "")
            )

        answer_text, used = extract_used_context(raw_answer)
        if not answer_text:
            raise EmptyCompletionError("The model returned only the citation marker, no answer text")

        if is_refusal(answer_text):
            await _audit(
                question=question, answer=REFUSAL_STRING, result=result,
                refused=True, streamed=False, outcome=outcome, started=started,
            )
            return REFUSAL_STRING

        indexed_chunks, preferred_clauses = _resolve_used_context(result.cited_chunks, used)
        outcome.citations = [
            citation_fields(
                i, c, preferred_clauses.get((c.file_name, c.policy_version, c.chunk_index))
            )
            for i, c in indexed_chunks
        ]
        cited_chunks = [c for _, c in indexed_chunks]
        await _audit(
            question=question, answer=answer_text, result=result,
            refused=False, streamed=False, outcome=outcome, started=started,
            cited_chunks=cited_chunks, preferred_clauses=preferred_clauses,
        )
        return answer_text


def _document_count(chunks: list[RetrievedChunk]) -> int:
    # Distinct source documents, not chunk count — several chunks commonly
    # come from the same policy file, and "N documents" means N files.
    return len({c.file_name for c in chunks})


async def stream_answer(
    question: str,
    history: list[tuple[str, str]] | None = None,
    outcome: AnswerOutcome | None = None,
) -> AsyncIterator[str | StageEvent]:
    """Yields, in order: a "retrieving" StageEvent, then either a "retrieved"
    StageEvent followed by the refusal string (below-threshold or gibberish
    refusal — see _retrieve_and_prepare), or "retrieved" + "generating" +
    the LLM's streamed answer tokens (never a trailing citation block — see
    AnswerOutcome.citations, which app.server sends as its own SSE event
    once this generator returns).

    The gibberish short-circuit (_retrieve_and_prepare returns `result=None`
    — no RetrievalResult was ever produced, retrieval never ran) skips
    "retrieved" too: there is no document count to report for a search that
    never happened.

    `history` — see _retrieve_and_prepare.

    `outcome`, if given, is populated with metadata the text can't carry —
    whether the provider truncated the answer, and the structured
    citations."""
    outcome = outcome if outcome is not None else AnswerOutcome()
    started = time.perf_counter()

    with timing.request_timing("stream_answer"), usage.collect():
        yield StageEvent("retrieving")
        result, user_message = await _retrieve_and_prepare(question, history or [])
        if user_message is None:
            if result is not None:
                yield StageEvent("retrieved", document_count=_document_count(result.cited_chunks))
            yield REFUSAL_STRING
            await _audit(
                question=question, answer=REFUSAL_STRING, result=result,
                refused=True, streamed=True, outcome=outcome, started=started,
            )
            return

        yield StageEvent("retrieved", document_count=_document_count(result.cited_chunks))
        yield StageEvent("generating")

        client = get_client()
        buffer: list[str] = []
        pending_line = ""
        held_lines: list[str] = []
        _t0 = time.perf_counter()
        _first_token_t = None
        async for token in client.stream(SYSTEM_PROMPT, user_message):
            if _first_token_t is None:
                _first_token_t = time.perf_counter()
                # Split into two NON-overlapping stages: waiting for the first
                # token, then streaming the rest. Recording ttft and a total
                # that contains it would double-count against wall time and
                # make every other stage's share look smaller than it is.
                timing.mark("llm_ttft", _first_token_t - _t0)
            buffer.append(token)
            # Hold back any run of trailing marker-shaped lines — the model
            # emits one "АШИГЛАСАН N: ..." line per used context block
            # (SYSTEM_PROMPT rule 7), and none of them must reach the
            # employee. A held line gets flushed after all if a genuine
            # content line follows it — a marker-shaped line isn't really
            # the trailing block unless nothing but more marker lines (or
            # end of stream) follows it; markers are only ever contiguous at
            # the very end. Costs at most the marker block's own line count
            # in latency, right at the end, never per-token.
            pending_line += token
            if "\n" in pending_line:
                *complete, pending_line = pending_line.split("\n")
                for line in complete:
                    if is_used_marker_line(line):
                        held_lines.append(line + "\n")
                    else:
                        if held_lines:
                            yield "".join(held_lines)
                            held_lines = []
                        yield line + "\n"
        usage.require_answer_call()
        _last_token_t = time.perf_counter()
        if _first_token_t is not None:
            timing.mark("llm_stream_tail", _last_token_t - _first_token_t)
        # The figure usually quoted as "LLM time" — first token wait plus tail.
        timing.note(llm_total_ms=round((_last_token_t - _t0) * 1000, 1))

        outcome.truncated = getattr(client, "truncated", False)
        raw_answer = "".join(buffer).strip()

        if not raw_answer:
            # See answer_question: an undelivered answer is not audited as one.
            raise EmptyCompletionError(
                "The model streamed no text"
                + (" (output truncated at LLM_MAX_TOKENS)" if outcome.truncated else "")
            )

        answer_text, used = extract_used_context(raw_answer)
        if not answer_text:
            raise EmptyCompletionError("The model streamed only the citation marker, no answer text")

        # Resolve whatever is still held back: any provisionally-held marker
        # lines, plus the final in-progress line (streams never end mid-flush,
        # so at most one line has no trailing newline yet). Genuine content
        # among this must still reach the employee before the refusal check,
        # so a one-line refusal — which never completes with its own newline
        # — still gets delivered.
        if pending_line and is_used_marker_line(pending_line):
            held_lines.append(pending_line)
        elif pending_line:
            if held_lines:
                yield "".join(held_lines)
                held_lines = []
            yield pending_line

        if is_refusal(answer_text):
            await _audit(
                question=question, answer=REFUSAL_STRING, result=result,
                refused=True, streamed=True, outcome=outcome, started=started,
            )
            return

        indexed_chunks, preferred_clauses = _resolve_used_context(result.cited_chunks, used)
        # Not yielded as text — app.server._stream_chat_completion reads this
        # after the text loop and sends it as its own "citations" SSE event.
        # See AnswerOutcome.citations.
        outcome.citations = [
            citation_fields(
                i, c, preferred_clauses.get((c.file_name, c.policy_version, c.chunk_index))
            )
            for i, c in indexed_chunks
        ]
        cited_chunks = [c for _, c in indexed_chunks]
        # Audited after the last yield, so `answer` is exactly the text the
        # employee received — the citations are audited separately, from
        # `cited_chunks`, not parsed back out of this string.
        await _audit(
            question=question, answer=answer_text, result=result,
            refused=False, streamed=True, outcome=outcome, started=started,
            cited_chunks=cited_chunks, preferred_clauses=preferred_clauses,
        )
