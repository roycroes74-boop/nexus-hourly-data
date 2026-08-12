#!/usr/bin/env python3
"""
detect_levels.py — Level detection from MBO-32 tick data
Scans 2-4 hours before given timestamp for significant price levels
based on absorption, iceberg activity, STACK events, book depth, and trade volume.
"""
import argparse
import gzip
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta

def load_blocks(date_str, end_hour_nl):
    """Load 2-4 hours of data before the given NL hour"""
    base = f"/home/ubuntu/nexus-hourly-export/full-tick-data/{date_str}"
    if not os.path.isdir(base):
        return []
    
    # Determine which blocks to load (2-4 hours before end_hour)
    blocks_needed = []
    for h in range(max(0, end_hour_nl - 4), end_hour_nl, 2):
        block_name = f"{h:02d}h00_{h+2:02d}h00_NL_FULL_MBO32.jsonl.gz"
        path = os.path.join(base, block_name)
        if os.path.exists(path):
            blocks_needed.append(path)
    
    events = []
    for path in blocks_needed:
        with gzip.open(path, 'rt') as f:
            for line in f:
                try:
                    events.append(json.loads(line))
                except:
                    continue
    return events

def detect_levels(events, end_hour_nl, end_minute):
    """Detect significant levels from MBO-32 data"""
    levels = defaultdict(lambda: {
        'price': 0,
        'absorption_vol': 0,
        'absorption_count': 0,
        'iceberg_vol': 0,
        'iceberg_count': 0,
        'stack_vol': 0,
        'stack_count': 0,
        'trade_vol': 0,
        'trade_count': 0,
        'book_size_max': 0,
        'touches': 0,
        'last_seen': '',
        'side': 'unknown'
    })
    
    for evt in events:
        etype = evt.get('type', '')
        
        if etype == 'nexus_orderflow_event':
            data = evt.get('data', evt)
            event_type = data.get('event_type', '')
            price = data.get('price')
            vol = data.get('vol', 0) or data.get('volume', 0)
            side = data.get('side', '')
            
            if not price:
                continue
            
            # Round to nearest 0.25
            price = round(price * 4) / 4
            key = price
            levels[key]['price'] = price
            
            if 'ABSORPTION' in event_type or 'absorption' in event_type.lower():
                levels[key]['absorption_vol'] += vol
                levels[key]['absorption_count'] += 1
                levels[key]['side'] = 'support' if 'BID' in event_type else 'resistance'
            elif 'ICEBERG' in event_type or 'iceberg' in event_type.lower():
                levels[key]['iceberg_vol'] += vol
                levels[key]['iceberg_count'] += 1
            elif 'STACK' in event_type or 'stack' in event_type.lower():
                levels[key]['stack_vol'] += vol
                levels[key]['stack_count'] += 1
            elif 'PULL' in event_type:
                pass  # PULL = weakness, not strength
            
            levels[key]['touches'] += 1
            levels[key]['last_seen'] = data.get('ts', '')
        
        elif etype == 'trade':
            price = evt.get('price')
            vol = evt.get('volume', evt.get('size', 0))
            if price:
                price = round(price * 4) / 4
                levels[price]['trade_vol'] += vol
                levels[price]['trade_count'] += 1
                levels[price]['price'] = price
        
        elif etype == 'book_snapshot':
            bids = evt.get('bids', [])
            asks = evt.get('asks', [])
            for bid in bids[:5]:
                p = bid.get('price')
                v = bid.get('volume', bid.get('size', 0))
                if p:
                    p = round(p * 4) / 4
                    levels[p]['book_size_max'] = max(levels[p]['book_size_max'], v)
            for ask in asks[:5]:
                p = ask.get('price')
                v = ask.get('volume', ask.get('size', 0))
                if p:
                    p = round(p * 4) / 4
                    levels[p]['book_size_max'] = max(levels[p]['book_size_max'], v)
    
    # Score levels
    scored = []
    for price, data in levels.items():
        score = 0
        score += min(data['absorption_vol'] / 100, 5)  # max 5 from absorption
        score += min(data['iceberg_vol'] / 200, 3)      # max 3 from icebergs
        score += min(data['stack_vol'] / 300, 3)        # max 3 from stacks
        score += min(data['book_size_max'] / 200, 2)    # max 2 from book depth
        score += min(data['trade_vol'] / 500, 2)        # max 2 from trade volume
        score += min(data['touches'] / 10, 2)           # max 2 from touches
        
        if score >= 2:  # minimum threshold
            scored.append({
                'price': price,
                'score': round(score, 1),
                'absorption': {'vol': data['absorption_vol'], 'count': data['absorption_count']},
                'iceberg': {'vol': data['iceberg_vol'], 'count': data['iceberg_count']},
                'stack': {'vol': data['stack_vol'], 'count': data['stack_count']},
                'book_max': data['book_size_max'],
                'trade_vol': data['trade_vol'],
                'touches': data['touches'],
                'side': data['side'],
                'last_seen': data['last_seen']
            })
    
    # Sort by score descending
    scored.sort(key=lambda x: x['score'], reverse=True)
    return scored[:20]  # top 20 levels

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', default=datetime.now().strftime('%Y-%m-%d'))
    parser.add_argument('--hour', type=int, default=14)
    parser.add_argument('--minute', type=int, default=0)
    args = parser.parse_args()
    
    events = load_blocks(args.date, args.hour)
    levels = detect_levels(events, args.hour, args.minute)
    
    result = {
        'date': args.date,
        'timestamp': f"{args.hour:02d}:{args.minute:02d} NL",
        'levels_found': len(levels),
        'scan_window': f"{max(0, args.hour-4):02d}:00 - {args.hour:02d}:00 NL",
        'levels': levels
    }
    
    print(json.dumps(result))

if __name__ == '__main__':
    main()
