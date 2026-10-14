"""The instrument table must match docs/NOTATION_SPEC.md §3."""

import pytest

from drum_agent.kit import DEFAULT_KIT, Kit, KitError, position_to_pitch

SPEC = {  # id: (display pitch, notehead, voice, GM note)
    "crash2": ("B5", "cross", 1, 57),
    "china": ("C6", "cross", 1, 52),
    "splash": ("B5", "xcircle", 1, 55),
    "crash": ("A5", "cross", 1, 49),
    "hihat": ("G5", "cross", 1, 42),
    "hihat_open": ("G5", "cross", 1, 46),
    "hihat_half": ("G5", "cross", 1, 46),
    "ride": ("F5", "cross", 1, 51),
    "ride_bell": ("F5", "diamond", 1, 53),
    "tom1": ("E5", "normal", 2, 48),
    "cowbell": ("E5", "triangle", 1, 56),
    "tom2": ("D5", "normal", 2, 45),
    "snare": ("C5", "normal", 2, 38),
    "cross_stick": ("C5", "cross", 2, 37),
    "rimshot": ("C5", "slashed", 2, 40),
    "floor_tom": ("A4", "normal", 2, 43),
    "floor_tom2": ("G4", "normal", 2, 41),
    "kick": ("F4", "normal", 2, 36),
    "kick2": ("E4", "normal", 2, 35),
    "hihat_pedal": ("D4", "cross", 2, 44),
    "hihat_splash": ("D4", "cross", 2, 44),
}


@pytest.mark.parametrize("inst", sorted(SPEC))
def test_spec_table(inst):
    pitch, head, voice, midi = SPEC[inst]
    ins = DEFAULT_KIT[inst]
    step, octave = position_to_pitch(ins.position)
    assert f"{step}{octave}" == pitch
    assert ins.notehead == head
    assert ins.voice == voice
    assert ins.midi == midi


def test_hands_up_voicing():
    """--voicing hands-up (Weinberg/PAS): everything but the feet stems up."""
    kit = DEFAULT_KIT.with_voicing("hands-up")
    for ins in kit.instruments:
        assert ins.voice == (2 if ins.id in ("kick", "kick2", "hihat_pedal", "hihat_splash") else 1), ins.id
        assert ins.position == DEFAULT_KIT[ins.id].position
    with pytest.raises(KitError):
        DEFAULT_KIT.with_voicing("sideways")


def test_every_instrument_documented():
    assert set(DEFAULT_KIT.ids()) == set(SPEC)


def test_aliases_and_errors():
    assert DEFAULT_KIT.resolve("BD") == "kick"
    assert DEFAULT_KIT.resolve("hho") == "hihat_open"
    with pytest.raises(KitError):
        DEFAULT_KIT.resolve("cymbalz")


def test_lilypond_names_alphabetic():
    for ins in DEFAULT_KIT.instruments:
        assert ins.ly_name.isalpha(), ins.ly_name


def test_kit_override_file(tmp_path):
    f = tmp_path / "kit.json"
    f.write_text('{"instruments": {"tom1": {"position": 4}}}')
    assert Kit.from_json(f)["tom1"].position == 4
    f.write_text('{"instruments": {"tomx": {"position": 4}}}')
    with pytest.raises(KitError):
        Kit.from_json(f)
