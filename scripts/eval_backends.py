"""Other drum transcription models on MDB Drums: alone, and as a second opinion for ours.

Benchmark only: nothing here ships with the app. Each model is downloaded on request
(--download) into ~/.cache/drum-agent/models/<model>/<revision>/, pinned by revision and
SHA-256, and its strokes on each recording are cached under ~/.cache/drum-agent/backends/.
Scoring is eval_real.py's (onset F at 50 ms, MDB's five classes), so the numbers compare
directly with benchmarks/results/*_phase1-dev-*.

  python scripts/eval_backends.py --model oaf --download
  python scripts/eval_backends.py --model oaf --split train              # alone: drums, mix, sep
  python scripts/eval_backends.py --model adt_str --split train --evidence '{"agree": {"CY": 0.5}}'

Models (licences in docs/DEPENDENCY_AND_MODEL_LICENSE_AUDIT.md):
  oaf      Onsets & Frames drums, E-GMD checkpoint, as ONNX (thebluescreen/oaf-drums-onnx;
           Apache-2.0). Needs onnxruntime. This conversion's closed hi-hat and clave outputs
           are always 0, so it has no hi-hat: its kick, snare, tom and crash outputs are used.
  adt_str  ADT_STR, setting tau-0.8 (Pierfrancesco/adt-str; CC BY-SA 4.0 by its README, sample
           rights unclear). Needs torch, transformers, omegaconf, pretty_midi. Its own sample()
           re-runs the whole decoder per token and its additive -1e4 mask lets earlier positions
           see later tokens with these weights; this script decodes greedily with a key/value
           cache instead (strictly causal, much faster), which is not token-identical.

--evidence runs our onset classifier with the model's strokes as classifier.Evidence (JSON:
{"agree": {family: factor}, "alone": {family: factor}, "add": [family, ...]}).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import time
import urllib.request
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_spec = importlib.util.spec_from_file_location("eval_real", ROOT / "scripts" / "eval_real.py")
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)

MODELS_DIR = ev.CACHE.parent / "models"
OUT_DIR = ev.CACHE.parent / "backends"
MODELS = {
    "oaf": {"repo": "thebluescreen/oaf-drums-onnx", "dir": "oaf-drums-onnx",
            "rev": "771fd5529062b9f6f0b58f01cc4b9819db046f4a",
            "files": {"oaf_drums.onnx": "23d4b05ce7e9715bdb4396823d68bc886e8a958fa9f6266c0f7132b78098b521",
                      "LICENSE": None, "NOTICE.md": None}},
    "adt_str": {"repo": "Pierfrancesco/adt-str", "dir": "adt-str", "rev": "a33c5c6b191a4ca1e0f6dc22140947485eb36ce8",
                "files": {"setting-tau-0.8/model.safetensors":
                          "f94d1773d929166e0a3f63d305975aa6667512f8a71d7706872e1f8b23ca930b",
                          **{f: None for f in (
                              "setting-tau-0.8/adt_config.yaml", "setting-tau-0.8/config.json", "adt_transcriber.py",
                              "build_model.py", "config.py", "model.py", "modules/midi_tokenizer.py",
                              "modules/segmenter.py", "modules/utils.py", "modules/clap_encoder.py",
                              "modules/synthetiser.py", "utils/audio_utils.py", "utils/config_utils.py",
                              "utils/mapping_utils.py", "utils/midi_utils.py", "utils/utils.py",
                              "utils/drum_audio_render.py", "README.md", "pyproject.toml")}}},
}
# Each model's outputs, in the onset classifier's class names (classifier.FAMILY gives MDB's).
OAF_CHANNELS = {0: "kick", 1: "snare", 2: "tom", 6: "crash"}  # of 36 38 48 42 51 53 49 75
OAF_THRESHOLD = 0.5
OAF_OFFSET = 0.0115  # its onsets are 11.5 ms early on average (MDB drum stems)
ADT_PITCHES = {35: "kick", 36: "kick", 37: "cross_stick", 38: "snare", 40: "snare", 41: "tom", 45: "tom",
               47: "tom", 42: "hihat", 43: "hihat_pedal", 44: "hihat_open", 46: "crash", 48: "ride",
               49: "crash", 51: "crash"}  # ADT_STR's own drum numbering (utils/mapping_utils.py)
MDB_OF = {"kick": "KD", "snare": "SD", "cross_stick": "SD", "tom": "TT", "hihat": "HH", "hihat_open": "HH",
          "hihat_pedal": "HH", "ride": "CY", "crash": "CY"}


def model_dir(name: str) -> Path:
    return MODELS_DIR / MODELS[name]["dir"] / MODELS[name]["rev"]


def download(name: str) -> None:
    m = MODELS[name]
    for f, sha in m["files"].items():
        dest = model_dir(name) / f
        if dest.exists() and (sha is None or _sha(dest) == sha):
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://huggingface.co/{m['repo']}/resolve/{m['rev']}/{f}"
        req = urllib.request.Request(url, headers={"User-Agent": "drum-agent-benchmark"})
        with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as out:
            while chunk := r.read(1 << 20):
                out.write(chunk)
        if sha is not None and _sha(dest) != sha:
            dest.unlink()
            raise SystemExit(f"{f}: SHA-256 mismatch; deleted")
        print(f"  {name}: {f}")


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def audio(track: str, inp: str) -> np.ndarray:
    import soundfile as sf
    if inp == "sep":
        stem = ev.CACHE / "separated" / f"{track}_{ev._separator()}.npy"
        if not stem.is_file():
            raise SystemExit(f"{stem.name} missing: run scripts/eval_real.py --separate once first")
        return np.load(stem)
    y, sr = sf.read(ev._paths(track)["drums" if inp == "drums" else "mix"], dtype="float32", always_2d=True)
    if sr != 44100:
        raise SystemExit(f"{track}: expected 44.1 kHz")
    return y.mean(axis=1)


# ---- Onsets & Frames (ONNX) ------------------------------------------------------------

def oaf_strokes(y: np.ndarray, session) -> list[tuple[float, str]]:
    probs = session.run(["onset_probs"], {"waveform": np.clip(y, -1, 1).astype(np.float32)[None, :]})[0][0]
    out = []
    for k, cls in OAF_CHANNELS.items():
        p = probs[:, k]
        on = p >= OAF_THRESHOLD
        i = 0
        while i < len(p):
            if on[i]:
                j = i
                while j + 1 < len(p) and on[j + 1]:
                    j += 1
                out.append(((i + int(np.argmax(p[i:j + 1]))) / 100.0 + OAF_OFFSET, cls))
                i = j + 1
            else:
                i += 1
    return sorted(out)


def oaf_session():
    import onnxruntime as ort
    so = ort.SessionOptions()
    so.intra_op_num_threads = 4
    return ort.InferenceSession(str(model_dir("oaf") / "oaf_drums.onnx"), so, providers=["CPUExecutionProvider"])


# ---- ADT_STR --------------------------------------------------------------------------

def adt_transcriber():
    import torch
    sys.path.insert(0, str(model_dir("adt_str")))
    from adt_transcriber import ADTTranscriber
    torch.set_num_threads(4)
    return ADTTranscriber.from_pretrained(str(model_dir("adt_str")), variant="setting-tau-0.8", device="cpu")


def adt_cached_sample(model, src, max_length: int, bos: int, eos: int):
    """Greedy decoding with a key/value cache, mirroring nn.TransformerDecoderLayer (post-norm,
    GELU, batch_first) in eval mode, with a strictly causal decoder."""
    import torch
    import torch.nn.functional as F
    dec = model.decoder
    layers = dec.decoder.layers
    d, H = dec.num_features, layers[0].self_attn.num_heads
    hd = d // H
    with torch.no_grad():
        memory = model.encoder(model.project_to_mel(model.compute_spectrogram(src)))
        B = src.shape[0]

        def heads(x):
            return x.view(B, -1, H, hd).transpose(1, 2)

        mem_kv = []
        for L in layers:
            W, b = L.multihead_attn.in_proj_weight, L.multihead_attn.in_proj_bias
            mem_kv.append((heads(F.linear(memory, W[d:2 * d], b[d:2 * d])), heads(F.linear(memory, W[2 * d:], b[2 * d:]))))
        ks, vs = [None] * len(layers), [None] * len(layers)
        tokens = torch.full((B, 1), bos, dtype=torch.long)
        finished = torch.zeros(B, dtype=torch.bool)
        for _ in range(max_length - 1):
            pos = tokens.shape[1] - 1
            x = dec.tgt_tok_emb(tokens[:, -1:]) + dec.positional_encoding.pos_embedding[:, pos:pos + 1, :]
            for li, L in enumerate(layers):
                W, b = L.self_attn.in_proj_weight, L.self_attn.in_proj_bias
                q, k, v = (heads(F.linear(x, W[i * d:(i + 1) * d], b[i * d:(i + 1) * d])) for i in range(3))
                ks[li] = k if ks[li] is None else torch.cat([ks[li], k], dim=2)
                vs[li] = v if vs[li] is None else torch.cat([vs[li], v], dim=2)
                a = F.scaled_dot_product_attention(q, ks[li], vs[li]).transpose(1, 2).reshape(B, 1, d)
                x = L.norm1(x + L.self_attn.out_proj(a))
                W2, b2 = L.multihead_attn.in_proj_weight, L.multihead_attn.in_proj_bias
                a2 = F.scaled_dot_product_attention(heads(F.linear(x, W2[:d], b2[:d])), *mem_kv[li])
                x = L.norm2(x + L.multihead_attn.out_proj(a2.transpose(1, 2).reshape(B, 1, d)))
                x = L.norm3(x + L.linear2(F.gelu(L.linear1(x))))
            nxt = torch.argmax(dec.generator(x)[:, -1, :], dim=-1)
            nxt = torch.where(finished, torch.full_like(nxt, eos), nxt)
            tokens = torch.cat([tokens, nxt[:, None]], dim=1)
            finished |= nxt == eos
            if bool(finished.all()):
                break
    return tokens


def adt_strokes(y: np.ndarray, tr, batch_size: int = 8) -> list[tuple[float, str]]:
    import torch
    from adt_transcriber import _chunk_audio
    wav = tr._prepare_waveform(torch.from_numpy(np.ascontiguousarray(y, dtype=np.float32))[None, :], 44100)
    chunks = _chunk_audio(wav, tr.chunk_samples)
    max_length = tr.cfg.get("inference", {}).get("max_length", 1024)
    notes = []
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        toks = adt_cached_sample(tr.model, torch.cat([c[1] for c in batch], dim=0), max_length,
                                 tr.tokenizer.BOS_token, tr.tokenizer.EOS_token)
        for (start, _), tk in zip(batch, toks):
            n = tr.tokenizer.decode(tk.cpu().numpy())
            if n.numel() > 0:
                n[:, 0:2] += start / tr.sample_rate
                notes.append(n)
    if not notes:
        return []
    rows = np.unique(torch.cat(notes, dim=0).cpu().numpy(), axis=0)
    return sorted((float(r[0]), ADT_PITCHES[int(r[2])]) for r in rows if int(r[2]) in ADT_PITCHES)


# ---- running and scoring --------------------------------------------------------------

def strokes_for(name: str, tracks: list[str], inputs: list[str]) -> dict:
    """The model's strokes per (track, input), from the cache or computed now."""
    out, todo = {}, []
    for t in tracks:
        for i in inputs:
            f = OUT_DIR / name / MODELS[name]["rev"][:12] / f"{t}_{i}.json"
            if f.exists():
                out[(t, i)] = [tuple(s) for s in json.loads(f.read_text())]
            else:
                todo.append((t, i, f))
    if todo:
        runner = oaf_session() if name == "oaf" else adt_transcriber()
        t0, secs = time.time(), 0.0
        for t, i, f in todo:
            y = audio(t, i)
            s = oaf_strokes(y, runner) if name == "oaf" else adt_strokes(y, runner)
            secs += len(y) / 44100
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(s))
            out[(t, i)] = s
            print(f"  {name} {t}/{i}: {len(s)} strokes ({secs / (time.time() - t0):.1f}x real time so far)", flush=True)
    return out


def _with_evidence(job):
    track, inp, strokes, cfg = job
    from drum_agent.audio.classifier import Evidence
    from drum_agent.audio.detect import DetectOptions, detect
    evd = Evidence(strokes, source=cfg.get("source", "other model"), agree=cfg.get("agree", {}),
                   alone=cfg.get("alone", {}), add=frozenset(cfg.get("add", [])))
    det = detect(audio(track, inp), DetectOptions(drums_only=inp != "mix", method="classifier"), evidence=evd)
    est = [(h.time, ev.OURS_TO_MDB.get(h.inst, "OT")) for h in det.hits]
    return track, inp, ev.score_track(ev.read_annotations(ev._paths(track)["class"]), est)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True, choices=sorted(MODELS))
    ap.add_argument("--download", action="store_true", help="fetch the pinned model files and exit")
    ap.add_argument("--split", default="train", choices=["train", "test"])
    ap.add_argument("--inputs", default="drums,sep", help="comma list of drums, mix, sep")
    ap.add_argument("--evidence", help="JSON: score our classifier with this model's strokes as evidence")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--label", help="name of this run in benchmarks/results (default: no record)")
    a = ap.parse_args()
    if a.download:
        download(a.model)
        return
    missing = [f for f, sha in MODELS[a.model]["files"].items() if sha and not (model_dir(a.model) / f).exists()]
    if missing:
        raise SystemExit(f"{a.model} is not downloaded: run with --download first")
    tracks = ev.TRAIN if a.split == "train" else ev.TEST
    inputs = a.inputs.split(",")
    t0 = time.time()
    strokes = strokes_for(a.model, tracks, inputs)
    if a.evidence:
        cfg = json.loads(a.evidence)
        cfg.setdefault("source", a.model)
        rows = {}
        with ProcessPoolExecutor(a.jobs) as pool:
            for track, inp, res in pool.map(_with_evidence, [(t, i, strokes[(t, i)], cfg) for t in tracks for i in inputs]):
                rows[(track, inp)] = res
        title = f"MDB Drums, {a.split}: our classifier with {a.model} as evidence {json.dumps(cfg)}"
    else:
        rows = {(t, i): ev.score_track(ev.read_annotations(ev._paths(t)["class"]),
                                       [(tm, MDB_OF[c]) for tm, c in strokes[(t, i)]])
                for t in tracks for i in inputs}
        title = f"MDB Drums, {a.split}: {a.model} alone"
    report = ev.render(ev.summarize(rows), title)
    print("\n" + report)
    if a.label:
        meta = ev._meta(argparse.Namespace(separate="sep" in inputs, no_band_check=True), tracks, time.time() - t0)
        meta.pop("band_mix_check", None)
        meta.update({"model": a.model, "model_revision": MODELS[a.model]["rev"], "evidence": a.evidence})
        result = {"summary": ev.summarize(rows), "split": a.split,
                  "tracks": {f"{t}/{i}": r for (t, i), r in rows.items()}, "meta": meta}
        ev.RESULTS.mkdir(parents=True, exist_ok=True)
        stem = ev.RESULTS / f"{time.strftime('%Y-%m-%d')}_{ev._slug(a.label)}"
        stem.with_suffix(".json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
        stem.with_suffix(".md").write_text(f"# {a.label}\n\n```\n{report}\n```\n\n{ev._meta_md(meta)}\n",
                                           encoding="utf-8")
        print(f"wrote {stem}.json/.md")


if __name__ == "__main__":
    main()
