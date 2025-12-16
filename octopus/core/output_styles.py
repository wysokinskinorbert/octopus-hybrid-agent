"""
Output Styles System - Claude Code style.
Controls verbosity and formatting of tool outputs.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class OutputLevel(Enum):
    """Output verbosity levels."""
    MINIMAL = "minimal"
    BALANCED = "balanced"
    DETAILED = "detailed"


@dataclass
class OutputStyle:
    """Configuration for output formatting."""
    level: OutputLevel
    show_tool_args: bool = True
    show_tool_results: bool = True
    show_reasoning: bool = True
    show_timestamps: bool = False
    max_result_length: int = 500
    collapse_code_blocks: bool = True
    show_model_info: bool = True
    truncate_long_text: bool = True


# Predefined style configurations
STYLES = {
    "minimal": OutputStyle(
        level=OutputLevel.MINIMAL,
        show_tool_args=False,
        show_tool_results=False,
        show_reasoning=False,
        show_timestamps=False,
        max_result_length=100,
        collapse_code_blocks=True,
        show_model_info=False,
        truncate_long_text=True,
    ),
    "balanced": OutputStyle(
        level=OutputLevel.BALANCED,
        show_tool_args=True,
        show_tool_results=True,
        show_reasoning=True,
        show_timestamps=False,
        max_result_length=300,
        collapse_code_blocks=True,
        show_model_info=True,
        truncate_long_text=True,
    ),
    "detailed": OutputStyle(
        level=OutputLevel.DETAILED,
        show_tool_args=True,
        show_tool_results=True,
        show_reasoning=True,
        show_timestamps=True,
        max_result_length=1000,
        collapse_code_blocks=False,
        show_model_info=True,
        truncate_long_text=False,
    ),
}


class OutputStyleManager:
    """
    Manages output style configuration.

    Usage:
        manager = OutputStyleManager()
        manager.set_style("minimal")

        if manager.should_show("tool_args"):
            print(args)

        truncated = manager.truncate("long text...", "result")
    """

    def __init__(self, default_style: str = "balanced"):
        """Initialize with default style."""
        self.current_style_name = default_style
        self.current_style = STYLES.get(default_style, STYLES["balanced"])

    def set_style(self, name: str) -> bool:
        """
        Set the current output style.

        Args:
            name: Style name (minimal, balanced, detailed)

        Returns:
            True if style was set, False if invalid name
        """
        if name in STYLES:
            self.current_style_name = name
            self.current_style = STYLES[name]
            return True
        return False

    def get_style(self) -> OutputStyle:
        """Get current output style configuration."""
        return self.current_style

    def get_style_name(self) -> str:
        """Get current style name."""
        return self.current_style_name

    def should_show(self, element: str) -> bool:
        """
        Check if an element should be shown based on current style.

        Args:
            element: Element name (tool_args, tool_results, reasoning, timestamps, model_info)

        Returns:
            True if element should be displayed
        """
        attr_name = f"show_{element}"
        return getattr(self.current_style, attr_name, True)

    def truncate(self, text: str, context: str = "general") -> str:
        """
        Truncate text based on current style settings.

        Args:
            text: Text to potentially truncate
            context: Context hint (result, code, general)

        Returns:
            Original or truncated text
        """
        if not self.current_style.truncate_long_text:
            return text

        max_len = self.current_style.max_result_length
        if context == "code":
            max_len = max_len * 2  # Allow more for code

        if len(text) > max_len:
            return text[:max_len] + f"\n... ({len(text) - max_len} chars truncated)"
        return text

    def format_tool_call(self, tool_name: str, args: dict, result: str) -> str:
        """
        Format a tool call for display based on current style.

        Args:
            tool_name: Name of the tool
            args: Tool arguments
            result: Tool result

        Returns:
            Formatted string for display
        """
        style = self.current_style
        parts = []

        # Tool name (always shown)
        parts.append(f"[bold]{tool_name}[/bold]")

        # Arguments
        if style.show_tool_args and args:
            args_str = ", ".join(f"{k}={repr(v)[:30]}" for k, v in args.items())
            if len(args_str) > 80:
                args_str = args_str[:80] + "..."
            parts.append(f"({args_str})")

        # Result
        if style.show_tool_results and result:
            truncated_result = self.truncate(result, "result")
            parts.append(f"\n  -> {truncated_result}")

        return "".join(parts)

    def format_reasoning(self, text: str, model_id: Optional[str] = None) -> Optional[str]:
        """
        Format reasoning/thinking text based on current style.

        Args:
            text: Reasoning text
            model_id: Optional model identifier

        Returns:
            Formatted string or None if reasoning should be hidden
        """
        if not self.current_style.show_reasoning:
            return None

        prefix = ""
        if self.current_style.show_model_info and model_id:
            prefix = f"[{model_id}] "

        truncated = self.truncate(text, "general")
        return f"{prefix}{truncated}"

    def get_available_styles(self) -> list:
        """Get list of available style names."""
        return list(STYLES.keys())
