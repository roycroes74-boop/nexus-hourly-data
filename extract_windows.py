#!/usr/bin/env python3
"""Extract tick-level book windows W1 and W2 from raw data"""
import json, gzip, os
from datetime import datetime, timezone, timedelta

NL = timezone(timedelta(hours=2))

# W1: 15:40-15:55 NL = 13:40-13:55 UTC on 2026-08-11
w1_start = datetime(2026, 8, 11, 13, 40, 0, tzinfo=timezone.utc)
w1_end   = datetime(2026, 8, 11, 13, 55, 0, tzinfo=timezone.utc)
# Add 1 min margin
w1_start_ms = int((w1_start - timedelta(minutes=1)).timestamp() * 1000)
w1_end_ms   = int((w1_end + timedelta(minutes=1)).timestamp() * 1000)

# W2: 09:58-10:08 NL = 07:58-08:08 UTC on 2026-08-11
w2_start = datetime(2026, 8, 11, 7, 58, 0, tzinfo=timezone.utc)
w2_end   = datetime(2026, 8, 11, 8, 8, 0, tzinfo=timezone.utc)
w2_start_ms = int((w2_start - timedelta(minutes=1)).timestamp() * 1000)
w2_end_ms   = int((w2_end + timedelta(minutes=1)).timestamp() * 1000)

out_dir = "/home/ubuntu/nexus-hourly-export/tick-windows/2026-08-11"
os.makedirs(out_dir, exist_ok=True)

raw_file = "/opt/nexus-flow/headless/data/ES_raw_20260811.jsonl"

w1_book = []
w2_book = []

print("Scanning raw book file (430MB)...")
with open(raw_file) as f:
    for i, line in enumerate(f):
        if i % 100000 == 0:
            print(f"  ...{i} lines scanned")
        try:
            d = json.loads(line)
            ts = d.get("ts_ms", 0)
            if w1_start_ms <= ts <= w1_end_ms:
                w1_book.append(line)
            elif w2_start_ms <= ts <= w2_end_ms:
                w2_book.append(line)
        except:
            continue

print(f"\nW1 (15:39-15:56 NL): {len(w1_book)} snapshots")
print(f"W2 (09:57-10:09 NL): {len(w2_book)} snapshots")

# Write gzipped
w1_book_path = f"{out_dir}/W1_1540-1555_book.jsonl.gz"
with gzip.open(w1_book_path, 'wt') as f:
    for line in w1_book:
        f.write(line)
print(f"W1 book: {os.path.getsize(w1_book_path)/1024:.0f} KB")

w2_book_path = f"{out_dir}/W2_0958-1008_book.jsonl.gz"
with gzip.open(w2_book_path, 'wt') as f:
    for line in w2_book:
        f.write(line)
print(f"W2 book: {os.path.getsize(w2_book_path)/1024:.0f} KB")

print("\nDone! Book windows extracted.")
