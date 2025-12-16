import yaml
import os
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict

# --- Data Models ---

@dataclass
class ProviderConfig:
    name: str  # e.g., "local-ollama", "openai-main"
    type: str  # "openai", "anthropic", "ollama", "deepseek"
    base_url: Optional[str] = None
    api_key_env: Optional[str] = None
    default_model: str = "gpt-4o"
    ollama_models_path: Optional[str] = None  # Ścieżka do lokalnych modeli Ollama
    available_models: List[str] = field(default_factory=list)  # Cache dostępnych modeli
    tool_mode: str = "auto"  # Strategy: "native", "xml_fallback", "auto"

@dataclass
class MCPServerConfig:
    name: str # e.g., "filesystem", "github"
    command: str # e.g., "npx", "python"
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    enabled: bool = True

@dataclass
class RoleConfig:
    name: str
    provider_name: str # Link to ProviderConfig.name
    model_id: str
    system_prompt: str
    temperature: float = 0.7
    # List of MCP server names to enable for this role
    active_mcp_servers: List[str] = field(default_factory=list)
    # List of tool names explicitly allowed for this role
    allowed_tools: List[str] = field(default_factory=list)
    # Autonomy level: "autonomous" (never ask), "balanced" (ask once for plan), "supervised" (always ask)
    autonomy_level: str = "balanced"

@dataclass
class AppConfig:
    providers: Dict[str, ProviderConfig] = field(default_factory=dict)
    mcp_servers: Dict[str, MCPServerConfig] = field(default_factory=dict)
    roles: Dict[str, RoleConfig] = field(default_factory=dict)
    active_role: str = "architect"

# --- Manager ---

class ConfigStore:
    def __init__(self, config_path: str = None):
        if config_path:
            self.config_path = Path(config_path)
        else:
            # Priority: Local config.yaml > User Home Config
            local_config = Path.cwd() / "config.yaml"
            if local_config.exists():
                self.config_path = local_config
            else:
                self.config_path = Path.home() / ".octopus" / "config.yaml"
        
        self.config = AppConfig()
        
        if self.config_path.exists():
            self.load()
            # If load resulted in empty config (e.g. empty file), we might want defaults, 
            # but strictly speaking, user provided file should be respected even if empty.
            # To be safe, if NO providers loaded, maybe fallback? 
            # For now, strictly respect file.
            if not self.config.providers:
                 # Optional: self._ensure_defaults() if you want auto-repair
                 pass
        else:
            self._ensure_defaults()

    def _ensure_defaults(self):
        # Default Providers
        if not self.config.providers:
            self.config.providers["openai"] = ProviderConfig("openai", "openai", api_key_env="OPENAI_API_KEY", default_model="gpt-4o")
            self.config.providers["anthropic"] = ProviderConfig("anthropic", "anthropic", api_key_env="ANTHROPIC_API_KEY", default_model="claude-3-5-sonnet-20241022")
            self.config.providers["ollama_local"] = ProviderConfig("ollama_local", "ollama", base_url="http://localhost:11434", default_model="qwen2.5-coder:latest")

        # Default MCP Server (Internal Filesystem)
        # Note: We will implement an internal python script for this
        if not self.config.mcp_servers:
            self.config.mcp_servers["internal_fs"] = MCPServerConfig(
                name="internal_fs",
                command="python",
                args=["-m", "octopus.tools.internal_fs_server"], # We will build this
                enabled=True
            )

        # Default Roles
        if not self.config.roles:
            self.config.roles["architect"] = RoleConfig(
                "architect", "anthropic", "claude-3-5-sonnet-20241022", 
                "You are a System Architect. Design robust, scalable systems.",
                active_mcp_servers=["internal_fs"]
            )
            self.config.roles["developer"] = RoleConfig(
                "developer", "ollama_local", "qwen2.5-coder:latest",
                "You are an expert Developer. Write clean, working code.",
                active_mcp_servers=["internal_fs"]
            )

    def load(self):
        if not self.config_path.exists():
            return

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if not data: return

                # Load Providers
                providers_data = data.get("providers") or {}
                for k, v in providers_data.items():
                    self.config.providers[k] = ProviderConfig(**v)
                
                # Load MCP
                mcp_data = data.get("mcp_servers") or {}
                for k, v in mcp_data.items():
                    self.config.mcp_servers[k] = MCPServerConfig(**v)

                # Load Roles
                roles_data = data.get("roles") or {}
                for k, v in roles_data.items():
                    self.config.roles[k] = RoleConfig(**v)
                
                self.config.active_role = data.get("active_role", "architect")

        except Exception as e:
            print(f"[Warning] Config load error: {e}")

    def save(self):
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "providers": {k: asdict(v) for k, v in self.config.providers.items()},
            "mcp_servers": {k: asdict(v) for k, v in self.config.mcp_servers.items()},
            "roles": {k: asdict(v) for k, v in self.config.roles.items()},
            "active_role": self.config.active_role
        }
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False)

    def get_role(self, name: str) -> Optional[RoleConfig]:
        return self.config.roles.get(name)

    def get_provider(self, name: str) -> Optional[ProviderConfig]:
        return self.config.providers.get(name)
