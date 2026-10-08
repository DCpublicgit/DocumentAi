"""The eval summary, ledger and report: what a run says about accuracy AND
cost, and that a bad run is flagged rather than hidden."""

from app.eval.ledger import append_entry, load_entries
from app.eval.report import build_ledger_report
from app.eval.runner import EvalResult, is_fatal_provider_error, summarize

_CALL = {"role": "answer", "provider": "gemini", "model": "gemini-3.5-flash-lite",
         "input_tokens": 5000, "output_tokens": 300, "cost_usd": 0.00225}


def _result(id, *, should_refuse=False, refused=False, source_ok=True, cost=0.00225, calls=(_CALL,), error="", latency=2.0):
    return EvalResult(
        id=id, question="q", expected_source_file="" if should_refuse else "a.txt",
        should_refuse=should_refuse, actual_refused=refused,
        refusal_correct=refused == should_refuse,
        cited_files="", citation_correct=True if should_refuse else (not refused and source_ok),
        latency_s=latency, error=error, answer_text="",
        input_tokens=5000 if cost is not None else None,
        output_tokens=300 if cost is not None else None,
        cost_usd=cost, calls=tuple(calls),
    )


def test_summary_splits_the_two_kinds_of_wrong_decision():
    """Answering an off-topic question is worse than refusing an answerable one
    (CONTRIBUTING.md rule 1), so a net accuracy number alone would hide a
    change that trades one for the other."""
    results = [
        _result(1),                                   # right
        _result(2, refused=True),                     # answerable, refused
        _result(3, should_refuse=True),               # off-topic, ANSWERED
        _result(4, should_refuse=True, refused=True),  # right
        _result(5, source_ok=False),                  # answered, wrong source
    ]

    s = summarize(results, "gemini", "gemini-3.5-flash-lite")

    assert (s["off_topic_answered"], s["n_off_topic"]) == (1, 2)
    assert (s["answerable_refused"], s["n_answerable"]) == (1, 3)
    assert s["answered_wrong_source"] == 1


def test_summary_costs_come_from_the_recorded_calls():
    results = [_result(1), _result(2)]

    s = summarize(results, "gemini", "gemini-3.5-flash-lite", scenario_questions=110_000)

    assert s["cost_usd"] == 0.0045
    assert s["cost_per_question_usd"] == 0.00225
    assert s["cost_per_1k_questions_usd"] == 2.25
    assert s["scenario_monthly_usd"] == round(0.00225 * 110_000, 2)
    assert s["models_by_role"] == {"answer": "gemini/gemini-3.5-flash-lite"}
    assert s["cost_by_role_usd"] == {"answer": 0.0045}


def test_one_unknown_cost_makes_the_run_cost_unknown_not_a_partial_sum():
    unpriced = dict(_CALL, model="never-priced", cost_usd=None)
    results = [_result(1), _result(2, cost=None, calls=(unpriced,))]

    s = summarize(results, "openai", "never-priced")

    assert s["cost_usd"] is None and s["scenario_monthly_usd"] is None
    assert s["unpriced_models"] == ["gemini/never-priced"]


def test_summary_reports_latency_percentiles():
    results = [_result(i, latency=float(i)) for i in range(1, 11)]

    s = summarize(results, "gemini", "m")

    assert s["latency_p50_s"] == 5.0 and s["latency_p90_s"] == 9.0


def test_summary_lists_failing_question_ids_without_their_text():
    results = [_result(1), _result(7, refused=True)]

    assert summarize(results, "gemini", "m")["failed_ids"] == [7]


def test_ledger_round_trips_and_appends(tmp_path):
    path = tmp_path / "ledger.jsonl"
    append_entry({"label": "a", "n": 1}, path)
    append_entry({"label": "b", "n": 2}, path)

    assert [e["label"] for e in load_entries(path)] == ["a", "b"]


def test_missing_ledger_is_an_empty_history(tmp_path):
    assert load_entries(tmp_path / "nope.jsonl") == []


def test_report_shows_the_mix_cost_and_flags_a_stopped_run():
    good = summarize([_result(1), _result(2)], "gemini", "gemini-3.5-flash-lite", label="mix-a")
    stopped = summarize(
        [_result(1)], "anthropic", "claude-x", label="claude-run", n_planned=88,
        stopped_reason="provider error on question 1: credit balance",
    )

    table = build_ledger_report([good, stopped])

    assert "answer=gemini/gemini-3.5-flash-lite" in table
    assert "$2.25" in table
    assert "STOPPED: provider error on question 1" in table and "(1/88 run)" in table


def test_report_never_shows_unknown_cost_as_zero():
    unpriced = dict(_CALL, model="never-priced", cost_usd=None)
    s = summarize([_result(1, cost=None, calls=(unpriced,))], "openai", "never-priced", label="x")

    table = build_ledger_report([s])

    assert "n/a" in table and "$0.00" not in table and "unpriced: gemini/never-priced" in table


def test_report_on_an_empty_ledger_says_how_to_start():
    assert "No eval runs" in build_ledger_report([])


def test_billing_and_auth_errors_stop_a_run_but_ordinary_errors_do_not():
    assert is_fatal_provider_error("BadRequestError: Your credit balance is too low to access the Anthropic API")
    assert is_fatal_provider_error("HTTPStatusError: Client error '403 Forbidden' for url ...")
    assert not is_fatal_provider_error("ConnectError: ")
    assert not is_fatal_provider_error("EmptyCompletionError: The model returned no text")
