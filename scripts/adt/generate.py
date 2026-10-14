"""Synthesize labelled drum performances for training the onset classifier.

A clip is a random but musical drum performance (one of many styles, with
fills, ghost notes, flams, rolls, open hi-hats, pedal hi-hats, crashes on
phrase starts), rendered from one-shots of a randomly assembled kit
(scripts/adt/oneshots.py), with per-drum levels, tuning, room, EQ,
compression and sometimes a band accompaniment and MP3 coding. The ground
truth is the event list, so every candidate onset can be labelled.

Used by scripts/adt/train.py; not part of the runtime package.
"""

from __future__ import annotations

import os
import random
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

SR = 44100
ONESHOTS = Path(os.environ.get("DRUM_AGENT_DATA", Path.home() / ".cache" / "drum-agent")) / "adt" / "oneshots"
GM_SOUNDFONTS = ["/usr/share/sounds/sf2/FluidR3_GM.sf2", "/usr/share/sounds/sf2/MuseScore_General_Full.sf2",
                 "/usr/share/sounds/sf2/sf_GMbank.sf2", "/usr/share/sounds/sf2/TimGM6mb.sf2"]
HAND = ("snare", "cross_stick", "hihat", "hihat_open", "ride", "ride_bell", "crash", "tom", "other")


# ---------------------------------------------------------------- one-shot kits
class ShotBank:
    """All one-shots of one source kit, indexed by (class, sub-kind)."""

    def __init__(self, path: Path):
        d = np.load(path)
        self.name = path.stem
        self.audio = d["audio"]
        self.items: dict[str, list[tuple[int, int, int, str]]] = {}
        for off, ln, c, s, v in zip(d["offsets"], d["lengths"], d["cls"], d["sub"], d["vel"]):
            self.items.setdefault(str(c), []).append((int(off), int(ln), int(v), str(s)))

    def classes(self) -> set[str]:
        return set(self.items)

    def subs(self, cls: str) -> list[str]:
        return sorted({s for _, _, _, s in self.items.get(cls, [])})

    def get(self, cls: str, sub: str | None, vel: int, rng: random.Random) -> tuple[np.ndarray, int]:
        cands = [it for it in self.items[cls] if sub is None or it[3] == sub] or self.items[cls]
        best = min(abs(it[2] - vel) for it in cands)
        near = [it for it in cands if abs(it[2] - vel) <= best + 12]
        off, ln, v, _ = rng.choice(near)
        return self.audio[off:off + ln].astype(np.float32), v


_BANKS: dict[str, ShotBank] = {}


def bank(name: str) -> ShotBank:
    if name not in _BANKS:
        _BANKS[name] = ShotBank(ONESHOTS / f"{name}.npz")
    return _BANKS[name]


def bank_names() -> list[str]:
    return sorted(p.stem for p in ONESHOTS.glob("*.npz"))


def family(name: str) -> str:
    return name.split("_")[0] if not name.startswith("h2_") else "h2"


@dataclass
class Voice:
    bank: str
    cls: str
    sub: str | None
    gain: float  # linear channel gain
    shift: float  # resampling ratio (tuning)


@dataclass
class VirtualKit:
    """One drummer's kit for a clip: a source per instrument, toms ordered high->low."""
    voices: dict[str, Voice]
    toms: list[Voice] = field(default_factory=list)


def make_kit(rng: random.Random, electronic_ok: bool = True) -> VirtualKit:
    names = bank_names()
    fams: dict[str, list[str]] = {}
    for n in names:
        if n == "h2_gimme_a_hand_1_0":
            continue
        if not electronic_ok and n in ("fluid_24", "fluid_25", "csound_24", "csound_25", "h2_electricempirekit"):
            continue
        fams.setdefault(family(n), []).append(n)
    # Families equally likely, so the 22 FluidR3 variants don't dominate.
    def pick_bank() -> str:
        return rng.choice(fams[rng.choice(sorted(fams))])
    main = pick_bank()
    mixed = rng.random() < 0.35
    voices: dict[str, Voice] = {}
    for cls in ("kick", "snare", "cross_stick", "hihat", "hihat_open", "hihat_pedal", "ride", "ride_bell",
                "crash", "other"):
        src = pick_bank() if mixed and rng.random() < 0.5 else main
        tries = 0
        while cls not in bank(src).classes() and tries < 20:
            src = pick_bank()
            tries += 1
        if cls not in bank(src).classes():
            continue
        subs = bank(src).subs(cls)
        sub = rng.choice(subs) if cls in ("snare", "crash", "ride", "hihat_open", "other") else None
        db = rng.uniform(-9, 3) if cls != "kick" else rng.uniform(-6, 4)
        shift = 2 ** (rng.uniform(-2.5, 2.5) / 12) if cls in ("kick", "snare", "tom") else 2 ** (rng.uniform(-1, 1) / 12)
        voices[cls] = Voice(src, cls, sub, 10 ** (db / 20), shift)
    if "hihat" in voices:  # the same hi-hat for closed, open and foot when possible
        hb = voices["hihat"].bank
        for c in ("hihat_open", "hihat_pedal"):
            if c in bank(hb).classes():
                voices[c] = Voice(hb, c, voices[c].sub if c in voices else None,
                                  voices["hihat"].gain * 10 ** (rng.uniform(-3, 3) / 20), voices["hihat"].shift)
    # Toms: 1-4, from one source, ordered high -> low.
    src = main if "tom" in bank(main).classes() else pick_bank()
    tries = 0
    while "tom" not in bank(src).classes() and tries < 20:
        src = pick_bank()
        tries += 1
    toms: list[Voice] = []
    if "tom" in bank(src).classes():
        order = {"high": 0, "mid": 1, "floor": 2}
        subs = sorted(bank(src).subs("tom"), key=lambda s: order.get(s, 1))
        n = rng.choice([1, 2, 2, 3, 3, 3, 4])
        chosen = (subs * 4)[:n] if len(subs) < n else sorted(rng.sample(subs, n), key=lambda s: order.get(s, 1))
        base = rng.uniform(-6, 3)
        for i, s in enumerate(chosen):
            # Repeated sub-kinds get detuned downwards so the toms still descend.
            shift = 2 ** ((rng.uniform(-1.5, 1.5) - 2.5 * (chosen[:i].count(s))) / 12)
            toms.append(Voice(src, "tom", s, 10 ** ((base + rng.uniform(-2, 2)) / 20), shift))
    return VirtualKit(voices, toms)


# ---------------------------------------------------------------- performances
@dataclass
class Ev:
    t: float  # seconds
    inst: str  # kick snare cross_stick hihat hihat_open hihat_pedal ride ride_bell crash tom0..tom3 other
    vel: int


def _vel(rng, base, spread=10):
    return int(np.clip(rng.gauss(base, spread), 1, 127))


STYLES = ("rock", "pop", "funk", "disco", "jazz", "jazz_ballad", "shuffle", "metal", "punk", "reggae", "latin",
          "hiphop", "halftime", "ballad", "train", "electronic", "isolated", "chaos")
STYLE_WEIGHTS = (10, 8, 8, 4, 8, 4, 5, 6, 4, 4, 5, 5, 4, 5, 3, 3, 6, 4)


def performance(rng: random.Random, kit: VirtualKit, style: str | None = None) -> tuple[list[Ev], float, dict]:
    """A random performance; returns events, duration (s) and a description."""
    style = style or rng.choices(STYLES, STYLE_WEIGHTS)[0]
    n_toms = len(kit.toms)
    has = set(kit.voices)
    if style == "isolated":
        return _isolated(rng, kit), 0.0, {"style": style}
    tempo = {"jazz": (110, 260), "jazz_ballad": (55, 90), "metal": (120, 230), "punk": (150, 220),
             "ballad": (55, 85), "halftime": (70, 100), "reggae": (65, 90), "disco": (110, 130),
             "electronic": (110, 140), "hiphop": (75, 100), "shuffle": (80, 140), "train": (130, 190)}.get(
        style, (70, 180))
    bpm = rng.uniform(*tempo)
    if style in ("jazz", "shuffle", "jazz_ballad") or rng.random() < 0.1:
        swing = rng.uniform(0.58, 0.68)
    else:
        swing = 0.5
    beats = rng.choice([4] * 8 + [3, 2]) if style not in ("jazz_ballad",) else 4
    compound = style not in ("jazz", "shuffle") and beats == 4 and rng.random() < 0.08  # 12/8 feel
    n_bars = rng.randint(6, 16)
    spb = 60.0 / bpm
    human = rng.uniform(0, 14) / 1000
    ev: list[Ev] = []
    cym = "ride" if (style in ("jazz", "jazz_ballad") and "ride" in has) or ("ride" in has and rng.random() < 0.25) \
        else "hihat"
    if cym == "hihat" and "hihat" not in has:
        cym = "ride" if "ride" in has else "crash"
    hat_open_p = {"disco": 0.9, "funk": 0.15, "rock": 0.08, "pop": 0.1, "punk": 0.25}.get(style, 0.04)
    ghost_p = {"funk": 0.35, "rock": 0.08, "pop": 0.06, "hiphop": 0.15, "jazz": 0.25, "shuffle": 0.2,
               "halftime": 0.25, "latin": 0.1, "ballad": 0.05}.get(style, 0.03)
    loud = rng.uniform(70, 118)

    def at(bar, beat, frac=0.0):
        sub = frac
        if swing != 0.5 and abs(frac - 0.5) < 1e-6:
            sub = swing
        elif swing != 0.5 and abs(frac - 0.75) < 1e-6:
            sub = swing + (1 - swing) / 2
        return (bar * beats + beat + sub) * spb + rng.gauss(0, human)

    def add(t, inst, vel):
        if inst in has or inst.startswith("tom"):
            if inst.startswith("tom") and int(inst[3:]) >= n_toms:
                return
            ev.append(Ev(t, inst, vel))

    grid = [0, 1 / 3, 2 / 3] if compound else [0, 0.25, 0.5, 0.75]
    for bar in range(n_bars):
        fill = n_toms and (bar % 4 == 3 or (bar % 2 == 1 and style in ("metal", "funk"))) and rng.random() < 0.6
        fill_from = beats - rng.choice([1, 1, 2]) if fill else beats
        if bar % 4 == 0 and rng.random() < 0.7 and bar > 0 or (bar == 0 and rng.random() < 0.4):
            add(at(bar, 0), "crash", _vel(rng, loud + 10))
            add(at(bar, 0), "kick", _vel(rng, loud + 5))
        for beat in range(beats):
            if beat >= fill_from:
                continue
            for f in grid:
                t = at(bar, beat, f)
                on_beat, eighth = f == 0, f in (0, 0.5)
                # --- time-keeping cymbal
                if style in ("jazz", "jazz_ballad") and cym == "ride":
                    if on_beat or (f == 0.5 and beat % 2 == 1):
                        add(t, "ride", _vel(rng, loud - (0 if on_beat else 12)))
                    if on_beat and beat % 2 == 1 and "hihat_pedal" in has:
                        add(t, "hihat_pedal", _vel(rng, 70))
                elif style == "electronic":
                    if f == 0.5:
                        add(t, "hihat_open" if rng.random() < 0.7 else "hihat", _vel(rng, loud - 5))
                elif style == "disco":
                    if f == 0.5:
                        add(t, "hihat_open", _vel(rng, loud))
                    elif on_beat or f in (0.25, 0.75):
                        add(t, "hihat", _vel(rng, loud - 10))
                elif style == "reggae":
                    if eighth:
                        add(t, cym, _vel(rng, loud - 10))
                elif style == "train":
                    pass
                else:
                    dens = {"funk": 16, "hiphop": 16, "pop": 8, "rock": 8, "metal": 8, "punk": 8, "ballad": 8,
                            "halftime": 16, "latin": 8, "shuffle": 8}.get(style, 8)
                    if rng.random() < 0.15:
                        dens = 4 if dens == 8 else 8
                    want = on_beat if dens == 4 else eighth if dens == 8 else True
                    if compound:
                        want = True
                    if want:
                        inst = cym
                        if cym == "hihat" and f == 0.5 and rng.random() < hat_open_p and "hihat_open" in has:
                            inst = "hihat_open"
                        if cym == "ride" and on_beat and rng.random() < 0.15 and "ride_bell" in has:
                            inst = "ride_bell"
                        add(t, inst, _vel(rng, loud - (0 if on_beat else 14) - (8 if f in (0.25, 0.75) else 0)))
                # --- kick
                kick_p = {"metal": 0.55 if f in (0.25, 0.75) else 0.6, "punk": 0.45}.get(style)
                if style == "electronic" or style == "disco":
                    kp = 1.0 if on_beat else 0.03
                elif style == "reggae":
                    kp = 1.0 if (on_beat and beat == 2) else 0.03
                elif style in ("jazz", "jazz_ballad"):
                    kp = 0.12 if eighth else 0.02
                elif style == "train":
                    kp = 0.9 if on_beat and beat % 2 == 0 else 0.0
                elif style == "halftime":
                    kp = 0.95 if (beat == 0 and on_beat) else 0.25 if eighth and beat != 2 else 0.08
                elif kick_p is not None:
                    kp = kick_p if beat % 2 == 0 or f != 0 else 0.3
                else:
                    kp = (0.95 if beat == 0 and on_beat else 0.55 if beat == 2 and on_beat else
                          0.3 if f == 0.5 else 0.12 if f in (0.25, 0.75) else 0.05)
                if rng.random() < kp:
                    add(t, "kick", _vel(rng, loud))
                # --- snare / cross-stick
                back = on_beat and ((beat % 2 == 1 and beats in (2, 4) and style not in ("halftime", "reggae"))
                                    or (beat == 2 and style in ("halftime", "reggae") and beats == 4)
                                    or (beats == 3 and beat == 2))
                if style == "train":
                    if not compound:
                        add(t, "snare", _vel(rng, loud - (0 if f in (0.25, 0.75) and beat % 2 == 1 else 30), 8))
                    continue
                if style in ("jazz", "jazz_ballad"):
                    if rng.random() < 0.12:
                        add(t, "snare", _vel(rng, 40 if rng.random() < 0.7 else loud))
                    continue
                if back:
                    inst = "cross_stick" if style in ("ballad", "latin", "reggae") and rng.random() < 0.6 \
                        and "cross_stick" in has else "snare"
                    add(t, inst, _vel(rng, loud + 8))
                elif rng.random() < ghost_p and not on_beat:
                    add(t, "snare", _vel(rng, rng.uniform(14, 42), 5))
                elif style == "latin" and rng.random() < 0.15 and "cross_stick" in has:
                    add(t, "cross_stick", _vel(rng, loud - 10))
        if fill:
            _fill(rng, bar, fill_from, beats, spb, at, add, n_toms, loud)
        if rng.random() < 0.06 and "other" in has:
            add(at(bar, rng.randrange(beats), rng.choice(grid)), "other", _vel(rng, loud - 10))
    add(at(n_bars, 0), "crash", _vel(rng, loud + 10))
    add(at(n_bars, 0), "kick", _vel(rng, loud + 5))
    dur = (n_bars * beats + 1) * spb
    if style == "chaos":
        ev = _chaos(rng, kit, ev, dur)
    return sorted(ev, key=lambda e: e.t), dur, {"style": style, "bpm": round(bpm, 1), "swing": swing}


def _fill(rng, bar, start, beats, spb, at, add, n_toms, loud):
    kind = rng.choice(["16ths", "16ths", "triplets", "8ths", "flams", "roll", "unison"])
    toms = [f"tom{i}" for i in range(n_toms)]
    seq = ["snare"] + toms
    for beat in range(start, beats):
        if kind == "triplets":
            fracs = [0, 1 / 3, 2 / 3]
        elif kind == "8ths":
            fracs = [0, 0.5]
        elif kind == "roll":
            fracs = [i / 8 for i in range(8)]
        else:
            fracs = [0, 0.25, 0.5, 0.75]
        for j, f in enumerate(fracs):
            t = at(bar, beat, f)
            if kind == "roll":
                add(t, "snare", _vel(rng, loud - 25 + j * 3, 6))
                continue
            prog = (beat - start + f) / max(1, beats - start)
            inst = seq[min(len(seq) - 1, int(prog * len(seq)))] if rng.random() < 0.8 else rng.choice(seq)
            v = _vel(rng, loud + (8 if f == 0 else 0))
            if kind == "flams" and f == 0:
                add(t - rng.uniform(0.015, 0.04), inst, _vel(rng, v * 0.45, 5))
            add(t, inst, v)
            if kind == "unison" and f == 0:
                add(t, "crash", _vel(rng, loud + 5))
                add(t, "kick", _vel(rng, loud))
            elif rng.random() < 0.25:
                add(t, "kick", _vel(rng, loud - 5))


def _isolated(rng, kit) -> list[Ev]:
    """Single and combined strokes at irregular times: sound identity without rhythm cues."""
    insts = [c for c in kit.voices] + [f"tom{i}" for i in range(len(kit.toms))]
    t = 0.3
    ev = []
    while t < rng.uniform(12, 25):
        k = rng.choices([1, 2, 3], [0.55, 0.35, 0.1])[0]
        chosen = rng.sample(insts, min(k, len(insts)))
        hands = [c for c in chosen if c not in ("kick", "hihat_pedal")]
        if sum(c.startswith("hihat") and c != "hihat_pedal" for c in hands) > 1:
            chosen = [c for c in chosen if c not in ("hihat", "hihat_open")] + ["hihat"]
        for c in chosen:
            v = int(rng.choice([rng.uniform(10, 45), rng.uniform(45, 127)]))
            ev.append(Ev(t + rng.gauss(0, 0.002), c, v))
        t += rng.choice([rng.uniform(0.08, 0.3), rng.uniform(0.3, 1.2)])
    return ev


def _chaos(rng, kit, ev, dur) -> list[Ev]:
    insts = [c for c in kit.voices] + [f"tom{i}" for i in range(len(kit.toms))]
    for e in ev:
        if rng.random() < 0.3:
            e.inst = rng.choice(insts)
    return ev


# ---------------------------------------------------------------- rendering
def _resample(x: np.ndarray, ratio: float) -> np.ndarray:
    if abs(ratio - 1) < 1e-3:
        return x
    n = int(len(x) / ratio)
    return np.interp(np.arange(n) * ratio, np.arange(len(x)), x).astype(np.float32)


def render_drums(ev: list[Ev], dur: float, kit: VirtualKit, rng: random.Random) -> np.ndarray:
    out = np.zeros(int((dur + 3.5) * SR), dtype=np.float32)
    hat_events = sorted(e.t for e in ev if e.inst in ("hihat", "hihat_open", "hihat_pedal"))
    for e in ev:
        if e.inst.startswith("tom"):
            idx = int(e.inst[3:])
            if idx >= len(kit.toms):
                continue
            v = kit.toms[idx]
        else:
            v = kit.voices.get(e.inst)
            if v is None:
                continue
        x, layer_vel = bank(v.bank).get(v.cls, v.sub, e.vel, rng)
        x = _resample(x, v.shift)
        g = v.gain * (e.vel / max(layer_vel, 1)) ** 1.3 * (e.vel / 127) ** 0.4
        if e.inst == "hihat_open":  # choked by the next hi-hat stroke or the pedal
            nxt = next((t for t in hat_events if t > e.t + 0.02), None)
            if nxt is not None:
                cut = int((nxt - e.t) * SR)
                if cut < len(x):
                    fade = min(len(x) - cut, int(rng.uniform(0.008, 0.03) * SR))
                    x = x.copy()
                    x[cut:cut + fade] *= np.linspace(1, 0, fade, dtype=np.float32)
                    x[cut + fade:] = 0
        i0 = int(max(0.0, e.t) * SR)
        n = min(len(x), len(out) - i0)
        if n > 0:
            out[i0:i0 + n] += g * x[:n]
    return out


def _biquad(x, kind, f0, gain_db, q=0.7):
    from scipy.signal import lfilter
    A = 10 ** (gain_db / 40)
    w0 = 2 * np.pi * f0 / SR
    alpha = np.sin(w0) / (2 * q)
    c = np.cos(w0)
    if kind == "peak":
        b = [1 + alpha * A, -2 * c, 1 - alpha * A]
        a = [1 + alpha / A, -2 * c, 1 - alpha / A]
    elif kind == "low":
        sq = 2 * np.sqrt(A) * alpha
        b = [A * ((A + 1) - (A - 1) * c + sq), 2 * A * ((A - 1) - (A + 1) * c), A * ((A + 1) - (A - 1) * c - sq)]
        a = [(A + 1) + (A - 1) * c + sq, -2 * ((A - 1) + (A + 1) * c), (A + 1) + (A - 1) * c - sq]
    else:  # high shelf
        sq = 2 * np.sqrt(A) * alpha
        b = [A * ((A + 1) + (A - 1) * c + sq), -2 * A * ((A - 1) + (A + 1) * c), A * ((A + 1) + (A - 1) * c - sq)]
        a = [(A + 1) - (A - 1) * c + sq, 2 * ((A - 1) - (A + 1) * c), (A + 1) - (A - 1) * c - sq]
    return lfilter(np.array(b) / a[0], np.array(a) / a[0], x).astype(np.float32)


def process_bus(x: np.ndarray, rng: random.Random) -> np.ndarray:
    """Room, EQ, compression and saturation: a different 'recording' each clip."""
    from scipy.signal import fftconvolve
    if rng.random() < 0.8:  # room / reverb: exponentially decaying noise
        rt60 = rng.uniform(0.15, 1.6)
        n = int(min(2.5, rt60 * 1.2) * SR)
        t = np.arange(n) / SR
        ir = np.random.default_rng(rng.randrange(1 << 30)).standard_normal(n).astype(np.float32)
        ir *= np.exp(-6.9 * t / rt60).astype(np.float32)
        ir = _biquad(ir, "high", rng.uniform(3000, 8000), rng.uniform(-12, -3))
        ir[:int(rng.uniform(0.005, 0.03) * SR)] = 0
        ir /= np.sqrt(np.sum(ir ** 2)) + 1e-9
        wet = rng.uniform(0.05, 0.45)
        x = x + wet * fftconvolve(x, ir)[:len(x)].astype(np.float32)
    for _ in range(rng.randint(0, 3)):
        kind = rng.choice(["low", "high", "peak"])
        f0 = {"low": rng.uniform(60, 250), "high": rng.uniform(3000, 10000), "peak": rng.uniform(150, 8000)}[kind]
        x = _biquad(x, kind, f0, rng.uniform(-8, 8), q=rng.uniform(0.5, 2.0))
    if rng.random() < 0.6:  # feed-forward compressor
        thr = rng.uniform(0.05, 0.4) * float(np.max(np.abs(x)) + 1e-9)
        ratio = rng.uniform(2, 8)
        att = np.exp(-1 / (rng.uniform(0.001, 0.01) * SR))
        rel = np.exp(-1 / (rng.uniform(0.04, 0.25) * SR))
        env = _envelope(np.abs(x), att, rel)
        gain = np.where(env > thr, (thr + (env - thr) / ratio) / (env + 1e-9), 1.0).astype(np.float32)
        x = x * gain
    if rng.random() < 0.25:
        drive = rng.uniform(1.5, 5)
        x = np.tanh(drive * x / (np.max(np.abs(x)) + 1e-9)) / np.tanh(drive)
    return x.astype(np.float32)


def _envelope(a: np.ndarray, att: float, rel: float) -> np.ndarray:
    # Downsampled one-pole follower (exact per-sample loops are slow in Python).
    step = 32
    blocks = a[: len(a) // step * step].reshape(-1, step).max(axis=1)
    env = np.empty_like(blocks)
    level = 0.0
    a_b, r_b = att ** step, rel ** step
    for i, v in enumerate(blocks):
        coef = a_b if v > level else r_b
        level = coef * level + (1 - coef) * v
        env[i] = level
    full = np.repeat(env, step)
    if len(full) < len(a):
        full = np.concatenate([full, np.full(len(a) - len(full), env[-1] if len(env) else 0.0)])
    return full


def accompaniment(ev: list[Ev], dur: float, info: dict, rng: random.Random) -> np.ndarray | None:
    """Bass, chords and a lead line from General MIDI instruments, in time with the drums."""
    import mido
    bpm = info.get("bpm") or 120
    mid = mido.MidiFile(ticks_per_beat=480)
    tracks = []
    key = rng.randrange(12)
    prog = [0, 5, 3, 4] if rng.random() < 0.5 else rng.sample([0, 2, 3, 4, 5, 6], 4)
    scale = [0, 2, 4, 5, 7, 9, 11]
    beats = int(dur * bpm / 60)
    parts = [("bass", rng.choice([32, 33, 34, 35, 36, 37, 38, 39])),
             ("chords", rng.choice([0, 1, 4, 5, 16, 17, 18, 19, 24, 25, 26, 27, 28, 29, 30, 48, 49, 50, 61, 88, 89,
                                    90, 91, 94]))]
    if rng.random() < 0.6:
        parts.append(("lead", rng.choice([29, 30, 52, 53, 54, 56, 57, 65, 66, 71, 73, 80, 81, 85])))
    if rng.random() < 0.3:
        parts.append(("pad", rng.choice([48, 49, 50, 89, 91, 92, 95])))
    kicks = [e.t for e in ev if e.inst == "kick"]
    tpb = 480
    for ch, (role, program) in enumerate(parts):
        tr = mido.MidiTrack()
        tr.append(mido.MetaMessage("set_tempo", tempo=int(60e6 / bpm), time=0) if ch == 0 else
                  mido.MetaMessage("track_name", name=role, time=0))
        tr.append(mido.Message("program_change", channel=ch, program=program, time=0))
        notes = []  # (start_tick, end_tick, note, vel)
        for b in range(0, beats, 4):
            deg = prog[(b // 4) % 4]
            root = 36 + key + scale[deg]
            if role == "bass":
                if rng.random() < 0.5:  # follow the kick
                    for k in kicks:
                        kb = k * bpm / 60
                        if b <= kb < b + 4:
                            s = int(kb * tpb)
                            notes.append((s, s + int(0.45 * tpb), root, rng.randint(80, 115)))
                else:
                    step = rng.choice([1, 0.5])
                    x = 0.0
                    while x < 4:
                        n = root + (12 if rng.random() < 0.15 else 0) + (7 if rng.random() < 0.15 else 0)
                        s = int((b + x) * tpb)
                        notes.append((s, s + int(step * tpb * 0.9), n, rng.randint(80, 115)))
                        x += step
            elif role in ("chords", "pad"):
                chord = [root + 12 + scale[(deg + i) % 7] - scale[deg] + (12 if (deg + i) >= 7 else 0)
                         for i in (0, 2, 4)]
                if role == "pad" or rng.random() < 0.4:
                    for n in chord:
                        notes.append((int(b * tpb), int((b + 4) * tpb) - 10, n + 12, rng.randint(55, 90)))
                else:
                    step = rng.choice([0.5, 1, 0.25])
                    x = 0.0
                    while x < 4:
                        if rng.random() < 0.8:
                            s = int((b + x) * tpb)
                            for i, n in enumerate(chord):
                                notes.append((s + i * 8, s + int(step * tpb * 0.8), n + 12, rng.randint(60, 105)))
                        x += step
            else:  # lead
                x = 0.0
                while x < 4:
                    ln = rng.choice([0.5, 1, 1.5, 2])
                    if rng.random() < 0.75:
                        n = 60 + key + rng.choice(scale) + rng.choice([0, 12])
                        s = int((b + x) * tpb)
                        notes.append((s, s + int(ln * tpb * 0.95), n, rng.randint(60, 110)))
                    x += ln
        msgs = []
        for s, e, n, v in notes:
            msgs.append((s, mido.Message("note_on", channel=ch, note=int(n), velocity=int(v))))
            msgs.append((e, mido.Message("note_off", channel=ch, note=int(n), velocity=0)))
        msgs.sort(key=lambda m: (m[0], m[1].type == "note_on"))
        prev = 0
        for tk, m in msgs:
            tr.append(m.copy(time=max(0, tk - prev)))
            prev = max(prev, tk)
        tracks.append(tr)
    mid.tracks.extend(tracks)
    sf2 = rng.choice([f for f in GM_SOUNDFONTS if Path(f).exists()])
    import soundfile as sf
    with tempfile.TemporaryDirectory() as td:
        mp, wp = Path(td) / "a.mid", Path(td) / "a.wav"
        mid.save(str(mp))
        r = subprocess.run(["fluidsynth", "-ni", "-q", "-g", "0.6", "-r", str(SR), "-F", str(wp), sf2, str(mp)],
                           capture_output=True)
        if r.returncode != 0 or not wp.exists():
            return None
        y, _ = sf.read(wp, dtype="float32", always_2d=True)
    return y.mean(axis=1)


def mp3_roundtrip(x: np.ndarray, rng: random.Random) -> np.ndarray:
    br = rng.choice(["64k", "96k", "128k", "160k", "192k"])
    with tempfile.TemporaryDirectory() as td:
        import soundfile as sf
        w, m = Path(td) / "a.wav", Path(td) / "a.mp3"
        sf.write(w, x, SR, subtype="PCM_16")
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(w), "-b:a", br, str(m)], capture_output=True)
        if r.returncode != 0:
            return x
        r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(m), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                           capture_output=True)
        if r.returncode != 0:
            return x
        y = np.frombuffer(r.stdout, dtype=np.float32).copy()
    # MP3 adds encoder delay; realign by cross-correlating the envelopes' first second.
    n = min(len(x), len(y), SR * 2)
    a = np.abs(x[:n]) - np.abs(x[:n]).mean()
    b = np.abs(y[:n]) - np.abs(y[:n]).mean()
    lags = range(0, 3000)
    best = max(lags, key=lambda L: float(np.dot(a[: n - 3000], b[L:L + n - 3000])))
    y = y[best:]
    if len(y) < len(x):
        y = np.concatenate([y, np.zeros(len(x) - len(y), dtype=np.float32)])
    return y[: len(x)]


@dataclass
class Clip:
    audio: np.ndarray
    events: list[tuple[float, str]]  # (seconds, classifier class)
    drums_only: bool
    info: dict


def make_clip(seed: int, mix_p: float = 0.6) -> Clip:
    rng = random.Random(seed)
    np.random.seed(seed % (1 << 32))
    kit = make_kit(rng)
    ev, dur, info = performance(rng, kit)
    if not ev:
        return make_clip(seed + 1_000_003, mix_p)
    if dur == 0.0:
        dur = max(e.t for e in ev) + 0.5
    drums = process_bus(render_drums(ev, dur, kit, rng), rng)
    drums_only = rng.random() >= mix_p
    y = drums
    if not drums_only:
        acc = accompaniment(ev, dur, info, rng)
        if acc is not None and np.std(acc) > 1e-5:
            acc = process_bus(acc, rng) if rng.random() < 0.5 else acc
            n = len(drums)
            acc = acc[:n] if len(acc) >= n else np.concatenate([acc, np.zeros(n - len(acc), dtype=np.float32)])
            ratio_db = rng.uniform(-10, 4)  # drums relative to the band (RMS)
            rd = np.sqrt(np.mean(drums ** 2)) + 1e-9
            ra = np.sqrt(np.mean(acc ** 2)) + 1e-9
            y = drums + acc * (rd / ra) * 10 ** (-ratio_db / 20)
        else:
            drums_only = True
    if rng.random() < 0.25:
        y = y + np.random.default_rng(seed).standard_normal(len(y)).astype(np.float32) * float(np.std(y)) * \
            10 ** (rng.uniform(-60, -30) / 20)
    y = y / (np.max(np.abs(y)) + 1e-9) * 10 ** (rng.uniform(-12, -0.5) / 20)
    if rng.random() < 0.3:
        y = mp3_roundtrip(y, rng)
    labels = []
    for e in ev:
        c = "tom" if e.inst.startswith("tom") else e.inst
        labels.append((e.t, c))
    info.update(kit=sorted({v.bank for v in kit.voices.values()}), drums_only=drums_only, n_toms=len(kit.toms))
    return Clip(y.astype(np.float32), sorted(labels), drums_only, info)


if __name__ == "__main__":
    import sys
    import soundfile as sf
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    c = make_clip(seed)
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(f"clip_{seed}.wav")
    sf.write(out, c.audio, SR)
    print(out, len(c.audio) / SR, "s", c.info, len(c.events), "events")
