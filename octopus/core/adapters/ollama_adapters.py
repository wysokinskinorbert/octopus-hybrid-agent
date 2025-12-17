import re
import json
from typing import List, Dict, Any, Optional
from .base import BaseAdapter

class OllamaJSONAdapter(BaseAdapter):
    """
    Adapter for models that prefer strict JSON output (e.g., Qwen 2.5).
    Injects a JSON-enforcing system prompt and utilizes robust JSON parsing/sanitization.
    """

    @property
    def name(self) -> str:
        return "ollama_json"

    def prepare_messages(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """
        Injects a system instruction to force JSON format.
        """
        if not tools:
            # If no tools are provided, we don't need to force tool format
            return messages

        # Clone messages to avoid side effects
        new_messages = [m.copy() for m in messages]
        
        # Heuristic: Find the system prompt and append instructions, or add a new system prompt
        system_instruction = (
            "\n\n[TOOL USE PROTOCOL]\n"
            "You have access to the following tools. To use a tool, you MUST output a VALID JSON object.\n"
            "Do not use XML tags. Do not use Markdown code blocks for the JSON.\n"
            "Format: { \"name\": \"tool_name\", \"arguments\": { \"arg1\": \"value1\" } }\n"
        )
        
        # Inject tool definitions into the prompt (since local models might not see the 'tools' param natively)
        # Simplified tool text representation
        tools_desc = json.dumps([t['function'] for t in tools], indent=2)
        system_instruction += f"\nAvailable Tools:\n{tools_desc}\n"

        # Locate system message
        for msg in new_messages:
            if msg['role'] == 'system':
                msg['content'] += system_instruction
                return new_messages
        
        # If no system message, insert one
        new_messages.insert(0, {"role": "system", "content": system_instruction})
        return new_messages

    def parse_response(self, response_content: str, tool_calls: Optional[List[Any]] = None) -> Dict[str, Any]:
        """
        Parses JSON from the raw text content. Ignores 'tool_calls' from LiteLLM as we handle text manually.
        """
        standardized_calls = []
        
        # 1. Try generic JSON regex
        # We look for a JSON object with "name" and "arguments" keys
        json_match = re.search(r'(\{.*"name":\s*".*?".*"arguments":\s*\{.*?\}.*\})', response_content, re.DOTALL)
        
        if json_match:
            raw_json = json_match.group(1)
            sanitized = self._sanitize_json_from_llm(raw_json)
            try:
                data = json.loads(sanitized)
                if "name" in data and "arguments" in data:
                    standardized_calls.append({
                        "id": "json_heuristic",
                        "type": "function",
                        "function": {
                            "name": data["name"],
                            "arguments": json.dumps(data["arguments"])
                        }
                    })
            except Exception:
                # Fallback: Regex extraction
                self._fallback_regex_extraction(raw_json, standardized_calls)
        else:
             # Even if no full JSON object found, try finding specific tool patterns
             # HEURISTIC 2: Try finding JSON without the strict regex structure?
             # Actually, the regex above (\{.*"name":\s*".*?".*"arguments":\s*\{.*?\}.*\}) 
             # is already quite generic. If that fails, fallback extraction is the way.
             self._fallback_regex_extraction(response_content, standardized_calls)

        return {
            "content": response_content, # The full text is still the content
            "tool_calls": standardized_calls
        }

    def _sanitize_json_from_llm(self, s: str) -> str:
        # Replace Python triple-quotes with escaped JSON string
        s = re.sub(r'"{3}(.*?)"{3}', lambda m: '"' + m.group(1).replace('\\', '\\\\').replace('\n', '\\n').replace('"', '\\"') + '"', s, flags=re.DOTALL)
        # Remove trailing commas
        s = re.sub(r',\s*([}\]])', r'\1', s)
        return s

    def _fallback_regex_extraction(self, text: str, calls: List[Dict]):
         # FALLBACK: Extract write_file/read_file via raw regex
        write_match = re.search(r'"name"\s*:\s*"write_file".*?"path"\s*:\s*"([^"]+)".*?"content"\s*:\s*["\']{1,3}(.*?)["\']{1,3}\s*\}', text, re.DOTALL)
        read_match = re.search(r'"name"\s*:\s*"read_file".*?"path"\s*:\s*"([^"]+)"', text, re.DOTALL)
        list_match = re.search(r'"name"\s*:\s*"list_directory".*?"path"\s*:\s*"([^"]+)"', text, re.DOTALL)
        shell_match = re.search(r'"name"\s*:\s*"run_shell_command".*?"command"\s*:\s*"([^"]+)"', text, re.DOTALL)
        
        if write_match:
            path, content = write_match.groups()
            calls.append({
                "id": "fallback_write",
                "type": "function",
                "function": {
                    "name": "write_file", 
                    "arguments": json.dumps({"path": path, "content": content})
                }
            })
        if read_match:
            path = read_match.group(1)
            calls.append({
                "id": "fallback_read",
                "type": "function",
                "function": {
                    "name": "read_file", 
                    "arguments": json.dumps({"path": path})
                }
            })
        if list_match:
            path = list_match.group(1)
            calls.append({
                "id": "fallback_list",
                "type": "function",
                "function": {
                    "name": "list_directory", 
                    "arguments": json.dumps({"path": path})
                }
            })
        if shell_match:
            cmd = shell_match.group(1)
            calls.append({
                "id": "fallback_shell",
                "type": "function",
                "function": {
                    "name": "run_shell_command", 
                    "arguments": json.dumps({"command": cmd})
                }
            })


class OllamaXMLAdapter(BaseAdapter):
    """
    Adapter for models that prefer XML tags (e.g., Mistral).
    Injects instructions to use <tool_code> tags.
    """
    
    @property
    def name(self) -> str:
        return "ollama_xml"

    def prepare_messages(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        if not tools:
            return messages
        
        new_messages = [m.copy() for m in messages]
        
        system_instruction = (
            "\n\n[TOOL USE PROTOCOL]\n"
            "You have access to tools. To use them, you MUST wrap the JSON tool call inside <tool_code> XML tags.\n"
            "Example:\n<tool_code>\n{\n  \"name\": \"tool_name\",\n  \"arguments\": {\"arg\": \"val\"}\n}\n</tool_code>\n"
        )
        tools_desc = json.dumps([t['function'] for t in tools], indent=2)
        system_instruction += f"\nAvailable Tools:\n{tools_desc}\n"

        for msg in new_messages:
            if msg['role'] == 'system':
                msg['content'] += system_instruction
                return new_messages
        
        new_messages.insert(0, {"role": "system", "content": system_instruction})
        return new_messages

    def parse_response(self, response_content: str, tool_calls: Optional[List[Any]] = None) -> Dict[str, Any]:
        standardized_calls = []
        
        # Robust Regex for XML tags
        tool_code_match = re.search(r'<tool_code>(.*?)</tool_code>', response_content, re.DOTALL)
        
        if tool_code_match:
            raw_json = tool_code_match.group(1).strip()
            # If the content inside tags has preamble/postscript, extracting just the JSON part
            # Find the first { and the last }
            json_start = raw_json.find('{')
            json_end = raw_json.rfind('}')
            
            if json_start != -1 and json_end != -1:
                raw_json = raw_json[json_start:json_end+1]

            sanitized = self._sanitize_json(raw_json)
            try:
                data = json.loads(sanitized)
                if "name" in data:
                     standardized_calls.append({
                        "id": "xml_heuristic",
                        "type": "function",
                        "function": {
                            "name": data["name"],
                            "arguments": json.dumps(data.get("arguments", {}))
                        }
                     })
            except Exception:
                 self._fallback_regex(raw_json, standardized_calls)
        else:
            # HEURISTIC 2: GENERIC JSON FALLBACK (For when Mistral forgets XML tags)
            # We look for any JSON object with "name" and "arguments" keys
            json_match = re.search(r'(\{.*"name":\s*".*?".*"arguments":\s*\{.*?\}.*\})', response_content, re.DOTALL)
            if json_match:
                raw_json = json_match.group(1)
                sanitized = self._sanitize_json(raw_json)
                try:
                    data = json.loads(sanitized)
                    if "name" in data:
                        standardized_calls.append({
                            "id": "json_fallback_heuristic",
                            "type": "function",
                            "function": {
                                "name": data["name"],
                                "arguments": json.dumps(data.get("arguments", {}))
                            }
                        })
                except Exception:
                    # If generic JSON fails, try regex
                    self._fallback_regex(response_content, standardized_calls)
            else:
                # Try raw regex on the whole content just in case
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
         # Similar fallback
        write_match = re.search(r'"name"\s*:\s*"write_file".*?"path"\s*:\s*"([^"]+)".*?"content"\s*:\s*["\']{1,3}(.*?)["\']{1,3}\s*\}', text, re.DOTALL)
        read_match = re.search(r'"name"\s*:\s*"read_file".*?"path"\s*:\s*"([^"]+)"', text, re.DOTALL)
        list_match = re.search(r'"name"\s*:\s*"list_directory".*?"path"\s*:\s*"([^"]+)"', text, re.DOTALL)
        shell_match = re.search(r'"name"\s*:\s*"run_shell_command".*?"command"\s*:\s*"([^"]+)"', text, re.DOTALL)
        
        if write_match:
            path, content = write_match.groups()
            calls.append({
                "id": "fallback_write",
                "type": "function",
                "function": {
                    "name": "write_file", 
                    "arguments": json.dumps({"path": path, "content": content})
                }
            })
        if read_match:
            path = read_match.group(1)
            calls.append({
                "id": "fallback_read",
                "type": "function",
                "function": {
                    "name": "read_file", 
                    "arguments": json.dumps({"path": path})
                }
            })
        if list_match:
            path = list_match.group(1)
            calls.append({
                "id": "fallback_list",
                "type": "function",
                "function": {
                    "name": "list_directory", 
                    "arguments": json.dumps({"path": path})
                }
            })
        if shell_match:
            cmd = shell_match.group(1)
            calls.append({
                "id": "fallback_shell",
                "type": "function",
                "function": {
                    "name": "run_shell_command", 
                    "arguments": json.dumps({"command": cmd})
                }
            })
