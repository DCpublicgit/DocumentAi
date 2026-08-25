from app.eval.runner import EvalResult, parse_cited_files, summarize


def test_parse_cited_files_extracts_file_names_from_citation_block():
    answer = (
        "Ажлын долоо хоногийн ажлын цаг 40 цаг байна.\n\n"
        "Эх сурвалж:\n"
        "[Ажлын цагийн хуваарийн журам.txt · 2. Ажлын цаг · v1 (огноогүй)]"
    )

    assert parse_cited_files(answer) == ["Ажлын цагийн хуваарийн журам.txt"]


def test_parse_cited_files_returns_empty_list_when_no_citation_header():
    assert parse_cited_files("Уучлаарай, олдсонгүй.") == []


def test_summarize_computes_accuracy_across_results():
    results = [
        EvalResult(
            id=1,
            question="q1",
            expected_source_file="a.txt",
            should_refuse=False,
            actual_refused=False,
            refusal_correct=True,
            cited_files="a.txt",
            citation_correct=True,
            latency_s=1.0,
            error="",
            answer_text="...",
        ),
        EvalResult(
            id=2,
            question="q2",
            expected_source_file="",
            should_refuse=True,
            actual_refused=False,
            refusal_correct=False,
            cited_files="",
            citation_correct=True,
            latency_s=3.0,
            error="",
            answer_text="...",
        ),
    ]

    summary = summarize(results, provider="anthropic", model="claude-haiku-4-5-20251001")

    assert summary["n_questions"] == 2
    assert summary["refusal_accuracy"] == 0.5
    assert summary["citation_accuracy"] == 1.0
    assert summary["avg_latency_s"] == 2.0
