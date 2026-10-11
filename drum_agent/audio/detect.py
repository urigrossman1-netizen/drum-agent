"""Drum stroke detection: audio -> timed, labelled strokes with confidence.

Method (classical, explainable; no network model is available offline):

1. Harmonic/percussive separation (skipped for isolated drum stems).
2. Semi-adaptive NMF on a mel magnitude spectrogram. Fixed drum templates
   (drum_agent/data/templates.npz) explain drum sounds; a few free components
   absorb whatever else is in the mix. Templates may adapt slightly toward the
   actual kit after the first iterations.
3. A superflux onset function finds candidate strokes (high recall).
4. At each candidate, every drum class is scored by how much its activation
   *rises* there, both relative to its own typical level and as a share of
   the total rise. Several classes can fire at once (kick + crash + snare).
5. Hi-hat open/closed is decided by how long the hi-hat activation rings.
6. Flams (two strokes 12-45 ms apart, the first softer) become one flam.

Every stroke carries a confidence; weak or ambiguous ones are flagged so the
chart marks the bar for human review instead of silently guessing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .features import FMAX as FMAX_ALL, FMIN as FMIN_ALL, HOP, SR, band_centers, band_spectrogram
from .templates import load_templates

FRAME = HOP / SR


@dataclass
class DrumHit:
    time: float
    inst: str
    strength: float  # rise relative to the class's typical stroke (1.0 = typical)
    velocity: int
    confidence: float
    flam: bool = False
    ghost: bool = False
    accent: bool = False
    ride_vs_hat: tuple[float, float] | None = None  # (ride evidence, hi-hat evidence) for cymbal strokes


@dataclass
class DetectOptions:
    drums_only: bool = False
    sensitivity: float = 1.0
    nmf_iter: int = 80
    adapt: float = 0.25  # how far templates may move toward the recording (0 = fixed)
    free_components: int | None = None
    nmf_input: str = "auto"  # "full" | "percussive" | "auto" (full for mixes, as-is for stems)
    hpss_margin: float = 1.0
    seed: int = 0


@dataclass
class Detection:
    hits: list[DrumHit]
    onset_env: np.ndarray  # frame-rate onset strength (for beat tracking)
    candidates: int
    duration: float
    activations: dict[str, np.ndarray] = field(default_factory=dict)
    stats: dict = field(default_factory=dict)


# Each class is judged inside the frequency region where it is distinctive.
REGIONS = {
    "kick": (30, 150),
    "snare": (150, 5000),
    "tom1": (60, 600),
    "tom2": (60, 600),
    "floor_tom": (50, 500),
    "hihat": (4000, 17000),
    "hihat_open": (4000, 17000),
    "ride": (2500, 17000),
    "crash": (2500, 17000),
}
CYMBALS = ("hihat", "hihat_open", "ride", "crash")
TOMS = ("tom1", "tom2", "floor_tom")
FEET = ("kick",)
FLAM_DRUMS = ("snare", "tom1", "tom2", "floor_tom")
FAMILIES = (("hihat", "hihat_open", "ride", "crash"), ("snare", "tom1", "tom2", "floor_tom"), ("kick", "floor_tom"))  # instruments not played with the hands (hi-hat pedal has no detector class)
# (minimum share of the regional rise, minimum loudness vs the region's typical rise)
_THRESH = {
    "kick": (0.35, 0.10),
    "snare": (0.50, 0.10),
    "tom1": (0.35, 0.15),
    "tom2": (0.35, 0.15),
    "floor_tom": (0.35, 0.15),
    "hihat": (0.30, 0.06),
    "hihat_open": (0.30, 0.06),
    "ride": (0.30, 0.08),
    "crash": (0.35, 0.10),
}


HARM_MARGIN = 1.0  # HPSS margin for the harmonic part that trains the accompaniment basis
CHUNK_S = 30.0  # front end works in chunks so memory doesn't grow with song length
OVERLAP_S = 1.0


def _front_end(y: np.ndarray, fb: np.ndarray, opts: "DetectOptions") -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Mel magnitude spectrograms of the signal and of its percussive part (HPSS).

    Computed chunk by chunk with overlap and stitched on exact frame indices, so
    a full song needs ~200 MB instead of ~2 GB (HPSS median filters on a whole
    1025-bin spectrogram were the peak).
    """
    import librosa
    n_frames = 1 + len(y) // HOP
    M_full = np.zeros((fb.shape[0], n_frames), dtype=np.float32)
    M_perc = np.zeros((fb.shape[0], n_frames), dtype=np.float32)
    M_harm = np.zeros((fb.shape[0], n_frames), dtype=np.float32)
    core = int(CHUNK_S * SR) // HOP * HOP
    ov = int(OVERLAP_S * SR) // HOP * HOP
    c0 = 0
    while c0 // HOP < n_frames:
        c1 = min(c0 + core, n_frames * HOP)
        s0, s1 = max(0, c0 - ov), min(len(y), c1 + ov)
        S = np.abs(librosa.stft(y[s0:s1], n_fft=2048, hop_length=HOP, center=True)).astype(np.float32)
        if opts.drums_only:
            P, Hm = S, np.zeros_like(S)
        else:
            # Percussive part with the usual margin; harmonic part with a strict margin
            # (only clearly tonal content: sustained cymbal wash falls into the residual).
            mask_h, mask_p = librosa.decompose.hpss(S, kernel_size=(17, 31), margin=(HARM_MARGIN, opts.hpss_margin),
                                                    mask=True)
            Hm, P = S * mask_h, S * mask_p
        g0 = s0 // HOP  # global index of this segment's first frame
        lo, hi = c0 // HOP - g0, min(c1 // HOP, n_frames) - g0
        hi = min(hi, S.shape[1])
        M_full[:, g0 + lo:g0 + hi] = fb @ S[:, lo:hi]
        M_perc[:, g0 + lo:g0 + hi] = fb @ P[:, lo:hi]
        M_harm[:, g0 + lo:g0 + hi] = fb @ Hm[:, lo:hi]
        del S, P, Hm
        c0 = c1
    return M_full, M_perc, M_harm


def _harmonic_basis(M_harm: np.ndarray, k: int, seed: int, iters: int = 40) -> np.ndarray:
    """Free components for the accompaniment, learned from the harmonic part only.

    They are then frozen in the main decomposition: adaptive free components
    learned on the full signal can turn into a copy of a drum that doesn't match
    the templates (a solo snare lost 75% of its share that way).
    """
    from .features import stack_frames
    V = stack_frames(M_harm)
    rng = np.random.default_rng(seed + 1)
    W = rng.random((V.shape[0], k)).astype(np.float32) + 0.1
    H = rng.random((k, V.shape[1])).astype(np.float32) + 0.1
    eps = 1e-9
    ones = np.ones_like(V)
    for _ in range(iters):
        R = V / (W @ H + eps)
        H *= (W.T @ R) / (W.T @ ones + eps)
        R = V / (W @ H + eps)
        W *= (R @ H.T) / (ones @ H.T + eps)
        scale = W.sum(axis=0, keepdims=True) + eps
        W /= scale
        H *= scale.T
    return W


def _nmf(V: np.ndarray, W0: np.ndarray, free: int, iters: int, adapt: float, seed: int,
         W_fixed: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """KL-NMF: semi-adaptive drum columns, plus either `free` adaptive columns or
    `W_fixed` frozen accompaniment columns."""
    rng = np.random.default_rng(seed)
    F, T = V.shape
    K0 = W0.shape[1]
    if W_fixed is not None:
        W = np.concatenate([W0, W_fixed], axis=1)
        free = 0
    else:
        W = np.concatenate([W0, rng.random((F, free)).astype(np.float32) + 0.1], axis=1) if free else W0.copy()
    W = W / (W.sum(axis=0, keepdims=True) + 1e-9)
    H = (rng.random((W.shape[1], T)).astype(np.float32) + 0.1) * (V.mean() + 1e-9)
    eps = 1e-9
    ones = np.ones_like(V)
    for it in range(iters):
        WH = W @ H + eps
        R = V / WH
        H *= (W.T @ R) / (W.T @ ones + eps)
        if free or (adapt > 0 and it >= iters // 2):
            WH = W @ H + eps
            R = V / WH
            upd = (R @ H.T) / (ones @ H.T + eps)
            Wn = W * upd
            if free:
                W[:, K0:] = Wn[:, K0:]
            if adapt > 0 and it >= iters // 2:
                Wd = Wn[:, :K0] / (Wn[:, :K0].sum(axis=0, keepdims=True) + eps)
                W[:, :K0] = (1 - adapt) * W0 + adapt * Wd
            scale = W.sum(axis=0, keepdims=True) + eps
            W /= scale
            H *= scale.T
    return W, H


def _superflux(V: np.ndarray) -> np.ndarray:
    L = np.log1p(100.0 * V / (V.max() + 1e-9))
    from scipy.ndimage import maximum_filter1d
    Lm = maximum_filter1d(L, size=3, axis=0)
    lag = 2
    d = np.zeros(L.shape[1], dtype=np.float32)
    d[lag:] = np.maximum(0.0, L[:, lag:] - Lm[:, :-lag]).sum(axis=0)
    return d


def _peaks(env: np.ndarray, delta: float, wait: int = 4) -> np.ndarray:
    import librosa
    if env.max() <= 0:
        return np.array([], dtype=int)
    e = env / (np.percentile(env, 99) + 1e-9)
    return librosa.util.peak_pick(e, pre_max=2, post_max=2, pre_avg=12, post_avg=6, delta=delta, wait=wait)


def detect(y: np.ndarray, options: DetectOptions | None = None) -> Detection:
    import librosa
    opts = options or DetectOptions()
    y = np.asarray(y, dtype=np.float32)
    if y.size == 0 or np.max(np.abs(y)) < 1e-5:
        return Detection([], np.zeros(1, dtype=np.float32), 0, len(y) / SR)
    y = y / (np.max(np.abs(y)) + 1e-9) * 0.9
    duration = len(y) / SR
    # Lead-in silence: a stroke at t=0 would otherwise be analysed with half-empty
    # STFT windows and no pre-onset baseline (it was being missed or mislabelled).
    PAD = 0.25
    y = np.concatenate([np.zeros(int(PAD * SR), dtype=np.float32), y])

    from .features import STACK, filterbank, stack_frames
    fb = filterbank()
    M_full, V_plain, M_harm = _front_end(y, fb, opts)  # full signal, percussive part, harmonic part
    use_full = opts.nmf_input == "full" or (opts.nmf_input == "auto" and not opts.drums_only)
    V = stack_frames(M_full if use_full else V_plain)

    W0, labels = load_templates()
    classes = list(dict.fromkeys(labels))
    free = opts.free_components if opts.free_components is not None else (2 if opts.drums_only else 10)
    W_fixed = None
    if not opts.drums_only and use_full and free:
        # The accompaniment basis is learned from the strictly harmonic part (see
        # HARM_MARGIN) so it can't absorb drums or cymbal wash.
        W_fixed = _harmonic_basis(M_harm, free, opts.seed)
    W, H = _nmf(V, W0, free, opts.nmf_iter, opts.adapt, opts.seed, W_fixed=W_fixed)
    K0 = W0.shape[1]
    A = {c: H[[i for i, lab in enumerate(labels) if lab == c]].sum(axis=0) for c in classes}
    A_free = H[K0:].sum(axis=0) if W.shape[1] > K0 else np.zeros(V.shape[1], dtype=np.float32)

    flux = _superflux(V_plain)
    delta = 0.06 / max(opts.sensitivity, 0.1)
    cand = _peaks(flux, delta)
    T = V.shape[1]
    centers = np.tile(band_centers(), len(STACK))

    # Regional energy of each class and of the whole reconstruction.
    E_cls: dict[str, np.ndarray] = {}
    E_tot: dict[str, np.ndarray] = {}
    for c in classes:
        lo, hi = REGIONS.get(c, (FMIN_ALL, FMAX_ALL))
        band_mask = (centers >= lo) & (centers <= hi)
        idx = [i for i, lab in enumerate(labels) if lab == c]
        E_cls[c] = W[band_mask][:, idx].sum(axis=0) @ H[idx]
        E_tot[c] = W[band_mask].sum(axis=0) @ H

    def rise(a: np.ndarray, t: int) -> float:
        hi = a[max(0, t - 1):min(T, t + 5)].max()
        lo = a[max(0, t - 6):max(1, t)].min()
        return float(max(0.0, hi - lo))

    r_cls = {c: np.array([rise(E_cls[c], t) for t in cand]) for c in classes}
    r_tot = {c: np.array([rise(E_tot[c], t) for t in cand]) for c in classes}
    region_ref = {c: max(float(np.percentile(r_tot[c], 90)) if len(cand) else 0.0, 1e-9) for c in classes}

    sens = max(opts.sensitivity, 0.1)
    # Per-recording loudness floors: where a class's candidate strokes split into a
    # weak cluster (bleed from other sounds) and a strong one, cut between them.
    # Capped for the snare so ghost notes survive; not used for the hi-hat.
    floors = {}
    for c in classes:
        base = _THRESH[c][1] / sens
        if c == "hihat" or not len(cand):
            floors[c] = base
            continue
        share = r_cls[c] / (r_tot[c] + 1e-9)
        loud = r_cls[c] / region_ref[c]
        floors[c] = _adaptive_floor(loud[share >= _THRESH[c][0]], base)
        if c == "snare":
            # Bleed onto the snare from kick+hat strokes is cut, but never above the
            # level of a soft ghost note.
            floors[c] = min(floors[c], max(base, 0.25 / sens))

    # High-band energy of the full signal: an open hi-hat keeps ringing up there,
    # even when the NMF lets free components absorb its wash in a band mix.
    hf_energy = M_full[band_centers() > 6000].sum(axis=0)

    hits: list[DrumHit] = []
    debug: list[tuple[float, dict]] = []
    for k, t in enumerate(cand):
        time = float(t * FRAME) - PAD
        if time < -0.02:
            continue
        dbg = {c: (round(float(r_cls[c][k] / (r_tot[c][k] + 1e-9)), 2),
                   round(float(r_cls[c][k] / region_ref[c]), 2)) for c in classes}
        debug.append((time, dbg))
        score: dict[str, tuple[float, float, float]] = {}  # class -> (share, loudness, margin)
        evidence: dict[str, float] = {}  # margin for every class, accepted or not
        for c in classes:
            share = r_cls[c][k] / (r_tot[c][k] + 1e-9)
            loud = r_cls[c][k] / region_ref[c]
            thr_share = _THRESH[c][0]
            thr_loud = floors[c]
            evidence[c] = min(share / thr_share, loud / thr_loud)
            if share >= thr_share and loud >= thr_loud:
                score[c] = (share, loud, evidence[c])
        # Cymbals: hi-hat and ride are never struck at the same instant (one hand
        # each would be needed, and their templates overlap on real cymbals), so
        # keep the stronger. A crash may sound with either only on strong evidence.
        cym = sorted(((c, v) for c, v in score.items() if c in CYMBALS), key=lambda x: -x[1][0] * x[1][1])
        if cym:
            keep = {cym[0][0]}
            for c, v in cym[1:]:
                if "crash" in (c, cym[0][0]) and c not in keep and v[0] >= 0.6 and v[1] >= 0.8 \
                        and not ({c} | keep) <= {"hihat", "hihat_open"}:
                    keep.add(c)
            for c, _ in cym:
                if c not in keep:
                    score.pop(c)
        # Snare wires put noise into the cymbal region: a crash that coincides with a
        # snare stroke needs stronger evidence of its own.
        if "crash" in score and "snare" in score and score["crash"][0] < 0.5:
            score.pop("crash")
        # Hi-hat open/closed from how long the hi-hat activation rings.
        hh_c = next((c for c in ("hihat", "hihat_open") if c in score), None)
        if hh_c:
            v = score.pop(hh_c)
            nxt = cand[k + 1] if k + 1 < len(cand) else T
            ring = max(_ring(A["hihat"] + A["hihat_open"], t, nxt, T, baseline=False),
                       _ring(hf_energy, t, nxt, T, baseline=True))
            score["hihat_open" if ring > 0.45 else "hihat"] = v
        # Toms: strongest one; drop toms that look like kick/snare bleed.
        toms = sorted(((c, v) for c, v in score.items() if c in TOMS), key=lambda x: -x[1][1])
        for c, v in toms[1:]:
            if v[1] < 0.7 * toms[0][1][1]:
                score.pop(c)
        for c in [c for c in score if c in TOMS]:
            # A crash + kick downbeat partly matches the floor-tom template; a tom that
            # coincides with a kick must show strong evidence of its own.
            if "kick" in score and (score[c][1] < 0.9 or score[c][0] < 0.5):
                score.pop(c)
                continue
            for other in ("snare", "kick"):
                if other in score and r_cls[c][k] < 0.6 * r_cls[other][k] * (region_ref[c] / region_ref[other]):
                    score.pop(c, None)
        # Two hands: at most two hand-played instruments can sound at one instant.
        hands = sorted((c for c in score if c not in FEET), key=lambda c: -score[c][2])
        for c in hands[2:]:
            score.pop(c)
        for c, (share, loud, margin) in score.items():
            flam = False
            conf = float(1 / (1 + np.exp(-3.0 * (margin - 1.3))))
            # Ambiguity: a same-family rival that wasn't chosen but has similar evidence
            # (hi-hat vs ride, snare vs tom, kick vs floor tom) makes the label uncertain.
            rivals = [evidence[o] for fam in FAMILIES if c in fam for o in fam
                      if o != c and o not in score and o in evidence]
            if rivals:
                amb = min(1.0, max(rivals) / max(margin, 1e-9))
                conf *= 1.0 - 0.7 * amb ** 2
            vel = int(np.clip(35 + 75 * min(loud, 1.5) / 1.5, 1, 127))
            hits.append(DrumHit(time, c, round(float(loud), 3), vel, round(conf, 3), flam=flam,
                                ride_vs_hat=(evidence["ride"], evidence["hihat"] + evidence["hihat_open"])
                                if c in ("hihat", "ride") else None))

    # Flams: a grace bump before the stroke, looking back no further than the
    # previous detected stroke on the same drum (the grace itself is often an
    # onset candidate that wasn't classified, so candidates can't be the limit).
    last_frame: dict[str, int] = {}
    for h in sorted(hits, key=lambda h: h.time):
        if h.inst in FLAM_DRUMS:
            f = int(round((h.time + PAD) / FRAME))
            h.flam = _has_grace(A[h.inst], f, last_frame.get(h.inst, -10**9), T)
            last_frame[h.inst] = f
    hits = _merge_flams(hits)
    _smooth_cymbals(hits)
    _dynamics(hits)
    pad_frames = int(round(PAD / FRAME))
    return Detection(
        hits=sorted(hits, key=lambda h: (h.time, h.inst)),
        onset_env=flux[pad_frames:],
        candidates=int(len(cand)),
        duration=duration,
        activations={c: a[pad_frames:] for c, a in {**A, "_free": A_free}.items()},
        stats={"free_components": free, "templates": K0, "frames": int(T), "debug": debug},
    )


def _has_grace(a: np.ndarray, t: int, prev_t: int, T: int) -> bool:
    """A flam: a small separate bump in the drum's activation 12-70 ms before the stroke."""
    peak = float(a[t:min(T, t + 5)].max())
    lo = max(0, t - 12, prev_t + 3)  # never reach back into the previous detected stroke
    hi = t - 1
    if peak <= 0 or hi - lo < 3:
        return False
    win = a[lo:hi]
    j = int(np.argmax(win))
    bump = float(win[j])
    if bump < 0.12 * peak or bump > 0.6 * peak or j >= len(win) - 1:
        return False
    dip = float(win[j:].min())
    before = float(a[max(0, lo - 3):lo + 1].min())
    return dip < 0.7 * bump and before < 0.5 * bump


def _ring(a: np.ndarray, t: int, nxt: int, T: int, baseline: bool) -> float:
    """How much of a stroke's level remains 70-175 ms later (0 = dead, 1 = sustained)."""
    pre = float(a[max(0, t - 6):max(1, t - 1)].min()) if baseline else 0.0
    peak = float(a[t:min(T, t + 4)].max()) - pre
    if peak <= 1e-9:
        return 0.0
    stop = min(T, t + 30, nxt - 1)
    tail = a[min(T - 1, t + 12):stop] if stop > t + 12 else a[min(T - 1, t + 6):max(t + 7, stop)]
    return float((tail.mean() - pre) / peak) if tail.size else 0.0


def _adaptive_floor(values: np.ndarray, base: float) -> float:
    """Otsu split of log-loudness, used only when clearly bimodal with a weak lower cluster."""
    v = values[values > 0.02]
    if len(v) < 12:
        return base
    lv = np.log(v)
    best = None
    for thr in np.quantile(lv, np.linspace(0.05, 0.95, 37)):
        lo, hi = lv[lv < thr], lv[lv >= thr]
        if len(lo) < 3 or len(hi) < 6:
            continue
        w0, w1 = len(lo) / len(lv), len(hi) / len(lv)
        sb = w0 * w1 * (lo.mean() - hi.mean()) ** 2
        if best is None or sb > best[0]:
            best = (sb, thr, lo.mean(), hi.mean())
    if best is None:
        return base
    sb, thr, m0, m1 = best
    eta = sb / (lv.var() + 1e-9)
    if eta > 0.65 and (m1 - m0) > 1.1 and np.exp(m0) < 0.45:
        return max(base, float(np.exp(thr)))
    return base


def _smooth_cymbals(hits: list[DrumHit], window: float = 2.0) -> None:
    """Keep time-keeping cymbal strokes on one instrument within a phrase.

    Drummers ride one cymbal (hi-hat or ride) for a passage. A stroke whose
    label disagrees with a clear local majority (>= 70% of nearby strokes,
    confidence-weighted) and whose own evidence isn't strong takes the
    majority label, with a little less confidence. A passage-level evidence
    vote was tried and rejected: it measurably mislabelled strokes near
    hi-hat/ride section changes.
    """
    cym = [h for h in hits if h.inst in ("hihat", "ride")]
    times = np.array([h.time for h in cym])
    changes = []
    for i, h in enumerate(cym):
        near = [cym[j] for j in np.nonzero(np.abs(times - h.time) <= window)[0] if j != i]
        if len(near) < 4:
            continue
        w = {"hihat": 0.0, "ride": 0.0}
        for o in near:
            w[o.inst] += o.confidence
        maj = max(w, key=w.get)
        share = w[maj] / (sum(w.values()) + 1e-9)
        if maj != h.inst and share >= 0.7 and h.confidence < 0.85:
            changes.append((h, maj))
    for h, maj in changes:
        h.inst = maj
        h.confidence = round(h.confidence * 0.85, 3)


def _merge_flams(hits: list[DrumHit]) -> list[DrumHit]:
    """Two strokes on the same drum 12-45 ms apart, first softer -> one flam."""
    out: list[DrumHit] = []
    by_inst: dict[str, list[DrumHit]] = {}
    for h in sorted(hits, key=lambda h: h.time):
        by_inst.setdefault(h.inst, []).append(h)
    for inst, hs in by_inst.items():
        skip = set()
        for i in range(len(hs) - 1):
            a, b = hs[i], hs[i + 1]
            if inst in ("snare", "tom1", "tom2", "floor_tom") and 0.012 <= b.time - a.time <= 0.045 \
                    and a.strength < 0.8 * b.strength:
                b.flam = True
                skip.add(i)
        out += [h for i, h in enumerate(hs) if i not in skip]
    return out


def _dynamics(hits: list[DrumHit]) -> None:
    """Mark snare ghost notes and accents relative to the player's normal stroke.

    Ghost notes: well below the median stroke. Accents: at least 1.6x the
    player's ordinary nearby strokes (30th percentile within 3 s).
    """
    sn = [h for h in hits if h.inst == "snare"]
    if len(sn) < 8:
        return
    med = float(np.median([h.strength for h in sn]))
    for h in sn:
        if h.strength < 0.4 * med and not h.flam:
            h.ghost = True
    normal = [h for h in sn if not h.ghost]
    times = np.array([h.time for h in normal])
    vals = np.array([h.strength for h in normal])
    for h in normal:
        near = vals[np.abs(times - h.time) <= 3.0]
        if len(near) < 4:
            continue
        # Relative to the player's ordinary strokes nearby (30th percentile), so a
        # passage played uniformly loud gets no accents.
        if h.strength >= 1.6 * float(np.percentile(near, 30)):
            h.accent = True
