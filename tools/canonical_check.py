#!/usr/bin/env python3
"""Canonieke reproduceerbaarheidspoort: draait BEIDE fixtures.
Gebruik: python3 tools/canonical_check.py   (vanuit repo-root)
Exit 0 = omgeving reproduceerbaar; exit 1 = STOP, omgeving wijkt af."""
import sys, os, json, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
os.chdir(ROOT)
sys.path.insert(0, HERE)

# Poort 1: bevroren kern
r = subprocess.run([sys.executable, os.path.join(HERE, "fixture_check.py")],
                   capture_output=True, text=True)
print(r.stdout.strip())
if r.returncode != 0:
    print("POORT 1 (kern) = FAIL"); sys.exit(1)

# Poort 2: canonieke uitbreiding
import canonical_pipeline as cp
rep = cp.day_report("2026-08-13", upto_h=12, behaviour_t1_h=12)
exp = json.load(open(os.path.join(HERE, "fixture_expected_canonical.json")))
cur = dict(engine=rep["engine"], version=rep["version"], config_hash=rep["config_hash"],
           core=rep["core"], day=rep["day"],
           turning_points=rep["behaviour"]["turning_points"],
           episodes=rep["behaviour"]["episodes"],
           episodes_closed=rep["behaviour"]["episodes_closed"],
           hold=rep["behaviour"]["hold"],
           brick_locations=rep["behaviour"]["brick_locations"],
           chain_fires=rep["chain"]["fires"],
           recall_primary=rep["chain"]["primary"]["recall"],
           recall_strict=rep["chain"]["strict"]["recall"],
           precision_primary=rep["chain"]["primary"]["precision"])
diffs = [k for k in exp if exp[k] != cur.get(k)]
if diffs:
    print("POORT 2 (canoniek) = FAIL - afwijkend:", diffs); sys.exit(1)
print("POORT 2 (canoniek) = PASS")
print("RESEARCH ENVIRONMENT = REPRODUCIBLE")
