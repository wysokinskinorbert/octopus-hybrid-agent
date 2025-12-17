from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import json

class BaseAdapter(ABC):
    """
    Abstract Base Class for Model Adapters.
    Responsible for normalizing communication between the Agent Session and different LLM providers/families.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the adapter strategy."""
        pass

    @abstractmethod
    def prepare_messages(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """
        Prepares the message history for the specific model.
        Injects system protocols (e.g., XML instructions, JSON schemas) if needed.
        """
        pass

    @abstractmethod
    def parse_response(self, response_content: str, tool_calls: Optional[List[Any]] = None) -> Dict[str, Any]:
        """
        Parses the raw model response into a standardized format.
        
        Returns a dict with:
        - content (str): The text content (assistant message)
        - tool_calls (List[Dict]): Standardized list of tool calls [{"name": "...", "arguments": {...}}]
        """
        pass
