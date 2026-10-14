"""Build the one-shot sample library used to synthesize classifier training data.

Every kit becomes a set of labelled one-shots (class, sub-kind, velocity,
mono float audio at 44.1 kHz) in ~/.cache/drum-agent/adt/oneshots/<kit>.npz.

Sources (all installed from the Ubuntu archive; nothing is redistributed, the
samples only shape the classifier's weights; see docs/MODELS.md):
  - SF2 kits rendered note by note with FluidSynth: AVL Drumkits (Black Pearl,
    Red Zeppelin, Blonde Bop; CC BY-SA 3.0), FluidR3 GM (MIT) and the csound
    GM bank.
  - Hydrogen drumkits (CC0 / CC BY / CC BY-SA / GPL), read from their samples.

Held out, never used here: every FluidR3 sample that only the Jazz (32) and
Brush (40) kits use, so scripts/eval_detection.py's held-out conditions stay
unseen, and the whole MDB Drums dataset (scripts/eval_real.py).

Usage: python scripts/adt/oneshots.py [--kits avl_black_pearl,...] [--list]
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import mido
import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sf2info import presets  # noqa: E402

SR = 44100
CACHE = Path(os.environ.get("DRUM_AGENT_DATA", Path.home() / ".cache" / "drum-agent")) / "adt" / "oneshots"
SF2 = "/usr/share/sounds/sf2"
HYDROGEN = "/usr/share/hydrogen/data/drumkits"
VELOCITIES = (20, 40, 62, 84, 106, 127)
MAX_LEN = {"crash": 3.0, "ride": 2.5, "ride_bell": 2.5, "hihat_open": 1.6, "tom": 1.5, "kick": 1.0,
           "snare": 1.0, "other": 1.2}
DEFAULT_MAX = 0.8

# Classifier classes. "tom" is one class (tom order is relative to the kit and is
# decided per recording from pitch); "other" is aux percussion, a distractor.
CLASSES = ("kick", "snare", "cross_stick", "hihat", "hihat_open", "hihat_pedal", "ride", "ride_bell",
           "crash", "tom", "other")

# General MIDI drum notes -> (class, sub-kind).
GM_NOTES = {
    35: ("kick", "kick"), 36: ("kick", "kick"),
    37: ("cross_stick", "cross_stick"),
    38: ("snare", "snare"), 40: ("snare", "snare_edge"),
    42: ("hihat", "hihat"), 44: ("hihat_pedal", "hihat_pedal"), 46: ("hihat_open", "hihat_open"),
    41: ("tom", "floor"), 43: ("tom", "floor"), 45: ("tom", "mid"), 47: ("tom", "mid"),
    48: ("tom", "high"), 50: ("tom", "high"),
    49: ("crash", "crash"), 57: ("crash", "crash"), 52: ("crash", "china"), 55: ("crash", "splash"),
    51: ("ride", "ride"), 59: ("ride", "ride"), 53: ("ride_bell", "ride_bell"),
    39: ("other", "clap"), 54: ("other", "tambourine"), 56: ("other", "cowbell"), 69: ("other", "cabasa"),
    70: ("other", "maracas"), 75: ("other", "claves"),
}
# AVL Drumkits use their own map (the sample names say what each key is).
AVL_NOTES = {
    36: ("kick", "kick"), 37: ("cross_stick", "cross_stick"), 38: ("snare", "snare"),
    40: ("snare", "snare_edge"), 41: ("tom", "floor"), 43: ("tom", "floor"), 42: ("hihat", "hihat"),
    44: ("hihat_pedal", "hihat_pedal"), 45: ("tom", "high"), 47: ("tom", "high"),
    46: ("hihat_open", "hihat_semi"), 48: ("hihat_open", "hihat_swish"), 49: ("crash", "crash"),
    51: ("ride", "ride"), 59: ("ride", "ride_shank"), 53: ("ride_bell", "ride_bell"),
    55: ("crash", "splash"), 57: ("crash", "crash"), 60: ("crash", "crash3"),
    39: ("other", "clap"), 54: ("other", "tambourine"), 56: ("other", "cowbell"), 61: ("other", "shaker"),
}

# name -> (kind, sf2 file or hydrogen dir, bank, program or None)
SF2_KITS = {
    "avl_black_pearl": ("Black_Pearl_4_LV2.sf2", 0, 0, AVL_NOTES),
    "avl_red_zeppelin": ("Red_Zeppelin_4_LV2.sf2", 0, 0, AVL_NOTES),
    "avl_blonde_bop": ("Blonde_Bop_LV2.sf2", 0, 0, AVL_NOTES),
    **{f"fluid_{p}": ("FluidR3_GM.sf2", 128, p, GM_NOTES) for p in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11,
                                                                     12, 13, 14, 15, 16, 17, 18, 19, 24, 25)},
    **{f"csound_{p}": ("sf_GMbank.sf2", 128, p, GM_NOTES) for p in (0, 8, 16, 24, 25, 32, 40)},
}
HYDROGEN_KITS = ("Audiophob", "BJA_Pacific", "ColomboAcousticDrumkit", "ForzeeStereo", "Millo_MultiLayered2",
                 "Millo_MultiLayered3", "Millo-Drums_v.1", "The Black Pearl 1.0", "VariBreaks",
                 "rumpf_kit_z01_h2", "ElectricEmpireKit", "Gimme A Hand 1.0")
HELD_OUT_FLUID_PROGRAMS = (32, 40)

# Licence of each source (from /usr/share/doc/<package>/copyright and the kits' own files).
# The samples are never redistributed; they shape the classifier's weights (docs/MODELS.md).
LICENSES = {
    "avl": ("AVL Drumkits, Glen MacArthur", "CC-BY-SA-3.0"),
    "fluid": ("FluidR3 GM, Frank Wen", "MIT"),
    "csound": ("csound sf_GMbank.sf2", "public-domain"),
    "h2_audiophob": ("Hydrogen Audiophob kit", "CC0"),
    "h2_bja_pacific": ("Hydrogen BJA Pacific kit, Luc Tunguay", "CC-BY-SA-3.0-US"),
    "h2_colomboacousticdrumkit": ("Hydrogen Colombo Acoustic kit, Marcos Guglielmetti", "GPL-2+"),
    "h2_forzeestereo": ("Hydrogen ForzeeStereo kit", "GPL-2"),
    "h2_millo_multilayered2": ("Hydrogen Millo MultiLayered 2, Emiliano Grilli", "GPL-2"),
    "h2_millo_multilayered3": ("Hydrogen Millo MultiLayered 3, Emiliano Grilli", "GPL-2"),
    "h2_millo_drums_v_1": ("Hydrogen Millo Drums, Emiliano Grilli", "GPL-2"),
    "h2_the_black_pearl_1_0": ("Hydrogen The Black Pearl, Glen MacArthur", "GPL-2"),
    "h2_varibreaks": ("Hydrogen VariBreaks", "GPL-2+"),
    "h2_rumpf_kit_z01_h2": ("Hydrogen rumpf kit, Emanuel Rumpf", "CC-BY-3.0"),
    "h2_electricempirekit": ("Hydrogen Electric Empire kit", "GPL-2+"),
    "h2_gimme_a_hand_1_0": ("Hydrogen Gimme A Hand", "GPL-2+"),
}
PERMISSIVE = {"MIT", "public-domain", "CC0", "CC-BY-3.0"}


def license_of(kit: str) -> tuple[str, str]:
    return LICENSES.get(kit) or LICENSES[kit.split("_")[0]]


def held_out_fluid_samples() -> set[str]:
    """Sample names that only FluidR3's held-out Jazz/Brush kits (and their variants) use."""
    ps = [p for p in presets(f"{SF2}/FluidR3_GM.sf2") if p["bank"] == 128]
    used_train, used_held = set(), set()
    train_progs = {p for name, (f, b, p, _) in SF2_KITS.items() if f == "FluidR3_GM.sf2"}
    for p in ps:
        names = {s for zones in p["keys"].values() for _, s, _, _ in zones}
        if p["program"] in train_progs:
            used_train |= names
        elif 32 <= p["program"] <= 47:
            used_held |= names
    return used_held - used_train


def _render_sf2(sf2: str, bank: int, program: int, notes: list[int]) -> tuple[np.ndarray, list[tuple[int, int, float]]]:
    """Render every (note, velocity) as an isolated hit; returns audio and (note, vel, onset_s)."""
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.MetaMessage("set_tempo", tempo=500000, time=0))  # 0.5 s per beat
    ch = 9 if bank == 128 else 0
    if bank != 128:
        tr.append(mido.Message("control_change", channel=ch, control=0, value=bank, time=0))
    tr.append(mido.Message("program_change", channel=ch, program=program, time=0))
    spacing = 3.2  # seconds: long enough for a crash to die away
    gap = int(spacing / 0.5 * 480)
    events = []
    t = 0.5
    first = True
    for n in notes:
        for v in VELOCITIES:
            tr.append(mido.Message("note_on", channel=ch, note=n, velocity=v, time=480 if first else gap - 10))
            tr.append(mido.Message("note_off", channel=ch, note=n, velocity=0, time=10))
            events.append((n, v, t))
            t += spacing
            first = False
    with tempfile.TemporaryDirectory() as td:
        mp, wp = Path(td) / "k.mid", Path(td) / "k.wav"
        mid.save(str(mp))
        subprocess.run(["fluidsynth", "-ni", "-q", "-g", "0.5", "-R", "0", "-C", "0", "-r", str(SR),
                        "-F", str(wp), sf2, str(mp)], check=True, capture_output=True)
        y, sr = sf.read(wp, dtype="float32", always_2d=True)
    return y.mean(axis=1), events


def _trim(x: np.ndarray, cls: str) -> np.ndarray | None:
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    if peak < 1e-4:
        return None
    x = x[: int(MAX_LEN.get(cls, DEFAULT_MAX) * SR)]
    env = np.maximum.accumulate(np.abs(x)[::-1])[::-1]  # remaining peak from each sample on
    keep = np.nonzero(env > peak * 10 ** (-60 / 20))[0]
    end = int(keep[-1]) + 1 if len(keep) else len(x)
    x = x[:end].copy()
    fade = min(len(x), int(0.01 * SR))
    x[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
    return x


def build_sf2_kit(name: str, held: set[str]) -> list[dict]:
    file, bank, program, notemap = SF2_KITS[name]
    path = f"{SF2}/{file}"
    pr = next((p for p in presets(path) if p["bank"] == bank and p["program"] == program), None)
    if pr is None:
        raise SystemExit(f"{name}: no preset bank {bank} program {program} in {file}")
    notes = [n for n in sorted(notemap) if n in pr["keys"]]
    if file == "FluidR3_GM.sf2":
        notes = [n for n in notes if not ({s for _, s, _, _ in pr["keys"][n]} & held)]
    y, events = _render_sf2(path, bank, program, notes)
    out = []
    for n, v, t in events:
        cls, sub = notemap[n]
        i0 = int(t * SR)
        # FluidSynth starts the note on the tick; take a few ms before it.
        seg = y[max(0, i0 - int(0.005 * SR)): i0 + int(3.1 * SR)]
        x = _trim(seg, cls)
        if x is not None:
            out.append({"cls": cls, "sub": sub, "vel": v, "audio": x, "src": f"{file}:{bank}:{program}:{n}"})
    return out


_HH_KEYS = [
    (r"choke|roll", None),
    (r"kick|bass ?drum|bassdrum|\bbd\b", ("kick", "kick")),
    (r"rim ?click|side ?stick|sidestick|^stick$|cross", ("cross_stick", "cross_stick")),
    (r"snare", ("snare", "snare")),
    (r"(hat|hh).*(pedal|\bpd\b|foot)|pedal hh", ("hihat_pedal", "hihat_pedal")),
    (r"(hat|hh).*(open|\bop\b|semi|swish|free)|open hh", ("hihat_open", "hihat_open")),
    (r"(hat|hh).*(closed|\bcl\b)|closed hh|^.*hat \d+ cl", ("hihat", "hihat")),
    (r"crash/ride (bell)", ("ride_bell", "ride_bell")),
    (r"crash/ride (bow)", ("ride", "ride")),
    (r"ride.*(bell|cup)|bell \(|paiste bell|ride-cup", ("ride_bell", "ride_bell")),
    (r"ride", ("ride", "ride")),
    (r"crash|china|splash", ("crash", "crash")),
    (r"tom.*(floor|low)|floor", ("tom", "floor")),
    (r"tom.*mid|tom 2", ("tom", "mid")),
    (r"tom", ("tom", "high")),
    (r"tamb|cowbell|clap|shaker|maraca|agogo|clave|woodblock|conga|bongo|cajon|snap", ("other", "aux")),
]


def classify_name(name: str) -> tuple[str, str] | None:
    n = name.lower()
    for pat, res in _HH_KEYS:
        if re.search(pat, n):
            return res
    return None


def build_hydrogen_kit(kit: str) -> list[dict]:
    d = Path(HYDROGEN) / kit
    root = ET.parse(d / "drumkit.xml").getroot()
    ns = root.tag.split("}")[0] + "}" if "}" in root.tag else ""
    out = []
    for inst in root.iter(f"{ns}instrument"):
        name_el = inst.find(f"{ns}name")
        name = name_el.text.strip() if name_el is not None and name_el.text else ""
        what = classify_name(name)
        if what is None:
            continue
        cls, sub = what
        layers = []
        for layer in inst.iter(f"{ns}layer"):
            fn = layer.findtext(f"{ns}filename")
            lo = float(layer.findtext(f"{ns}min") or 0)
            hi = float(layer.findtext(f"{ns}max") or 1)
            gain = float(layer.findtext(f"{ns}gain") or 1)
            if fn:
                layers.append((fn, lo, hi, gain))
        if not layers:  # old format: one sample per instrument
            fn = inst.findtext(f"{ns}filename")
            if fn:
                layers.append((fn, 0.0, 1.0, 1.0))
        for fn, lo, hi, gain in layers:
            p = d / fn
            if not p.exists():
                continue
            try:
                x, sr = sf.read(p, dtype="float32", always_2d=True)
            except RuntimeError:
                continue
            x = x.mean(axis=1) * gain
            if sr != SR:
                import librosa
                x = librosa.resample(x, orig_sr=sr, target_sr=SR)
            x = _trim(x, cls)
            if x is None:
                continue
            vel = int(round(max(1, min(127, (lo + hi) / 2 * 127))))
            out.append({"cls": cls, "sub": sub, "vel": vel, "audio": x, "src": f"hydrogen:{kit}:{name}:{fn}"})
    # Hydrogen samples are recorded at their own levels; scale so the loudest layer
    # of each sub-kind peaks like a velocity-127 hit (relative layer levels are kept).
    by: dict[str, float] = {}
    for o in out:
        by[o["sub"] + o["cls"]] = max(by.get(o["sub"] + o["cls"], 0.0), float(np.max(np.abs(o["audio"]))))
    for o in out:
        o["audio"] = o["audio"] * (0.5 / (by[o["sub"] + o["cls"]] + 1e-9))
    return out


def save_kit(name: str, shots: list[dict]) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    audio = np.concatenate([s["audio"] for s in shots]).astype(np.float16)
    lengths = np.array([len(s["audio"]) for s in shots], dtype=np.int64)
    offsets = np.concatenate([[0], np.cumsum(lengths)[:-1]])
    path = CACHE / f"{name}.npz"
    np.savez_compressed(path, audio=audio, offsets=offsets, lengths=lengths,
                        cls=np.array([s["cls"] for s in shots]), sub=np.array([s["sub"] for s in shots]),
                        vel=np.array([s["vel"] for s in shots], dtype=np.int16),
                        src=np.array([s["src"] for s in shots]))
    return path


def all_kits() -> list[str]:
    return list(SF2_KITS) + [f"h2_{re.sub(r'[^a-z0-9]+', '_', k.lower()).strip('_')}" for k in HYDROGEN_KITS]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kits", help="comma list (default: all)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--permissive-only", action="store_true",
                    help="only sources under MIT, public domain, CC0 or CC BY (no share-alike or GPL samples)")
    a = ap.parse_args()
    h2 = {f"h2_{re.sub(r'[^a-z0-9]+', '_', k.lower()).strip('_')}": k for k in HYDROGEN_KITS}
    names = a.kits.split(",") if a.kits else all_kits()
    if a.permissive_only:
        names = [n for n in names if license_of(n)[1] in PERMISSIVE]
    if a.list:
        print("\n".join(f"{n:28s} {license_of(n)[1]:16s} {license_of(n)[0]}" for n in names))
        return
    held = held_out_fluid_samples()
    print(f"held-out FluidR3 samples (Jazz/Brush only): {len(held)}")
    for name in names:
        shots = build_sf2_kit(name, held) if name in SF2_KITS else build_hydrogen_kit(h2[name])
        if not shots:
            print(f"{name}: no usable samples")
            continue
        path = save_kit(name, shots)
        counts: dict[str, int] = {}
        for s in shots:
            counts[s["cls"]] = counts.get(s["cls"], 0) + 1
        print(f"{name:28s} {len(shots):4d} shots  " + " ".join(f"{c}:{n}" for c, n in sorted(counts.items()))
              + f"  ({path.stat().st_size / 1e6:.1f} MB)", flush=True)


if __name__ == "__main__":
    main()
