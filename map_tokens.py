import csv
import json
import subprocess
from datetime import datetime

def analyze_all_history():
    csv_path = ".history/performance_history.csv"
    output_csv = "docs/reports/comprehensive_token_usage_map.csv"
    
    mapped_runs = []
    with open(csv_path, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # We want to catch everything with token usage reported
            tokens_total = int(row.get('tokens_total', 0) or 0)
            tokens_input = int(row.get('tokens_input', 0) or 0)
            
            if tokens_total > 0 or tokens_input > 0:
                config_json_str = row.get('run_config_json', '{}')
                try:
                    config = json.loads(config_json_str)
                except:
                    config = {}
                
                llm_recipe = config.get('llm_recipe_pipeline', 'off')
                line_role = config.get('line_role_pipeline', 'off')
                
                if not llm_recipe: llm_recipe = 'off'
                if not line_role: line_role = 'off'

                is_line_role_llm = line_role not in ['off', 'deterministic-v1', 'deterministic']
                is_recipe_llm = llm_recipe not in ['off']
                
                # Report mentions 2,703 messages and ~10M input tokens
                # If a run is very close to these numbers, it's the one.
                # However, the audit might be an aggregate of multiple runs in a batch.
                
                category = "Unknown"
                if is_line_role_llm and not is_recipe_llm:
                    category = "Leak (LineRole Only)"
                elif is_line_role_llm and is_recipe_llm:
                    category = "Full LLM Stack"
                elif not is_line_role_llm and is_recipe_llm:
                    category = "Recipe LLM Only"
                
                run_dir = row.get('run_dir', '').lower()
                if "exhaustive" in run_dir or "singleton" in run_dir:
                    category = f"Exhaustive Sweep: {category}"
                elif "benchmark" in run_dir:
                    category = f"Automated: {category}"

                mapped_runs.append({
                    'timestamp': row['run_timestamp'],
                    'category': category,
                    'tokens': tokens_total,
                    'input_tokens': tokens_input,
                    'llm_recipe': llm_recipe,
                    'line_role': line_role,
                    'file': row.get('file_name', ''),
                    'run_dir': row.get('run_dir', ''),
                    'config_hash': row.get('run_config_hash', '')[:8]
                })

    # Sort by timestamp
    mapped_runs.sort(key=lambda x: x['timestamp'], reverse=True)

    with open(output_csv, mode='w', encoding='utf-8', newline='') as f:
        fieldnames = ['timestamp', 'category', 'tokens', 'input_tokens', 'llm_recipe', 'line_role', 'file', 'run_dir', 'config_hash']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for run in mapped_runs:
            writer.writerow(run)
    
    print(f"Wrote {len(mapped_runs)} token-consuming runs to {output_csv}")

if __name__ == "__main__":
    analyze_all_history()
