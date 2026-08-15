#!/usr/bin/env python3
"""FROZEN TEST FIXTURE v1.0 - reproduceerbaarheidspoort (Nicolas punt 2).
Vast venster: 2026-08-13 10:00-12:00 NL. Eerste run bevriest de waarden,
elke latere run verifieert. Afwijking = STOP, omgeving is veranderd."""
import sys, os, json, gzip, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evening_lite as ev

DAY = "2026-08-13"
F = f"full-tick-data/{DAY}/10h00_12h00_NL_FULL_MBO32.jsonl.gz"
EXP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixture_expected.json")

def compute():
    h = hashlib.sha256(open(F, "rb").read()).hexdigest()
    counts = {}; S = []
    vol = 0; st_trans = 0; last_st = None
    first_ts = None; last_ts = None
    with gzip.open(F, "rt") as fh:
        for line in fh:
            r = json.loads(line)
            t = r["_record_type"]; counts[t] = counts.get(t, 0) + 1
            ts = r["ts_ms"]
            if first_ts is None: first_ts = ts
            last_ts = ts
            if t == "trade":
                vol += r["volume"]
            elif t == "nexus_state":
                p = r["payload"]
                S.append((ts, p.get("mid"), p.get("market_state_id"), p.get("dq"), p.get("bid"), p.get("ask")))
                sid = p.get("market_state_id")
                if last_st is not None and sid != last_st: st_trans += 1
                last_st = sid
    tps = ev.zigzag(S)
    return {"fixture_version": "1.0", "engine": ev.CONFIG["ENGINE"],
            "engine_version": ev.CONFIG["VERSION"], "config_hash": ev.CFG_HASH,
            "source_file": F, "source_sha256": h, "counts": counts,
            "first_ts_ms": first_ts, "last_ts_ms": last_ts,
            "trade_volume_sum": vol, "state_transitions": st_trans,
            "turning_points": len(tps),
            "tp_list": [[int(t), float(p), k] for t, p, k in tps]}

cur = compute()
if not os.path.exists(EXP):
    json.dump(cur, open(EXP, "w"), indent=1)
    print("FIXTURE BEVROREN:", json.dumps({k: cur[k] for k in ("counts", "turning_points", "state_transitions", "trade_volume_sum", "config_hash")}))
else:
    exp = json.load(open(EXP))
    diffs = [k for k in exp if exp[k] != cur.get(k)]
    if diffs:
        print("FIXTURE = FAIL - afwijkend:", diffs); sys.exit(1)
    print("FIXTURE = PASS |", exp["counts"], "| TPs:", exp["turning_points"], "| config:", exp["config_hash"])
