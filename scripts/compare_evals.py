"""Compare two eval_notation.py JSON results run by run.

Usage: python scripts/compare_evals.py BASELINE.json NEW.json
Prints notation F before -> after for each (chart, condition) and the mean,
and marks regressions larger than 0.005.
"""

import json
import sys


def main() -> None:
    old = {(r["chart"], r["condition"]): r for r in json.load(open(sys.argv[1]))}
    new = {(r["chart"], r["condition"]): r for r in json.load(open(sys.argv[2]))}
    keys = [k for k in new if k in old]
    worse = 0
    for k in keys:
        a, b = old[k].get("notation_F"), new[k].get("notation_F")
        if a is None or b is None:
            print(f"{k[0][:28]:28s} {k[1]:11s} error: {old[k].get('error') or new[k].get('error')}")
            continue
        mark = " <-- worse" if b < a - 0.005 else (" better" if b > a + 0.005 else "")
        worse += b < a - 0.005
        print(f"{k[0][:28]:28s} {k[1]:11s} {a:.3f} -> {b:.3f}{mark}")
    ok = [k for k in keys if old[k].get("notation_F") is not None and new[k].get("notation_F") is not None]
    ma = sum(old[k]["notation_F"] for k in ok) / len(ok)
    mb = sum(new[k]["notation_F"] for k in ok) / len(ok)
    print(f"MEAN over {len(ok)} runs: {ma:.4f} -> {mb:.4f}; runs worse by >0.005: {worse}")


if __name__ == "__main__":
    main()
