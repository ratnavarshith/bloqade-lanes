import json, statistics, collections
runs=[json.load(open(f"bench/phase2c/run{i}.json")) for i in (1,2,3)]
key=lambda r:(r["case"],r["strategy"])
det=["success","move_events","nodes","cuts_by_h","cuts_by_g","cuts_inf","max_gap"]
extra_det=["h_root_sum","cost_sum","gap_pct","certificates","proven_solves"]
# determinism across runs
bad=[]
for r in runs[1:]:
    for a,b in zip(sorted(runs[0],key=key),sorted(r,key=key)):
        for k in det:
            if a[k]!=b[k]: bad.append((key(a),k,a[k],b[k]))
        for k in extra_det:
            if a["extra"].get(k)!=b["extra"].get(k): bad.append((key(a),k,a["extra"].get(k),b["extra"].get(k)))
print("non-deterministic fields across runs:",bad)
M=collections.defaultdict(dict)
for r in runs[0]: M[r["case"]][r["strategy"]]=dict(r)
W=collections.defaultdict(list)
for run in runs:
    for r in run:
        if r["wall_ms"] is not None: W[key(r)].append(r["wall_ms"])
H,B="rust_cascade_ids","rust_cascade_ids_bus_cut"
def f(x):
    x=x.get("extra",{})
    return float(x["cost_sum"]),float(x["h_root_sum"]),x["certificates"],x["proven_solves"]
print(f'{"case":<20}{"cost h0/bc":>14}{"events h0/bc":>16}{"nodes h0/bc":>16}{"cuts_by_h h0/bc":>20}{"rootgap h0/bc":>18}{"maxgap h0/bc":>16}{"certs h0/bc":>16}{"wall ms h0/bc (median of 3)":>34}')
tot=collections.Counter()
for case in sorted(M):
    a,b=M[case][H],M[case][B]
    if not a["success"] or not b["success"]:
        print(f'{case:<20} h0 success={a["success"]} bc success={b["success"]}  (h0 notes: ...{a["notes"][-70:]})')
        continue
    ca,ha,cea,pa=f(a); cb,hb,ceb,pb=f(b)
    ga=100*(ca-ha)/ca if ca else float("nan"); gb=100*(cb-hb)/cb if cb else float("nan")
    wa=statistics.median(W[(case,H)]); wb=statistics.median(W[(case,B)])
    mg=lambda x:"-" if x["max_gap"] is None else f'{x["max_gap"]*100:.1f}%'
    print(f'{case:<20}{ca:>7.0f}/{cb:<6.0f}{a["move_events"]:>8}/{b["move_events"]:<7}{a["nodes"]:>8}/{b["nodes"]:<7}{a["cuts_by_h"]:>10}/{b["cuts_by_h"]:<9}{ga:>8.1f}%/{gb:<7.1f}%{mg(a):>8}/{mg(b):<7}{cea:>8}/{ceb:<7}{wa:>12.0f}/{wb:<9.0f}')
    for k,v in (("cost",(ca,cb)),("events",(a["move_events"],b["move_events"])),("nodes",(a["nodes"],b["nodes"])),("cuts_h",(a["cuts_by_h"],b["cuts_by_h"])),("wall",(wa,wb))):
        tot[k+"_h0"]+=v[0]; tot[k+"_bc"]+=v[1]
print("TOTAL (successful cases):",dict(tot))
print("wall samples:",{f"{k[0]}|{k[1][-7:]}":[round(x) for x in v] for k,v in W.items() if k[0] in("adder_64","trotter_rand_35")})
