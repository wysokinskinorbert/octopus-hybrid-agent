import yaml
import sys

try:
    with open("config.yaml", "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
        print("Active Role:", data.get("active_role"))
        print("\nRoles:")
        for name, role in data.get("roles", {}).items():
            print(f"- {name}: Provider={role.get('provider_name')}, Model={role.get('model_id')}")
except Exception as e:
    print(e)
