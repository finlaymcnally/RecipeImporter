import csv
from datetime import datetime
from collections import defaultdict
import os

def analyze_all_activity():
    activity_paths = [
        "var/codex_exec_activity.csv",
        "var/codex_exec_activity.legacy-2026-03-04_01.48.08.csv"
    ]
    output_summary = "docs/reports/codex_activity_detailed_line_items.csv"
    
    stats = defaultdict(lambda: {
        'count': 0,
        'tokens_total': 0,
        'tokens_input': 0,
        'tokens_output': 0,
        'tokens_cached': 0,
        'model': set(),
        'pipeline': set(),
        'first_seen': None,
        'last_seen': None,
        'run_id': set(),
        'source': set()
    })
    
    for activity_path in activity_paths:
        if not os.path.exists(activity_path):
            continue
        with open(activity_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    timestamp_str = row['logged_at_utc']
                    dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    # Group by hour to see the rollout
                    key_ts = dt.strftime('%Y-%m-%d %H:00')
                    
                    run_id = row.get('run_id', 'unknown')
                    pipeline = row.get('pipeline_id', 'unknown')
                    key = (key_ts, run_id, pipeline)
                    
                    s = stats[key]
                    s['count'] += 1
                    s['tokens_total'] += int(row.get('tokens_total', 0) or 0)
                    s['tokens_input'] += int(row.get('tokens_input', 0) or 0)
                    s['tokens_output'] += int(row.get('tokens_output', 0) or 0)
                    s['tokens_cached'] += int(row.get('tokens_cached_input', 0) or 0)
                    s['model'].add(row.get('model', 'unknown'))
                    s['pipeline'].add(pipeline)
                    s['run_id'].add(run_id)
                    s['source'].add(row.get('source', 'unknown'))
                    
                    if s['first_seen'] is None or dt < s['first_seen']:
                        s['first_seen'] = dt
                    if s['last_seen'] is None or dt > s['last_seen']:
                        s['last_seen'] = dt
                except Exception as e:
                    continue

    sorted_keys = sorted(stats.keys(), key=lambda x: x[0], reverse=True)
    
    with open(output_summary, mode='w', encoding='utf-8', newline='') as f:
        fieldnames = ['hour', 'run_id', 'pipeline', 'call_count', 'tokens_total', 'tokens_input', 'tokens_output', 'tokens_cached', 'models', 'source_type']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for key in sorted_keys:
            s = stats[key]
            if s['tokens_total'] == 0: continue
            writer.writerow({
                'hour': key[0],
                'run_id': key[1],
                'pipeline': key[2],
                'call_count': s['count'],
                'tokens_total': s['tokens_total'],
                'tokens_input': s['tokens_input'],
                'tokens_output': s['tokens_output'],
                'tokens_cached': s['tokens_cached'],
                'models': ",".join(s['model']),
                'source_type': ",".join(s['source'])
            })

if __name__ == "__main__":
    analyze_all_activity()
