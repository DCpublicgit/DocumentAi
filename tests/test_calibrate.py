from app.eval.calibrate import ThresholdCase, best_threshold, sweep


def _case(id_, should_refuse, top_score):
    return ThresholdCase(id=id_, question=f"q{id_}", should_refuse=should_refuse, top_score=top_score)


def test_sweep_counts_false_passes_and_false_refuses_per_threshold():
    cases = [
        _case(1, should_refuse=False, top_score=0.60),  # relevant, clears any threshold <=0.60
        _case(2, should_refuse=False, top_score=0.40),  # relevant, only clears low thresholds
        _case(3, should_refuse=True, top_score=0.50),  # off-topic, clears thresholds <=0.50
    ]

    rows = sweep(cases, candidates=[0.35, 0.45, 0.55])

    by_threshold = {r.threshold: r for r in rows}
    # 0.35: both relevant clear it (0 false_refuse); off-topic (0.50) also
    # clears it -> answered when it shouldn't (1 false_pass).
    assert by_threshold[0.35].false_pass == 1
    assert by_threshold[0.35].false_refuse == 0
    # 0.45: case 2 (0.40) now falls short -> 1 false_refuse. Off-topic still
    # clears it -> still 1 false_pass.
    assert by_threshold[0.45].false_pass == 1
    assert by_threshold[0.45].false_refuse == 1
    # 0.55: off-topic (0.50) no longer clears it -> 0 false_pass. Both
    # false_refuse cases (0.40 relevant) still short -> 1 false_refuse
    # (case 1 at 0.60 still clears 0.55).
    assert by_threshold[0.55].false_pass == 0
    assert by_threshold[0.55].false_refuse == 1


def test_sweep_default_candidates_span_020_to_080():
    cases = [_case(1, False, 0.5)]
    rows = sweep(cases)
    thresholds = [r.threshold for r in rows]
    assert thresholds[0] == 0.20
    assert thresholds[-1] == 0.80
    assert 0.51 in thresholds


def test_best_threshold_weights_false_pass_worse_than_false_refuse():
    """Two candidate thresholds with the same RAW total error count: one
    trades a false pass for a false refuse. The weighted pick must prefer
    fewer false passes — CONTRIBUTING.md rule 1: a false pass (answering
    from irrelevant policy content) is the worse compliance failure, an
    over-cautious refusal is explicitly "correct behavior, not a failure."
    """
    rows = [
        # total_errors equal (2), but composition differs.
        _row(0.40, false_pass=2, false_refuse=0),
        _row(0.60, false_pass=0, false_refuse=2),
    ]

    result = best_threshold(rows, false_pass_weight=2.0)

    assert result.threshold == 0.60


def test_best_threshold_picks_the_lower_threshold_on_a_true_tie():
    rows = [
        _row(0.40, false_pass=1, false_refuse=1),
        _row(0.50, false_pass=1, false_refuse=1),
    ]

    result = best_threshold(rows, false_pass_weight=2.0)

    assert result.threshold == 0.40


def _row(threshold, false_pass, false_refuse):
    from app.eval.calibrate import ThresholdSweepRow

    return ThresholdSweepRow(
        threshold=threshold,
        false_pass=false_pass,
        false_refuse=false_refuse,
        total_errors=false_pass + false_refuse,
    )
