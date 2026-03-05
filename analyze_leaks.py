import csv
import json
from pathlib import Path

csv_path = ".history/performance_history.csv"
output_csv = "docs/reports/token_leak_mapping.csv"

def analyze_leaks():
    leaks = []
    with open(csv_path, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            tokens_total = int(row.get('tokens_total', 0) or 0)
            if tokens_total > 0:
                config_json_str = row.get('run_config_json', '{}')
                try:
                    config = json.loads(config_json_str)
                except:
                    config = {}
                
                llm_recipe = config.get('llm_recipe_pipeline', 'off')
                line_role = config.get('line_role_pipeline', 'off')
                
                # Intentional Codex Farm runs usually have llm_recipe_pipeline set to something else
                # BUT the leak report says benchmarks ran with llm_recipe_pipeline off
                # but line_role_pipeline leaked.
                
                is_leak = False
                if llm_recipe == 'off' and line_role != 'off' and line_role != 'deterministic-v1':
                    is_leak = True
                
                # Also check if it's a suspicious case even if llm_recipe is on
                # but for now let's focus on the "invisible" ones.
                
                leaks.append({
                    'run_timestamp': row['run_timestamp'],
                    'tokens_total': tokens_total,
                    'llm_recipe_pipeline': llm_recipe,
                    'line_role_pipeline': line_role,
                    'file_name': row.get('file_name', ''),
                    'run_dir': row.get('run_dir', ''),
                    'run_config_hash': row.get('run_config_hash', '')[:8],
                    'is_leak': is_leak
                })

    # Sort by is_leak (True first), then by tokens_total descending
    leaks.sort(key=lambda x: (not x['is_leak'], -x['tokens_total']))

    with open(output_csv, mode='w', encoding='utf-8', newline='') as f:
        fieldnames = ['run_timestamp', 'tokens_total', 'llm_recipe_pipeline', 'line_role_pipeline', 'file_name', 'is_leak', 'run_dir', 'run_config_hash']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for leak in leaks:
            writer.writerow({k: leak[k] for k in fieldnames})

if __name__ == "__main__":
    analyze_leaks()
