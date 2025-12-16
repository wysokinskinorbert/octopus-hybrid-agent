import sys
import os
import yaml

sys.path.append(os.getcwd())

try:
    with open("config.yaml", "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    print("YAML Syntax OK!")
    print(f"Loaded {len(data['providers'])} providers.")
except Exception as e:
    print(f"YAML ERROR: {e}")
    sys.exit(1)
