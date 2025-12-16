import os
import yaml
from octopus.core.config_store import ConfigStore

def test_broken_config_loading():
    print("Testing resilience against broken config...")
    
    cfg_path = "broken_config.yaml"
    
    # Create a config with null values which caused crashes before
    broken_data = {
        "providers": None,
        "mcp_servers": None,
        "roles": None
    }
    
    with open(cfg_path, "w") as f:
        yaml.dump(broken_data, f)
        
    try:
        store = ConfigStore(cfg_path)
        print("[PASS] ConfigStore loaded broken file without crashing.")
        
        # Check if defaults were applied or if it's just empty
        # My implementation doesn't re-apply defaults if keys exist but are None, 
        # it just loads empty dicts.
        if isinstance(store.config.providers, dict):
            print("[PASS] Providers is a dict.")
        else:
            print(f"[FAIL] Providers is {type(store.config.providers)}")
            
    except Exception as e:
        print(f"[FAIL] Crashed: {e}")
    finally:
        if os.path.exists(cfg_path):
            os.remove(cfg_path)

if __name__ == "__main__":
    test_broken_config_loading()
