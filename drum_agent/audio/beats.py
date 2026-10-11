"""Tempo, beats, meter and downbeat estimation from detected drum strokes.

* Beats: dynamic-programming beat tracking (librosa, Ellis 2007) on the drum
  onset envelope, with the tempo octave chosen in a drum-chart range.
* Meter: which bar length (3 or 4 beats) makes the beat-level drum pattern
  repeat best, with a prior toward 4/4. Compound feel (12/8) is chosen only
  when triplet subdivisions dominate; otherwise users pass --time-signature.
* Downbeat: the phase where kicks and crashes land on beat 1 and snares on
  the backbeats. Its confidence is reported; --downbeat overrides it.

All of this is heuristic. The report states the estimates and their
confidence so a human can correct them (--bpm, --time-signature, --downbeat).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .detect import DrumHit
from .features import HOP, SR


@dataclass
class BeatGrid:
    beat_times: list[float]  # one entry per beat, plus one past the end
    tempo: float  # quarter-note BPM (for compound meters: dotted-quarter beats converted)
    beats_per_bar: int
    time_sig: str
    downbeat_index: int  # index of the first downbeat in beat_times
    meter_confidence: float
    downbeat_confidence: float
    notes: list[str] = field(default_factory=list)


def track_beats(onset_env: np.ndarray, duration: float, bpm_hint: float | None = None,
                hits: list[DrumHit] | None = None) -> tuple[float, np.ndarray, list[str]]:
    """Return (beat-level BPM, beat times in seconds, notes).

    Without a hint, related tempo candidates (x3/4, x4/3, x2/3, x3/2, x1/2, x2)
    are compared by how well they explain the strokes, because syncopated kicks
    or dense hi-hats can make the strongest periodicity a wrong metrical level.
    """
    import librosa
    env = onset_env.astype(np.float64)
    if env.max() <= 0:
        raise ValueError("no onsets found; is this a drum recording?")
    notes: list[str] = []
    if bpm_hint:
        tempo, beats = librosa.beat.beat_track(onset_envelope=env, sr=SR, hop_length=HOP, bpm=bpm_hint,
                                               tightness=300, trim=False, units="time")
        beats = np.asarray(beats, dtype=float)
        tempo = float(np.atleast_1d(tempo)[0])
    else:
        t0 = _tempo_estimate(env)
        cands = sorted({round(t0 * r, 2) for r in (1, 0.75, 4 / 3, 2 / 3, 1.5, 0.5, 2) if 55 <= t0 * r <= 210})
        scored = []
        for c in cands:
            # bpm= forces the tempo (start_bpm is only a prior and gets re-estimated).
            tc, bc = librosa.beat.beat_track(onset_envelope=env, sr=SR, hop_length=HOP, bpm=c,
                                             tightness=400, trim=False, units="time")
            bc = np.asarray(bc, dtype=float)
            if len(bc) < 4:
                continue
            scored.append((_grid_fit(hits or [], bc, float(np.atleast_1d(tc)[0])), c, float(np.atleast_1d(tc)[0]), bc))
        if not scored:
            # Forcing a fixed tempo fails when the tempo keeps changing (accelerando,
            # rubato): let the tracker follow the pulse freely instead.
            tc, bc = librosa.beat.beat_track(onset_envelope=env, sr=SR, hop_length=HOP, start_bpm=t0,
                                             tightness=40, trim=False, units="time")
            bc = np.asarray(bc, dtype=float)
            if len(bc) < 4:
                raise ValueError("beat tracking failed; pass --bpm")
            scored.append((0.0, t0, float(np.atleast_1d(tc)[0]), bc))
            notes.append("tempo varies strongly; beats were tracked freely (check the tempo marks)")
        scored.sort(key=lambda x: -x[0])
        best_score, _, tempo, beats = scored[0]
        for sc, _, tc, _ in scored[1:]:
            ratio = tc / tempo
            related = min(abs(ratio - r) for r in (0.5, 2.0, 2 / 3, 1.5, 0.75, 4 / 3))
            if related < 0.05 and sc > 0.85 * best_score:
                notes.append(f"tempo ambiguous: {tempo:.0f} BPM chosen, {tc:.0f} BPM also plausible "
                             f"(score {sc / best_score:.2f} of best); pass --bpm if the chart reads at the wrong speed")
                break
    if len(beats) < 4:
        raise ValueError("beat tracking found fewer than 4 beats; pass --bpm")
    # Steady-tempo music: a regular grid (period and phase searched) can explain the
    # strokes better than DP beats, which syncopation can bend or shift. Keep
    # whichever fits better; songs with real tempo changes keep the DP beats.
    if hits and len(hits) >= 8:
        reg = _regular_grid(hits, beats, tempo)
        if reg is not None:
            reg_beats, reg_tempo, reg_fit = reg
            dp_fit = _grid_fit(hits, beats, tempo)
            if reg_fit > dp_fit + 0.02:
                beats, tempo = reg_beats, reg_tempo
                notes.append("steady tempo: beats placed on a regular grid fitted to the strokes")
    # Phase: syncopated kicks can pull the tracker onto the off-beats (tempo right,
    # beats half a beat late). Compare with the half-beat-shifted grid.
    if hits:
        mids = (beats[:-1] + beats[1:]) / 2
        shifted = np.concatenate([[beats[0] - (mids[0] - beats[0])], mids])
        here, there = _grid_fit(hits, beats, tempo), _grid_fit(hits, shifted, tempo)
        if there > here + 0.05:
            beats = shifted
            notes.append("beat phase corrected by half a beat (syncopated pattern)")
    return tempo, beats, notes


def _regular_grid(hits: list[DrumHit], beats: np.ndarray, tempo: float):
    """Best constant-tempo grid near the tracked tempo: (beats, tempo, fit) or None."""
    p0 = float(np.median(np.diff(beats)))
    if p0 <= 0:
        return None
    first = min(h.time for h in hits)
    last = max(h.time for h in hits)
    best = None
    for p in p0 * np.linspace(0.97, 1.03, 25):
        for phi in np.linspace(0, p, 48, endpoint=False):
            start = first - ((first - phi) % p)  # last grid point at or before the first stroke
            n = int(np.ceil((last - start) / p)) + 2
            grid = start + p * np.arange(n)
            f = _grid_fit(hits, grid, 60.0 / p)
            if best is None or f > best[2]:
                best = (grid, 60.0 / p, f)
    return best


def _grid_fit(hits: list[DrumHit], beats: np.ndarray, tempo: float) -> float:
    """How plausibly a beat grid explains the strokes (higher is better)."""
    if not hits or len(beats) < 4:
        return 0.0
    times = np.array([h.time for h in hits])
    k = np.clip(np.searchsorted(beats, times, side="right") - 1, 0, len(beats) - 2)
    d = beats[k + 1] - beats[k]
    pos = (times - beats[k]) / d  # position within the beat, 0..1
    w = np.array([_PULSE_WEIGHT.get(h.inst, 0.3) for h in hits])
    sigma = 0.06

    def closeness(grid: np.ndarray) -> np.ndarray:
        dist = np.min(np.abs(pos[:, None] - grid[None, :]), axis=1)
        return np.exp(-(dist / sigma) ** 2)

    binary = closeness(np.array([0, 0.25, 0.5, 0.75, 1.0]))
    ternary = closeness(np.array([0, 1 / 3, 2 / 3, 1.0]))
    fit = float((w * np.maximum(binary, 0.9 * ternary)).sum() / w.sum())
    sn = np.array([h.inst == "snare" and h.strength > 0.5 and not h.ghost for h in hits])
    on_beat = closeness(np.array([0.0, 1.0]))
    backbeat = float(on_beat[sn].mean()) if sn.any() else 0.5
    # Backbeat spacing: in a groove, strong snares come every two beats at the
    # true tempo (every four at double time, every beat at half time).
    spacing = 0.0
    if sn.sum() >= 4:
        beat_pos = k[sn] + pos[sn]
        gaps = np.diff(np.sort(beat_pos))
        gaps = gaps[gaps > 0.3]
        if len(gaps):
            spacing = float(np.mean(np.abs(gaps - 2.0) < 0.2))
    prior = float(np.exp(-0.5 * (np.log2(tempo / 105) / 0.5) ** 2))
    return fit + 0.6 * backbeat + 0.3 * spacing + 0.35 * prior


def _tempo_estimate(env: np.ndarray) -> float:
    """Tempo prior: autocorrelation peak, folded into 70-180 BPM.

    Computed on a 4x max-pooled envelope (23 ms frames, librosa's usual
    resolution): the full-rate tempogram of a song needed over 2 GB.
    """
    import librosa
    f = 4
    n = len(env) // f * f
    pooled = env[:n].reshape(-1, f).max(axis=1) if n else env
    t = librosa.feature.tempo(onset_envelope=pooled, sr=SR, hop_length=HOP * f, start_bpm=110, aggregate=np.median)
    bpm = float(np.atleast_1d(t)[0])
    while bpm < 70:
        bpm *= 2
    while bpm > 180:
        bpm /= 2
    return bpm


def _extend(beats: np.ndarray, duration: float, first_onset: float, last_onset: float) -> np.ndarray:
    """Extrapolate the beat grid to cover every onset (plus one beat past the end)."""
    ibi = float(np.median(np.diff(beats)))
    b = list(beats)
    while b[0] > first_onset - ibi * 0.1:
        b.insert(0, b[0] - ibi)
    while b[-1] < max(last_onset, 0) + ibi * 0.9:
        b.append(b[-1] + ibi)
    b.append(b[-1] + ibi)
    return np.array(b)


def _beat_features(hits: list[DrumHit], beats: np.ndarray) -> np.ndarray:
    """Per beat: strength of kick, snare, crash, hi-hat/ride and toms near the beat."""
    cols = {"kick": 0, "snare": 1, "crash": 2, "hihat": 3, "hihat_open": 3, "ride": 3, "tom1": 4, "tom2": 4, "floor_tom": 4}
    F = np.zeros((len(beats) - 1, 5))
    for h in hits:
        k = int(np.searchsorted(beats, h.time, side="right")) - 1
        if not 0 <= k < len(beats) - 1:
            continue
        d = beats[k + 1] - beats[k]
        rel = (h.time - beats[k]) / d
        if rel > 0.88:  # slightly early stroke belongs to the next beat
            k, rel = k + 1, rel - 1
            if k >= len(beats) - 1:
                continue
        if abs(rel) < 0.12 and h.inst in cols:
            # Presence, not loudness: the first stroke of a file is attenuated by
            # STFT padding, and dynamics shouldn't decide where beat 1 is.
            F[k, cols[h.inst]] = max(F[k, cols[h.inst]], 0.5 + 0.5 * h.confidence)
    return F


def _repetition(F: np.ndarray, lag: int) -> float:
    if len(F) <= lag + 2:
        return 0.0
    a, b = F[:-lag], F[lag:]
    num = (a * b).sum(axis=1)
    den = np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1) + 1e-9
    mask = (np.linalg.norm(a, axis=1) > 0) & (np.linalg.norm(b, axis=1) > 0)
    return float((num / den)[mask].mean()) if mask.any() else 0.0


_PULSE_WEIGHT = {"kick": 1.0, "snare": 1.0, "crash": 0.8, "floor_tom": 0.5, "tom1": 0.4, "tom2": 0.4,
                 "ride": 0.35, "hihat": 0.25, "hihat_open": 0.35}


def drum_envelope(hits: list[DrumHit], n_frames: int) -> np.ndarray:
    """Onset envelope from detected strokes: kick/snare/crash weighted over cymbal ostinatos.

    Dense hi-hat 16ths dominate a plain spectral-flux envelope and pull tempo
    estimates to the wrong metrical level; the backbeat and kick carry the pulse.
    """
    env = np.zeros(n_frames, dtype=np.float64)
    for h in hits:
        k = int(round(h.time * SR / HOP))
        if 0 <= k < n_frames:
            env[k] += _PULSE_WEIGHT.get(h.inst, 0.3) * (0.5 + 0.5 * min(h.strength, 1.5))
    from scipy.ndimage import gaussian_filter1d
    return gaussian_filter1d(env, sigma=2.0)


def estimate_grid(hits: list[DrumHit], onset_env: np.ndarray, duration: float, bpm_hint: float | None = None,
                  time_signature: str | None = None, downbeat: float | None = None,
                  feel: str | None = None) -> BeatGrid:
    notes: list[str] = []
    env = drum_envelope(hits, len(onset_env)) if hits else onset_env
    tempo, beats, tnotes = track_beats(env, duration, bpm_hint, hits)
    notes += tnotes
    if not hits:
        raise ValueError("no drum strokes detected")
    first, last = min(h.time for h in hits), max(h.time for h in hits)
    beats = _extend(beats, duration, first, last)
    F_all = _beat_features(hits, beats)
    # Score phases only on beats that lie within the music (no extrapolated empty beats).
    lo = int(np.searchsorted(beats, first - 0.05, side="right")) - 1
    hi = int(np.searchsorted(beats, last + 0.05, side="right"))
    lo = max(lo, 0)
    F = F_all[lo:hi]

    # Meter.
    if time_signature:
        num, den = (int(x) for x in time_signature.split("/"))
        compound = den == 8 and num % 3 == 0 and num >= 6
        bpb = num // 3 if compound else num
        ts = time_signature
        meter_conf = 1.0
    else:
        r3 = (_repetition(F, 3) + _repetition(F, 6)) / 2
        r4 = (_repetition(F, 4) + _repetition(F, 8)) / 2
        bpb = 3 if r3 > r4 + 0.08 else 4
        meter_conf = float(min(1.0, abs(r4 - r3) * 4 + 0.3))
        compound = feel == "triplet" and bpb == 4 and tempo < 100
        ts = "12/8" if compound else f"{bpb}/4"
        if meter_conf < 0.5:
            notes.append(f"meter uncertain (pattern repetition 3 beats {r3:.2f} vs 4 beats {r4:.2f}); pass --time-signature")

    # Downbeat phase.
    strong = np.nonzero((F[:, 0] > 0) | (F[:, 2] > 0))[0]  # first kick or crash
    first_strong = int(strong[0]) if len(strong) else None
    if downbeat is not None:
        k0 = int(np.argmin(np.abs(beats - downbeat)))
        phase = k0 % bpb
        db_conf = 1.0
        scores = None
    else:
        scores = []
        for p in range(bpb):
            idx = np.arange(p, len(F), bpb)
            one = F[idx]
            s = one[:, 0].mean() + 2.0 * one[:, 2].mean() - 0.7 * one[:, 1].mean()
            if bpb == 4:
                back = np.concatenate([F[np.arange(p + 1, len(F), 4)], F[np.arange(p + 3, len(F), 4)]])
                s += 0.8 * back[:, 1].mean() if len(back) else 0
                three = F[np.arange(p + 2, len(F), 4)]
                s += 0.3 * (one[:, 0].mean() - (three[:, 0].mean() if len(three) else 0))
            elif bpb == 3:
                rest = np.concatenate([F[np.arange(p + 1, len(F), 3)], F[np.arange(p + 2, len(F), 3)]])
                s += 0.5 * (rest[:, 1].mean() if len(rest) else 0)
            # Fills (toms) usually end just before a downbeat.
            before = F[np.arange(p - 1 if p > 0 else bpb - 1, len(F), bpb)]
            s += 0.3 * (before[:, 4].mean() if len(before) else 0)
            # Recordings usually start on beat 1: favour the phase that puts the first
            # strong kick or crash on a downbeat (a real pickup outweighs this).
            if first_strong is not None and first_strong % bpb == p:
                s += 0.4
            scores.append(s)
        scores = np.array(scores)
        phase = (int(np.argmax(scores)) + lo) % bpb
        srt = np.sort(scores)[::-1]
        db_conf = float(min(1.0, (srt[0] - srt[1]) / (abs(srt[0]) + 1e-9) * 3)) if len(srt) > 1 else 1.0
        if db_conf < 0.35:
            notes.append("downbeat placement uncertain; check bar 1 and pass --downbeat <seconds> if it is wrong")

    # First downbeat at or before the first stroke (a pickup bar covers earlier beats).
    k = phase
    while k - bpb >= 0 and beats[k - bpb] >= first - 0.05:
        k -= bpb
    quarter_bpm = tempo * (1.5 if compound else 1.0)
    return BeatGrid([float(b) for b in beats], round(quarter_bpm, 2), bpb, ts, k, round(meter_conf, 2),
                    round(db_conf, 2), notes)
