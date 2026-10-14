"""Train the onset classifier (drum_agent/audio/classifier.py).

  python scripts/adt/oneshots.py                       # once: the sample library
  python scripts/adt/train.py build --clips 3000 --jobs 4
  python scripts/adt/train.py train --epochs 25

`build` synthesizes clips (scripts/adt/generate.py), runs the detector's own
front end and feature code on each, and labels every candidate onset with the
classes of the ground-truth strokes nearest to it (within 40 ms). `train` fits
a multi-layer perceptron with plain numpy (Adam, dropout, class-balanced
binary cross-entropy), picks per-class thresholds on held-out clips and writes
drum_agent/data/onset_classifier.npz.

No real recording is used for training: MDB Drums is the evaluation set only
(scripts/eval_real.py).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from drum_agent.audio.classifier import CLASSES, FEATURE_DIM, FRAME, MODEL_PATH, onset_features  # noqa: E402

DATA = Path(os.environ.get("DRUM_AGENT_DATA", Path.home() / ".cache" / "drum-agent")) / "adt" / "shards"
MATCH_S = 0.04


def label_candidates(cand_times: np.ndarray, events: list[tuple[float, str]]) -> np.ndarray:
    Y = np.zeros((len(cand_times), len(CLASSES)), dtype=np.uint8)
    if not len(cand_times):
        return Y
    ci = {c: i for i, c in enumerate(CLASSES)}
    for t, c in events:
        k = int(np.argmin(np.abs(cand_times - t)))
        if abs(cand_times[k] - t) <= MATCH_S:
            Y[k, ci[c]] = 1
    return Y


def build_one(seed: int) -> tuple[np.ndarray, np.ndarray, int, dict] | None:
    import generate as G
    from drum_agent.audio.detect import PAD, DetectOptions, front_end
    clip = G.make_clip(seed)
    fe = front_end(clip.audio, DetectOptions(drums_only=clip.drums_only))
    if fe is None or not len(fe.cand):
        return None
    X = onset_features(fe.M_full, fe.M_perc, fe.flux, fe.cand).astype(np.float16)
    Y = label_candidates(fe.cand * FRAME - PAD, clip.events)
    missed = 0
    ct = fe.cand * FRAME - PAD
    for t, _ in clip.events:
        if np.min(np.abs(ct - t)) > MATCH_S:
            missed += 1
    return X, Y, int(clip.drums_only), {"seed": seed, "events": len(clip.events), "missed": missed,
                                        "style": clip.info.get("style")}


def cmd_build(a) -> None:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    seeds = list(range(a.start_seed, a.start_seed + a.clips))
    per_shard = 100
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=a.jobs) as ex:
        for s0 in range(0, len(seeds), per_shard):
            chunk = seeds[s0:s0 + per_shard]
            path = out / f"shard_{chunk[0]:07d}.npz"
            if path.exists():
                continue
            Xs, Ys, clip_id, dry, meta = [], [], [], [], []
            for res in ex.map(build_one, chunk):
                if res is None:
                    continue
                X, Y, d, m = res
                Xs.append(X)
                Ys.append(Y)
                clip_id.append(np.full(len(X), m["seed"], dtype=np.int32))
                dry.append(np.full(len(X), d, dtype=np.uint8))
                meta.append(m)
            np.savez(path, X=np.concatenate(Xs), Y=np.concatenate(Ys), clip=np.concatenate(clip_id),
                     drums_only=np.concatenate(dry))
            ev = sum(m["events"] for m in meta)
            miss = sum(m["missed"] for m in meta)
            print(f"{path.name}: {sum(len(x) for x in Xs)} candidates from {len(meta)} clips, "
                  f"{miss}/{ev} strokes without a candidate ({time.time() - t0:.0f}s)", flush=True)


def load_shards(d: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    Xs, Ys, Cs, Ds = [], [], [], []
    for p in sorted(d.glob("shard_*.npz")):
        z = np.load(p)
        Xs.append(z["X"])
        Ys.append(z["Y"])
        Cs.append(z["clip"])
        Ds.append(z["drums_only"])
    return np.concatenate(Xs), np.concatenate(Ys), np.concatenate(Cs), np.concatenate(Ds)


class MLP:
    def __init__(self, sizes: list[int], rng: np.random.Generator):
        self.W = [(rng.standard_normal((a, b)) * np.sqrt(2.0 / a)).astype(np.float32) for a, b in zip(sizes, sizes[1:])]
        self.b = [np.zeros(b, dtype=np.float32) for b in sizes[1:]]
        self.m = [np.zeros_like(w) for w in self.W + self.b]
        self.v = [np.zeros_like(w) for w in self.W + self.b]
        self.t = 0

    def forward(self, x, drop: float = 0.0, rng=None):
        acts, masks = [x], []
        h = x
        for i, (W, b) in enumerate(zip(self.W, self.b)):
            h = h @ W + b
            if i < len(self.W) - 1:
                h = np.maximum(h, 0)
                if drop > 0:
                    mk = (rng.random(h.shape) >= drop).astype(np.float32) / (1 - drop)
                    h = h * mk
                    masks.append(mk)
                else:
                    masks.append(None)
            acts.append(h)
        return acts, masks

    def step(self, x, y, pos_w, lr, drop, wd, rng):
        acts, masks = self.forward(x, drop, rng)
        z = acts[-1]
        p = 1 / (1 + np.exp(-np.clip(z, -30, 30)))
        w = np.where(y > 0, pos_w, 1.0).astype(np.float32)
        loss = float(np.mean(-w * (y * np.log(p + 1e-7) + (1 - y) * np.log(1 - p + 1e-7))))
        g = (w * (p - y)) / len(x)
        grads_W, grads_b = [], []
        for i in reversed(range(len(self.W))):
            grads_W.append(acts[i].T @ g + wd * self.W[i])
            grads_b.append(g.sum(axis=0))
            if i > 0:
                g = g @ self.W[i].T
                g = g * (acts[i] > 0)
                if masks[i - 1] is not None:
                    g = g * masks[i - 1]
        grads = list(reversed(grads_W)) + list(reversed(grads_b))
        self.t += 1
        b1, b2 = 0.9, 0.999
        params = self.W + self.b
        for k, (prm, gr) in enumerate(zip(params, grads)):
            self.m[k] = b1 * self.m[k] + (1 - b1) * gr
            self.v[k] = b2 * self.v[k] + (1 - b2) * gr * gr
            mh = self.m[k] / (1 - b1 ** self.t)
            vh = self.v[k] / (1 - b2 ** self.t)
            prm -= (lr * mh / (np.sqrt(vh) + 1e-8)).astype(np.float32)
        return loss

    def predict(self, x, batch=8192):
        out = []
        for i in range(0, len(x), batch):
            z = self.forward(x[i:i + batch])[0][-1]
            out.append(1 / (1 + np.exp(-np.clip(z, -30, 30))))
        return np.concatenate(out)


def best_thresholds(P: np.ndarray, Y: np.ndarray) -> tuple[np.ndarray, list[float]]:
    thr, fs = [], []
    for c in range(Y.shape[1]):
        best = (0.0, 0.5)
        for t in np.linspace(0.05, 0.95, 37):
            pred = P[:, c] >= t
            tp = int(np.sum(pred & (Y[:, c] > 0)))
            fp = int(np.sum(pred & (Y[:, c] == 0)))
            fn = int(np.sum(~pred & (Y[:, c] > 0)))
            f = 2 * tp / (2 * tp + fp + fn) if tp else 0.0
            if f > best[0]:
                best = (f, float(t))
        fs.append(round(best[0], 4))
        thr.append(best[1])
    return np.array(thr, dtype=np.float32), fs


def cmd_train(a) -> None:
    X, Y, clip, dry = load_shards(Path(a.data))
    print(f"{len(X)} candidates, {X.shape[1]} features, {len(np.unique(clip))} clips; positives per class: "
          + ", ".join(f"{c} {int(Y[:, i].sum())}" for i, c in enumerate(CLASSES)), flush=True)
    assert X.shape[1] == FEATURE_DIM, (X.shape, FEATURE_DIM)
    rng = np.random.default_rng(a.seed)
    clips = np.unique(clip)
    val_clips = set(rng.choice(clips, size=max(1, int(len(clips) * a.val)), replace=False).tolist())
    is_val = np.isin(clip, list(val_clips))
    Xf = X.astype(np.float32)
    mu = Xf[~is_val].mean(axis=0)
    sd = Xf[~is_val].std(axis=0) + 1e-3
    Xf = (Xf - mu) / sd
    Xtr, Ytr = Xf[~is_val], Y[~is_val].astype(np.float32)
    Xva, Yva = Xf[is_val], Y[is_val]
    del Xf, X
    pos = Ytr.mean(axis=0)
    pos_w = np.clip(np.sqrt((1 - pos) / (pos + 1e-6)), 1.0, a.max_pos_weight).astype(np.float32)
    sizes = [FEATURE_DIM] + [int(h) for h in a.hidden.split(",")] + [len(CLASSES)]
    net = MLP(sizes, rng)
    n = len(Xtr)
    steps_per_epoch = n // a.batch
    best = (-1.0, None)
    t0 = time.time()
    for ep in range(a.epochs):
        lr = a.lr * (0.5 * (1 + np.cos(np.pi * ep / a.epochs)))  # cosine schedule
        perm = rng.permutation(n)
        losses = []
        for s in range(steps_per_epoch):
            bi = perm[s * a.batch:(s + 1) * a.batch]
            losses.append(net.step(Xtr[bi], Ytr[bi], pos_w, lr, a.dropout, a.wd, rng))
        P = net.predict(Xva)
        thr, fs = best_thresholds(P, Yva)
        main = float(np.mean([fs[CLASSES.index(c)] for c in CLASSES if c != "other"]))
        print(f"epoch {ep + 1:2d} loss {np.mean(losses):.4f} val mean F {main:.4f}  "
              + " ".join(f"{c[:6]} {f:.2f}" for c, f in zip(CLASSES, fs)) + f"  ({time.time() - t0:.0f}s)", flush=True)
        if main > best[0]:
            best = (main, ([w.copy() for w in net.W], [b.copy() for b in net.b], thr.copy(), fs))
    Ws, bs, thr, fs = best[1]
    out = Path(a.out)
    payload = {"classes": np.array(CLASSES), "n_layers": np.array(len(Ws)), "mu": mu.astype(np.float32),
               "sd": sd.astype(np.float32), "thresholds": thr, "version": np.array(a.version)}
    for i, (W, b) in enumerate(zip(Ws, bs)):
        payload[f"W{i}"] = W.astype(np.float16 if a.fp16 else np.float32)
        payload[f"b{i}"] = b.astype(np.float32)
    np.savez_compressed(out, **payload)
    meta = {"version": a.version, "val_F": dict(zip(CLASSES, fs)), "thresholds": dict(zip(CLASSES, thr.tolist())),
            "train_candidates": int(n), "val_candidates": int(len(Xva)), "clips": int(len(clips)),
            "hidden": a.hidden, "epochs": a.epochs, "dropout": a.dropout}
    print(json.dumps(meta, indent=1))
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--clips", type=int, default=3000)
    b.add_argument("--start-seed", type=int, default=1)
    b.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2)))
    b.add_argument("--out", default=str(DATA))
    t = sub.add_parser("train")
    t.add_argument("--data", default=str(DATA))
    t.add_argument("--epochs", type=int, default=25)
    t.add_argument("--batch", type=int, default=512)
    t.add_argument("--lr", type=float, default=1e-3)
    t.add_argument("--hidden", default="384,192")
    t.add_argument("--dropout", type=float, default=0.2)
    t.add_argument("--wd", type=float, default=1e-5)
    t.add_argument("--val", type=float, default=0.06)
    t.add_argument("--max-pos-weight", type=float, default=6.0)
    t.add_argument("--seed", type=int, default=0)
    t.add_argument("--fp16", action="store_true", help="store weights as float16 (half the file size)")
    t.add_argument("--version", default="1")
    t.add_argument("--out", default=str(MODEL_PATH))
    a = ap.parse_args()
    {"build": cmd_build, "train": cmd_train}[a.cmd](a)


if __name__ == "__main__":
    main()
