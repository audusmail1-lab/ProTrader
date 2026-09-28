"""
Build the results page for research_management.py.

    python research_management_report.py mgmt.json breakeven-test.html
"""
from __future__ import annotations

import json
import sys
import time

KEEP_SETS = ("ARIA 7.2c", "Random")


def slim(rep: dict) -> dict:
    out = {"period": rep["period"], "holdout_from": rep["holdout_from"], "markets": rep.get("markets", []),
           "generated": rep.get("generated"), "sets": {}}
    for st in KEEP_SETS:
        b = rep["sets"][st]
        out["sets"][st] = {k: b[k] for k in ("all", "holdout", "real", "synthetic", "vs_hold", "vs_72c", "by_market")}
    return out


def main(src: str, dst: str) -> None:
    rep = json.load(open(src))
    data = json.dumps(slim(rep), separators=(",", ":"))
    html = open(__file__.replace(".py", ".tpl.html")).read()
    html = html.replace("/*__DATA__*/null", data)
    html = html.replace("__BUILT__", time.strftime("%d %b %Y", time.gmtime(rep.get("generated") or time.time())))
    with open(dst, "w") as f:
        f.write(html)
    print(f"wrote {dst} ({len(html)//1024} KB)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
