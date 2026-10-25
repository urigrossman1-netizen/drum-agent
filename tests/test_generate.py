"""The beat generator: settings, determinism, validity, drumming conventions, transforms,
plain-language edits and engraving."""

from fractions import Fraction

import pytest
from conftest import needs_lilypond

from drum_agent.charts import compile_spec
from drum_agent.generate import BeatSpec, generate
from drum_agent.generate.edits import EditError, edit_command, transform
from drum_agent.generate.parse import interpret
from drum_agent.generate.styles import STYLES
from drum_agent.playability import check
from drum_agent.validate import validate_score

Q = Fraction(1, 4)


def kicks(m):
    return sorted(h.pos for h in m.hits if h.inst == "kick")


def insts(m):
    return {h.inst for h in m.hits}


def test_spec_from_untrusted_input_is_clamped():
    s = BeatSpec.from_dict({"style": "polka-step", "bpm": 9999, "bars": -3, "time_signature": "13/7",
                            "difficulty": "godlike", "complexity": 7, "ending": "fireworks", "hat_rate": "64ths",
                            "fill_every": "x", "layer_seeds": {"kick": 2, "evil": 1}, "sections": ["Verse", "<b>"]})
    assert (s.style, s.bpm, s.bars, s.time_signature, s.difficulty, s.complexity) == ("rock", 300.0, 1, None,
                                                                                    "intermediate", 1.0)
    assert s.ending is None and s.hat_rate is None and s.fill_every is None
    assert s.layer_seeds == {"kick": 2} and s.sections == ["Verse"]


def test_same_spec_same_beat_and_seeds_change_it():
    a = generate(BeatSpec(style="funk", seed=11)).to_dict()
    b = generate(BeatSpec(style="funk", seed=11)).to_dict()
    c = generate(BeatSpec(style="funk", seed=12)).to_dict()
    assert a["measures"] == b["measures"] and a["measures"] != c["measures"]


@pytest.mark.parametrize("style", sorted(STYLES))
def test_every_style_gives_valid_playable_bars(style):
    for difficulty in ("beginner", "intermediate", "advanced"):
        for bars, seed in ((4, 1), (8, 2), (16, 3), (32, 4)):
            s = generate(BeatSpec(style=style, difficulty=difficulty, bars=bars, seed=seed))
            v = validate_score(s)
            assert v.ok, [c.detail for c in v.checks if not c.ok]
            assert not check(s), (style, difficulty, bars, check(s)[:2])
            assert len(s.measures) == bars and all(m.hits for m in s.measures)
            assert s.chart_type == "original_beat" and s.rights == "original"
            assert s.measures[0].tempo == STYLES[style].bpm


def groove_bars(score):
    gen = score.analysis["generator"]
    fills = set(gen["fills"])
    last = len(score.measures)
    return [m for i, m in enumerate(score.measures, 1) if i not in fills and i != last and not (insts(m) & {"tom1", "tom2", "floor_tom"})]


def test_rock_backbeat_and_downbeat_kick():
    s = generate(BeatSpec(style="rock", bars=16, seed=5))
    for m in groove_bars(s):
        snares = sorted(h.pos for h in m.hits if h.inst == "snare" and not h.ghost)
        assert Q in snares and 3 * Q in snares
        assert Fraction(0) in kicks(m)


def test_half_time_puts_the_backbeat_on_three():
    s = generate(BeatSpec(style="rock", feel="half_time", bars=8, seed=2, ghost_notes=False))
    for m in groove_bars(s):
        assert sorted(h.pos for h in m.hits if h.inst == "snare") == [2 * Q]


def test_fills_land_where_asked():
    spec, _ = interpret("Create a powerful pop-punk beat at 165 BPM in 4/4 with eighth-note hi-hats, a driving kick and "
                        "a two-bar tom fill every eight bars", seed=3)
    s = generate(spec)
    assert len(s.measures) == 16 and s.initial_tempo == 165
    fills = s.analysis["generator"]["fills"]
    assert {7, 8} <= set(fills)  # bars 7-8: the two-bar fill
    assert insts(s.measures[7]) & {"tom1", "tom2", "floor_tom"}
    assert any(h.inst == "crash" and h.pos == 0 for h in s.measures[8].hits)  # the fill lands on a crash
    assert not ({"hihat"} & {h.inst for h in s.measures[7].hits})  # no hi-hat under the fill
    no_fills = generate(BeatSpec(style="rock", bars=8, fill_every=0, seed=3))
    assert no_fills.analysis["generator"]["fills"] == []


def test_endings():
    for kind in ("crash", "stop", "dramatic"):
        s = generate(BeatSpec(style="rock", bars=8, ending=kind, seed=1))
        last = s.measures[-1]
        assert any(h.inst == "crash" and h.pos == 0 for h in last.hits)
        if kind == "stop":
            assert any(h.choke for h in last.hits)
        if kind == "dramatic":
            assert len({h.pos for h in last.hits}) >= 2
    loop = generate(BeatSpec(style="rock", bars=4, seed=1))
    assert loop.analysis["generator"]["ending"] == "none"


def test_more_complexity_adds_to_the_same_groove():
    base = BeatSpec(style="hip_hop", bars=4, seed=9, fill_every=0, complexity=0.3, ending="none")
    busy = BeatSpec(style="hip_hop", bars=4, seed=9, fill_every=0, complexity=0.8, ending="none")
    a, b = generate(base).measures[0], generate(busy).measures[0]
    assert set(kicks(a)) <= set(kicks(b)) and len(kicks(b)) > len(kicks(a))


def test_part_swaps_change_only_that_part():
    s = generate(BeatSpec(style="funk", bars=8, seed=4))
    k, _ = transform(s, "kick")
    for m0, m1 in zip(s.measures, k.measures):
        assert sorted((h.pos, h.inst) for h in m0.hits if h.inst != "kick") == \
            sorted((h.pos, h.inst) for h in m1.hits if h.inst != "kick")
    assert any(kicks(a) != kicks(b) for a, b in zip(s.measures, k.measures))
    hats, msg = transform(s, "hats", {"cymbal": "ride"})
    assert "ride" in msg
    for m0, m1 in zip(s.measures[:-1], hats.measures[:-1]):
        assert kicks(m0) == kicks(m1)


def test_hand_edits_survive_a_part_swap():
    s = generate(BeatSpec(style="rock", bars=4, seed=6, fill_every=0, ending="none"))
    s.measures[1].hits = [h for h in s.measures[1].hits if h.inst != "snare"]  # the user removed the backbeat
    k, _ = transform(s, "kick")
    assert not any(h.inst == "snare" for h in k.measures[1].hits)


def test_interpretation_of_the_example_prompts():
    spec, notes = interpret("Make a relaxed R&B groove at 82 BPM, with subtle hi-hat variations, a syncopated kick, a "
                            "strong backbeat, ghost notes, and a four-bar arrangement.", seed=1)
    assert (spec.style, spec.bpm, spec.bars, spec.ghost_notes, spec.energy) == ("rnb", 82, 4, True, "low")
    assert spec.syncopation and spec.syncopation > 0.7
    assert {n["field"] for n in notes if n["source"] == "default"} >= {"time_signature"}
    spec, _ = interpret("Give me a heavy rock beat at 120 BPM with open hi-hats, syncopated kicks, crash accents, and a "
                        "dramatic ending.", seed=1)
    assert (spec.style, spec.bpm, spec.open_hats, spec.ending) == ("hard_rock", 120, True, "dramatic")
    spec, _ = interpret("a waltz in 3/4 for beginners, no fills", seed=1)
    assert (spec.time_signature, spec.difficulty, spec.fill_every) == ("3/4", "beginner", 0)
    s = generate(spec)
    assert all(str(m.time_sig) == "3/4" for m in s.measures)


def test_quick_settings_override_the_prompt():
    spec, notes = interpret("rock beat at 100 bpm", {"bpm": 140, "bars": 12, "style": "funk"}, seed=1)
    assert (spec.bpm, spec.bars, spec.style) == (140, 12, "funk")
    assert any(n["field"] == "bpm" and n["source"] == "setting" for n in notes)


@pytest.mark.parametrize("command, check_fn", [
    ("Replace the final bar with a tom fill", lambda a, b: insts(b.measures[-1]) & {"tom1", "tom2", "floor_tom"}),
    ("Add an eighth-note kick variation to the last two bars", lambda a, b: [kicks(m) for m in a.measures[:-2]] ==
     [kicks(m) for m in b.measures[:-2]]),
    ("change the tempo to 90", lambda a, b: b.initial_tempo == 90),
    ("Make the hi-hat pattern busier but keep the kick and snare",
     lambda a, b: [kicks(m) for m in a.measures] == [kicks(m) for m in b.measures]),
    ("remove the crashes", lambda a, b: not any(h.inst == "crash" for m in b.measures for h in m.hits)),
    ("copy bar 1 to bars 2-3", lambda a, b: b.measures[1].hits == b.measures[0].hits),
    ("give it a dramatic ending", lambda a, b: any(h.choke for h in b.measures[-1].hits)),
])
def test_plain_language_edits(command, check_fn):
    s = generate(BeatSpec(style="rnb", bars=8, seed=7, ghost_notes=True))
    new, done = edit_command(s, command)
    assert done and check_fn(s, new)
    assert validate_score(new).ok and not check(new)


def test_unreadable_edits_are_reported_with_examples():
    s = generate(BeatSpec(style="rock", bars=4, seed=1))
    with pytest.raises(EditError) as e:
        edit_command(s, "make it sound like a famous band")
    assert "Things I can do" in str(e.value)


def test_a_transcription_is_never_regenerated():
    written = compile_spec({"title": "t", "tempo": 100, "sections": [{"label": "A", "bars": [
        {"hh": "x-x-x-x-", "sn": "--x---x-", "bd": "x---x---"}] * 4}]})
    for action in ("regenerate", "simpler", "kick", "set_bars"):
        with pytest.raises(EditError):
            transform(written, action, {"bars": 8})
    with pytest.raises(EditError):
        edit_command(written, "make it simpler")
    new, done = edit_command(written, "add a fill to bar 4")  # direct edits still work
    assert insts(new.measures[3]) & {"snare", "tom1", "tom2", "floor_tom"} and done


@needs_lilypond
def test_generated_beats_engrave_and_every_export_matches(tmp_path):
    from drum_agent.pipeline import ExportOptions, export_all
    for k, style in enumerate(("pop_punk", "funk", "shuffle", "six_eight", "jazz")):
        s = generate(BeatSpec(style=style, bars=8, seed=k + 1, difficulty="advanced"))
        report = export_all(s, tmp_path / style, "beat", options=ExportOptions(png=False))
        assert report.rendering_ok, [c.summary() for c in report.comparisons if not c.ok]
        assert not [w for w in report.warnings if "LilyPond" in w and "compressed" not in w]
