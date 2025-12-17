import re
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Input, Static, Label, Button, DataTable, TabbedContent, TabPane, Select, SelectionList, TextArea, LoadingIndicator, Markdown, RichLog
from textual.containers import Vertical, Horizontal, Grid, VerticalScroll

# ... (other imports) ...

class CollapsibleLog(Vertical):
    """Collapsible widget for verbose logs (e.g. shell output)."""
    
    DEFAULT_CSS = """
    CollapsibleLog {
        height: auto;
        margin-top: 1;
        border-left: solid $accent;
    }
    CollapsibleLog .header {
        width: 100%;
        height: 1;
        background: $surface;
        color: $text;
        padding: 0 1;
    }
    CollapsibleLog .header:hover {
        background: $surface-lighten-1;
    }
    CollapsibleLog RichLog {
        height: auto;
        max-height: 20;  /* Limit max height by default */
        min-height: 5;
        background: $surface-darken-2;
        display: none;   /* Hidden by default */
        padding: 0 1;
        border-top: solid $secondary;
    }
    CollapsibleLog.expanded RichLog {
        display: block;
    }
    """
    
    def __init__(self, title: str, **kwargs):
        super().__init__(**kwargs)
        self.title_text = title
        self.is_expanded = False
        self.log_widget = RichLog(markup=True, wrap=True)
        self.header = Static(f"▶ {title}", classes="header")
        
    def compose(self) -> ComposeResult:
        yield self.header
        yield self.log_widget
        
    def on_click(self):
        """Toggle expansion on click."""
        self.is_expanded = not self.is_expanded
        self.toggle_class("expanded")
        icon = "▼" if self.is_expanded else "▶"
        self.header.update(f"{icon} {self.title_text}")
        if self.is_expanded:
            self.log_widget.scroll_end(animate=False)
            
    def write(self, content: str):
        """Append text to the log."""
        self.log_widget.write(content)
        
    def update_status(self, new_title: str):
        """Update header title (e.g. to show status)."""
        self.title_text = new_title
        icon = "▼" if self.is_expanded else "▶"
        self.header.update(f"{icon} {self.title_text}")
from textual.containers import Vertical, Horizontal, Grid, VerticalScroll
from textual.screen import Screen, ModalScreen
from textual.worker import Worker, get_current_worker
from textual import work, on
from textual.reactive import reactive
from textual.coordinate import Coordinate
from rich.syntax import Syntax
from rich.markup import escape
from rich.text import Text

import os
import time
import httpx
from pathlib import Path
from typing import Dict, List, Tuple

from .core.session import OctopusSession
from .core.config_store import ConfigStore, ProviderConfig, RoleConfig, MCPServerConfig
from .core.commands import SlashCommandRegistry
from .ui.remediation_components import ErrorRecoveryModal, LiveTimerLabel, ConfirmModal, MarkdownModal
from .ui.tool_monitor import ToolExecutionMonitor

# Calculate absolute path to CSS to avoid CWD dependency
_CSS_PATH = os.path.join(os.path.dirname(__file__), "ui", "styles.tcss")

# --- CUSTOM WIDGETS ---

class ModeHeader(Static):
    """Displays current session mode (PLAN | EXECUTE | REVIEW) - Claude Code minimal style."""
    DEFAULT_CSS = """
    ModeHeader {
        dock: top;
        height: 1;
        background: #1e1e1e;
        padding: 0 1;
        color: #888888;
    }
    .mode-plan { color: #9b59b6; }
    .mode-execute { color: #007acc; }
    .mode-review { color: #2ecc71; }
    """
    mode = reactive("plan")

    def compose(self) -> ComposeResult:
        mode_text = f"MODE: {self.mode.upper()}"
        yield Label(mode_text, id="mode-label", classes=f"mode-{self.mode}")

    def watch_mode(self, mode: str):
        """Update mode display when mode changes."""
        try:
            label = self.query_one("#mode-label", Label)
            label.update(f"MODE: {mode.upper()}")
            label.remove_class("mode-plan", "mode-execute", "mode-review")
            label.add_class(f"mode-{mode}")
        except Exception:
            pass

class ShellInput(Input):
    """Input with command history support."""
    
    BINDINGS = [
        ("up", "history_up", "Previous command"),
        ("down", "history_down", "Next command"),
    ]
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.history = []
        self.history_index = -1
        self.current_input = ""

    def action_history_up(self):
        if not self.history: return
        if self.history_index == -1:
            self.current_input = self.value
            self.history_index = len(self.history) - 1
        else:
            self.history_index = max(0, self.history_index - 1)
        self.value = self.history[self.history_index]
        self.cursor_position = len(self.value)

    def action_history_down(self):
        if self.history_index == -1: return
        if self.history_index == len(self.history) - 1:
            self.history_index = -1
            self.value = self.current_input
        else:
            self.history_index += 1
            self.value = self.history[self.history_index]
        self.cursor_position = len(self.value)
        
    def add_to_history(self, cmd: str):
        if cmd and (not self.history or self.history[-1] != cmd):
            self.history.append(cmd)
        self.history_index = -1
        self.current_input = ""

class CodeBlock(Vertical):
    """Collapsible Code Block."""
    DEFAULT_CSS = """
    CodeBlock {
        background: $surface-darken-1;
        border: solid $secondary;
        margin: 1 0;
        height: auto;
    }
    CodeBlock > Static {
        padding: 0 1;
        color: $accent;
        text-style: bold;
        height: 1;
        background: $surface-darken-2;
    }
    CodeBlock > #code_view {
        display: none;
        padding: 1;
    }
    CodeBlock.expanded > #code_view {
        display: block;
    }
    """

    def __init__(self, code: str, language: str = "python", **kwargs):
        super().__init__(**kwargs)
        self.code = code
        self.language = language
        self.is_expanded = False

    def compose(self) -> ComposeResult:
        # Header (Click to expand)
        yield Static(f"▶ Click to View Code ({self.language}) - {len(self.code.splitlines())} lines", id="header")
        # Code View (Hidden by default)
        yield Static(Syntax(self.code, self.language, theme="monokai", word_wrap=True), id="code_view")

    def on_click(self):
        self.toggle_class("expanded")
        self.is_expanded = not self.is_expanded
        icon = "▼" if self.is_expanded else "▶"
        self.query_one("#header").update(f"{icon} Click to View Code ({self.language}) - {len(self.code.splitlines())} lines")


class MessageWidget(Vertical):
    """Widget for a single chat message with enhanced styling."""
    DEFAULT_CSS = """
    MessageWidget {
        background: $surface;
        margin-bottom: 1;
        padding: 0;
        border-left: wide $primary;
        height: auto;
    }
    
    .header {
        dock: top;
        background: $surface-darken-1;
        padding: 0 1;
        height: 1;
        color: $text-secondary;
    }
    
    .content-box {
        padding: 1;
        background: $surface;
    }
    
    .code-block {
        margin: 1 0;
        border: solid $secondary;
        background: #1e1e1e;
        padding: 1;
    }
    """

    def __init__(self, role: str, content: str, model_id: str = None, **kwargs):
        super().__init__(**kwargs)
        self.role = role.lower()
        self.content = content
        self.model_id = model_id

    def compose(self):
        # Role prefixes (Claude Code style)
        role_prefixes = {
            "architect": "[arch]",
            "developer": "[dev]",
            "reviewer": "[✓]",
            "user": "[user]",
            "system": "[sys]"
        }
        
        role_colors = {
            "architect": "#888888",  # Muted
            "developer": "#007acc",  # Primary blue
            "reviewer": "#2ecc71",   # Success green
            "user": "#007acc",       # Primary blue
            "system": "#888888"      # Muted
        }
        
        color = role_colors.get(self.role, "#888888")
        prefix = role_prefixes.get(self.role, f"[{self.role}]")
        
        # Strip whitespace to avoid extra vertical gaps
        content = self.content.strip()
        
        # Format: [role] content
        # Optionally show model in verbose mode (can be toggled later)
        full_content = f"{prefix} {content}"
        
        # Render as simple markdown without header badge
        yield Markdown(full_content)


# --- TODO WIDGETS (Claude Code Style) ---

class TodoItem(Static):
    """Single TODO item with checkbox and status."""
    DEFAULT_CSS = """
    TodoItem {
        height: 1;
        padding: 0 1;
    }
    TodoItem.todo-pending {
        color: $text-muted;
    }
    TodoItem.todo-in_progress {
        color: yellow;
        text-style: bold;
    }
    TodoItem.todo-completed {
        color: $success;
    }
    """

    def __init__(self, todo_id: str, content: str, status: str = "pending", **kwargs):
        super().__init__(**kwargs)
        self.todo_id = todo_id
        self.content = content
        self.status = status
        self.add_class(f"todo-{status}")

    def compose(self) -> ComposeResult:
        icons = {"pending": "☐", "in_progress": "🔧", "completed": "✅"}
        icon = icons.get(self.status, "☐")
        yield Label(f"{icon} {self.content[:35]}{'...' if len(self.content) > 35 else ''}")

    def update_status(self, new_status: str):
        self.remove_class(f"todo-{self.status}")
        self.status = new_status
        self.add_class(f"todo-{new_status}")
        icons = {"pending": "☐", "in_progress": "🔧", "completed": "✅"}
        icon = icons.get(self.status, "☐")
        self.query_one(Label).update(f"{icon} {self.content[:35]}{'...' if len(self.content) > 35 else ''}")


class TodoWidget(Vertical):
    """Claude Code style TODO panel with progress bar."""
    DEFAULT_CSS = """
    TodoWidget {
        width: 30;
        height: 100%;
        border-left: solid $accent;
        padding: 1;
        background: $surface-darken-1;
    }
    TodoWidget #todo-header {
        text-style: bold;
        color: $accent;
        height: 1;
        margin-bottom: 1;
    }
    TodoWidget #todo-list {
        height: auto;
        max-height: 20;
    }
    TodoWidget #todo-progress {
        height: 1;
        margin-top: 1;
        color: $text-muted;
    }
    TodoWidget #todo-progress-bar {
        height: 1;
        margin-top: 0;
        color: $accent;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.todos: Dict[str, TodoItem] = {}

    def compose(self) -> ComposeResult:
        yield Label("📋 TODO", id="todo-header")
        yield VerticalScroll(id="todo-list")
        yield Static("Progress: 0/0 (0%)", id="todo-progress")
        yield Static("░░░░░░░░░░░░░░░░░░░░", id="todo-progress-bar")  # Wizualny progress bar

    def add_todo(self, todo_id: str, content: str, status: str = "pending"):
        if todo_id in self.todos:
            return  # Already exists
        item = TodoItem(todo_id, content, status)
        self.todos[todo_id] = item
        try:
            self.query_one("#todo-list").mount(item)
        except Exception:
            pass
        self._update_progress()

    def update_todo(self, todo_id: str, status: str):
        if todo_id in self.todos:
            self.todos[todo_id].update_status(status)
            self._update_progress()

    def clear_todos(self):
        for item in self.todos.values():
            item.remove()
        self.todos.clear()
        self._update_progress()

    def _update_progress(self):
        total = len(self.todos)
        done = sum(1 for t in self.todos.values() if t.status == "completed")
        pct = int((done / total * 100)) if total > 0 else 0
        bar_filled = int(pct / 5)  # 20 char bar
        bar = "█" * bar_filled + "░" * (20 - bar_filled)
        try:
            self.query_one("#todo-progress").update(f"Progress: {done}/{total} ({pct}%)")
            self.query_one("#todo-progress-bar").update(bar)
        except Exception:
            pass


# --- ITERATION PROGRESS WIDGET (Claude Code Style) ---

class IterationProgress(Static):
    """Shows iteration progress with visual bar for delegated tasks."""

    DEFAULT_CSS = """
    IterationProgress {
        height: 3;
        padding: 0 1;
        background: $surface-darken-2;
        margin: 1 0;
        border-left: wide $secondary;
    }
    IterationProgress .iter-header {
        color: $warning;
        text-style: bold;
    }
    IterationProgress .iter-bar {
        color: $accent;
    }
    """

    def __init__(self, role: str, model: str, current: int = 1, total: int = 10, **kwargs):
        super().__init__(**kwargs)
        self.role = role
        self.model = model
        self.current = current
        self.total = total

    def compose(self) -> ComposeResult:
        pct = int((self.current / self.total) * 100) if self.total > 0 else 0
        bar_filled = int(pct / 5)  # 20 char bar
        bar = "█" * bar_filled + "░" * (20 - bar_filled)

        yield Label(f"[yellow]{self.role}[/yellow] ({self.model}) iteration {self.current}/{self.total}", classes="iter-header")
        yield Label(f"[cyan]{bar}[/cyan] {pct}%", classes="iter-bar")

    def update_progress(self, current: int, total: int = None):
        """Update iteration progress."""
        self.current = current
        if total is not None:
            self.total = total
        pct = int((self.current / self.total) * 100) if self.total > 0 else 0
        bar_filled = int(pct / 5)
        bar = "█" * bar_filled + "░" * (20 - bar_filled)

        try:
            self.query_one(".iter-header", Label).update(
                f"[yellow]{self.role}[/yellow] ({self.model}) iteration {self.current}/{self.total}"
            )
            self.query_one(".iter-bar", Label).update(f"[cyan]{bar}[/cyan] {pct}%")
        except Exception:
            pass


class EnhancedStatusBar(Horizontal):
    """Claude Code style status bar with timer and per-model stats."""
    DEFAULT_CSS = """
    EnhancedStatusBar {
        dock: bottom;
        height: 1;
        background: $surface-darken-2;
        padding: 0 1;
    }
    EnhancedStatusBar .status-section {
        width: auto;
        padding: 0 1;
    }
    EnhancedStatusBar #cwd-label {
        color: $text-muted;
    }
    EnhancedStatusBar #timer-label {
        color: $accent;
    }
    EnhancedStatusBar #model-stats {
        color: $text;
    }
    """

    def __init__(self, cwd: str = ".", **kwargs):
        super().__init__(**kwargs)
        self.cwd = cwd
        self.start_time = time.time()
        self.model_stats: Dict[str, int] = {}
        self.current_model = "N/A"
        self.git_branch = self._get_git_branch()

    def _get_git_branch(self) -> str:
        """Get current git branch name."""
        try:
            import subprocess
            result = subprocess.run(
                ['git', 'branch', '--show-current'],
                cwd=self.cwd,
                capture_output=True,
                text=True,
                timeout=1
            )
            if result.returncode == 0:
                return result.stdout.strip() or "main"
        except Exception:
            pass
        return "N/A"

    def compose(self) -> ComposeResult:
        # Yield labels directly - EnhancedStatusBar is already Horizontal
        yield Label(f"📁 {self.cwd}", id="cwd-label")
        yield Label(f"🔀 {self.git_branch}", id="git-label")
        yield Label("⏱ 00:00:00", id="timer-label")
        yield Label("🧠 N/A", id="model-label")
        yield Label("", id="model-stats")

    def update_timer(self):
        """Update session timer display."""
        elapsed = int(time.time() - self.start_time)
        mins, secs = divmod(elapsed, 60)
        hours, mins = divmod(mins, 60)
        if hours > 0:
            timer_str = f"⏱ {hours:02d}:{mins:02d}:{secs:02d}"
        else:
            timer_str = f"⏱ {mins:02d}:{secs:02d}"
        try:
            self.query_one("#timer-label").update(timer_str)
        except Exception:
            pass

    def on_mount(self):
        """Start refresh timer for status bar updates (300ms)."""
        self.set_interval(0.3, self.refresh_display)

    def refresh_display(self):
        """Refresh timer display (called every 300ms)."""
        self.update_timer()

    def update_model_stats(self, stats: Dict[str, int]):
        """Update per-model token statistics."""
        self.model_stats.update(stats)
        parts = []
        total = 0

        # Format each model's tokens
        colors = ["cyan", "magenta", "green", "yellow", "blue"]
        for i, (model, tokens) in enumerate(self.model_stats.items()):
            color = colors[i % len(colors)]
            short_name = model.split("/")[-1][:12]
            if tokens >= 1000:
                parts.append(f"[{color}]{short_name}[/{color}]: {tokens/1000:.1f}k")
            else:
                parts.append(f"[{color}]{short_name}[/{color}]: {tokens}")
            total += tokens

        # Add total
        if total >= 1000:
            parts.append(f"[bold]Total: {total/1000:.1f}k[/bold]")
        else:
            parts.append(f"[bold]Total: {total}[/bold]")

        try:
            self.query_one("#model-stats").update(" | ".join(parts))
        except Exception:
            pass

    def update_cwd(self, new_cwd: str):
        """Update current working directory display."""
        self.cwd = new_cwd
        try:
            self.query_one("#cwd-label").update(f"📁 {new_cwd}")
        except Exception:
            pass


class ActivityWidget(Vertical):
    """Live Activity Log (Modern, Minimalist)."""
    DEFAULT_CSS = """
    ActivityWidget {
        height: auto;
        margin: 1 0;
        border-left: wide $accent;
        background: $surface-darken-1;
        padding: 0 1;
    }
    .step {
        height: auto;
        color: $text-muted;
        margin-top: 0;
    }
    .step-running {
        color: $accent;
        text-style: bold;
    }
    .step-done {
        color: $success;
    }
    .step-error {
        color: $error;
    }
    .step-reasoning {
        color: $text-muted;
        text-style: italic;
        margin-left: 2;
        border-left: solid $secondary-darken-2;
        padding-left: 1;
    }
    LoadingIndicator {
        height: 1;
        display: none;
    }
    .running LoadingIndicator {
        display: block;
    }
    .streaming {
        color: $text-muted;
        text-style: italic;
    }
    .step-arg {
        color: $text-muted;
        margin-left: 4;
        height: auto;
    }
    """

    def __init__(self, show_timestamps: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.step_counter = 0
        self.current_step_id = None
        self.step_texts = {}  # Przechowuj oryginalne teksty kroków
        self.show_timestamps = show_timestamps
        # Streaming buffer (fix dla rozciągniętego tekstu)
        self.streaming_buffer = ""
        self.streaming_label = None
        self._streaming_active = False

    def add_step(self, text: str, tool_name: str = None, arguments: dict = None) -> str:
        """Add a new step (Claude Code minimal style - single line)."""
        self.step_counter += 1
        step_id = f"step_{self.step_counter}"
        self.step_texts[step_id] = text
        self.current_step_id = step_id

        # Determine display text
        is_shell = False
        display_text = text
        if tool_name == "run_shell_command" and arguments and "command" in arguments:
            is_shell = True
            cmd = arguments["command"]
            if len(cmd) > 80: cmd = cmd[:77] + "..."
            display_text = f"⟳ {cmd}"
        elif tool_name:
            display_text = f"⟳ {tool_name}..."
        else:
            display_text = f"⟳ {text}..."

        # Use CollapsibleLog for shell commands
        if is_shell:
            widget = CollapsibleLog(display_text, id=step_id, classes="step step-running")
            self.mount(widget)
            self.call_after_refresh(self.scroll_end)
            return step_id

        self.mount(Label(display_text, id=step_id, classes="step step-running"))
        return step_id

    def update_step(self, step_id: str, suffix: str, status: str = "done"):
        """Aktualizuje krok zachowując oryginalny tekst i dodając suffix."""
        try:
            widget = self.query_one(f"#{step_id}")
            icon = "✓" if status == "done" else "✗"
            cls = "step-done" if status == "done" else "step-error"

            widget.remove_class("step-running")
            widget.add_class(cls)
            
            try:
                 self.stop_tool_indicator()
            except: pass

            if isinstance(widget, CollapsibleLog):
                # Update header title
                # Extract cmd from original title if possible, or just use suffix
                # We kept original text in step_texts[step_id]
                original = self.step_texts[step_id]
                
                # Logic to format final status
                clean_status = suffix
                # Check for exit code pattern
                if "Exit 0" in suffix:
                     clean_status = "Done"
                
                # Construct new title
                if "⟳" in widget.title_text:
                     base_title = widget.title_text.replace("⟳ ", "").replace("...", "")
                else:
                     base_title = "Command"
                     
                new_title = f"{base_title} ({clean_status})"
                widget.update_status(new_title)
                
            elif isinstance(widget, Label):
                # Standard label update
                original = self.step_texts.get(step_id, "Step")
                if status == "done":
                    widget.update(f"{icon} {original} {suffix}")
                else:
                    widget.update(f"{icon} {original} ({suffix})")

        except Exception:
            pass # Widget might be gone

    def log(self, text: str):
        """Add a simple log line (info)."""
        self.mount(Label(f"  {text}", classes="step"))

    def log_reasoning(self, text: str, model: str = None):
        """Add detailed reasoning/thought block."""
        prefix = f"[{model}] " if model else ""
        self.mount(Label(f"{prefix}{text}", classes="step step-reasoning"))
    
    def log_thinking(self, model: str):
        """Show model is thinking/generating."""
        self.mount(Label(f"💭 Thinking ({model})...", classes="step step-running"))

    def add_detail(self, content: str):
        """Add expandable detail block (e.g. diffs, logs)."""
        # Simple Markdown rendering for diffs/logs
        self.mount(Markdown(content, classes="step"))

    # ==================== Streaming Methods (fix dla rozciągniętego tekstu) ====================

    def start_streaming(self, prefix: str = "") -> str:
        """Rozpocznij streaming - utwórz pojedynczy label zamiast wielu."""
        self.streaming_buffer = prefix
        self._streaming_active = True
        # Utwórz jeden reużywalny label dla całego strumienia
        self.streaming_label = Label(prefix or "...", id="streaming_output", classes="step streaming")
        self.mount(self.streaming_label)
        return "streaming_output"

    def append_streaming(self, text: str):
        """Dodaj tekst do istniejącego labela (BEZ tworzenia nowego)."""
        if not self._streaming_active:
            self.start_streaming()

        self.streaming_buffer += text

        # Filtruj XML tool_code przed wyświetleniem
        import re
        clean_text = re.sub(r'</?tool_code>', '', self.streaming_buffer)
        clean_text = re.sub(r'<tool_code>.*?</tool_code>', '[tool call]', clean_text, flags=re.DOTALL)

        # Ogranicz długość wyświetlanego tekstu
        display_text = clean_text
        if len(display_text) > 500:
            display_text = "..." + display_text[-500:]

        if self.streaming_label:
            try:
                self.streaming_label.update(display_text)
            except Exception:
                pass

    def end_streaming(self) -> str:
        """Zakończ streaming i zwróć pełny tekst."""
        result = self.streaming_buffer
        self.streaming_buffer = ""
        self._streaming_active = False

        # Zamień label streaming na finalny
        if self.streaming_label:
            try:
                self.streaming_label.set_classes("step step-done")
            except Exception:
                pass
        self.streaming_label = None
        return result

    def is_streaming(self) -> bool:
        """Sprawdź czy streaming jest aktywny."""
        return self._streaming_active


class QuestionModal(ModalScreen):
    """Modal for multiple-choice questions."""
    CSS = """
    QuestionModal { align: center middle; }
    #q_dialog {
        width: 80%;
        max-width: 100;
        height: auto;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #q_title {
        text-style: bold;
        margin-bottom: 1;
        color: $secondary;
        width: 100%;
        text-align: center;
    }
    #q_list {
        height: auto;
        max-height: 15;
        border: solid $primary;
        margin: 1 0;
        overflow-y: auto;
    }
    .btn-group {
        align: center middle;
        height: auto;
        margin-top: 1;
    }
    .btn-group Button {
        margin: 0 1;
        min-width: 10;
    }
    .action-row {
        align: center middle;
        margin-top: 1;
    }
    """

    def __init__(self, question: str, options: list):
        super().__init__()
        self.question = question
        self.options = options

    def compose(self) -> ComposeResult:
        with Vertical(id="q_dialog"):
            yield Label(f"❓ {self.question}", id="q_title")
            
            # Simple choice (<= 3 options): Buttons
            if len(self.options) <= 3 and all(len(o) < 20 for o in self.options):
                with Horizontal(classes="btn-group"):
                    for opt in self.options:
                        # Use option text as ID (sanitized) or just handle by event
                        yield Button(opt, variant="primary" if opt.lower() in ["yes", "confirm"] else "default", id=f"opt_{self.options.index(opt)}")
            
            # Complex choice: Selection List
            else:
                yield SelectionList(*[(opt, opt) for opt in self.options], id="q_list")
                with Horizontal(classes="action-row"):
                    yield Button("Submit Selection", variant="success", id="submit")

    @on(Button.Pressed)
    def on_btn(self, event: Button.Pressed):
        btn_id = event.button.id
        if btn_id == "submit":
            # Handle list submission
            sl = self.query_one("#q_list")
            selected = sl.selected
            if selected:
                self.dismiss(", ".join(selected))
        elif btn_id and btn_id.startswith("opt_"):
            # Handle quick button click
            idx = int(btn_id.split("_")[1])
            if 0 <= idx < len(self.options):
                self.dismiss(self.options[idx])


# --- FORMS (MODALS) ---

def fetch_ollama_models_from_api(base_url: str = "http://localhost:11434") -> List[str]:
    """Pobiera listę modeli z Ollama API."""
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(f"{base_url}/api/tags")
            if response.status_code == 200:
                data = response.json()
                models = data.get("models", [])
                return [m["name"] for m in models]
    except Exception:
        pass
    return []

def fetch_remote_models(provider_type: str, base_url: str, api_key_env: str) -> List[str]:
    """Generic fetcher for cloud providers using httpx."""
    try:
        # Default env vars if not provided
        if not api_key_env:
            if provider_type == "openai": api_key_env = "OPENAI_API_KEY"
            elif provider_type == "anthropic": api_key_env = "ANTHROPIC_API_KEY"
            elif provider_type == "deepseek": api_key_env = "DEEPSEEK_API_KEY"
            elif provider_type == "openrouter": api_key_env = "OPENROUTER_API_KEY"

        api_key = os.environ.get(api_key_env, "")
        if not api_key:
            return [f"Error: Env var '{api_key_env}' missing/empty"]

        headers = {"Authorization": f"Bearer {api_key}"}
        url = ""
        
        # 1. OpenAI / DeepSeek / Compatible
        if provider_type in ["openai", "deepseek", "openrouter"]:
            # Determine Base URL
            if not base_url:
                if provider_type == "openai": base_url = "https://api.openai.com/v1"
                elif provider_type == "deepseek": base_url = "https://api.deepseek.com"
            
            # Ensure URL structure
            url = base_url.rstrip("/")
            if not url.endswith("/models"):
                if not url.endswith("/v1") and provider_type == "openai": 
                    url += "/v1"
                url += "/models"

            with httpx.Client(timeout=10.0) as client:
                resp = client.get(url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    return sorted([item["id"] for item in data.get("data", [])])
                else:
                    return [f"API Error {resp.status_code}"]

        # 2. Anthropic
        elif provider_type == "anthropic":
            url = "https://api.anthropic.com/v1/models"
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01"
            }
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    return sorted([item["id"] for item in data.get("data", [])])
                else:
                    return [f"API Error {resp.status_code}"]

    except Exception as e:
        return [f"Connection Error: {str(e)}"]
    
    return []

def scan_ollama_models_directory(models_path: str) -> List[str]:
    """Skanuje lokalny katalog Ollama w poszukiwaniu modeli."""
    models = []
    path = Path(models_path).expanduser()

    # Sprawdź czy to katalog główny Ollama (~/.ollama/models) czy podkatalog
    manifests_path = path / "manifests"
    if not manifests_path.exists():
        # Może użytkownik podał ścieżkę wyżej lub do blobs
        parent_manifests = path.parent / "manifests"
        if parent_manifests.exists():
            manifests_path = parent_manifests
        else:
            # Spróbuj szukać w katalogu nadrzędnym
            grandparent_manifests = path.parent.parent / "manifests"
            if grandparent_manifests.exists():
                manifests_path = grandparent_manifests

    if manifests_path.exists():
        # Struktura: manifests/registry.ollama.ai/library/{model}/{tag}
        try:
            for registry_dir in manifests_path.iterdir():
                if registry_dir.is_dir():
                    library_path = registry_dir / "library"
                    if library_path.exists():
                        for model_dir in library_path.iterdir():
                            if model_dir.is_dir():
                                model_name = model_dir.name
                                # Znajdź tagi
                                for tag_file in model_dir.iterdir():
                                    if tag_file.is_file():
                                        tag = tag_file.name
                                        full_name = f"{model_name}:{tag}" if tag != "latest" else model_name
                                        models.append(full_name)
        except Exception:
            pass

    # Jeśli nie znaleziono w manifests, szukaj plików .gguf w katalogu
    if not models:
        try:
            for file in path.rglob("*.gguf"):
                models.append(file.stem)
            for file in path.rglob("*.bin"):
                if "model" in file.name.lower():
                    models.append(file.stem)
        except Exception:
            pass

    return sorted(set(models))


class ProviderModal(ModalScreen):
    """Form to Add/Edit Provider."""
    CSS = """
    ProviderModal { align: center middle; }
    #dialog {
        width: 80;
        height: 85%;
        border: thick $background 80%;
        background: $surface;
        padding: 1 2;
    }
    #dialog-scroll {
        height: 1fr;
        margin-bottom: 1;
    }
    .form-row {
        height: auto;
        margin-bottom: 1;
    }
    .form-row Label {
        width: 100%;
        height: 1;
        margin-bottom: 0;
    }
    .form-row Input, .form-row Select {
        width: 100%;
    }
    .hidden { display: none; }
    .ollama-section {
        border: solid $primary-darken-2;
        padding: 1;
        margin: 1 0;
    }
    .ollama-section.hidden { display: none; }
    .buttons-row {
        height: auto;
        margin-top: 1;
        align: center middle;
    }
    .buttons-row Button {
        margin: 0 1;
    }
    #models_list {
        height: 15;
        margin: 1 0;
        border: solid $accent;
        overflow-y: auto;
    }
    #models_list.hidden { display: none; }
    #models_label {
        margin-top: 1;
        color: $success;
    }
    #models_label.hidden { display: none; }
    #main_buttons {
        dock: bottom;
        height: auto;
        padding: 1;
        background: $surface;
        border-top: solid $primary-darken-2;
    }
    """

    def __init__(self, provider: ProviderConfig = None):
        super().__init__()
        self.provider = provider
        self.is_edit = provider is not None
        self._loading_models = False

    def compose(self) -> ComposeResult:
        # Wartości początkowe
        initial_model = self.provider.default_model if self.is_edit else "gpt-4o"
        initial_type = self.provider.type if self.is_edit else "openai"
        initial_base_url = self.provider.base_url if self.is_edit else ""

        with Vertical(id="dialog"):
            yield Label("Edit Provider" if self.is_edit else "New Provider", classes="title")

            with VerticalScroll(id="dialog-scroll"):
                # Name
                with Vertical(classes="form-row"):
                    yield Label("Name:")
                    yield Input(
                        value=self.provider.name if self.is_edit else "",
                        id="name",
                        disabled=self.is_edit
                    )

                # Type
                with Vertical(classes="form-row"):
                    yield Label("Type:")
                    yield Select.from_values(
                        ["openai", "anthropic", "ollama", "deepseek"],
                        value=initial_type,
                        id="type"
                    )

                # Base URL
                with Vertical(classes="form-row"):
                    yield Label("Base URL:")
                    yield Input(
                        value=initial_base_url,
                        placeholder="http://localhost:11434",
                        id="base_url"
                    )

                # Default Model (Changed to Select)
                with Vertical(classes="form-row"):
                    yield Label("Default Model:")
                    yield Select([("", "")], value="", id="model_select", prompt="Select or fetch models below", allow_blank=True)

                # API Key Env
                with Vertical(classes="form-row"):
                    yield Label("API Key Env:")
                    yield Input(
                        value=self.provider.api_key_env or "",
                        placeholder="OPENAI_API_KEY",
                        id="api_key"
                    )

                # Sekcja Ollama - ukryta domyślnie (pokazywana gdy type=ollama)
                initial_ollama_path = ""
                if self.is_edit and hasattr(self.provider, 'ollama_models_path') and self.provider.ollama_models_path:
                    initial_ollama_path = self.provider.ollama_models_path

                with Vertical(classes="ollama-section hidden", id="ollama_section"):
                    yield Label("Ollama - Lokalne modele:", classes="title")

                    with Vertical(classes="form-row"):
                        yield Label("Katalog modeli Ollama (opcjonalnie):")
                        yield Input(
                            value=initial_ollama_path,
                            placeholder="~/.ollama/models lub zostaw puste dla API",
                            id="ollama_models_path"
                        )

                    with Horizontal(classes="buttons-row"):
                        yield Button("Pobierz z API", id="fetch_api", variant="primary")
                        yield Button("Skanuj katalog", id="fetch_dir", variant="default")

                    # Logic to pre-populate models list if available in config
                    initial_models = []
                    is_hidden = "hidden"
                    if self.is_edit and hasattr(self.provider, 'available_models') and self.provider.available_models:
                        initial_models = self.provider.available_models
                        is_hidden = ""
                    
                    yield Label(f"Dostępne modele (zapisano {len(initial_models)}):", id="models_label", classes=is_hidden)
                    
                    # Create SelectionList and populate immediately if we have data
                    sl = SelectionList(id="models_list", classes=is_hidden)
                    for m in initial_models:
                        sl.add_option((m, m))
                    yield sl

            # Przyciski na dole - zawsze widoczne
            with Horizontal(id="main_buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Save", variant="success", id="save")

    def on_mount(self):
        """Po zamontowaniu - sprawdź czy pokazać przycisk Ollama."""
        self._update_ui_for_type()
        
        # Populate Default Model Select
        model_select = self.query_one("#model_select", Select)
        options = []
        current_default = self.provider.default_model if self.is_edit else "gpt-4o"
        
        # Add cached models
        if self.is_edit and self.provider.available_models:
            options.extend(self.provider.available_models)
        
        # Always ensure current default is in options
        if current_default and current_default not in options:
            options.insert(0, current_default)
            
        # Deduplicate
        unique_opts = list(dict.fromkeys(options))
        model_select.set_options([(o, o) for o in unique_opts])
        model_select.value = current_default

    @on(Select.Changed, "#type")
    def on_type_changed(self, event: Select.Changed):
        """Reaguj na zmianę typu providera."""
        self._update_ui_for_type()
        
        # Logic to clear/restore models based on type change
        new_type = event.value
        original_type = self.provider.type if self.is_edit else None
        
        models_list = self.query_one("#models_list", SelectionList)
        models_label = self.query_one("#models_label", Label)
        model_select = self.query_one("#model_select", Select)
        
        if self.is_edit and new_type == original_type and self.provider.available_models:
            # Restore original models
            models_list.clear_options()
            for m in self.provider.available_models:
                models_list.add_option((m, m))
            
            models_label.remove_class("hidden")
            models_label.update(f"Dostępne modele (zapisano {len(self.provider.available_models)}):")
            models_list.remove_class("hidden")
            
            # Restore default model in dropdown
            opts = [(m, m) for m in self.provider.available_models]
            if self.provider.default_model and self.provider.default_model not in self.provider.available_models:
                opts.insert(0, (self.provider.default_model, self.provider.default_model))
            model_select.set_options(opts)
            model_select.value = self.provider.default_model
            
        else:
            # Clear models because type changed (incompatible)
            models_list.clear_options()
            models_label.add_class("hidden")
            models_list.add_class("hidden")
            
            # Reset dropdown
            model_select.set_options([("", "")]) # Dummy to prevent crash
            model_select.value = ""

    def _update_ui_for_type(self):
        """Aktualizuj UI na podstawie wybranego typu."""
        provider_type = self.query_one("#type", Select).value
        ollama_section = self.query_one("#ollama_section", Vertical)
        base_url_input = self.query_one("#base_url", Input)
        
        # Buttons
        fetch_api_btn = self.query_one("#fetch_api", Button)
        fetch_dir_btn = self.query_one("#fetch_dir", Button)

        if provider_type == "ollama":
            # Pokaż sekcję Ollama
            ollama_section.remove_class("hidden")
            fetch_dir_btn.remove_class("hidden")
            fetch_api_btn.label = "Pobierz z Ollama API"
            
            base_url_input.placeholder = "http://localhost:11434"
            if not base_url_input.value:
                base_url_input.value = "http://localhost:11434"
        else:
            # Ukryj sekcję Ollama (katalog)
            ollama_section.add_class("hidden")
            fetch_dir_btn.add_class("hidden") # Hide directory scan for cloud
            fetch_api_btn.label = "Pobierz listę modeli z Chmury"
            
            base_url_input.placeholder = "Opcjonalnie - własny endpoint API"

    @on(Button.Pressed, "#fetch_api")
    def on_fetch_from_api(self):
        """Pobierz modele z API Ollama."""
        if self._loading_models:
            return
        self._loading_models = True
        self._load_models_from_api()

    @on(Button.Pressed, "#fetch_dir")
    def on_fetch_from_dir(self):
        """Skanuj katalog w poszukiwaniu modeli."""
        if self._loading_models:
            return
        self._loading_models = True
        self._load_models_from_directory()

    @work(thread=True)
    def _load_models_from_api(self):
        """Asynchronicznie pobierz modele z API (Ollama lub Chmura)."""
        try:
            provider_type = self.query_one("#type", Select).value
            base_url = self.query_one("#base_url", Input).value
            
            models = []
            source_label = "API"

            if provider_type == "ollama":
                # Old logic for Ollama
                url = base_url or "http://localhost:11434"
                models = fetch_ollama_models_from_api(url)
                source_label = "Ollama API"
            else:
                # New logic for Cloud
                api_key_env = self.query_one("#api_key", Input).value
                models = fetch_remote_models(provider_type, base_url, api_key_env)
                source_label = f"{provider_type.capitalize()} API"

            self.app.call_from_thread(self._on_models_loaded, models, source_label)
        finally:
            self._loading_models = False

    @work(thread=True)
    def _load_models_from_directory(self):
        """Asynchronicznie skanuj katalog modeli."""
        try:
            models_path = self.query_one("#ollama_models_path", Input).value
            if not models_path:
                # Domyślna ścieżka Ollama
                models_path = os.path.expanduser("~/.ollama/models")
            models = scan_ollama_models_directory(models_path)
            self.app.call_from_thread(self._on_models_loaded, models, "katalog")
        finally:
            self._loading_models = False

    def _on_models_loaded(self, models: List[str], source: str = ""):
        """Callback po pobraniu modeli - wyświetl listę wyboru."""
        models_list = self.query_one("#models_list", SelectionList)
        models_label = self.query_one("#models_label", Label)
        model_select = self.query_one("#model_select", Select)

        # 1. Update scanning list (checkboxes)
        models_list.clear_options()
        
        if models:
            for model in models:
                models_list.add_option((model, model))
            
            models_label.remove_class("hidden")
            models_label.update(f"Znaleziono {len(models)} modeli ({source}):")
            models_list.remove_class("hidden")

            # 2. Update Default Model Dropdown
            # Keep current selection if valid
            current = model_select.value
            # Create list of tuples (label, value)
            opts = [(m, m) for m in models]
            
            # Ensure current is present to avoid clearing it
            if current and current not in models:
                opts.insert(0, (current, current))
            
            model_select.set_options(opts)
            
            # If nothing selected, pick first
            if not current and opts:
                model_select.value = opts[0][0]

        else:
            # Ukryj listę i pokaż komunikat
            models_label.remove_class("hidden")
            models_label.update(f"Nie znaleziono modeli ({source}) - sprawdź ustawienia")
            models_list.add_class("hidden")

    @on(SelectionList.SelectedChanged, "#models_list")
    def on_model_selected(self, event: SelectionList.SelectedChanged):
        """Gdy użytkownik wybierze model z listy."""
        selected = event.selection_list.selected
        if selected:
            # Weź ostatnio wybrany model
            model_name = list(selected)[-1]
            model_select = self.query_one("#model_select", Select)
            
            # Check if option exists in Select, if not add it temporary?
            # Actually Select usually crashes if value not in options.
            # But options should be sync'd by _on_models_loaded.
            # If manual scan, we might need to add it.
            
            # Safe set:
            try:
                model_select.value = model_name
            except Exception:
                pass

    @on(Button.Pressed, "#cancel")
    def cancel(self):
        self.dismiss(None)

    @on(Button.Pressed, "#save")
    def save(self):
        name = self.query_one("#name", Input).value
        if not name:
            return

        # Get value from Select
        default_model = self.query_one("#model_select", Select).value or ""
        provider_type = self.query_one("#type", Select).value

        # Pobierz ścieżkę modeli Ollama jeśli typ to ollama
        ollama_models_path = None
        if provider_type == "ollama":
            ollama_path_value = self.query_one("#ollama_models_path", Input).value
            # Save if not empty, otherwise None
            if ollama_path_value:
                ollama_models_path = ollama_path_value

        # Collect models from the list if present
        collected_models = []
        try:
            models_list = self.query_one("#models_list", SelectionList)
            # Access internal options to get all items, not just selected
            for idx in range(models_list.option_count):
                opt = models_list.get_option_at_index(idx)
                collected_models.append(opt.value)
        except Exception:
            pass # List might be hidden or empty

        new_conf = ProviderConfig(
            name=name,
            type=provider_type,
            base_url=self.query_one("#base_url", Input).value or None,
            default_model=default_model,
            api_key_env=self.query_one("#api_key", Input).value or None,
            ollama_models_path=ollama_models_path,
            available_models=collected_models
        )
        self.dismiss(new_conf)


class RoleModal(ModalScreen):
    """Form to Add/Edit Role."""
    CSS = """
    RoleModal { align: center middle; }
    #dialog { width: 80; height: 80%; border: thick $background 80%; background: $surface; overflow-y: auto; }
    .field { margin: 1; }
    """

    def __init__(self, role: RoleConfig = None, providers_map: dict = {}, mcp_servers: list = [], available_tools: list = []):
        super().__init__()
        self.role = role
        self.is_edit = role is not None
        self.providers_map = providers_map
        self.mcp_servers = mcp_servers
        self.available_tools = available_tools

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Edit Role" if self.is_edit else "New Role", classes="title")
            
            yield Label("Name:")
            yield Input(value=self.role.name if self.is_edit else "", id="name", disabled=self.is_edit)
            
            yield Label("Provider:")
            prov_names = list(self.providers_map.keys())
            
            # Safety: If role has a provider not in current map (e.g. deleted), add it to allow viewing/changing
            current_prov = self.role.provider_name if self.is_edit else None
            if current_prov and current_prov not in prov_names:
                prov_names.append(current_prov)
                
            yield Select.from_values(prov_names, value=current_prov, id="provider")
            
            yield Label("Model ID:")
            # Initial model value handled in on_mount
            yield Select([("", "")], value="", id="model", prompt="Select Provider first", allow_blank=True)
            yield Input(placeholder="Wpisz nazwę modelu (np. gpt-4-32k)...", id="custom_model_input", classes="hidden")
            
            yield Label("System Prompt:")
            yield TextArea(self.role.system_prompt if self.is_edit else "You are a helpful assistant.", id="prompt")
            
            yield Label("Active MCP Servers:")
            selected_mcp = self.role.active_mcp_servers if self.is_edit else []
            mcp_options = [(s, s) for s in self.mcp_servers]
            mcp_sl = SelectionList(*mcp_options, id="mcp_list")
            if self.is_edit:
                for s in selected_mcp:
                    if s in self.mcp_servers:
                        mcp_sl.select(s)
            yield mcp_sl

            yield Label("Allowed Tools:")
            selected_tools = self.role.allowed_tools if self.is_edit else []
            tool_options = [(t, t) for t in self.available_tools]
            tool_sl = SelectionList(*tool_options, id="tools_list")
            if self.is_edit:
                for t in selected_tools:
                    if t in self.available_tools:
                        tool_sl.select(t)
            yield tool_sl

            with Horizontal():
                yield Button("Cancel", id="cancel")
                yield Button("Save", variant="primary", id="save")

    def on_mount(self):
        """Initialize model options based on current provider."""
        if self.is_edit and self.role.provider_name:
            self._update_model_options(self.role.provider_name, self.role.model_id)
        elif self.providers_map:
            # Default to first provider if new
            first_prov = list(self.providers_map.keys())[0]
            self.query_one("#provider", Select).value = first_prov
            self._update_model_options(first_prov)

    @on(Select.Changed, "#provider")
    def on_provider_changed(self, event: Select.Changed):
        if not event.value: return
        
        target_model = None
        if self.is_edit and event.value == self.role.provider_name:
             target_model = self.role.model_id
        
        self._update_model_options(event.value, target_model)

    @on(Select.Changed, "#model")
    def on_model_changed(self, event: Select.Changed):
        custom_input = self.query_one("#custom_model_input", Input)
        if event.value == "custom_input":
            custom_input.remove_class("hidden")
            custom_input.focus()
        else:
            custom_input.add_class("hidden")

    def _update_model_options(self, provider_name: str, current_model: str = None):
        model_select = self.query_one("#model", Select)
        custom_input = self.query_one("#custom_model_input", Input)
        provider = self.providers_map.get(provider_name)
        
        options = []
        if provider:
            # 1. PRIORITY: Cached models
            if hasattr(provider, 'available_models') and provider.available_models:
                options.extend(provider.available_models)
            
            # 2. FALLBACK: Static lists
            else:
                if provider.type == "openai":
                    options.extend([
                        "gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4", "gpt-3.5-turbo",
                        "o1-preview", "o1-mini"
                    ])
                elif provider.type == "anthropic":
                    options.extend([
                        "claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022",
                        "claude-3-opus-20240229", "claude-3-sonnet-20240229"
                    ])
                elif provider.type == "deepseek":
                    options.extend(["deepseek-chat", "deepseek-coder"])
            
            # 3. SAFETY: Default model
            if provider.default_model and provider.default_model not in options:
                options.insert(0, provider.default_model)
        
        # 4. CONTEXT: Current role model
        model_in_list = False
        if current_model:
            if current_model in options:
                model_in_list = True
            else:
                # If current model is not in list, maybe it was custom?
                # We won't add it to options, we will set Custom mode
                pass
            
        # Deduplicate
        unique_options = list(dict.fromkeys(options))
        
        # Build Select options
        select_items = [(o, o) for o in unique_options]
        select_items.append(("Inny (wpisz ręcznie)...", "custom_input"))
        
        model_select.set_options(select_items)
        
        if current_model and (current_model in unique_options):
            model_select.value = current_model
            custom_input.add_class("hidden")
        elif current_model:
            # Model exists but not in list -> assume custom
            model_select.value = "custom_input"
            custom_input.value = current_model
            custom_input.remove_class("hidden")
        elif unique_options:
            model_select.value = unique_options[0]
            custom_input.add_class("hidden")
        else:
            model_select.value = "custom_input" # Default to custom if empty
            custom_input.remove_class("hidden")

    @on(Button.Pressed, "#cancel")
    def cancel(self):
        self.dismiss(None)

    @on(Button.Pressed, "#save")
    def save(self):
        name = self.query_one("#name").value
        if not name: return
        
        provider_name = self.query_one("#provider").value
        model_val = self.query_one("#model").value
        
        final_model_id = ""
        if model_val == "custom_input":
            final_model_id = self.query_one("#custom_model_input").value
        else:
            final_model_id = model_val
            
        if not provider_name or not final_model_id:
            return

        new_conf = RoleConfig(
            name=name,
            provider_name=provider_name,
            model_id=final_model_id,
            system_prompt=self.query_one("#prompt").text,
            active_mcp_servers=self.query_one("#mcp_list").selected,
            allowed_tools=self.query_one("#tools_list").selected
        )
        self.dismiss(new_conf)


class LauncherModal(ModalScreen):
    """Startup/Task Manager screen."""
    CSS = """
    LauncherModal { align: center middle; }
    #launcher-dialog {
        width: 90%;
        height: 90%;
        border: thick $accent 80%;
        background: $surface;
        padding: 1 2;
    }
    #task-table {
        height: 1fr;
        margin: 1 0;
        border: solid $primary;
    }
    #task-details {
        height: 10;
        dock: bottom;
        margin-bottom: 1;
        border: solid $secondary;
    }
    .buttons-row {
        height: auto;
        dock: bottom;
        align: center middle;
        padding-top: 1;
    }
    .buttons-row Button {
        margin: 0 1;
    }
    """

    def __init__(self, tasks: list, task_history_manager=None):
        super().__init__()
        self.tasks = tasks
        # Sort tasks by date desc if not already
        self.tasks.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
        self.manager = task_history_manager # Pass the TaskHistory instance to allow deletion

    def compose(self) -> ComposeResult:
        with Vertical(id="launcher-dialog"):
            yield Label("Task Manager", classes="title")
            yield Label("Select a task to view details or resume:", classes="subtitle")
            
            yield DataTable(id="task-table", cursor_type="row")
            
            yield Label("Full Prompt / Details:", classes="subtitle")
            yield TextArea("", id="task-details", read_only=True)

            with Horizontal(classes="buttons-row"):
                yield Button("Cancel / New", variant="primary", id="new_session")
                yield Button("Resume", variant="success", id="resume_btn", disabled=True)
                yield Button("Delete", variant="error", id="delete_btn", disabled=True)
                yield Button("Clear All", variant="error", id="clear_btn")

    def on_mount(self):
        table = self.query_one("#task-table", DataTable)
        table.add_columns("Date", "Status", "Prompt Summary", "ID") # ID hidden? No column hiding in Textual yet easily
        
        for t in self.tasks:
            tid = t.get('id', str(t.get('timestamp')))
            status = t.get('status', '?')
            icon = "🟢" if status == "in_progress" else "⚫"
            date_str = t.get('date', 'Unknown')
            prompt_summary = t.get('prompt', '')[:60].replace("\n", " ") + "..."
            
            table.add_row(date_str, f"{icon} {status}", prompt_summary, tid)

    @on(DataTable.RowSelected, "#task-table")
    def on_row_selected(self, event: DataTable.RowSelected):
        """Update details view and enable buttons."""
        self._update_selection(event.row_key)

    @on(DataTable.RowHighlighted, "#task-table")
    def on_row_highlighted(self, event: DataTable.RowHighlighted):
        """Update details on hover/highlight."""
        self._update_selection(event.row_key)

    def _update_selection(self, row_key):
        table = self.query_one("#task-table", DataTable)
        try:
            row = table.get_row(row_key)
            tid = row[3] # ID is 4th column
            
            # Find full task data
            task = next((t for t in self.tasks if t.get('id') == tid or str(t.get('timestamp')) == tid), None)
            
            if task:
                details = f"Prompt:\n{task.get('prompt')}\n\nResult Summary:\n{task.get('result_summary', 'N/A')}\n\nLog: {task.get('log_path', 'N/A')}"
                self.query_one("#task-details", TextArea).text = details
                
                self.query_one("#resume_btn").disabled = False
                self.query_one("#delete_btn").disabled = False
        except:
            pass

    @on(Button.Pressed, "#new_session")
    def on_new(self):
        self.dismiss(None)

    @on(Button.Pressed, "#resume_btn")
    def on_resume(self):
        table = self.query_one("#task-table", DataTable)
        if not table.cursor_row is not None: return
        
        row = table.get_row_at(table.cursor_row)
        tid = row[3]
        task = next((t for t in self.tasks if t.get('id') == tid or str(t.get('timestamp')) == tid), None)
        self.dismiss(task)

    @on(Button.Pressed, "#delete_btn")
    def on_delete(self):
        if not self.manager: return
        
        table = self.query_one("#task-table", DataTable)
        if not table.cursor_row is not None: return
        
        # Fix: Pass Coordinate object
        row_key = table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0)).row_key
        row = table.get_row(row_key)
        tid = row[3]
        
        # Delete from backend
        self.manager.delete_task(tid)
        
        # Update UI
        table.remove_row(row_key)
        self.tasks = [t for t in self.tasks if t.get('id') != tid and str(t.get('timestamp')) != tid]
        
        self.query_one("#task-details", TextArea).text = ""
        self.query_one("#resume_btn").disabled = True
        self.query_one("#delete_btn").disabled = True

    @on(Button.Pressed, "#clear_btn")
    def on_clear(self):
        if not self.manager: return
        self.manager.clear_history()
        self.tasks = []
        self.query_one("#task-table", DataTable).clear()
        self.query_one("#task-details", TextArea).text = ""


# --- MAIN CONFIG SCREEN ---

class ConfigScreen(Screen):
    """Interactive Configuration Manager."""

    DEFAULT_CSS = """
    ConfigScreen {
        align: center middle;
    }

    #config-dialog {
        width: 95%;
        height: 90%;
        max-height: 95%;
        border: thick $primary 60%;
        background: $surface;
        padding: 1 2;
        layout: vertical;
    }

    #config-dialog .main-title {
        text-align: center;
        text-style: bold;
        color: $accent;
        padding: 1 0;
    }

    #config-dialog TabbedContent {
        height: 1fr;
    }

    #config-dialog ContentSwitcher {
        height: 1fr;
    }

    #config-dialog TabPane {
        layout: vertical;
        padding: 1;
    }

    #config-dialog DataTable {
        height: 1fr;
        min-height: 5;
        border: solid $secondary;
    }

    #config-dialog .actions {
        height: auto;
        min-height: 3;
        padding: 1 0;
        align: center middle;
    }

    #config-dialog .back-btn {
        margin-top: 1;
        width: auto;
    }

    #config-dialog .info {
        color: $text-muted;
        text-style: italic;
        padding: 1;
    }
    """

    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        with Vertical(id="config-dialog"):
            yield Label("Octopus Configuration Manager", classes="main-title")

            with TabbedContent():
                with TabPane("Providers", id="tab_providers"):
                    yield DataTable(id="providers_table", cursor_type="row")
                    with Horizontal(classes="actions"):
                        yield Button("Add Provider", id="add_provider", variant="success")
                        yield Button("Edit Selected", id="edit_provider")
                        yield Button("Delete Selected", id="del_provider", variant="error")

                with TabPane("Roles", id="tab_roles"):
                    yield DataTable(id="roles_table", cursor_type="row")
                    with Horizontal(classes="actions"):
                        yield Button("Set Active", id="set_active_role", variant="primary")
                        yield Button("Add Role", id="add_role", variant="success")
                        yield Button("Edit Selected", id="edit_role")
                        yield Button("Delete Selected", id="del_role", variant="error")

                with TabPane("MCP Servers", id="tab_mcp"):
                    yield DataTable(id="mcp_table", cursor_type="row")
                    yield Label("MCP configuration is read-only in TUI v6. Please edit config.yaml for command args.", classes="info")

            yield Button("Back to Chat", variant="primary", id="back_btn", classes="back-btn")

    def on_mount(self):
        self.call_after_refresh(self.load_tables)

    def load_tables(self):
        store = self.app.session.config_store
        store.load()
        
        pt = self.query_one("#providers_table", DataTable)
        pt.clear(columns=True)
        pt.add_columns("Name", "Type", "Model", "Base URL")
        for p in store.config.providers.values():
            pt.add_row(p.name, p.type, p.default_model, p.base_url or "-")

        rt = self.query_one("#roles_table", DataTable)
        rt.clear(columns=True)
        rt.add_columns("Name", "Provider", "Model", "MCPs", "Tools")
        for r in store.config.roles.values():
            rt.add_row(r.name, r.provider_name, r.model_id, str(len(r.active_mcp_servers)), str(len(r.allowed_tools)))

        mt = self.query_one("#mcp_table", DataTable)
        mt.clear(columns=True)
        mt.add_columns("Name", "Command", "Enabled")
        for m in store.config.mcp_servers.values():
            mt.add_row(m.name, m.command, str(m.enabled))

    @on(Button.Pressed, "#back_btn")
    def back(self):
        self.app.pop_screen()

    @on(Button.Pressed, "#add_provider")
    def add_provider(self):
        self.app.push_screen(ProviderModal(), self.on_provider_saved)

    @on(Button.Pressed, "#edit_provider")
    def edit_provider(self):
        table = self.query_one("#providers_table", DataTable)
        if not table.cursor_row is not None: return
        name = table.get_row_at(table.cursor_row)[0]
        provider = self.app.session.config_store.config.providers.get(name)
        self.app.push_screen(ProviderModal(provider), self.on_provider_saved)

    @on(Button.Pressed, "#del_provider")
    def del_provider(self):
        table = self.query_one("#providers_table", DataTable)
        if not table.cursor_row is not None: return
        name = table.get_row_at(table.cursor_row)[0]
        del self.app.session.config_store.config.providers[name]
        self.app.session.config_store.save()
        self.load_tables()

    def on_provider_saved(self, result: ProviderConfig):
        if result:
            self.app.session.config_store.config.providers[result.name] = result
            self.app.session.config_store.save()
            self.load_tables()

    @on(Button.Pressed, "#set_active_role")
    def set_active_role(self):
        table = self.query_one("#roles_table", DataTable)
        if not table.cursor_row is not None: return
        name = table.get_row_at(table.cursor_row)[0]
        
        # Update Config
        self.app.session.config_store.config.active_role = name
        self.app.session.config_store.save()
        
        # Update Session
        self.app.session.role_name = name
        self.app.session.role_config = self.app.session.config_store.get_role(name)
        
        # Update App Title
        self.app.title = f"Octopus ({name})"
        self.app.notify(f"Active role switched to: {name}")
        
        # Reload tables to reflect (maybe highlight active?)
        self.load_tables()

    @on(Button.Pressed, "#add_role")
    def add_role(self):
        store = self.app.session.config_store
        prov_map = store.config.providers
        mcp_names = list(store.config.mcp_servers.keys())
        # Pass all potential tools to the RoleModal for selection
        all_tool_names = list(self.app.session.tools_map.keys()) + ["delegate_task", "ask_user", "request_admin_privileges"] # Include dynamic
        self.app.push_screen(RoleModal(providers_map=prov_map, mcp_servers=mcp_names, available_tools=all_tool_names), self.on_role_saved)

    @on(Button.Pressed, "#edit_role")
    def edit_role(self):
        table = self.query_one("#roles_table", DataTable)
        if not table.cursor_row is not None: return
        name = table.get_row_at(table.cursor_row)[0]
        store = self.app.session.config_store
        role = store.config.roles.get(name)
        prov_map = store.config.providers
        mcp_names = list(store.config.mcp_servers.keys())
        all_tool_names = list(self.app.session.tools_map.keys()) + ["delegate_task", "ask_user", "request_admin_privileges"]
        self.app.push_screen(RoleModal(role, prov_map, mcp_names, all_tool_names), self.on_role_saved)

    @on(Button.Pressed, "#del_role")
    def del_role(self):
        table = self.query_one("#roles_table", DataTable)
        if not table.cursor_row is not None: return
        name = table.get_row_at(table.cursor_row)[0]
        del self.app.session.config_store.config.roles[name]
        self.app.session.config_store.save()
        self.load_tables()

    def on_role_saved(self, result: RoleConfig):
        if result:
            self.app.session.config_store.config.roles[result.name] = result
            self.app.session.config_store.save()
            self.load_tables()


# --- APP ---

class OctopusApp(App):
    CSS_PATH = _CSS_PATH
    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("f2", "config_screen", "Config"),
        ("f3", "show_tasks", "Tasks"),
        ("f4", "cancel", "Stop")
    ]

    def __init__(self, auto_approve: bool = False):
        super().__init__()
        self.session = OctopusSession(auto_approve=auto_approve)
        
        # Connect async event callback for real-time streaming
        self.session.on_event_callback = self.handle_async_event
        
        self.worker = None
        self.activity_widget = None
        self.cwd = os.getcwd()  # Store CWD
        self.output_style = "balanced"  # Claude Code style: minimal/balanced/detailed
        self.command_registry = None  # Initialized after mount

    def compose(self) -> ComposeResult:
        """Create the main UI layout (Claude Code style - No Sidebar, Minimal)."""
        yield ModeHeader(id="mode_header")
        with Vertical(id="main_container"):
            yield VerticalScroll(id="chat_container")
            yield ShellInput(placeholder=">> Enter command... | /help", id="user_input")
        # EnhancedStatusBar zamiast Footer
        yield EnhancedStatusBar(cwd=self.cwd, id="status_bar")

    def get_or_create_activity_widget(self):
        chat = self.query_one("#chat_container")
        # If we don't have an active widget, create one
        if not self.activity_widget:
            self.activity_widget = ActivityWidget()
            chat.mount(self.activity_widget)
            chat.scroll_end()
        return self.activity_widget

    def close_activity_widget(self):
        """Mark activity as finished (visually separate next block)."""
        # Zakończ streaming jeśli jest aktywny
        if self.activity_widget and hasattr(self.activity_widget, 'end_streaming'):
            if self.activity_widget.is_streaming():
                self.activity_widget.end_streaming()
        self.activity_widget = None

    def action_show_tasks(self):
        """Show list of all recent tasks."""
        # Get all tasks (reversed to show newest first)
        all_tasks = list(reversed(self.session.task_history.history))
        self.push_screen(LauncherModal(all_tasks, self.session.task_history), self.on_task_resume)

    @on(Button.Pressed, "#tasks_btn")
    def on_tasks_btn(self):
        self.action_show_tasks()

    def get_status_text(self, stats: Dict = None) -> str:
        stats_str = ""
        if stats:
            parts = []
            total_tokens = 0
            
            # Simple hash-based color generator for consistent model colors
            def get_model_color(name):
                colors = ["cyan", "magenta", "green", "yellow", "blue", "red"]
                return colors[hash(name) % len(colors)]

            for key, value in stats.items():
                # Skip the by_role dictionary - only show model totals
                if key == "by_role":
                    continue
                if isinstance(value, (int, float)):
                    color = get_model_color(key)
                    # Use rich markup: [color]name[/]: value
                    parts.append(f"[{color}]{key}[/]: {int(value):,}")
                    total_tokens += int(value)
            
            stats_str = f" | Tokens: {', '.join(parts)} (Total: {total_tokens:,})"

        return f"CWD: {self.cwd}{stats_str}"

    def on_mount(self):
        self.title = f"Octopus ({self.session.role_name})"
        self.command_registry = SlashCommandRegistry(self)  # Initialize slash commands
        self.init_session()

    def check_for_tasks(self):
        """Check for incomplete tasks and show launcher."""
        incomplete = self.session.task_history.get_incomplete_tasks()
        if incomplete:
            self.push_screen(LauncherModal(incomplete, self.session.task_history), self.on_task_resume)

    def on_task_resume(self, task_data: dict):
        """Callback from LauncherModal."""
        
        def _do_resume():
            try:
                # Force refresh and focus to prevent black screen
                self.refresh()
                try:
                    self.query_one("#user_input").focus()
                except: pass

                if not task_data:
                    # New session started (modal cancelled/closed)
                    return

                # User chose to resume
                task_id = task_data.get("id")
                log_path = task_data.get("log_path")
                prompt = task_data.get("prompt") or "Unknown Task"
                
                if not log_path:
                    self.notify("Cannot resume legacy task (no log path saved).", severity="warning")
                    return

                chat = self.query_one("#chat_container")
                # Escape prompt to prevent MarkupError
                safe_prompt = escape(prompt)
                chat.mount(Label(f"[bold magenta]Resuming Task: {safe_prompt}[/bold magenta]"))
                
                if self.session.resume_session(task_id, log_path):
                    chat.mount(Label("[dim]History loaded. Context restored.[/dim]"))
                    # Trigger an autonomous step by the Architect to review state
                    self.process_chat("STATUS REVIEW: Check files and logs to determine next steps.")
                else:
                    chat.mount(Label(f"[error]Failed to load log: {log_path}[/error]"))
            except Exception as e:
                import traceback
                with open("crash_debug.log", "w") as f:
                    f.write(traceback.format_exc())
                self.notify(f"CRITICAL ERROR: {e}. See crash_debug.log", severity="error")

        # Schedule resumption after the modal closes and screen refreshes
        self.call_after_refresh(_do_resume)

    @work(exclusive=True, thread=True)
    def init_session(self):
        def _mount_status(text):
            try:
                self.query_one("#chat_container").mount(Label(text))
            except Exception: pass

        for event in self.session.initialize():
            if event.type == "status":
                self.call_from_thread(_mount_status, f"[dim]{event.content}[/dim]")
        
        # After init, start status bar timer
        def _init_status_bar():
            try:
                status_bar = self.query_one("#status_bar", EnhancedStatusBar)
                status_bar.update_timer()
            except Exception:
                pass
        self.call_from_thread(_init_status_bar)

        # Start periodic timer update (every second)
        self.call_from_thread(self.set_interval, 1.0, self._update_status_timer)
        
        # Check for pending tasks AFTER init is done
        self.call_from_thread(self.check_for_tasks)

    async def on_input_submitted(self, message: Input.Submitted):
        if not message.value.strip():
            return
        user_msg = message.value.strip()
        
        inp = self.query_one("#user_input", ShellInput)
        inp.add_to_history(user_msg)
        inp.value = ""

        # Handle exit commands
        if user_msg.lower() in ["/exit", "exit", "/quit", "quit"]:
            self.exit()
            return
            
        # Handle Debug Toggle
        if user_msg.lower() == "/debug":
            current = self.session.debug_mode
            self.session.debug_mode = not current
            state = "ON" if not current else "OFF"
            self.show_system_message(f"🛠️ Debug Mode: **{state}**", style="bold orange" if not current else "dim")
            return

        # Handle slash commands FIRST (Claude Code style)
        if user_msg.startswith("/") and self.command_registry:
            if self.command_registry.execute(user_msg):
                return  # Command was handled

        # Normal message processing
        await self.query_one("#chat_container").mount(MessageWidget("user", user_msg))
        self.process_chat(user_msg)

    def action_config_screen(self): # Przywrócona akcja F2
        self.push_screen(ConfigScreen())

    @on(Button.Pressed, "#cancel_btn")
    def action_cancel(self):
        self.session.abort()
        if self.worker:
            self.worker.cancel()

    # ==================== Slash Commands Helper Methods ====================

    def show_system_message(self, text: str, style: str = "info"):
        """Display a system message in chat (for slash commands)."""
        chat = self.query_one("#chat_container")
        # Use Markdown for rich formatting
        msg_widget = MessageWidget("system", text)
        chat.mount(msg_widget)
        chat.scroll_end()

    def _add_system_message(self, text: str):
        """Alias for show_system_message (backwards compat)."""
        self.show_system_message(text)

    def clear_chat(self):
        """Clear all messages from chat container."""
        chat = self.query_one("#chat_container")
        chat.remove_children()
        self.activity_widget = None

    def toggle_todo_panel(self):
        """Toggle TODO panel visibility."""
        try:
            todo_panel = self.query_one("#todo_panel")
            todo_panel.display = not todo_panel.display
        except Exception:
            pass

    def show_todo_panel(self):
        """Show TODO panel."""
        try:
            self.query_one("#todo_panel").display = True
        except Exception:
            pass

    def hide_todo_panel(self):
        """Hide TODO panel."""
        try:
            self.query_one("#todo_panel").display = False
        except Exception:
            pass

    def clear_todo_panel(self):
        """Clear all TODOs from panel."""
        try:
            todo_panel = self.query_one("#todo_panel")
            if hasattr(todo_panel, 'clear_all'):
                todo_panel.clear_all()
        except Exception:
            pass

    def set_output_style(self, style_name: str):
        """Set output style (minimal/balanced/detailed)."""
        valid = ["minimal", "balanced", "detailed"]
        if style_name in valid:
            self.output_style = style_name
            self.notify(f"Output style: {style_name}")

    def refresh_status(self):
        """Refresh the status bar."""
        try:
            status_bar = self.query_one("#status_bar", EnhancedStatusBar)
            status_bar.update_timer()
        except Exception:
            pass

    def _update_status_timer(self):
        """Periodic timer update callback."""
        try:
            status_bar = self.query_one("#status_bar", EnhancedStatusBar)
            status_bar.update_timer()
            
            # Update Mode Header
            try:
                mode_header = self.query_one("#mode_header", ModeHeader)
                if hasattr(self.session, 'session_mode'):
                    current_mode = self.session.session_mode.value
                    if mode_header.mode != current_mode:
                        mode_header.mode = current_mode
            except: pass

        except Exception:
            pass

    def switch_role(self, role_name: str):
        """Switch active role."""
        if hasattr(self.session, 'config_store') and self.session.config_store:
            if role_name in self.session.config_store.roles:
                self.session.config_store.active_role_name = role_name
                self.title = f"Octopus ({role_name})"
                self.notify(f"Switched to role: {role_name}")
                self.refresh_status()
            else:
                self.notify(f"Unknown role: {role_name}", severity="warning")

    def switch_model(self, model_name: str):
        """Switch model for active role."""
        if hasattr(self.session, 'active_role'):
            self.session.active_role.model_id = model_name
            self.notify(f"Model set to: {model_name}")
            self.refresh_status()

    def action_open_config(self):
        """Open config screen (alias for F2)."""
        self.push_screen(ConfigScreen())

    # ==================== End Slash Commands Helpers ====================

    @work(exclusive=True, thread=True)
    def process_chat(self, user_msg):
        self.worker = get_current_worker()
        chat = self.query_one("#chat_container")
        
        try:
            # Start activity block
            self.call_from_thread(self.get_or_create_activity_widget)
            
            for event in self.session.process_user_input(user_msg):
                role = event.metadata.get("role", "system")
                
                if event.type == "text":
                    # Close activity block visually
                    self.call_from_thread(self.close_activity_widget)
                    def _mount_and_scroll():
                        model_id = event.metadata.get("model_id")
                        msg_widget = MessageWidget(role, event.content, model_id=model_id)
                        chat.mount(msg_widget)
                        # Use call_after_refresh for reliable scroll (waits for render)
                        chat.call_after_refresh(lambda: chat.scroll_end(animate=False))

                    self.call_from_thread(_mount_and_scroll)
                
                elif event.type == "reasoning":
                    # Display model thoughts/plans inside the activity widget
                    r_model = event.metadata.get('model_id')
                    def _log_reasoning(txt, model):
                        aw = self.get_or_create_activity_widget()
                        aw.log_reasoning(txt, model)
                    self.call_from_thread(_log_reasoning, event.content, r_model)

                elif event.type == "streaming":
                    # Stream content to activity widget
                    s_content = event.content
                    def _stream_output(txt):
                        aw = self.get_or_create_activity_widget()
                        aw.append_streaming(txt)
                    self.call_from_thread(_stream_output, s_content)

                elif event.type == "status":
                    s_model = event.metadata.get('model_id', '')
                    s_role = event.metadata.get('role', '')
                    iteration = event.metadata.get('iteration')
                    max_iterations = event.metadata.get('max_iterations')

                    # Check if this is an iteration event (delegation)
                    if iteration is not None and max_iterations is not None:
                        # Claude Code style: Compact iteration status as text
                        def _show_iteration(role, model, cur, mx):
                            aw = self.get_or_create_activity_widget()
                            # Simple text instead of heavy widget
                            iter_text = f"[dim]{role} ({model}) iteration {cur}/{mx}[/dim]"
                            aw.log(iter_text)
                        self.call_from_thread(_show_iteration, s_role, s_model, iteration, max_iterations)
                    else:
                        # Regular status - log as text
                        def _log_status(txt, model):
                            aw = self.get_or_create_activity_widget()
                            prefix = f"[{model}] " if model else ""
                            aw.log(f"[dim]{prefix}{txt}[/dim]")
                        self.call_from_thread(_log_status, event.content, s_model)

                elif event.type == "stats":
                    # Update status bar with model token usage
                    stats = event.metadata.get("stats", {})
                    def _update_stats_ui(s):
                        try:
                            self.query_one("#status_bar", EnhancedStatusBar).update_model_stats(s)
                            # self.notify(f"Stats updated: {s}") # Debug
                        except: pass
                    self.call_from_thread(_update_stats_ui, stats)

                elif event.type == "tool_call":
                    t_name = event.metadata.get('name')
                    t_model = event.metadata.get('model_id')
                    t_args = event.metadata.get('arguments', {})

                    # --- STAGE 3: Tool Execution Monitor ---
                    # --- STAGE 3: Tool Execution Monitor ---
                    cmd = t_args.get('command', '')
                    def _start_monitor(t_start_name, t_start_cmd):
                        self.current_monitor = ToolExecutionMonitor(
                            app=self,
                            tool_name=t_start_name,
                            command=t_start_cmd,
                            timeout=300
                        )
                        self.current_monitor.start()
                    
                    self.call_from_thread(_start_monitor, t_name, cmd)
                    # ---------------------------------------
                    # ---------------------------------------

                    def _add_tool_step(name, model, args):
                        aw = self.get_or_create_activity_widget()
                        prefix = f"[{model}] " if model else ""

                        # Krótki opis dla głównej linii
                        brief = ""
                        if name == "read_file":
                            brief = args.get('path', '')
                        elif name == "write_file":
                            brief = args.get('path', '')
                        elif name == "run_shell_command":
                            cmd = args.get('command', '')
                            brief = cmd[:40] + ('...' if len(cmd) > 40 else '')
                        elif name == "delegate_task":
                            brief = args.get('role', '')
                        elif name == "list_directory":
                            brief = args.get('path', '.')
                        elif name == "glob":
                            brief = args.get('pattern', '*')
                        elif name == "search_file_content":
                            brief = args.get('pattern', '')

                        # Nowy format: add_step z tool_name i arguments
                        # Dla delegate_task i write_file pokazuj więcej szczegółów
                        show_args = {}
                        if name == "delegate_task":
                            show_args = {
                                'role': args.get('role', ''),
                                'instruction': args.get('instruction', '')
                            }
                        elif name == "write_file":
                            show_args = {
                                'path': args.get('path', ''),
                                'content': f"({len(args.get('content', ''))} chars)"
                            }
                        elif name in ("read_file", "list_directory"):
                            show_args = {'path': args.get('path', '')}
                        elif name == "run_shell_command":
                            show_args = {'command': args.get('command', '')}
                        elif name == "search_file_content":
                            show_args = {
                                'pattern': args.get('pattern', ''),
                                'path': args.get('path', '')
                            }

                        aw.add_step(f"{prefix}{brief}", tool_name=name, arguments=show_args if show_args else None)
                    self.call_from_thread(_add_tool_step, t_name, t_model, t_args)

                elif event.type == "tool_result":
                    # --- STAGE 3: Stop Monitor ---
                    def _stop_monitor():
                        if self.current_monitor:
                            self.current_monitor.stop()
                            self.current_monitor = None
                    self.call_from_thread(_stop_monitor)
                    # -----------------------------

                    full_result = event.metadata.get('full_result', event.content)
                    tool_name = event.metadata.get('name', '')
                    
                    # --- STAGE 2: Error Detection ---
                    content = event.content
                    is_error = any([
                        "Error:" in content,
                        "Failed" in content,
                        "Exception" in content,
                        event.metadata.get("is_error", False),
                        ("exit code" in content.lower() and 
                         not any(x in content.lower() for x in ["exit code: 0", "exit code 0"]))
                    ])
                    
                    if is_error:
                        self.session.last_error = content
                        
                        def _show_recovery(err_text, t_name):
                            self.push_screen(
                                ErrorRecoveryModal(
                                    error_text=err_text[:500] + "..." if len(err_text) > 500 else err_text,
                                    tool_name=t_name or "Unknown Tool"
                                ),
                                callback=self.handle_error_recovery
                            )
                        self.call_from_thread(_show_recovery, content, tool_name)
                    # --------------------------------

                    def _finish_tool_step(res, full, name):
                        aw = self.get_or_create_activity_widget()

                        # Inteligentne podsumowanie w zależności od narzędzia
                        summary = "Done"
                        if "Error" in res:
                            summary = "Failed"
                        elif "Successfully" in res:
                            summary = "Success"
                        elif name == "read_file":
                            lines = full.count('\n') + 1 if full else 0
                            summary = f"Read {lines} lines"
                        elif name == "list_directory":
                            items = len(full.strip().split('\n')) if full and full.strip() else 0
                            summary = f"Found {items} items"
                        elif name == "run_shell_command":
                            if "Exit Code: 0" in full:
                                summary = "Exit 0 ✓"
                            elif "Exit Code:" in full:
                                try:
                                    code = full.split("Exit Code:")[1].split()[0]
                                    summary = f"Exit {code} ✗"
                                except:
                                    summary = "Exit ✗"
                        elif name == "write_file":
                            summary = "Written ✓"
                        elif name == "glob":
                            matches = len(full.strip().split('\n')) if full and full.strip() else 0
                            summary = f"{matches} matches"
                        elif name == "search_file_content":
                            matches = len(full.strip().split('\n')) if full and full.strip() else 0
                            summary = f"{matches} results"

                        if aw.current_step_id:
                            status = "done" if "Error" not in res else "error"
                            aw.update_step(aw.current_step_id, f"→ {summary}", status)

                        # Pokaż szczegóły dla ważnych wyników
                        has_diff = "**File Changes:**" in full or "```diff" in full
                        show_detail = (
                            has_diff or
                            "Error" in full or
                            ("STDOUT" in full and len(full) > 50)
                        )
                        if show_detail:
                            # Ogranicz do 500 znaków
                            display_content = full[:500] + ('...' if len(full) > 500 else '')
                            aw.add_detail(f"```\n{display_content}\n```")

                    self.call_from_thread(_finish_tool_step, event.content, full_result, tool_name)

                elif event.type == "question":
                    self.call_from_thread(self.close_activity_widget)
                    options = event.metadata.get("options", [])
                    
                    def handle_answer(answer):
                        if answer:
                            self.query_one("#chat_container").mount(MessageWidget("user", answer))
                            self.process_chat(answer)
                    
                    if options:
                        self.call_from_thread(self.push_screen, QuestionModal(event.content, options), handle_answer)
                    else:
                        self.call_from_thread(chat.mount, MessageWidget("system", f"QUESTION: {event.content}"))

                elif event.type == "streaming":
                    # Real-time streaming output from LLM (especially for slow Ollama models)
                    # FIX: Używaj append_streaming() zamiast log() - unika tworzenia nowego Label dla każdego chunka
                    chunk_text = event.content
                    s_model = event.metadata.get("model_id", "")

                    def _append_stream(text, model):
                        aw = self.get_or_create_activity_widget()
                        # Użyj bufferowanego streamingu zamiast wielu Labels
                        if not aw.is_streaming():
                            prefix = f"[{model}] " if model else ""
                            aw.start_streaming(prefix)
                        aw.append_streaming(text)

                    self.call_from_thread(_append_stream, chunk_text, s_model)

                elif event.type == "stats":
                    stats = event.metadata.get("stats", {})
                    def _update_model_stats(s):
                        try:
                            status_bar = self.query_one("#status_bar", EnhancedStatusBar)
                            status_bar.update_model_stats(s)
                        except Exception:
                            pass
                    self.call_from_thread(_update_model_stats, stats)

                elif event.type == "todo_add":
                    # Claude Code style: add TODO item to panel
                    # [DISABLED] Panel removed in minimalist UI
                    # todo_id = event.metadata.get("id", f"todo_{len(self.query_one('#todo_panel').todos)}")
                    # content = event.content
                    # status = event.metadata.get("status", "pending")
                    # def _add_todo(tid, txt, st):
                    #     try:
                    #         self.query_one("#todo_panel").add_todo(tid, txt, st)
                    #     except Exception:
                    #         pass
                    # self.call_from_thread(_add_todo, todo_id, content, status)
                    pass

                elif event.type == "todo_update":
                    # Claude Code style: update TODO item status
                    # [DISABLED] Panel removed in minimalist UI
                    # todo_id = event.metadata.get("id")
                    # status = event.metadata.get("status")
                    # def _update_todo(tid, st):
                    #     try:
                    #         self.query_one("#todo_panel").update_todo(tid, st)
                    #     except Exception:
                    #         pass
                    # self.call_from_thread(_update_todo, todo_id, status)
                    pass

                elif event.type == "todo_clear":
                    # Clear all TODOs
                    def _clear_todos():
                        try:
                            self.query_one("#todo_panel").clear_todos()
                        except Exception:
                            pass
                    self.call_from_thread(_clear_todos)

                elif event.type == "log":
                    # NOWY HANDLER: Obsługa eventów "log" z session.py
                    # Session emituje 15+ eventów tego typu, które wcześniej były ignorowane
                    log_text = event.content
                    log_style = event.metadata.get("style", "dim")
                    log_model = event.metadata.get("model_id", "")
                    log_role = event.metadata.get("role", "")

                    def _log_event(text, style, model, role):
                        aw = self.get_or_create_activity_widget()
                        # Prefix z modelu lub roli
                        prefix = ""
                        if model:
                            prefix = f"[{model}] "
                        elif role:
                            prefix = f"[{role}] "

                        # Formatuj tekst wg stylu (z session.py metadata)
                        if "yellow" in style:
                            formatted = f"[dim yellow]{prefix}{text}[/dim yellow]"
                        elif "red" in style or "error" in style:
                            formatted = f"[red]{prefix}{text}[/red]"
                        elif "green" in style or "success" in style:
                            formatted = f"[green]{prefix}{text}[/green]"
                        elif "cyan" in style:
                            formatted = f"[dim cyan]{prefix}{text}[/dim cyan]"
                        else:
                            formatted = f"[dim]{prefix}{text}[/dim]"
                        aw.log(formatted)

                    self.call_from_thread(_log_event, log_text, log_style, log_model, log_role)

        except Exception as e:
            self.call_from_thread(chat.mount, Label(f"[bold red]Error: {e}[/bold red]"))
        finally:
            self.call_from_thread(self.close_activity_widget)

if __name__ == "__main__":
    app = OctopusApp()
    app.run()
    # --- SLASH COMMAND HANDLERS (Stage 4) ---

    def handle_slash_command(self, cmd: str):
        """Route slash commands to handlers."""
        # Simple parsing
        parts = cmd.split()
        base_cmd = parts[0]
        
        handler = self.slash_commands.get(base_cmd)
        if handler:
            handler()
        else:
            self.notify(f"Unknown command: {base_cmd}. Type /help for available commands.")

    def show_system_status(self):
        """Display current system status."""
        status = self.session.get_current_status()
        
        status_text = f"""
# System Status

- **Mode**: {status['mode'].upper()}
- **Current Task**: {status['task'] or 'None'}
- **Elapsed Time**: {status['elapsed']:.1f}s
- **Active Model**: {status['model']}
- **Role**: {status['role']}
- **Last Error**: {status['last_error'] or 'None'}
        """
        
        self.push_screen(MarkdownModal(status_text, title="System Status"))

    def show_debug_info(self):
        """Show last error and debug information."""
        last_error = getattr(self.session, 'last_error', None) or "No recent errors"
        
        debug_text = f"""
# Debug Information

### Last Error
```
{last_error}
```

- **Session Log**: `{self.session.logger.log_file}`
- **Trajectory**: `logs/trajectory_{self.session.trajectory.session_id}.json`
        """
        
        self.push_screen(MarkdownModal(debug_text, title="Debug Info"))

    def show_trajectory(self):
        """Show agent trajectory summary."""
        summary = self.session.trajectory.get_summary()
        
        text = f"""
# Agent Trajectory Summary

- **Total Steps**: {summary['total_steps']}
- **Duration**: {summary.get('duration', 0):.1f}s
- **Decision Types**:
```json
{json.dumps(summary.get('decision_types', {}), indent=2)}
```
        """
        
        self.push_screen(MarkdownModal(text, title="Trajectory"))

    def show_logs(self):
        """Open log viewer modal."""
        log_file = self.session.logger.log_file
        self.notify(f"Session log: {log_file}")
        # Ideally we would show content, but for now just notify path

    def retry_last_operation(self):
        """Retry last failed operation."""
        # Placeholder for deeper retry logic
        self.notify("🔄 Retry initiated (via command)")

    def cancel_operation(self):
        """Cancel current operation."""
        try:
            self.session.abort()
            self.notify("❌ Operation cancelled")
        except Exception as e:
            self.notify(f"Cancellation failed: {e}", severity="error")

    def show_slash_help(self):
        """Show available slash commands."""
        help_text = """
# Available Slash Commands

- `/status` - Show current task status
- `/debug` - Show last error details
- `/logs` - View session logs path
- `/trajectory` - View agent decisions
- `/retry` - Retry last failed operation
- `/cancel` - Cancel current operation
- `/help` - Show this help
        """
        self.push_screen(MarkdownModal(help_text, title="Slash Commands"))

    # --- ERROR RECOVERY HANDLERS (Stage 2) ---

    def handle_error_recovery(self, choice: str):
        """Handle user's error recovery choice."""
        if choice == "retry":
            self.notify("🔄 Retrying last operation...")
            # Trigger retry logic here
            
        elif choice == "skip":
            self.notify("⏭ Skipping failed operation, continuing...")
            # Continue logic here
            
        elif choice == "abort":
            self.notify("❌ Aborting task...")
            self.session.abort()

    # ==================== Async Event Handlers ====================

    def handle_async_event(self, event):
        """Handle async events from session (e.g. streaming from background threads)."""
        if event.type == "streaming":
            def _update_ui(content):
                aw = self.get_or_create_activity_widget()
                if aw:
                    aw.append_streaming(content)
            self.call_from_thread(_update_ui, event.content)

    def _log_event(self, text, style="dim", model=None, role=None):
        """Log event to activity widget."""
        def _do_log(txt, st, mdl, rl):
            # Check if app is closing
            if not self.is_running: return
            try:
                aw = self.get_or_create_activity_widget()
                prefix = f"[{mdl}] " if mdl else ""
                aw.log(f"[{st}]{prefix}{txt}[/{st}]")
            except: pass
            
        self.call_from_thread(_do_log, text, style, model, role)
            
        elif choice == "logs":
            self.show_debug_info()
