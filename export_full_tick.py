#!/usr/bin/env python3
"""
Export FULL tick-level MBO-32 data for a time window.
ALL trades + ALL book snapshots + ALL NEXUS events, chronologically sorted.
Output: gzipped JSONL file pushed to GitHub.

Usage:
  python3 export_full_tick.py                    # Default: previous 2h block
  python3 export_full_tick.py 20 22             # Specific NL hours: 20:00-22:00
  python3 export_full_tick.py 20 22 2026-08-11  # Specific date + hours
"""
import json, glob, gzip, os, subprocess, sys
from datetime import datetime, timezone, timedelta
from collections import Counter

NL = timezone(timedelta(hours=2))
now_nl = datetime.now(NL)

# Parse arguments
if len(sys.argv) >= 3:
    hour_start = int(sys.argv[1])
    hour_end = int(sys.argv[2])
    date_str = sys.argv[3] if len(sys.argv) >= 4 else now_nl.strftime("%Y-%m-%d")
else:
    # Default: previous 2-hour block
    prev = now_nl - timedelta(hours=2)
    hour_start = prev.hour
    hour_end = hour_start + 2
    date_str = prev.strftime("%Y-%m-%d")

# Calculate UTC timestamps
from datetime import date as date_type
target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
start_nl = datetime(target_date.year, target_date.month, target_date.day, 
                    hour_start, 0, 0, tzinfo=NL)
end_nl = datetime(target_date.year, target_date.month, target_date.day,
                  hour_end, 0, 0, tzinfo=NL)
start_ms = int(start_nl.timestamp() * 1000)
end_ms = int(end_nl.timestamp() * 1000)

out_dir = f"/home/ubuntu/nexus-hourly-export/full-tick-data/{date_str}"
os.makedirs(out_dir, exist_ok=True)
out_file = f"{out_dir}/{hour_start:02d}h00_{hour_end:02d}h00_NL_FULL_MBO32.jsonl.gz"

print(f"=== FULL TICK EXPORT ===")
print(f"Window: {date_str} {hour_start:02d}:00-{hour_end:02d}:00 NL")
print(f"UTC range: {start_nl.astimezone(timezone.utc).strftime('%H:%M')}-{end_nl.astimezone(timezone.utc).strftime('%H:%M')} UTC")
print(f"Output: {out_file}")
print()

all_records = []

# 1. Extract ALL raw data (book snapshots + trades)
print("Extracting raw book snapshots + trades...")
raw_files = sorted(glob.glob("/opt/nexus-flow/headless/data/ES_raw_*.jsonl"))
for rf in raw_files:
    try:
        with open(rf) as f:
            for line in f:
                try:
                    d = json.loads(line)
                    ts = d.get('ts_ms', 0)
                    if ts < start_ms:
                        continue
                    if ts >= end_ms:
                        break
                    if 'bids' in d:
                        d['_record_type'] = 'book_snapshot'
                    elif d.get('type') == 'trade':
                        d['_record_type'] = 'trade'
                    else:
                        d['_record_type'] = 'raw_other'
                    all_records.append((ts, d))
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"  Warning: {rf}: {e}")

raw_count = len(all_records)
print(f"  Raw records: {raw_count}")

# 2. Extract ALL NEXUS events + state updates + memory snapshots
print("Extracting NEXUS events + state + memory...")
event_files = sorted(glob.glob("/opt/nexus-flow/headless/data/ES_events_*.jsonl"))
for ef in event_files:
    try:
        with open(ef) as f:
            for line in f:
                try:
                    d = json.loads(line)
                    ts = d.get('ts_ms', 0)
                    if ts < start_ms:
                        continue
                    if ts >= end_ms:
                        break
                    etype = d.get('type', 'unknown')
                    if etype == 'orderflow_event':
                        d['_record_type'] = 'nexus_orderflow_event'
                    elif etype == 'analytics_state':
                        d['_record_type'] = 'nexus_state'
                    elif etype == 'liquidity_memory_snapshot':
                        d['_record_type'] = 'nexus_memory_snapshot'
                    else:
                        d['_record_type'] = f'nexus_{etype}'
                    all_records.append((ts, d))
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"  Warning: {ef}: {e}")

nexus_count = len(all_records) - raw_count
print(f"  NEXUS records: {nexus_count}")
print(f"  Total records: {len(all_records)}")

if len(all_records) == 0:
    print("WARNING: No data found in this window!")
    sys.exit(1)

# 3. Sort chronologically
print("Sorting chronologically...")
all_records.sort(key=lambda x: x[0])

# 4. Write gzipped JSONL
print(f"Writing gzipped output...")
with gzip.open(out_file, 'wt', encoding='utf-8') as f:
    for ts, record in all_records:
        f.write(json.dumps(record) + '\n')

size_mb = os.path.getsize(out_file) / 1024 / 1024
print(f"\n=== DONE ===")
print(f"Output: {out_file}")
print(f"Size: {size_mb:.2f} MB (gzipped)")
print(f"Records: {len(all_records)}")

# Breakdown
types = Counter(r[1]['_record_type'] for r in all_records)
print(f"\nBreakdown:")
for t, c in types.most_common():
    print(f"  {t}: {c}")

# Time range
first_ts = all_records[0][0]
last_ts = all_records[-1][0]
first_dt = datetime.fromtimestamp(first_ts/1000, tz=NL)
last_dt = datetime.fromtimestamp(last_ts/1000, tz=NL)
print(f"\nActual time range: {first_dt.strftime('%H:%M:%S')}-{last_dt.strftime('%H:%M:%S')} NL")

# 5. Git push
print("\nPushing to GitHub...")
os.chdir("/home/ubuntu/nexus-hourly-export")
subprocess.run(["git", "add", "-A"], capture_output=True)
commit_msg = f"data: full tick MBO-32 {date_str} {hour_start:02d}:00-{hour_end:02d}:00 NL ({len(all_records)} records, {size_mb:.1f}MB gz)"
subprocess.run(["git", "commit", "-m", commit_msg], capture_output=True)
result = subprocess.run(["git", "push", "origin", "main"], capture_output=True, text=True)
if result.returncode == 0:
    print("  Pushed to GitHub ✅")
else:
    print(f"  Push failed: {result.stderr[:200]}")
