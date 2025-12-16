from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich.panel import Panel
from ..core.config_store import ConfigStore, ProviderConfig, MCPServerConfig, RoleConfig

class TUI:
    def __init__(self, config: ConfigStore):
        self.config = config
        self.console = Console()

    def main_menu(self):
        while True:
            try:
                self.console.clear()
                self.console.print(Panel.fit("[bold magenta]Octopus Framework v4.0[/bold magenta]\nFully Configurable Agentic System", subtitle="Claude Code Architecture"))
                
                self.console.print("\n[1] Providers (LLM Backends)")
                self.console.print("[2] MCP Servers (Tools/Plugins)")
                self.console.print("[3] Roles (Agent Profiles)")
                self.console.print("[4] Active Settings")
                self.console.print("[0] Exit & Save")
                
                choice = Prompt.ask("Select", choices=["1", "2", "3", "4", "0"])
                
                if choice == "1": self.providers_menu()
                elif choice == "2": self.mcp_menu()
                elif choice == "3": self.roles_menu()
                elif choice == "4": self.active_settings_menu()
                elif choice == "0":
                    self.config.save()
                    break
            except Exception as e:
                self.console.print(f"\n[bold red]An error occurred in TUI:[/bold red] {e}")
                Prompt.ask("Press Enter to continue")

    def providers_menu(self):
        while True:
            self.console.clear()
            table = Table(title="Configured Providers")
            table.add_column("Name")
            table.add_column("Type")
            table.add_column("Base URL")
            
            for p in self.config.config.providers.values():
                table.add_row(p.name, p.type, p.base_url or "(default)")
            
            self.console.print(table)
            self.console.print("\n[A] Add Provider  [D] Delete Provider  [B] Back")
            action = Prompt.ask("Action", choices=["A", "D", "B", "a", "d", "b"]).upper()
            
            if action == "B": break
            if action == "A":
                name = Prompt.ask("Friendly Name (e.g. local-lm-studio)")
                ptype = Prompt.ask("Type", choices=["openai", "anthropic", "ollama", "deepseek"], default="openai")
                base_url = Prompt.ask("Base URL (optional)", default="")
                api_key_env = Prompt.ask("Env Var for API Key (optional)")
                
                self.config.config.providers[name] = ProviderConfig(
                    name=name, type=ptype, base_url=base_url if base_url else None, api_key_env=api_key_env if api_key_env else None
                )
            if action == "D":
                name = Prompt.ask("Name to delete")
                if name in self.config.config.providers:
                    del self.config.config.providers[name]

    def mcp_menu(self):
        while True:
            self.console.clear()
            table = Table(title="MCP Servers (Tools)")
            table.add_column("Name")
            table.add_column("Command")
            table.add_column("Enabled")
            
            for s in self.config.config.mcp_servers.values():
                table.add_row(s.name, f"{s.command} {' '.join(s.args)}", str(s.enabled))
            
            self.console.print(table)
            self.console.print("\n[A] Add MCP Server  [T] Toggle  [B] Back")
            action = Prompt.ask("Action").upper()
            
            if action == "B": break
            if action == "A":
                name = Prompt.ask("Server Name (e.g. github)")
                cmd_str = Prompt.ask("Full Command (e.g. npx -y @modelcontextprotocol/server-github)")
                parts = cmd_str.split(" ")
                self.config.config.mcp_servers[name] = MCPServerConfig(
                    name=name, command=parts[0], args=parts[1:]
                )
            if action == "T":
                name = Prompt.ask("Server Name")
                if name in self.config.config.mcp_servers:
                    s = self.config.config.mcp_servers[name]
                    s.enabled = not s.enabled

    def roles_menu(self):
        while True:
            self.console.clear()
            table = Table(title="Roles")
            table.add_column("Name")
            table.add_column("Provider")
            table.add_column("Model")
            table.add_column("MCP Servers")
            
            for r in self.config.config.roles.values():
                table.add_row(r.name, r.provider_name, r.model_id, ", ".join(r.active_mcp_servers))
            
            self.console.print(table)
            self.console.print("\n[A] Add/Edit Role  [S] Set Active  [B] Back")
            action = Prompt.ask("Action").upper()
            
            if action == "B": break
            if action == "A":
                name = Prompt.ask("Role Name")
                
                # Choose Provider
                p_names = list(self.config.config.providers.keys())
                p_name = Prompt.ask("Provider", choices=p_names)
                
                model_id = Prompt.ask("Model ID (e.g. gpt-4o, llama3)")
                prompt = Prompt.ask("System Prompt")
                
                # Toggle MCPs
                mcp_names = list(self.config.config.mcp_servers.keys())
                self.console.print(f"Available MCPs: {mcp_names}")
                selected_mcps_str = Prompt.ask("Active MCPs (comma separated)", default="internal_fs")
                selected_mcps = [s.strip() for s in selected_mcps_str.split(",")]
                
                self.config.config.roles[name] = RoleConfig(
                    name=name, provider_name=p_name, model_id=model_id, system_prompt=prompt, active_mcp_servers=selected_mcps
                )

    def active_settings_menu(self):
        self.console.clear()
        self.console.print(f"Current Active Role: [bold green]{self.config.config.active_role}[/bold green]")
        
        new_role = Prompt.ask("Set Active Role", choices=list(self.config.config.roles.keys()), default=self.config.config.active_role)
        self.config.config.active_role = new_role
