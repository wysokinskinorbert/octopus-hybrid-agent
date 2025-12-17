import re
import json
from typing import List, Dict, Any, Optional

class OllamaXMLAdapter:
    def parse_response(self, response_content: str, tool_calls: Optional[List[Any]] = None) -> Dict[str, Any]:
        standardized_calls = []
        
        # Relaxed Regex from v4 (XML)
        tool_code_match = re.search(r'<tool_code>.*(\{.*\})', response_content, re.DOTALL)
        
        if tool_code_match:
            print("MATCHED <tool_code>")
            raw_json = tool_code_match.group(1)
            print(f"RAW JSON EXTRACTED: {raw_json!r}")
            sanitized = self._sanitize_json(raw_json)
            print(f"SANITIZED JSON: {sanitized!r}")
            try:
                data = json.loads(sanitized)
                print("JSON LOAD SUCCESS")
                if "name" in data:
                     standardized_calls.append({
                        "name": data["name"],
                        "arguments": data.get("arguments", {}),
                        "id": "xml_heuristic"
                     })
            except Exception as e:
                 print(f"JSON LOAD FAILED: {e}")
                 self._fallback_regex(raw_json, standardized_calls)
        else:
            print("NO <tool_code> MATCH")
            # HEURISTIC 2: GENERIC JSON FALLBACK
            json_match = re.search(r'(\{.*"name":\s*".*?".*"arguments":\s*\{.*?\}.*\})', response_content, re.DOTALL)
            if json_match:
                print("MATCHED HEURISTIC 2")
                raw_json = json_match.group(1)
                sanitized = self._sanitize_json(raw_json)
                try:
                    data = json.loads(sanitized)
                    if "name" in data:
                        standardized_calls.append({
                            "name": data["name"],
                            "arguments": data.get("arguments", {}),
                            "id": "json_fallback_heuristic"
                        })
                except Exception:
                    self._fallback_regex(response_content, standardized_calls)
            else:
                self._fallback_regex(response_content, standardized_calls)

        return {
            "content": response_content,
            "tool_calls": standardized_calls
        }
    
    def _sanitize_json(self, s: str) -> str:
        s = re.sub(r'"{3}(.*?)"{3}', lambda m: '"' + m.group(1).replace('\\', '\\\\').replace('\n', '\\n').replace('"', '\\"') + '"', s, flags=re.DOTALL)
        s = re.sub(r',\s*([}\]])', r'\1', s)
        return s

    def _fallback_regex(self, text: str, calls: List[Dict]):
        print("ENTERING FALLBACK REGEX")
        write_match = re.search(r'"name"\s*:\s*"write_file".*?"path"\s*:\s*"([^"]+)".*?"content"\s*:\s*["\']{1,3}(.*?)["\']{1,3}\s*\}', text, re.DOTALL)
        read_match = re.search(r'"name"\s*:\s*"read_file".*?"path"\s*:\s*"([^"]+)"', text, re.DOTALL)
        list_match = re.search(r'"name"\s*:\s*"list_directory".*?"path"\s*:\s*"([^"]+)"', text, re.DOTALL)
        shell_match = re.search(r'"name"\s*:\s*"run_shell_command".*?"command"\s*:\s*"([^"]+)"', text, re.DOTALL)
        
        if write_match:
            print("FALLBACK MATCHED: write_file")
            path, content = write_match.groups()
            calls.append({"name": "write_file", "arguments": {"path": path, "content": content}, "id": "fallback_write"})
        if read_match:
            print("FALLBACK MATCHED: read_file")
            path = read_match.group(1)
            calls.append({"name": "read_file", "arguments": {"path": path}, "id": "fallback_read"})
        if list_match:
            print("FALLBACK MATCHED: list_directory")
            path = list_match.group(1)
            calls.append({"name": "list_directory", "arguments": {"path": path}, "id": "fallback_list"})
        if shell_match:
            print("FALLBACK MATCHED: run_shell_command")
            cmd = shell_match.group(1)
            calls.append({"name": "run_shell_command", "arguments": {"command": cmd}, "id": "fallback_shell"})

# TEST CASE FROM LOGS
adapter = OllamaXMLAdapter()
log_content = """<tool_code>
{
   "name": "list_directory",
   "arguments": {
       "path": "demo_project/pogoda-dashboard"
   }
}
</tool_code>"""

print(f"TESTING WITH:\n{log_content}\n")
result = adapter.parse_response(log_content)
print(f"RESULT: {result}")

log_content_2 = """<tool_code>
{
   "name": "read_file",
   "arguments": {
       "path": "demo_project/pogoda-dashboard/package.json"
   }
}
</tool_code>"""
print(f"\nTESTING WITH:\n{log_content_2}\n")
result_2 = adapter.parse_response(log_content_2)
print(f"RESULT 2: {result_2}")
