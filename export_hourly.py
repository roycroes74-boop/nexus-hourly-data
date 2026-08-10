#!/usr/bin/env python3
"""
NEXUS Hourly Event Export
=========================
Exporteert elk uur alle NEXUS events naar een compact JSONL bestand.
Bevat ALLE MBO-32 features: absorption, stack, pull, iceberg, sweep,
market state, liquidity memory, DQ, calibrated scores, delta, vacuum.

Gebruik:
  python3 export_hourly.py

Draait via cron elk uur. Exporteert het VORIGE uur.
Pusht automatisch naar GitHub (roycroes74-boop/tradingalgo).

Output: hourly-data/YYYY-MM-DD/hour_HH.jsonl
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Configuratie
NEXUS_DATA_DIR = Path("/opt/nexus-flow/headless/data")
EXPORT_DIR = Path("/home/ubuntu/nexus-hourly-export/hourly-data")
REPO_DIR = Path("/home/ubuntu/nexus-hourly-export")

# Tijdzone: Nederland (UTC+2 in zomer)
NL_OFFSET = timedelta(hours=2)


def get_current_hour_nl():
    """Geeft het VORIGE uur in NL tijd (want we exporteren wat net is afgelopen)."""
    now_utc = datetime.now(timezone.utc)
    now_nl = now_utc + NL_OFFSET
    # Vorige uur
    prev_hour = now_nl - timedelta(hours=1)
    return prev_hour


def find_event_files(date_str: str) -> list[Path]:
    """Vind alle NEXUS event files voor een datum (YYYYMMDD)."""
    files = []
    for f in sorted(NEXUS_DATA_DIR.glob(f"ES_events_{date_str}*.jsonl")):
        files.append(f)
    return files


def export_hour(target_hour: datetime) -> Path | None:
    """Exporteer alle events van een specifiek uur."""
    date_str = target_hour.strftime("%Y%m%d")
    hour_start_utc = (target_hour - NL_OFFSET).replace(minute=0, second=0, microsecond=0)
    hour_end_utc = hour_start_utc + timedelta(hours=1)
    
    start_ms = int(hour_start_utc.timestamp() * 1000)
    end_ms = int(hour_end_utc.timestamp() * 1000)
    
    # Maak output directory
    day_dir = EXPORT_DIR / target_hour.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    
    output_file = day_dir / f"hour_{target_hour.strftime('%H')}.jsonl"
    
    # Zoek in alle event files van vandaag EN gisteren (voor nacht-uren)
    dates_to_check = [date_str]
    # Als het uur rond middernacht NL is, check ook de UTC-datum
    utc_date_str = hour_start_utc.strftime("%Y%m%d")
    if utc_date_str != date_str:
        dates_to_check.append(utc_date_str)
    
    event_count = 0
    with open(output_file, 'w') as out:
        for d in dates_to_check:
            for event_file in find_event_files(d):
                try:
                    with open(event_file, 'r') as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                ev = json.loads(line)
                                ts = ev.get('ts_ms', 0)
                                if start_ms <= ts < end_ms:
                                    out.write(line + '\n')
                                    event_count += 1
                                elif ts >= end_ms:
                                    # Events zijn chronologisch, stop hier
                                    break
                            except json.JSONDecodeError:
                                continue
                except FileNotFoundError:
                    continue
    
    if event_count == 0:
        # Geen events = verwijder leeg bestand
        output_file.unlink(missing_ok=True)
        print(f"[Export] Geen events voor {target_hour.strftime('%Y-%m-%d %H:00')} NL")
        return None
    
    print(f"[Export] {event_count} events → {output_file.name} ({target_hour.strftime('%Y-%m-%d %H:00')} NL)")
    return output_file


def git_push():
    """Commit en push naar GitHub."""
    os.chdir(REPO_DIR)
    
    # Add alle nieuwe/gewijzigde bestanden
    subprocess.run(["git", "add", "-A"], check=True, capture_output=True)
    
    # Check of er iets te committen is
    result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
    if not result.stdout.strip():
        print("[Git] Niets te committen")
        return
    
    # Commit
    now_nl = datetime.now(timezone.utc) + NL_OFFSET
    msg = f"data: hourly export {now_nl.strftime('%Y-%m-%d %H:%M')} NL"
    subprocess.run(["git", "commit", "-m", msg], check=True, capture_output=True)
    
    # Push
    result = subprocess.run(
        ["git", "push", "origin", "main"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print("[Git] Push succesvol")
    else:
        # Eerste push: force push om branch te creëren
        result2 = subprocess.run(
            ["git", "push", "-u", "origin", "main", "--force"],
            capture_output=True, text=True
        )
        if result2.returncode == 0:
            print("[Git] Eerste push succesvol (force)")
        else:
            print(f"[Git] Push mislukt: {result2.stderr}")


def cleanup_old_data(keep_days: int = 7):
    """Verwijder exports ouder dan X dagen."""
    cutoff = datetime.now(timezone.utc) + NL_OFFSET - timedelta(days=keep_days)
    for day_dir in EXPORT_DIR.iterdir():
        if not day_dir.is_dir():
            continue
        try:
            dir_date = datetime.strptime(day_dir.name, "%Y-%m-%d")
            if dir_date < cutoff.replace(tzinfo=None):
                import shutil
                shutil.rmtree(day_dir)
                print(f"[Cleanup] Verwijderd: {day_dir.name}")
        except ValueError:
            continue


def main():
    """Hoofdfunctie: exporteer vorige uur, push naar GitHub."""
    target = get_current_hour_nl()
    print(f"[Export] Start: exporteer {target.strftime('%Y-%m-%d %H:00')} NL")
    
    output = export_hour(target)
    
    if output:
        cleanup_old_data()
        git_push()
    
    print("[Export] Klaar")


if __name__ == "__main__":
    main()
