import sys
import os

# Add project root to sys.path
sys.path.append(os.getcwd())

from octopus.core.adapters.ollama_adapters import OllamaXMLAdapter

def test_adapter():
    adapter = OllamaXMLAdapter()
    
    # Simulate a malformed or raw log entry where list_directory might fail JSON parsing
    # or just rely on fallback if XML is missing (common with Mistral)
    
    # Case 1: Missing XML tags, raw JSON (Mistral sometimes does this)
    log_content_raw = """
    Here is the tool you asked for:
    {
       "name": "list_directory",
       "arguments": {
           "path": "demo_project/pogoda-dashboard"
       }
    }
    """
    
    print("--- TEST 1: Raw JSON list_directory ---")
    result1 = adapter.parse_response(log_content_raw)
    print(f"Result: {result1['tool_calls']}")
    
    # Case 2: XML tags but maybe malformed JSON inside (simulated by regex fallback reliance)
    # We force regex fallback by making JSON invalid but regex-friendly
    log_content_malformed = """<tool_code>
    {
       "name": "list_directory",
       "arguments": {
           "path": "demo_project/pogoda-dashboard"
    }
    </tool_code>""" # Missing closing brace for arguments
    
    print("\n--- TEST 2: Malformed JSON list_directory (Regex Fallback) ---")
    result2 = adapter.parse_response(log_content_malformed)
    print(f"Result: {result2['tool_calls']}")

if __name__ == "__main__":
    test_adapter()
