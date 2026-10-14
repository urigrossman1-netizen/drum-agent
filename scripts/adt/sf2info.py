"""Minimal SoundFont 2 reader: presets and the instrument/sample names behind each key.

Used to build the one-shot library for training the onset classifier (which
note of which preset is which drum). Reads only the 'pdta' hydra; no audio.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path


def _chunks(data: bytes, start: int, end: int):
    i = start
    while i + 8 <= end:
        cid = data[i:i + 4].decode("latin-1")
        size = struct.unpack("<I", data[i + 4:i + 8])[0]
        yield cid, i + 8, size
        i += 8 + size + (size & 1)


def read_pdta(path: str | Path) -> dict[str, bytes]:
    data = Path(path).read_bytes()
    if data[:4] != b"RIFF" or data[8:12] != b"sfbk":
        raise ValueError(f"{path}: not a SoundFont 2 file")
    for cid, off, size in _chunks(data, 12, len(data)):
        if cid == "LIST" and data[off:off + 4] == b"pdta":
            return {c: data[o:o + s] for c, o, s in _chunks(data, off + 4, off + size)}
    raise ValueError(f"{path}: no pdta chunk")


def _name(b: bytes) -> str:
    return b.split(b"\0", 1)[0].decode("latin-1").strip()


def presets(path: str | Path) -> list[dict]:
    """[{name, bank, program, keys: {note: [(instrument, sample, vel_lo, vel_hi), ...]}}]"""
    p = read_pdta(path)
    phdr = [struct.unpack("<20sHHHIII", p["phdr"][i:i + 38]) for i in range(0, len(p["phdr"]), 38)]
    pbag = [struct.unpack("<HH", p["pbag"][i:i + 4]) for i in range(0, len(p["pbag"]), 4)]
    pgen = [struct.unpack("<HH", p["pgen"][i:i + 4]) for i in range(0, len(p["pgen"]), 4)]
    inst = [struct.unpack("<20sH", p["inst"][i:i + 22]) for i in range(0, len(p["inst"]), 22)]
    ibag = [struct.unpack("<HH", p["ibag"][i:i + 4]) for i in range(0, len(p["ibag"]), 4)]
    igen = [struct.unpack("<HH", p["igen"][i:i + 4]) for i in range(0, len(p["igen"]), 4)]
    shdr = [struct.unpack("<20sIIIIIBbHH", p["shdr"][i:i + 46]) for i in range(0, len(p["shdr"]), 46)]

    def gens(bags, gen, b0, b1):
        for b in range(b0, b1):
            g0, g1 = bags[b][0], bags[b + 1][0]
            yield {op: amt for op, amt in gen[g0:g1]}

    def rng(amt):
        return amt & 0xFF, amt >> 8

    out = []
    for pi in range(len(phdr) - 1):  # last record is the terminal "EOP"
        name, prog, bank, bag0 = _name(phdr[pi][0]), phdr[pi][1], phdr[pi][2], phdr[pi][3]
        bag1 = phdr[pi + 1][3]
        keys: dict[int, list] = {}
        for g in gens(pbag, pgen, bag0, bag1):
            if 41 not in g:
                continue  # global zone
            plo, phi = rng(g[43]) if 43 in g else (0, 127)
            ii = g[41]
            iname, ib0, ib1 = _name(inst[ii][0]), inst[ii][1], inst[ii + 1][1]
            for ig in gens(ibag, igen, ib0, ib1):
                if 53 not in ig:
                    continue
                klo, khi = rng(ig[43]) if 43 in ig else (0, 127)
                vlo, vhi = rng(ig[44]) if 44 in ig else (0, 127)
                sname = _name(shdr[ig[53]][0])
                for k in range(max(klo, plo), min(khi, phi) + 1):
                    keys.setdefault(k, []).append((iname, sname, vlo, vhi))
        out.append({"name": name, "bank": bank, "program": prog, "keys": keys})
    return out


if __name__ == "__main__":
    for f in sys.argv[1:]:
        print(f"== {f}")
        for pr in presets(f):
            if pr["bank"] != 128 and "drum" not in pr["name"].lower() and "kit" not in pr["name"].lower() \
                    and "LV2" not in f:
                continue
            notes = sorted(pr["keys"])
            print(f"  bank {pr['bank']} prog {pr['program']:3d} {pr['name']!r}: {len(notes)} keys "
                  f"{notes[0] if notes else '-'}..{notes[-1] if notes else '-'}")
            if "-v" in sys.argv[:2] or "LV2" in f:
                for k in notes:
                    names = sorted({i for i, _, _, _ in pr["keys"][k]})
                    layers = len(pr["keys"][k])
                    print(f"      {k:3d}: {', '.join(names)} ({layers} zones)")
