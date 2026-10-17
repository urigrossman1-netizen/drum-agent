"""Chart-spec authoring format."""

from fractions import Fraction as F

import pytest

from drum_agent.charts import ChartSpecError, compile_spec, parse_tempo
from drum_agent.model import TimeSig


def one_bar(pattern, **kw):
    spec = {"sections": [{"bars": [pattern]}]}
    spec.update(kw)
    return compile_spec(spec).measures[0]


def test_symbols():
    m = one_bar({"sn": "xXgf" "Fdr~" "D---" "----", "hh": "o---h---x-------", "cr": "c---------------"})
    by = {(h.pos, h.inst): h for h in m.hits}
    assert by[(F(1, 16), "snare")].accent
    assert by[(F(2, 16), "snare")].ghost
    assert by[(F(3, 16), "snare")].flam
    assert by[(F(4, 16), "snare")].flam and by[(F(4, 16), "snare")].accent
    assert by[(F(5, 16), "snare")].drag and not by[(F(5, 16), "snare")].accent
    assert by[(F(8, 16), "snare")].drag and by[(F(8, 16), "snare")].accent  # D: accented drag
    assert by[(F(6, 16), "snare")].roll == F(2, 16)
    assert (F(0), "hihat_open") in by and (F(1, 4), "hihat_half") in by
    assert by[(F(0), "crash")].choke


def test_beat_segments_allow_mixed_grids():
    m = one_bar({"sn": "xxx|xxxx|x|xxxxxx"})
    assert [h.pos for h in m.hits][:4] == [F(0), F(1, 12), F(1, 6), F(1, 4)]
    with pytest.raises(ChartSpecError):
        one_bar({"sn": "xxx|xxxx|x"})


def test_errors_are_explicit():
    with pytest.raises(ChartSpecError):
        one_bar({"sn": "x?--"})
    with pytest.raises(ChartSpecError):
        one_bar({"sn": "o---"})  # open only valid on the hi-hat line
    with pytest.raises(ChartSpecError):
        compile_spec({"sections": [{"bars": ["nope"]}]})
    with pytest.raises(ChartSpecError, match="instrument lines only"):
        compile_spec({"patterns": {"turn": {"time": "2/4", "sn": "xxxx"}},
                      "sections": [{"bars": ["turn"]}]})


def test_tempo_units():
    assert parse_tempo(120) == 120
    assert parse_tempo("4.=80") == 120
    assert parse_tempo("2=60") == 120
    assert parse_tempo("8=240") == 120


def test_time_and_tempo_changes_persist():
    s = compile_spec({"tempo": 90, "sections": [
        {"bars": [{"sn": "x---"}, {"time": "7/8", "sn": "x------"}, {"sn": "x------"}]},
        {"tempo": 100, "time": "4/4", "bars": [{"sn": "x---"}]}]})
    assert [str(m.time_sig) for m in s.measures] == ["4/4", "7/8", "7/8", "4/4"]
    assert [m.tempo for m in s.measures] == [90, None, None, 100]


def test_miscounted_lines_fail_with_a_clear_message():
    with pytest.raises(ChartSpecError, match=r"section 'V', bar 2 \(pattern 'verse', 4/4\): sn line .*17 characters.*16"):
        compile_spec({"patterns": {"verse": {"sn": "x---x---x---x----"}},
                      "sections": [{"label": "V", "bars": [{"sn": "x---"}, "verse"]}]})
    with pytest.raises(ChartSpecError, match="beat 1 has 5 characters"):
        one_bar({"sn": "xxxxx|x|x|x"})
    with pytest.raises(ChartSpecError, match="use 2, 4, 6, 8, 12, 24"):
        one_bar({"sn": "xxxxxxxxxx"}, time="6/8")
