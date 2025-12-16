import os
import json
import re
from typing import List, Dict, Any
from litellm import completion
from ..core.config_store import ProviderConfig
from ..core.types import OctopusMessage

class ProviderManager:
    def _create_tool_system_prompt(self, tools: List[Dict[str, Any]]) -> str:
        """Creates a system prompt instruction for XML-based tool calling."""
        if not tools:
            return ""
            
        tools_desc = []
        for t in tools:
            func = t.get("function", {})
            params = json.dumps(func.get("parameters", {}), indent=2)
            tools_desc.append(f"- {func.get('name')}: {func.get('description')}\n  Parameters: {params}")
            
        tools_str = "\n".join(tools_desc)
        
        return f"""
### TOOL USE INSTRUCTION ###
You have access to the following tools:
{tools_str}

To use a tool, you MUST output a valid XML block containing JSON, like this:
<tool_code>
{{
    "name": "tool_name",
    "arguments": {{
        "param1": "value1"
    }}
}}
</tool_code>

RULES:
1. Only use tools if strictly necessary.
2. You can only call one tool at a time.
3. Output ONLY the XML block when calling a tool.
4. If no tool is needed, just respond with text.
5. Do NOT use Markdown code blocks (like ```json) inside the XML tags.
"""

    def _parse_xml_tool_calls(self, content: str) -> List[Dict[str, Any]]:
        """Parses <tool_code> blocks from text content with robust error handling."""
        tool_calls = []
        # Find all content between tags, treating it as potentially dirty JSON
        pattern = r'<tool_code>(.*?)</tool_code>'
        matches = re.findall(pattern, content, re.DOTALL)
        
        for match in matches:
            # Clean up common model formatting artifacts
            clean_json = match.strip()
            # Remove markdown code blocks if present
            clean_json = re.sub(r'^```[a-zA-Z]*\s*', '', clean_json)
            clean_json = re.sub(r'\s*```$', '', clean_json)
            clean_json = clean_json.strip()

            try:
                # Attempt to parse
                data = json.loads(clean_json)
                
                # Validate structure
                if "name" in data and "arguments" in data:
                    tool_calls.append({
                        "id": f"call_{os.urandom(4).hex()}",
                        "type": "function",
                        "function": {
                            "name": data.get("name"),
                            "arguments": json.dumps(data.get("arguments", {}))
                        }
                    })
                elif "tool" in data: # Handle potential hallucinated key "tool" instead of "name"
                     tool_calls.append({
                        "id": f"call_{os.urandom(4).hex()}",
                        "type": "function",
                        "function": {
                            "name": data.get("tool"),
                            "arguments": json.dumps(data.get("parameters", {}) if "parameters" in data else data.get("arguments", {}))
                        }
                    })
            except json.JSONDecodeError as e:
                print(f"[ProviderManager] Failed to parse tool JSON: {e}. Raw chunk: {clean_json[:50]}...")
                continue
                
        return tool_calls

    def chat_complete(
                      self,
                      provider: ProviderConfig,
                      model_id: str,
                      messages: List[Dict[str, Any]],
                      tools: List[Dict[str, Any]] = None,
                      temperature: float = None) -> Any:

        # 1. Determine Strategy
        strategy = provider.tool_mode
        if strategy == "auto":
            # Heuristic: OpenAI/Anthropic/DeepSeek usually support native tools reliably.
            if provider.type in ["openai", "anthropic", "deepseek"]:
                strategy = "native"
            elif provider.type == "ollama":
                # Ollama models vary in tool support - safer to use xml_fallback
                # Native tool calls often fail silently with local models
                strategy = "xml_fallback"
            else:
                # For other providers, try native as default
                strategy = "native"

        # 2. Prepare Arguments
        model_name = f"{provider.type}/{model_id}"
        effective_temp = temperature if temperature is not None else 0.2

        # ABSTRACTION: Convert all inputs to uniform OctopusMessage objects
        # This handles dicts, Pydantic objects (litellm Messages), etc.
        unified_messages = [OctopusMessage.from_any(m) for m in messages]

        # SANITIZATION: If using XML fallback, modify the objects in-place
        if strategy == "xml_fallback":
             for msg in unified_messages:
                 msg.sanitize_for_xml_fallback()

        # Convert back to list of dicts for litellm
        final_messages = [m.to_dict() for m in unified_messages]

        kwargs = {
            "model": model_name,
            "messages": final_messages,
            "temperature": effective_temp
        }

        # API Key & Base URL
        if provider.api_key_env:
            key = os.getenv(provider.api_key_env)
            if key: kwargs["api_key"] = key
        
        if provider.base_url:
            kwargs["api_base"] = provider.base_url

        # 3. Apply Strategy
        if tools:
            if strategy == "native":
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            
            elif strategy == "xml_fallback":
                # Inject instructions
                tool_instructions = self._create_tool_system_prompt(tools)
                
                # Check if system message exists
                system_msg_index = -1
                for i, msg in enumerate(kwargs["messages"]):
                    if msg.get("role") == "system":
                        system_msg_index = i
                        break
                
                if system_msg_index >= 0:
                    kwargs["messages"][system_msg_index]["content"] += f"\n\n{tool_instructions}"
                else:
                    kwargs["messages"].insert(0, {"role": "system", "content": tool_instructions})

        # 4. Execute
        try:
            response = completion(**kwargs)
            message = response.choices[0].message
        except Exception as e:
            # If native tool calling fails with a specific error (like the one we saw earlier),
            # we could theoretically retry with fallback, but let's trust the config for now.
            raise e

        # 5. Post-process (if fallback was used)
        if tools and strategy == "xml_fallback" and message.content:
            # Check for XML tags
            if "<tool_code>" in message.content:
                extracted_tools = self._parse_xml_tool_calls(message.content)
                if extracted_tools:
                    message.tool_calls = extracted_tools
                    # Clean content so user doesn't see raw XML
                    # We remove the whole block including tags
                    clean_content = re.sub(r'<tool_code>.*?</tool_code>', '', message.content, flags=re.DOTALL).strip()
                    message.content = clean_content if clean_content else None
            
        return message, response.usage

    def chat_complete_stream(
                      self,
                      provider: ProviderConfig,
                      model_id: str,
                      messages: List[Dict[str, Any]],
                      tools: List[Dict[str, Any]] = None,
                      temperature: float = None):
        """
        Streaming version of chat_complete.
        Yields dictionaries with streaming events:
        - {"type": "chunk", "content": "partial text"}
        - {"type": "done", "message": <complete message>, "usage": <usage object>}
        - {"type": "error", "error": "error message"}
        """
        import litellm

        # 1. Determine Strategy (same as chat_complete)
        strategy = provider.tool_mode
        if strategy == "auto":
            if provider.type in ["openai", "anthropic", "deepseek"]:
                strategy = "native"
            elif provider.type == "ollama":
                strategy = "xml_fallback"
            else:
                strategy = "native"

        # 2. Prepare Messages (same as chat_complete)
        model_name = f"{provider.type}/{model_id}"
        effective_temp = temperature if temperature is not None else 0.2

        unified_messages = [OctopusMessage.from_any(m) for m in messages]
        if strategy == "xml_fallback":
            for msg in unified_messages:
                msg.sanitize_for_xml_fallback()

        final_messages = [m.to_dict() for m in unified_messages]

        kwargs = {
            "model": model_name,
            "messages": final_messages,
            "temperature": effective_temp,
            "stream": True,  # ENABLE STREAMING
        }

        if provider.api_key_env:
            key = os.getenv(provider.api_key_env)
            if key:
                kwargs["api_key"] = key

        if provider.base_url:
            kwargs["api_base"] = provider.base_url

        # 3. Apply Strategy (tools)
        if tools:
            if strategy == "native":
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            elif strategy == "xml_fallback":
                tool_instructions = self._create_tool_system_prompt(tools)
                system_msg_index = -1
                for i, msg in enumerate(kwargs["messages"]):
                    if msg.get("role") == "system":
                        system_msg_index = i
                        break
                if system_msg_index >= 0:
                    kwargs["messages"][system_msg_index]["content"] += f"\n\n{tool_instructions}"
                else:
                    kwargs["messages"].insert(0, {"role": "system", "content": tool_instructions})

        # 4. Execute with streaming
        try:
            response_stream = completion(**kwargs)
            chunks = []
            accumulated_content = ""

            for chunk in response_stream:
                chunks.append(chunk)

                # Extract delta content
                if chunk.choices and chunk.choices[0].delta:
                    delta = chunk.choices[0].delta
                    if hasattr(delta, 'content') and delta.content:
                        accumulated_content += delta.content
                        yield {"type": "chunk", "content": delta.content}

            # Build complete response from chunks
            try:
                complete_response = litellm.stream_chunk_builder(chunks, messages=messages)
                message = complete_response.choices[0].message
                usage = complete_response.usage
            except Exception as build_err:
                # Fallback: create synthetic message from accumulated content
                class SyntheticMessage:
                    def __init__(self, content):
                        self.content = content
                        self.tool_calls = None
                message = SyntheticMessage(accumulated_content)
                usage = None

            # 5. Post-process for xml_fallback (same as non-streaming)
            if tools and strategy == "xml_fallback" and message.content:
                if "<tool_code>" in message.content:
                    extracted_tools = self._parse_xml_tool_calls(message.content)
                    if extracted_tools:
                        message.tool_calls = extracted_tools
                        clean_content = re.sub(r'<tool_code>.*?</tool_code>', '', message.content, flags=re.DOTALL).strip()
                        message.content = clean_content if clean_content else None

            yield {"type": "done", "message": message, "usage": usage}

        except Exception as e:
            yield {"type": "error", "error": str(e)}