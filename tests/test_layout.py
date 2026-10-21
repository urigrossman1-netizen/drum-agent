"""Repeat compression and line breaking (NOTATION_SPEC §6)."""

from drum_agent.charts import compile_spec
from drum_agent.layout import plan_layout

A = {"hh": "xxxxxxxx", "sn": "--x---x-", "bd": "x---x---"}
B = {"hh": "xxxxxxxx", "sn": "--x---x-", "bd": "x--xx---"}
FILL = {"sn": "xxxxxxxxxxxxxxxx"}


def score(sections, **kw):
    spec = {"tempo": 100, "patterns": {"a": A, "b": B, "f": FILL}, "sections": sections}
    spec.update(kw)
    return compile_spec(spec)


def kinds(plan):
    return ["%" if b.percent else str(b.index) for b in plan.bars]


def test_identical_bars_become_simile_marks():
    s = score([{"label": "V", "bars": ["a", "a", "a", "f"]}])
    plan = plan_layout(s)
    assert kinds(plan) == ["0", "%", "%", "3"]
    assert plan.bars[0].percent_run == 3
    assert plan.expand() == [0, 1, 2, 3]


def test_repeated_phrase_becomes_volta():
    s = score([{"label": "C", "bars": ["a", "b", "a", "b", "a", "b"]}])
    plan = plan_layout(s)
    assert len(plan.bars) == 2 and plan.bars[0].volta_start and plan.bars[-1].volta_end
    assert plan.bars[0].volta_times == 3
    assert plan.expand() == list(range(6))


def test_fill_is_never_hidden_by_a_repeat():
    s = score([{"label": "V", "bars": ["a", "b", "a", "f"]}])
    plan = plan_layout(s)
    assert not any(b.volta_start for b in plan.bars)
    assert kinds(plan) == ["0", "1", "2", "3"]


def test_repeats_none_writes_everything():
    s = score([{"label": "V", "bars": ["a", "a", "a", "a"]}])
    assert kinds(plan_layout(s, repeats="none")) == ["0", "1", "2", "3"]


def test_uncertain_and_tempo_bars_are_not_compressed():
    s = score([{"label": "V", "bars": ["a", "a", "a", "a"]}])
    s.measures[2].uncertain = True
    assert kinds(plan_layout(s)) == ["0", "%", "2", "3"]
    s = score([{"label": "V", "bars": ["a", "a", "a", "a"]}])
    s.measures[2].tempo = 140
    assert kinds(plan_layout(s)) == ["0", "%", "2", "%"]


def test_sections_start_new_lines_and_lines_are_balanced():
    s = score([{"label": "Intro", "bars": ["a", "b", "f", "b", "a", "f"]},
               {"label": "Verse", "bars": ["b", "a", "b", "f"]}])
    plan = plan_layout(s)
    starts = [b.index for b in plan.bars if b.line_break]
    assert starts == [0, 3, 6]  # 6 bars -> 3 + 3, not 4 + 2; Verse on a new line


def test_simile_mark_never_starts_a_line():
    s = score([{"label": "V", "bars": ["a"] * 12}])
    plan = plan_layout(s)
    for b in plan.bars:
        if b.line_break:
            assert not b.percent
    assert plan.expand() == list(range(12))


def test_pickup_shares_first_line():
    s = score([{"bars": [{"sn": "xxxx"}]}, {"label": "Intro", "bars": ["a", "b", "a", "f"]}], pickup="1/4")
    plan = plan_layout(s)
    assert [b.line_break for b in plan.bars][:2] == [True, False]
    assert plan.printed_numbers[0] == 0 and plan.printed_numbers[1] == 1


def test_dense_bars_with_ghosts_and_sticking_take_more_room():
    # A 16th-note bar with ghost notes and a sticking letter under every hand stroke
    # needs more width than a plain groove bar: four of them overflowed a line.
    from drum_agent.layout import _weight
    plain = compile_spec({"sections": [{"bars": [{"hh": "x-x-x-x-x-x-x-x-", "sn": "----x-------x---",
                                                  "bd": "x-------x-------"}]}]}).measures[0]
    dense = compile_spec({"sections": [{"bars": [{
        "hh": "x-x-|x-x-|x-x-|x-x-", "sn": "-g-g|X--g|-g-g|X--g", "bd": "x---|--x-|-x--|--x-",
        "sticking": "RLRL|L-RL|RLRL|L-RL"}]}]}).measures[0]
    assert _weight(plain) == 1.0
    assert _weight(dense) > 1.0
    bar = {"hh": "x-x-|x-x-|x-x-|x-x-", "sn": "-g-g|X--g|-g-g|X--g", "bd": "x---|--x-|-x--|--x-",
           "sticking": "RLRL|L-RL|RLRL|L-RL"}
    plan = plan_layout(compile_spec({"sections": [{"bars": [bar] * 4}]}), repeats="none")
    assert [b.index for b in plan.bars if b.line_break] != [0]  # not all four on one line


def _bars_per_line(s, plan):
    lines = []
    for b in plan.bars:
        if b.line_break or not lines:
            lines.append(0)
        if not b.in_rest and not s.measures[b.index].is_pickup:
            lines[-1] += 1
    return lines


def test_light_bars_never_put_more_than_four_bars_on_a_line():
    # 2/4, 3/4 and sparse 6/8 bars weigh less than a 4/4 groove bar, which let G33 put
    # seven 2/4 bars on one line and G35 six 6/8 bars (its 2-bar "Out" joined the line).
    march = {"sn": "x-x-x-x-", "bd": "x---x---"}
    s = compile_spec({"time": "2/4", "sections": [{"label": "A", "bars": [march] * 7}]})
    assert _bars_per_line(s, plan_layout(s, repeats="none")) == [4, 3]
    ballad = {"hh": "xxxxxx", "sn": "---x--", "bd": "x-----"}
    s = compile_spec({"time": "6/8", "sections": [{"label": "Ballad", "bars": [ballad] * 4},
                                                  {"label": "Out", "bars": [ballad, {"bd": "x-----"}]}]})
    assert _bars_per_line(s, plan_layout(s, repeats="none")) == [4, 2]


def test_a_one_bar_ending_still_joins_a_full_line():
    # The one exception (NOTATION_SPEC §6): a short last section joins the previous line
    # rather than sit alone on a system, with at most one bar more than a full line.
    s = score([{"label": "A", "bars": ["a", "b", "a", "f"]}, {"label": "End", "bars": [{"bd": "x-------"}]}])
    assert _bars_per_line(s, plan_layout(s, repeats="none")) == [5]
