import json
import os

log_file = r"e:\APLICATION_PROJECTS\octopus\logs\session_20251217_001720.jsonl"

print(f"--- Analyzing {log_file} ---")

if not os.path.exists(log_file):
    print("File not found")
    exit(1)

with open(log_file, 'r', encoding='utf-8') as f:
    for line in f:
        try:
            entry = json.loads(line)
            role = entry.get('metadata', {}).get('role', '')
            evt_type = entry.get('type')
            
            # Show Reviewer Text
            if role == 'reviewer' and evt_type == 'text':
                print(f"[REVIEWER]: {entry.get('content')}")
                
            # Show Errors
            if evt_type == 'error':
                print(f"[ERROR]: {entry.get('content')}")
                
            # Show Failover Logs
            if "Failover:" in str(entry.get('content')):
                print(f"[FAILOVER]: {entry.get('content')}")

        except Exception as e:
            pass
