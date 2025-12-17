"""
Slash Commands System - Claude Code style.
Handles /help, /clear, /todo, /model, /role, /style commands.
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Any


@dataclass
class SlashCommand:
    """Represents a single slash command."""
    name: str
    description: str
    handler: Callable
    aliases: List[str] = field(default_factory=list)
    usage: str = ""


class SlashCommandRegistry:
    """
    Claude Code style slash commands registry.

    Usage:
        registry = SlashCommandRegistry(app)
        if registry.execute("/help"):
            # Command was handled
            pass
    """

    def __init__(self, app: Any):
        """
        Initialize registry with reference to the TUI app.

        Args:
            app: OctopusApp instance for accessing app methods
        """
        self.app = app
        self.commands: Dict[str, SlashCommand] = {}
        self._register_builtins()

    def _register_builtins(self):
        """Register all built-in slash commands."""
        self.register(
            "help",
            "Show available commands",
            self._cmd_help,
            aliases=["h", "?"],
            usage="/help [command]"
        )
        self.register(
            "clear",
            "Clear chat history",
            self._cmd_clear,
            aliases=["cls", "c"],
            usage="/clear"
        )
        self.register(
            "todo",
            "Toggle TODO panel visibility",
            self._cmd_todo,
            aliases=["t"],
            usage="/todo [show|hide]"
        )
        self.register(
            "verbose",
            "Toggle verbose output mode",
            self._cmd_verbose,
            aliases=["v"],
            usage="/verbose [on|off]"
        )
        self.register(
            "theme",
            "Switch color theme",
            self._cmd_theme,
            aliases=["th"],
            usage="/theme [dark|light|minimal]"
        )
        self.register(
            "status",
            "Configure status bar display",
            self._cmd_status_bar,
            aliases=["stat"],
            usage="/status [compact|full]"
        )
        self.register(
            "export",
            "Export session as markdown",
            self._cmd_export,
            aliases=["save", "exp"],
            usage="/export [filename]"
        )
        self.register(
            "debug",
            "Toggle debug mode",
            self._cmd_debug,
            aliases=["dbg"],
            usage="/debug"
        )
        self.register(
            "config",
            "Open configuration modal (same as F2)",
            self._cmd_config,
            aliases=["cfg"],
            usage="/config"
        )
        self.register(
            "reset",
            "Reset conversation history",
            self._cmd_reset,
            aliases=[],
            usage="/reset confirm"
        )

    def register(self, name: str, description: str, handler: Callable,
                 aliases: List[str] = None, usage: str = ""):
        """
        Register a new slash command.

        Args:
            name: Command name (without /)
            description: Short description shown in /help
            handler: Function to call when command is executed
            aliases: Alternative names for the command
            usage: Usage string shown in detailed help
        """
        cmd = SlashCommand(
            name=name,
            description=description,
            handler=handler,
            aliases=aliases or [],
            usage=usage or f"/{name}"
        )
        self.commands[name] = cmd

        # Register aliases
        for alias in cmd.aliases:
            self.commands[alias] = cmd

    def execute(self, input_text: str) -> bool:
        """
        Try to execute input as a slash command.

        Args:
            input_text: User input string

        Returns:
            True if command was handled, False otherwise
        """
        if not input_text.startswith("/"):
            return False

        # Parse command and arguments
        parts = input_text[1:].split(maxsplit=1)
        if not parts:
            return False

        cmd_name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        # Find and execute command
        if cmd_name in self.commands:
            try:
                self.commands[cmd_name].handler(args)
                return True
            except Exception as e:
                self._show_error(f"Command error: {e}")
                return True

        # Unknown command
        self._show_error(f"Unknown command: /{cmd_name}. Type /help for available commands.")
        return True

    def _show_message(self, text: str, style: str = "info"):
        """Show a system message to the user."""
        if hasattr(self.app, 'show_system_message'):
            self.app.show_system_message(text, style)
        elif hasattr(self.app, '_add_system_message'):
            self.app._add_system_message(text)

    def _show_error(self, text: str):
        """Show an error message to the user."""
        self._show_message(f"[red]{text}[/red]", "error")

    # ==================== Command Handlers ====================

    def _cmd_help(self, args: str):
        """Show available commands or detailed help for a specific command."""
        if args:
            # Show detailed help for specific command
            cmd_name = args.strip().lstrip("/")
            if cmd_name in self.commands:
                cmd = self.commands[cmd_name]
                help_text = f"""
**/{cmd.name}** - {cmd.description}

Usage: `{cmd.usage}`
"""
                if cmd.aliases:
                    help_text += f"Aliases: {', '.join('/' + a for a in cmd.aliases)}\n"
                self._show_message(help_text)
            else:
                self._show_error(f"Unknown command: /{cmd_name}")
            return

        # Show all commands
        help_text = "**Available Commands:**\n\n"

        # Get unique commands (skip aliases)
        seen = set()
        for name, cmd in self.commands.items():
            if cmd.name in seen:
                continue
            seen.add(cmd.name)

            aliases_str = ""
            if cmd.aliases:
                aliases_str = f" ({', '.join('/' + a for a in cmd.aliases)})"
            help_text += f"  `/{cmd.name}`{aliases_str} - {cmd.description}\n"

        help_text += "\nType `/help <command>` for detailed usage."
        self._show_message(help_text)

    def _cmd_clear(self, args: str):
        """Clear chat history."""
        if hasattr(self.app, 'clear_chat'):
            self.app.clear_chat()
        elif hasattr(self.app, 'action_clear_chat'):
            self.app.action_clear_chat()
        self._show_message("Chat cleared.")

    def _cmd_todo(self, args: str):
        """Toggle or control TODO panel visibility."""
        action = args.strip().lower()

        if hasattr(self.app, 'toggle_todo_panel'):
            if action == "show":
                self.app.show_todo_panel()
            elif action == "hide":
                self.app.hide_todo_panel()
            elif action == "clear":
                self.app.clear_todo_panel()
            else:
                self.app.toggle_todo_panel()
        else:
            # Fallback: try to find and toggle the panel
            try:
                todo_panel = self.app.query_one("#todo_panel")
                if action == "show":
                    todo_panel.display = True
                elif action == "hide":
                    todo_panel.display = False
                else:
                    todo_panel.display = not todo_panel.display

                status = "visible" if todo_panel.display else "hidden"
                self._show_message(f"TODO panel is now {status}.")
            except Exception:
                self._show_error("TODO panel not found.")

    def _cmd_style(self, args: str):
        """Set output style."""
        style_name = args.strip().lower()
        valid_styles = ["minimal", "balanced", "detailed"]

        if not style_name:
            # Show current style and options
            current = getattr(self.app, 'output_style', 'balanced')
            self._show_message(
                f"**Output Styles:**\n\n"
                f"  Current: `{current}`\n\n"
                f"  Available: {', '.join(valid_styles)}\n\n"
                f"Usage: `/style <style_name>`"
            )
            return

        if style_name not in valid_styles:
            self._show_error(f"Invalid style. Choose from: {', '.join(valid_styles)}")
            return

        if hasattr(self.app, 'set_output_style'):
            self.app.set_output_style(style_name)
        else:
            self.app.output_style = style_name

        self._show_message(f"Output style set to: {style_name}")

    def _cmd_model(self, args: str):
        """Show or switch active model."""
        model_name = args.strip()

        if not model_name:
            # Show current model info
            if hasattr(self.app, 'session') and self.app.session:
                role = self.app.session.active_role
                model_info = f"**Current Model:**\n\n"
                model_info += f"  Role: `{role.name}`\n"
                model_info += f"  Provider: `{role.provider_name}`\n"
                model_info += f"  Model: `{role.model_id}`\n"

                # List available models if config available
                if hasattr(self.app, 'config_store'):
                    provider = self.app.config_store.get_provider(role.provider_name)
                    if provider and provider.available_models:
                        model_info += f"\n  Available: {', '.join(provider.available_models)}"

                self._show_message(model_info)
            else:
                self._show_error("No active session.")
            return

        # Switch model
        if hasattr(self.app, 'switch_model'):
            self.app.switch_model(model_name)
        else:
            self._show_error("Model switching not implemented.")

    def _cmd_role(self, args: str):
        """Show or switch active role."""
        role_name = args.strip()

        if not role_name:
            # Show available roles
            if hasattr(self.app, 'config_store'):
                roles = list(self.app.config_store.roles.keys())
                current = self.app.config_store.active_role_name

                role_info = "**Roles:**\n\n"
                for r in roles:
                    marker = " (active)" if r == current else ""
                    role_info += f"  `{r}`{marker}\n"
                role_info += f"\nUsage: `/role <role_name>`"
                self._show_message(role_info)
            else:
                self._show_error("Config not loaded.")
            return

        # Switch role
        if hasattr(self.app, 'switch_role'):
            self.app.switch_role(role_name)
        elif hasattr(self.app, 'config_store'):
            if role_name in self.app.config_store.roles:
                self.app.config_store.active_role_name = role_name
                self._show_message(f"Switched to role: {role_name}")
                if hasattr(self.app, 'refresh_status'):
                    self.app.refresh_status()
            else:
                self._show_error(f"Unknown role: {role_name}")
        else:
            self._show_error("Role switching not available.")

    def _cmd_status(self, args: str):
        """Show session status and statistics."""
        status_info = "**Session Status:**\n\n"

        if hasattr(self.app, 'session') and self.app.session:
            session = self.app.session

            # Role info
            if hasattr(session, 'active_role'):
                role = session.active_role
                status_info += f"  Role: `{role.name}` ({role.provider_name}/{role.model_id})\n"

            # Token stats
            if hasattr(session, 'token_stats'):
                stats = session.token_stats
                total = sum(stats.values())
                status_info += f"\n  **Token Usage:**\n"
                for model, tokens in stats.items():
                    status_info += f"    {model}: {tokens:,}\n"
                status_info += f"    Total: {total:,}\n"

            # Message count
            if hasattr(session, 'history'):
                msg_count = len(session.history)
                status_info += f"\n  Messages: {msg_count}\n"

            # CWD
            if hasattr(session, 'cwd'):
                status_info += f"\n  CWD: `{session.cwd}`\n"
        else:
            status_info += "  No active session.\n"

        self._show_message(status_info)

    def _cmd_verbose(self, args: str):
        """Toggle verbose output mode (Stage 3 feature)."""
        mode = args.strip().lower()
        
        current = getattr(self.app, 'verbose_mode', False)
        
        if not mode or mode == "toggle":
            new_mode = not current
        elif mode in ["on", "true", "1"]:
            new_mode = True
        elif mode in ["off", "false", "0"]:
            new_mode = False
        else:
            self._show_error(f"Invalid mode. Use: on, off, or toggle")
            return
        
        self.app.verbose_mode = new_mode
        status = "enabled" if new_mode else "disabled"
        self._show_message(f"Verbose mode {status}. Tool outputs will be {'detailed' if new_mode else 'compact'}.")

    def _cmd_theme(self, args: str):
        """Switch color theme (Stage 4 feature)."""
        theme = args.strip().lower()
        valid_themes = ["dark", "light", "minimal"]
        
        if not theme:
            current = getattr(self.app, 'current_theme', 'dark')
            self._show_message(
                f"**Themes:**\n\n"
                f"  Current: `{current}`\n\n"
                f"  Available: {', '.join(valid_themes)}\n\n"
                f"Usage: `/theme <theme_name>`"
            )
            return
        
        if theme not in valid_themes:
            self._show_error(f"Invalid theme. Choose from: {', '.join(valid_themes)}")
            return
        
        self.app.current_theme = theme
        self._show_message(f"Theme set to: {theme}. Restart app to apply.")

    def _cmd_status_bar(self, args: str):
        """Configure status bar display (Stage 4 feature)."""
        mode = args.strip().lower()
        valid_modes = ["compact", "full"]
        
        if not mode:
            current = getattr(self.app, 'status_bar_mode', 'full')
            self._show_message(
                f"**Status Bar Modes:**\n\n"
                f"  Current: `{current}`\n\n"
                f"  Available: {', '.join(valid_modes)}\n\n"
                f"Usage: `/status <mode>`"
            )
            return
        
        if mode not in valid_modes:
            self._show_error(f"Invalid mode. Choose from: {', '.join(valid_modes)}")
            return
        
        self.app.status_bar_mode = mode
        self._show_message(f"Status bar mode set to: {mode}")

    def _cmd_export(self, args: str):
        """Export session as markdown (Stage 4 feature)."""
        import time
        filename = args.strip() or f"octopus_session_{int(time.time())}.md"
        
        if not filename.endswith('.md'):
            filename += '.md'
        
        try:
            # Build markdown content
            content = "# Octopus Session Export\n\n"
            
            if hasattr(self.app, 'session') and self.app.session:
                session = self.app.session
                
                # Metadata
                content += f"**Role**: {session.role_name}\n"
                content += f"**Model**: {session.role_config.model_id}\n\n"
                content += "---\n\n"
                
                # Messages
                if hasattr(session, 'history'):
                    for msg in session.history:
                        role = msg.get('role', 'unknown')
                        text = msg.get('content', '')
                        content += f"### {role.upper()}\n\n{text}\n\n"
                
                # Token stats
                if hasattr(session, 'token_stats'):
                    content += "---\n\n## Token Usage\n\n"
                    for model, tokens in session.token_stats.items():
                        content += f"- {model}: {tokens:,}\n"
            
            # Write to file
            import os
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(content)
            
            abs_path = os.path.abspath(filename)
            self._show_message(f"Session exported to: `{abs_path}`")
        except Exception as e:
            self._show_error(f"Export failed: {e}")

    def _cmd_debug(self, args: str):
        """Toggle debug mode."""
        if hasattr(self.app, 'session') and self.app.session:
            current = getattr(self.app.session, 'debug_mode', False)
            self.app.session.debug_mode = not current
            status = "enabled" if self.app.session.debug_mode else "disabled"
            self._show_message(f"Debug mode {status}. Raw model output will be {'shown' if self.app.session.debug_mode else 'hidden'}.")
        else:
            self._show_error("No active session.")

    def _cmd_config(self, args: str):
        """Open configuration modal."""
        if hasattr(self.app, 'action_config_screen'):
            self.app.action_config_screen()
        else:
            self._show_error("Config modal not available. Press F2.")

    def _cmd_reset(self, args: str):
        """Reset conversation history."""
        confirm = args.strip().lower()

        if confirm != "confirm":
            self._show_message(
                "**Warning:** This will clear all conversation history.\n\n"
                "Type `/reset confirm` to proceed."
            )
            return

        if hasattr(self.app, 'reset_session'):
            self.app.reset_session()
        elif hasattr(self.app, 'session') and self.app.session:
            if hasattr(self.app.session, 'history'):
                self.app.session.history.clear()
            if hasattr(self.app.session, 'token_stats'):
                self.app.session.token_stats.clear()

        if hasattr(self.app, 'clear_chat'):
            self.app.clear_chat()

        self._show_message("Session reset. History cleared.")
