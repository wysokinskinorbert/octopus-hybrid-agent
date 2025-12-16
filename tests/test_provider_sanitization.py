import sys
import os
import json
import pytest
from pydantic import BaseModel

# Ensure project root is in path
sys.path.append(os.getcwd())

from octopus.core.types import OctopusMessage, ToolCall, ToolCallFunction

# Mocks
class MockProviderConfig:
    def __init__(self, tool_mode, provider_type="ollama"):
        self.tool_mode = tool_mode
        self.type = provider_type
        self.api_key_env = None
        self.base_url = None

# Tests
def test_octopus_message_from_dict():
    raw = {"role": "user", "content": "Hello"}
    msg = OctopusMessage.from_any(raw)
    assert msg.role == "user"
    assert msg.content == "Hello"

def test_octopus_message_from_pydantic():
    class TestModel(BaseModel):
        role: str
        content: str
        
    raw = TestModel(role="user", content="Hello")
    msg = OctopusMessage.from_any(raw)
    assert msg.role == "user"
    assert msg.content == "Hello"

def test_sanitization_assistant_tool_calls():
    # Setup message with tool calls
    msg = OctopusMessage(
        role="assistant",
        content="Thinking...",
        tool_calls=[
            ToolCall(
                id="call_1",
                function=ToolCallFunction(name="read_file", arguments='{"path": "test.py"}')
            )
        ]
    )
    
    # Run sanitization
    msg.sanitize_for_xml_fallback()
    
    # Verify
    assert msg.tool_calls is None
    assert "<tool_code>" in msg.content
    assert '"name": "read_file"' in msg.content
    assert '"arguments": {"path": "test.py"}' in msg.content

def test_sanitization_tool_result():
    # Setup tool result message
    msg = OctopusMessage(
        role="tool",
        name="read_file",
        tool_call_id="call_1",
        content="print('hello')"
    )
    
    # Run sanitization
    msg.sanitize_for_xml_fallback()
    
    # Verify conversion to user message
    assert msg.role == "user"
    assert "[Tool Result: read_file]" in msg.content
    assert "print('hello')" in msg.content
    assert msg.tool_call_id is None
    assert msg.name is None

def test_native_strategy_preserves_structure():
    # If we don't call sanitize, structure should remain
    msg = OctopusMessage(
        role="assistant",
        tool_calls=[
            ToolCall(
                id="call_1",
                function=ToolCallFunction(name="test", arguments="{}")
            )
        ]
    )
    
    # Simulate Native Strategy (i.e. we do NOT call sanitize)
    # verify export
    exported = msg.to_dict()
    assert "tool_calls" in exported
    assert exported["tool_calls"][0]["function"]["name"] == "test"

if __name__ == "__main__":
    # Allow running directly
    pytest.main([__file__])
