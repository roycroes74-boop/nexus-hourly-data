#!/usr/bin/env python3
"""Hourly NEXUS export: orderflow events + book snapshots (1/min) → GitHub"""
import json, glob, os, subprocess, sys
from datetime import datetime, timezone, timedelta

NL = timezone(timedelta(hours=2))
now_nl = datetime.now(NL)
# Export the PREVIOUS hour
prev_hour = now_nl - timedelta(hours=1)
date_str = prev_hour.strftime("%Y-%m-%d")
hour_num = prev_hour.hour

out_dir = f"/home/ubuntu/nexus-hourly-export/hourly-data/{date_str}"
os.makedirs(out_dir, exist_ok=True)
out_file = f"{out_dir}/hour_{hour_num:02d}.jsonl"

# Time range (UTC ms)
start_utc = prev_hour.replace(minute=0, second=0, microsecond=0)
end_utc = start_utc + timedelta(hours=1)
start_ms = int(start_utc.timestamp() * 1000)
end_ms = int(end_utc.timestamp() * 1000)

print(f"Exporting {date_str} hour {hour_num:02d} ({start_utc.strftime('%H:%M')}-{end_utc.strftime('%H:%M')} NL)")

# Find event files
event_files = sorted(glob.glob("/opt/nexus-flow/headless/data/ES_events_*.jsonl"))
# Find raw book files
raw_files = sorted(glob.glob("/opt/nexus-flow/headless/data/ES_raw_*.jsonl"))

events_written = 0
book_written = 0
memory_written = False
analytics_written = False

with open(out_file, 'w') as out:
    # 1. Write orderflow events
    for ef in event_files:
        try:
            with open(ef) as f:
                for line in f:
                    try:
                        d = json.loads(line)
                        ts = d.get("ts_ms") or d.get("timestamp_ms") or 0
                        if ts < start_ms or ts >= end_ms:
                            continue
                        evt_type = d.get("type", "")
                        
                        # Orderflow events
                        if evt_type == "orderflow_event":
                            out.write(line)
                            events_written += 1
                        # 1x memory snapshot
                        elif evt_type == "analytics_state" and "liquidity_memory" in str(d) and not memory_written:
                            out.write(line)
                            memory_written = True
                        # 1x analytics state
                        elif evt_type == "analytics_state" and not analytics_written and "market_state" in str(d):
                            out.write(line)
                            analytics_written = True
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            print(f"  Warning: {ef}: {e}")

    # 2. Write book snapshots (1 per minute = 60 per hour)
    last_book_minute = -1
    for rf in raw_files:
        try:
            with open(rf) as f:
                for line in f:
                    try:
                        d = json.loads(line)
                        ts = d.get("ts_ms", 0)
                        if ts < start_ms or ts >= end_ms:
                            continue
                        if d.get("type") != "book":
                            continue
                        # 1 snapshot per minute
                        minute = (ts - start_ms) // 60000
                        if minute != last_book_minute:
                            last_book_minute = minute
                            out.write(line)
                            book_written += 1
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            print(f"  Warning raw: {rf}: {e}")

print(f"  Events: {events_written}, Book snapshots: {book_written}")
print(f"  Output: {out_file} ({os.path.getsize(out_file)/1024:.0f} KB)")

# Git push
os.chdir("/home/ubuntu/nexus-hourly-export")
subprocess.run(["git", "add", "-A"], capture_output=True)
subprocess.run(["git", "commit", "-m", f"data: hourly export {date_str} {now_nl.strftime('%H:%M')} NL (events+book)"], capture_output=True)
result = subprocess.run(["git", "push", "origin", "main"], capture_output=True, text=True)
if result.returncode == 0:
    print("  Pushed to GitHub ✅")
else:
    print(f"  Push failed: {result.stderr[:200]}")
