import os
from octopus.core.config_store import ConfigStore, ProviderConfig

def test_config_persistence():
    print("Testing ConfigStore Persistence...")
    
    # Use a temporary file
    test_cfg_path = "test_config.yaml"
    if os.path.exists(test_cfg_path):
        os.remove(test_cfg_path)
        
    store = ConfigStore(test_cfg_path)
    
    # Add a custom provider
    print("Adding Provider 'test-provider'...")
    store.config.providers["test-provider"] = ProviderConfig(
        name="test-provider",
        type="ollama",
        base_url="http://127.0.0.1:9999"
    )
    
    store.save()
    print("Saved config.")
    
    # Reload
    print("Reloading config...")
    store2 = ConfigStore(test_cfg_path)
    
    if "test-provider" in store2.config.providers:
        p = store2.config.providers["test-provider"]
        if p.base_url == "http://127.0.0.1:9999":
            print("[PASS] Config persisted correctly.")
        else:
            print(f"[FAIL] Value mismatch: {p.base_url}")
    else:
        print("[FAIL] Provider not found after reload.")
        
    # Cleanup
    if os.path.exists(test_cfg_path):
        os.remove(test_cfg_path)

if __name__ == "__main__":
    test_config_persistence()
