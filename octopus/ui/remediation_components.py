"""
UI Components for Error Recovery and Progress Monitoring.
Textual widgets used in remediation stages 2-3.
"""

from textual.screen import ModalScreen
from textual.containers import Vertical, Horizontal
from textual.widgets import Static, Button, Label
from textual.app import ComposeResult
import time


class ErrorRecoveryModal(ModalScreen):
    """Modal screen for error recovery options (Stage 2)."""
    
    CSS = """
    ErrorRecoveryModal {
        align: center middle;
    }
    
    #error-dialog {
        width: 80;
        height: auto;
        max-height: 30;
        border: thick $error;
        background: $surface;
        padding: 1 2;
    }
    
    .error-title {
        text-style: bold;
        color: $error;
        padding-bottom: 1;
    }
    
    .error-content {
        height: auto;
        max-height: 15;
        overflow-y: auto;
        border: solid $panel;
        background: $panel;
        padding: 1;
        margin: 1 0;
    }
    
    .dialog-prompt {
        padding: 1 0;
        text-style: bold;
    }
    
    .dialog-buttons {
        height: 3;
        align: center middle;
    }
    
    .dialog-buttons Button {
        margin: 0 1;
    }
    """
    
    def __init__(self, error_text: str, tool_name: str):
        super().__init__()
        self.error_text = error_text
        self.tool_name = tool_name
    
    def compose(self) -> ComposeResult:
        with Vertical(id="error-dialog"):
            yield Static(f"⚠ Tool Execution Failed: {self.tool_name}", classes="error-title")
            yield Static(self.error_text, classes="error-content")
            yield Static("\nChoose recovery action:", classes="dialog-prompt")
            
            with Horizontal(classes="dialog-buttons"):
                yield Button("🔄 Retry", id="btn_retry", variant="primary")
                yield Button("⏭ Skip", id="btn_skip", variant="default")
                yield Button("❌ Abort Task", id="btn_abort", variant="error")
                yield Button("📋 View Logs", id="btn_logs", variant="default")
    
    def on_button_pressed(self, event: Button.Pressed):
        button_id = event.button.id
        if button_id == "btn_retry":
            self.dismiss("retry")
        elif button_id == "btn_skip":
            self.dismiss("skip")
        elif button_id == "btn_abort":
            self.dismiss("abort")
        elif button_id == "btn_logs":
            self.dismiss("logs")


class LiveTimerLabel(Label):
    """Label that auto-updates to show elapsed time (Stage 3)."""
    
    def __init__(self, message: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.message = message
        self.start_time = time.time()
        self.timer = None
    
    def on_mount(self):
        # Update every 100ms
        self.timer = self.set_interval(0.1, self.update_timer)
    
    def update_timer(self):
        elapsed = time.time() - self.start_time
        
        # Format based on duration
        if elapsed < 60:
            time_str = f"{elapsed:.1f}s"
        else:
            mins = int(elapsed // 60)
            secs = int(elapsed % 60)
            time_str = f"{mins}m {secs}s"
        
        self.update(f"{self.message} ({time_str})")
    
    def stop_timer(self):
        if self.timer:
            self.timer.stop()
            self.timer = None


class ConfirmModal(ModalScreen):
    """Simple confirmation modal for timeout prompts."""
    
    CSS = """
    ConfirmModal {
        align: center middle;
    }
    
    #confirm-dialog {
        width: 60;
        height: auto;
        border: thick $warning;
        background: $surface;
        padding: 1 2;
    }
    
    .confirm-title {
        text-style: bold;
        padding-bottom: 1;
    }
    
    .confirm-message {
        padding: 1 0;
    }
    
    .confirm-buttons {
        height: 3;
        align: center middle;
    }
    
    .confirm-buttons Button {
        margin: 0 1;
    }
    """
    
    def __init__(self, title: str, message: str, confirm_text: str = "Yes", cancel_text: str = "No"):
        super().__init__()
        self.title = title
        self.message = message
        self.confirm_text = confirm_text
        self.cancel_text = cancel_text
    
    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Static(self.title, classes="confirm-title")
            yield Static(self.message, classes="confirm-message")
            
            with Horizontal(classes="confirm-buttons"):
                yield Button(self.confirm_text, id="btn_confirm", variant="primary")
                yield Button(self.cancel_text, id="btn_cancel", variant="default")
    
    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "btn_confirm":
            self.dismiss(True)
        else:
            self.dismiss(False)


class MarkdownModal(ModalScreen):
    """Modal for displaying markdown content (logs, debug info)."""
    
    CSS = """
    MarkdownModal {
        align: center middle;
    }
    
    #markdown-dialog {
        width: 90;
        height: 90%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    
    .markdown-title {
        text-style: bold;
        padding-bottom: 1;
        color: $primary;
    }
    
    .markdown-content {
        height: 1fr;
        overflow-y: auto;
        border: solid $panel;
        background: $panel;
        padding: 1;
    }
    
    .close-button {
        margin-top: 1;
        width: 100%;
    }
    """
    
    def __init__(self, content: str, title: str = "Information"):
        super().__init__()
        self.content = content
        self.title = title
    
    def compose(self) -> ComposeResult:
        with Vertical(id="markdown-dialog"):
            yield Static(self.title, classes="markdown-title")
            yield Static(self.content, classes="markdown-content")
            yield Button("Close", id="btn_close", variant="primary", classes="close-button")
    
    def on_button_pressed(self, event: Button.Pressed):
        self.dismiss()
