import csv, math, collections, sys
rows = list(csv.DictReader(open("bench/phase2/diag.csv")))
f = float
by = collections.OrderedDict()
for r in rows:
    by.setdefault(r["case"], []).append(r)
print("rows", len(rows), "| statuses", dict(collections.Counter(r["status"] for r in rows)))
print("h<h0:", sum(f(r["h"]) < f(r["h0"]) - 1e-9 for r in rows),
      "| h>cost:", sum(r["status"] == "Solved" and f(r["cost"]) > 0 and f(r["h"]) > f(r["cost"]) + 1e-9 for r in rows),
      "| infinite h:", sum(math.isinf(f(r["h"])) for r in rows))
hdr = ("case", "solves", "scored", "h>h0", "frac", "mean(h-h0)", "max", "aggGap_h0", "aggGap_h", "maxGap_h0", "maxGap_h", "cert_h0", "cert_h", "r>h0", "strong>h0")
print(("{:<20}" + "{:>11}" * (len(hdr) - 1)).format(*hdr))
def line(name, rs):
    sc = [r for r in rs if r["status"] == "Solved" and f(r["cost"]) > 0]
    n, m = len(rs), len(sc)
    gt = sum(f(r["h"]) > f(r["h0"]) + 1e-9 for r in rs)
    dif = [f(r["h"]) - f(r["h0"]) for r in rs]
    C = sum(f(r["cost"]) for r in sc); H0 = sum(f(r["h0"]) for r in sc); H = sum(f(r["h"]) for r in sc)
    ag0 = (C - H0) / C if C else float("nan"); ag = (C - H) / C if C else float("nan")
    mg0 = max(((f(r["cost"]) - f(r["h0"])) / f(r["cost"]) for r in sc), default=float("nan"))
    mg = max(((f(r["cost"]) - f(r["h"])) / f(r["cost"]) for r in sc), default=float("nan"))
    c0 = sum(abs(f(r["cost"]) - f(r["h0"])) < 1e-9 for r in sc); c1 = sum(abs(f(r["cost"]) - f(r["h"])) < 1e-9 for r in sc)
    rg = sum(f(r["r"]) > f(r["h0"]) + 1e-9 for r in rs); sg = sum(f(r["strong"]) > f(r["h0"]) + 1e-9 for r in rs)
    print(("{:<20}{:>11}{:>11}{:>11}{:>11.1%}{:>11.3f}{:>11.0f}{:>11.1%}{:>11.1%}{:>11.1%}{:>11.1%}{:>11}{:>11}{:>11}{:>11}").format(name, n, m, gt, gt / n, sum(dif) / n, max(dif), ag0, ag, mg0, mg, c0, c1, rg, sg))
for c, rs in by.items():
    line(c, rs)
line("ALL", rows)
