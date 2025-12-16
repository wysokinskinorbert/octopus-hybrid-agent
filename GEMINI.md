# Octopus Framework

## Project Overview
Octopus is a CLI-based framework for orchestrating AI agents using a **ReAct (Reasoning + Acting)** pattern. It is designed to autonomously solve complex tasks by coordinating specialized roles (Architect, Developer, Reviewer) and leveraging the **Model Context Protocol (MCP)** for tool integration. The interface is built with **Textual**, providing a rich Terminal User Interface (TUI).

## Architecture

### Core Components
- **Entry Point:** `octopus/main.py` - Launches the `OctopusApp` (Textual TUI).
- **Session Layer (`octopus/core/session.py`):** Manages the agent loop, handling tool calls, delegation, and context management (including history pruning).
- **LLM Integration (`octopus/llm`):** Uses `litellm` to support multiple providers (OpenAI, Anthropic, Ollama) via a unified API.
- **MCP Protocol (`octopus/mcp`):** Implements JSON-RPC 2.0 to communicate with local or remote tool servers.
- **TUI (`octopus/tui_app.py`):** A Textual-based interface for interacting with the agent mesh.

### Role System
Roles are specialized agent configurations defined in `config.yaml`:
- **Architect:** High-level planner. breaks down tasks, creates plans, and delegates to the Developer.
- **Developer:** Executor. Writes code, runs commands, and uses tools to implement the Architect's plan.
- **Reviewer:** QA. Verifies the work against requirements and ensures quality.

### Directory Structure
- `octopus/`: Main package source code.
  - `core/`: Session and configuration logic.
  - `llm/`: Provider management.
  - `mcp/`: Protocol implementation.
  - `tools/`: Built-in tools and servers (e.g., `internal_fs_server.py`).
  - `ui/`: UI components.
- `tests/`: Pytest suite.
- `demo_project/`: Example outputs or workspace.
- `pogoda-dashboard/`: A React/Vite frontend project (likely a demo or component).

## Getting Started

### Prerequisites
- Python 3.x
- Node.js & npm (for `pogoda-dashboard`)
- API Keys (OpenAI, Anthropic) or a local Ollama instance.

### Installation
Install the project in editable mode:
```bash
pip install -e .
```

### Running the Application
Launch the TUI:
```bash
octopus
```
*Note: Ensure your `config.yaml` is correctly set up with active providers.*

## Configuration
The system is driven by `config.yaml` (located in the root or `~/.octopus/`).

### Key Sections:
- **`providers`**: Define LLM backends (e.g., `openai_cloud`, `ollama_local`).
- **`roles`**: Map roles to providers, models, and allowed tools.
- **`mcp_servers`**: Configure tool servers (e.g., `internal_fs`).

### Environment Variables
- `OPENAI_API_KEY`: Required for OpenAI provider.
- `ANTHROPIC_API_KEY`: Required for Anthropic provider.

## Development

### Testing
Run the test suite using pytest:
```bash
python -m pytest tests/
```

### Development Guidelines
- **Agent Workflow:** The standard flow is **Plan (Architect) -> Execute (Developer) -> Verify (Reviewer)**.
- **Tool Usage:** Agents are strictly bound to tools defined in their `allowed_tools` list.
- **Autonomy:** The system is designed for high autonomy. Agents should use tools to verify their own work (e.g., `list_directory` after `write_file`).

## Sub-projects
- **pogoda-dashboard**: A React + Vite application.
  - `cd pogoda-dashboard` (or root `package.json` scripts)
  - `npm install`
  - `npm run dev`
