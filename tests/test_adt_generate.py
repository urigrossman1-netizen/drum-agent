"""Training-data generation (scripts/adt): the "nohat" style, the sample root, separated clips.
None of these needs the one-shot library or the separation model."""

import importlib
import random
import sys
from pathlib import Path

import numpy as np
import pytest

ADT = Path(__file__).resolve().parents[1] / "scripts" / "adt"


@pytest.fixture(scope="module")
def G():
    sys.path.insert(0, str(ADT))
    import generate
    return generate


def _kit(G, toms=2):
    voices = {c: G.Voice("test", c, None, 1.0, 1.0) for c in
              ("kick", "snare", "cross_stick", "hihat", "hihat_open", "hihat_pedal", "ride", "ride_bell", "crash")}
    return G.VirtualKit(voices, [G.Voice("test", "tom", None, 1.0, 1.0)] * toms)


def test_a_zero_weight_style_leaves_every_default_draw_as_it_was(G):
    assert G.STYLES[-1] == "nohat" and G.STYLE_WEIGHTS[-1] == 0
    for seed in range(500):
        assert random.Random(seed).choices(G.STYLES, G.STYLE_WEIGHTS) == \
               random.Random(seed).choices(G.STYLES[:-1], G.STYLE_WEIGHTS[:-1])


def test_nohat_grooves_keep_cymbals_off_the_loud_snares(G, monkeypatch):
    """Backbeat and fill snares (loud) come without a hi-hat or ride: in the default styles they
    almost always have one. Off-beat cymbals may still meet a kick or a ghost note on an "and"."""
    monkeypatch.setenv("DRUM_AGENT_STYLES", "nohat:1")
    near = total = 0
    for seed in range(40):
        ev, dur, info = G.performance(random.Random(seed), _kit(G))
        assert info["style"] == "nohat" and dur > 0
        timekeeping = [e.t for e in ev if e.inst in ("hihat", "hihat_open", "ride", "ride_bell")]
        for e in ev:
            if e.inst == "snare" and e.vel >= 50:
                total += 1
                near += any(abs(t - e.t) < 0.03 for t in timekeeping)
    assert total > 300 and near / total < 0.01


def test_the_sample_root_moves_every_source_path(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(ADT))
    monkeypatch.setenv("DRUM_AGENT_SAMPLE_ROOT", str(tmp_path))
    import generate
    import oneshots
    try:
        g, o = importlib.reload(generate), importlib.reload(oneshots)
        base = (tmp_path / "usr" / "share").as_posix()
        assert o.SF2 == f"{base}/sounds/sf2" and o.HYDROGEN == f"{base}/hydrogen/data/drumkits"
        assert all(p.startswith(f"{base}/sounds/sf2/") for p in g.GM_SOUNDFONTS)
    finally:
        monkeypatch.delenv("DRUM_AGENT_SAMPLE_ROOT")
        importlib.reload(generate)
        importlib.reload(oneshots)
    assert oneshots.SF2 == "/usr/share/sounds/sf2"  # unset: the Debian/Ubuntu paths


def test_build_one_separates_band_clips_and_reads_them_as_drums_only(G, monkeypatch):
    sys.path.insert(0, str(ADT))
    import train
    from drum_agent.audio import detect, separate
    sr = 44100
    y = np.zeros(sr * 3, dtype=np.float32)
    for t in (0.5, 1.0, 1.5, 2.0):  # four clicks
        i = int(t * sr)
        y[i:i + 400] = np.random.default_rng(1).standard_normal(400) * np.linspace(1, 0, 400)
    clip = G.Clip(y, [(0.5, "snare"), (1.0, "kick"), (1.5, "snare"), (2.0, "kick")], False, {"style": "rock"})
    seen = {}
    monkeypatch.setattr(G, "make_clip", lambda seed, mix_p=0.6: (seen.update(mix_p=mix_p), clip)[1])
    monkeypatch.setattr(separate, "separate_drums", lambda a, rate: (seen.update(separated=rate), a * 0.5)[1])
    real_fe = detect.front_end
    monkeypatch.setattr(detect, "front_end", lambda a, o: (seen.update(drums_only=o.drums_only), real_fe(a, o))[1])
    X, Y, dry, meta = train.build_one(7, mix_p=1.0, separate=True)
    assert seen == {"mix_p": 1.0, "separated": 44100, "drums_only": True}
    assert dry == 1 and meta["separated"] is True and len(X) == len(Y) and Y.sum() >= 3
    seen.clear()
    _, _, dry, meta = train.build_one(7)  # without --separate the band mix is read as it is
    assert seen == {"mix_p": 0.6, "drums_only": False} and dry == 0 and meta["separated"] is False
