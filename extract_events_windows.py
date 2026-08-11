#!/usr/bin/env python3
"""Extract events for W1 and W2 windows"""
import json, gzip, os, glob
from datetime import datetime, timezone, timedelta

NL = timezone(timedelta(hours=2))

# Same time ranges as book extraction (with 1 min margin)
w1_start_ms = int(datetime(2026, 8, 11, 13, 39, 0, tzinfo=timezone.utc).timestamp() * 1000)
w1_end_ms   = int(datetime(2026, 8, 11, 13, 56, 0, tzinfo=timezone.utc).timestamp() * 1000)
w2_start_ms = int(datetime(2026, 8, 11, 7, 57, 0, tzinfo=timezone.utc).timestamp() * 1000)
w2_end_ms   = int(datetime(2026, 8, 11, 8, 9, 0, tzinfo=timezone.utc).timestamp() * 1000)

out_dir = "/home/ubuntu/nexus-hourly-export/tick-windows/2026-08-11"

event_files = sorted(glob.glob("/opt/nexus-flow/headless/data/ES_events_20260811*.jsonl"))

w1_events = []
w2_events = []

print("Scanning event files...")
for ef in event_files:
    print(f"  {ef}")
    with open(ef) as f:
        for line in f:
            try:
                d = json.loads(line)
                ts = d.get("ts_ms") or d.get("timestamp_ms") or 0
                if w1_start_ms <= ts <= w1_end_ms:
                    w1_events.append(line)
                elif w2_start_ms <= ts <= w2_end_ms:
                    w2_events.append(line)
            except:
                continue

print(f"\nW1 events: {len(w1_events)}")
print(f"W2 events: {len(w2_events)}")

w1_path = f"{out_dir}/W1_1540-1555_events.jsonl.gz"
with gzip.open(w1_path, 'wt') as f:
    for line in w1_events:
        f.write(line)
print(f"W1 events: {os.path.getsize(w1_path)/1024:.0f} KB")

w2_path = f"{out_dir}/W2_0958-1008_events.jsonl.gz"
with gzip.open(w2_path, 'wt') as f:
    for line in w2_events:
        f.write(line)
print(f"W2 events: {os.path.getsize(w2_path)/1024:.0f} KB")

print("\nDone!")
