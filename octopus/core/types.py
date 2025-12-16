from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field
import json

class ToolCallFunction(BaseModel):
    name: str
    arguments: str  # JSON string

class ToolCall(BaseModel):
    id: Optional[str] = None
    type: str = "function"
    function: ToolCallFunction

class OctopusMessage(BaseModel):
    role: str
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None
    
    # Allow extra fields for provider-specific metadata without validation errors
    model_config = {"extra": "allow"}

    @classmethod
    def from_any(cls, msg: Any) -> "OctopusMessage":
        """Factory to robustly create an OctopusMessage from dict or object."""
        if isinstance(msg, cls):
            return msg.model_copy(deep=True)
        
        if isinstance(msg, dict):
            # Handle deep copy manually if needed, but Pydantic init handles dict
            return cls(**msg)
        
        # Try converting object to dict (Pydantic models, etc.)
        if hasattr(msg, "model_dump"):
            return cls(**msg.model_dump())
        if hasattr(msg, "dict"):
            return cls(**msg.dict())
        
        # Last resort: try casting to dict
        try:
            return cls(**dict(msg))
        except Exception as e:
            raise ValueError(f"Cannot convert {type(msg)} to OctopusMessage: {e}")

    def to_dict(self) -> Dict[str, Any]:
        """Convert back to dictionary for litellm, excluding None values."""
        return self.model_dump(exclude_none=True)

    def sanitize_for_xml_fallback(self) -> None:
        """
        Modifies the message in-place to be safe for XML fallback strategies.
        - Converts structured tool_calls to textual XML blocks.
        - Converts 'tool' role messages to 'user' role with context.
        """
        # 1. Handle Assistant Tool Calls -> XML
        if self.role == "assistant" and self.tool_calls:
            xml_blocks = []
            for tc in self.tool_calls:
                fname = tc.function.name
                fargs_str = tc.function.arguments
                
                # Double-check if arguments is a dict (should be str but safety first)
                if isinstance(fargs_str, dict):
                    fargs_str = json.dumps(fargs_str)
                
                # Sanitize arguments string if it's not valid JSON or needs escaping?
                # Usually we trust it's a JSON string.
                
                xml = f"<tool_code>\n{{\n    \"name\": \"{fname}\",\n    \"arguments\": {fargs_str}\n}}\n</tool_code>"
                xml_blocks.append(xml)
            
            # Append to content
            current_content = self.content or ""
            separator = "\n\n" if current_content else ""
            self.content = f"{current_content}{separator}" + "\n".join(xml_blocks)
            
            # CLEAR structured tool calls
            self.tool_calls = None

        # 2. Handle Tool Results -> User Message
        if self.role == "tool":
            self.role = "user"
            tool_name = self.name or "unknown"
            self.content = f"[Tool Result: {tool_name}]\n{self.content or ''}"
            
            # Clear tool-specific fields
            self.tool_call_id = None
            self.name = None
