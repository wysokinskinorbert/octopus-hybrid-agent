"""
Tool Execution Monitor for timeout guards and progress feedback.
Stage 3 implementation.
"""

import time
from typing import Optional, Callable
from .remediation_components import LiveTimerLabel, ConfirmModal


class ToolExecutionMonitor:
    """Monitors long-running tool executions with timeout prompts."""
    
    def __init__(
        self,
        app,
        tool_name: str,
        command: str = "",
        timeout: int = 300
    ):
        self.app = app
        self.tool_name = tool_name
        self.command = command
        self.timeout = timeout
        self.start_time = time.time()
        self.timer_widget: Optional[LiveTimerLabel] = None
        self.timeout_timer = None
    
    def start(self):
        """Start monitoring and display live timer."""
        # Create timer widget showing elapsed time
        msg = self.command if self.command else self.tool_name
        if len(msg) > 60:
            msg = msg[:57] + "..."
        
        self.timer_widget = LiveTimerLabel(f"⟳ {msg}")
        
        # Mount to activity widget
        try:
            aw = self.app.get_or_create_activity_widget()
            aw.mount(self.timer_widget)
        except Exception:
            pass
        
        # Schedule timeout check
        self.timeout_timer = self.app.set_timer(
            self.timeout,
            self.on_timeout
        )
    
    def on_timeout(self):
        """Called when timeout is reached - prompt user."""
        elapsed = time.time() - self.start_time
        
        self.app.push_screen(
            ConfirmModal(
                title="⏱ Long Running Operation",
                message=f"'{self.tool_name}' has been running for {elapsed:.0f}s.\n\nContinue waiting?",
                confirm_text="Keep Waiting",
                cancel_text="Cancel Operation"
            ),
            callback=self.handle_timeout_choice
        )
    
    def handle_timeout_choice(self, continue_waiting: bool):
        """Handle user's timeout choice."""
        if continue_waiting:
            # Extend timeout by another 5 minutes
            self.timeout_timer = self.app.set_timer(300, self.on_timeout)
            self.app.notify("⏱ Extended timeout by 5 minutes")
        else:
            # Cancel the operation
            try:
                self.app.session.abort()
                self.app.notify("❌ Operation cancelled")
            except Exception as e:
                self.app.notify(f"Failed to cancel: {e}", severity="error")
            self.stop()
    
    def stop(self):
        """Stop monitoring and remove timer widget."""
        if self.timer_widget:
            try:
                self.timer_widget.stop_timer()
                self.timer_widget.remove()
            except Exception:
                pass
            self.timer_widget = None
        
        if self.timeout_timer:
            try:
                self.timeout_timer.stop()
            except Exception:
                pass
            self.timeout_timer = None
    
    def get_elapsed(self) -> float:
        """Get elapsed time in seconds."""
        return time.time() - self.start_time
