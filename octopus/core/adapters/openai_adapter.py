from typing import List, Dict, Any, Optional
from .base import BaseAdapter

class OpenAIAdapter(BaseAdapter):
    """
    Adapter for models that support native OpenAI-compatible tool calls (e.g. GPT-4, official Ollama JSON mode if fully supported).
    """

    @property
    def name(self) -> str:
        return "openai"

    def prepare_messages(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        # OpenAI models understand tools natively via the 'tools' API param, so we don't need to inject special system prompts.
        # We just return the messages as is.
        return messages

    def parse_response(self, response_content: str, tool_calls: Optional[List[Any]] = None) -> Dict[str, Any]:
        """
        Parses the response assuming LiteLLM has already parsed tool_calls into objects.
        """
        standardized_calls = []
        if tool_calls:
            for tc in tool_calls:
                # LiteLLM/OpenAI tool call object usually has .function.name and .function.arguments
                # Arguments might be a JSON string or already a dict depending on the library version/mock.
                # Here we assume LiteLLM provides an object with function.name and function.arguments (string)
                
                try:
                    import json
                    args = tc.function.arguments
                    if isinstance(args, str):
                        args = json.loads(args)
                    
                    standardized_calls.append({
                        "name": tc.function.name,
                        "arguments": args,
                        "id": tc.id or "call_unknown"
                    })
                except Exception:
                    # If parsing arguments fails, we skip or log? For now skip.
                    continue
        
        return {
            "content": response_content,
            "tool_calls": standardized_calls
        }
