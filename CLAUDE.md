# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Octopus is a CLI framework for orchestrating AI agents using a ReAct (Reasoning + Acting) pattern. It supports multiple LLM providers (OpenAI, Anthropic, Ollama) and implements the Model Context Protocol (MCP) for tool communication.

## Commands

```bash
# Install in development mode
pip install -e .

# Run the application (launches TUI)
octopus

# Run tests
python -m pytest tests/

# Run a specific test
python -m pytest tests/test_config.py -v
```

## Architecture

### Core Components

**Entry Point**: `octopus/main.py` → launches `OctopusApp` (Textual TUI)

**Session Layer** (`octopus/core/session.py`):
- `OctopusSession` - main orchestration class managing the agent loop
- Implements ReAct pattern with up to 15 iterations per user input
- Handles tool calls, delegation between roles, and `ask_user` interrupts
- Uses `_prune_history()` to optimize context by truncating old tool outputs

**Configuration** (`octopus/core/config_store.py`):
- Loads from `config.yaml` (local) or `~/.octopus/config.yaml`
- Three main config types: `ProviderConfig`, `MCPServerConfig`, `RoleConfig`
- Roles define allowed tools via `allowed_tools` list

**LLM Integration** (`octopus/llm/provider_manager.py`):
- Uses `litellm` for unified API across providers
- Model naming: `{provider_type}/{model_id}` (e.g., `openai/gpt-4o`)

**MCP Protocol** (`octopus/mcp/protocol.py`):
- `JSONRPCClient` - spawns MCP servers as subprocesses
- Communicates via JSON-RPC 2.0 over stdin/stdout

**Built-in MCP Server** (`octopus/tools/internal_fs_server.py`):
- Provides: `read_file`, `write_file`, `list_directory`, `run_shell_command`
- Standalone Python script implementing MCP server protocol

### Role System

Roles are defined in `config.yaml` with:
- `provider_name` - links to a provider config
- `model_id` - specific model to use
- `system_prompt` - role instructions
- `allowed_tools` - whitelist of available tools
- `active_mcp_servers` - which MCP servers to connect

Default roles: `architect` (planner), `developer` (executor), `reviewer` (QA)

### Dynamic Tools

These are generated at runtime by `_refresh_dynamic_tools()`:
- `delegate_task(role, instruction)` - pass work to another role
- `ask_user(question, options)` - pause execution for user input
- `request_admin_privileges` - unlock restricted tools

### TUI Layer (`octopus/tui_app.py`)

Built with Textual framework:
- `MessageWidget` - renders chat messages with markdown/code block support
- `QuestionModal` - modal for multi-choice questions from `ask_user`
- `ThinkingWidget` - animated status indicator
- Uses `@work(thread=True)` decorators for async processing

## Key Patterns

1. **Event-Driven Architecture**: Session yields `SessionEvent` objects (types: `status`, `text`, `tool_call`, `tool_result`, `question`, `error`, `stats`)

2. **Tool Filtering**: All tools from MCP servers are filtered through `_filter_tools_by_role()` before being sent to the LLM

3. **Delegation Pattern**: When architect delegates to developer, a sub-conversation is created with its own tool loop (max 5 iterations)

4. **Failover**: If primary provider fails, `_get_fallback_provider()` switches to an alternative

## Configuration Example

```yaml
providers:
  openai_cloud:
    type: "openai"
    api_key_env: "OPENAI_API_KEY"

roles:
  architect:
    provider_name: "openai_cloud"
    model_id: "gpt-4o"
    allowed_tools: ["read_file", "delegate_task", "ask_user"]
    active_mcp_servers: ["internal_fs"]
```

## Environment Variables

- `OPENAI_API_KEY` - for OpenAI provider
- `ANTHROPIC_API_KEY` - for Anthropic provider
- Ollama requires local server at `http://localhost:11434`