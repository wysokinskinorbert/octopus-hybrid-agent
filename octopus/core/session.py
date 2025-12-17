import os
import sys
import json
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Generator, Callable
from enum import Enum

from .config_store import ConfigStore, RoleConfig, ProviderConfig
from .logger import SessionLogger
from .task_history import TaskHistory
from .types import TaskSpec, TaskResult
from ..mcp.protocol import JSONRPCClient
from ..llm.provider_manager import ProviderManager
from .adapters.base import BaseAdapter
from .adapters.openai_adapter import OpenAIAdapter
from .adapters.ollama_adapters import OllamaJSONAdapter, OllamaXMLAdapter
from .trajectory_logger import TrajectoryLogger


# Session Mode System (inspired by Claude Code Plan Mode)
class SessionMode(Enum):
    PLAN = "plan"           # Read-only, research phase - ask_user allowed for plan_approval
    EXECUTE = "execute"     # Full tools, implementation phase - ask_user DISABLED
    REVIEW = "review"       # Read-only, verification phase


# Tool categories for mode-based filtering
READ_ONLY_TOOLS = {
    "list_directory", "read_file", "glob", "search_file_content"
}
WRITE_TOOLS = {
    "write_file", "run_shell_command"
}
CONTROL_TOOLS = {
    "delegate_task", "ask_user", "request_admin_privileges"
}


@dataclass
class SessionEvent:
    type: str 
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)

class OctopusSession:
    def __init__(self, role_name: str = None, auto_approve: bool = False):
        self.auto_approve = auto_approve
        self.config_store = ConfigStore()
        self.role_name = role_name if role_name else self.config_store.config.active_role
        self.role_config = self.config_store.get_role(self.role_name)
        self.provider_config = self.config_store.get_provider(self.role_config.provider_name)
        
        self.logger = SessionLogger()
        self.logger.log_event("init", f"Session initialized for role: {self.role_name}", {"provider": self.provider_config.name})
        
        self.task_history = TaskHistory()
        
        # Trajectory logging for observability
        self.trajectory = TrajectoryLogger(session_id=f"session_{int(time.time())}")
        
        self.llm_manager = ProviderManager()
        self.history = [{"role": "system", "content": self.role_config.system_prompt}]
        
        self.debug_mode = False
        
        self.mcp_clients = {}
        self.tools_map = {}
        self.llm_tools = []
        self.sudo_tools = [] 
        
        self.session_stats = {}
        self.active_provider = self.provider_config
        self.active_model_id = self.role_config.model_id
        
        self.global_context_memory = []
        self.abort_flag = False
        self.waiting_tool_id = None
        self.current_task_id = None

        # Task completion tracking
        self.current_task_start = None
        self.current_task_description = ""
        self.last_error = None
        self.last_tool_call = None

        # Autonomy control flags
        self.plan_approved = False  # After first ask_user approval, set to True
        self.ask_user_count = 0     # Track number of questions asked per task
        self.max_ask_user_per_task = 2  # Maximum questions allowed per task

        # Delegation limit control
        self.delegation_counts = {}  # {"developer": 0, "reviewer": 0}
        self.max_delegations_per_role = 3  # Max delegations to same role per user message

        # Post-approval ask_user tracking (to prevent infinite loops)
        self.post_approval_ask_count = 0

        # Session Mode Control (Claude Code style)
        self.session_mode = SessionMode.PLAN  # Start in PLAN mode
        self.plan_text = None  # Store the approved plan text
        self.question_context = None  # Track what type of question we're asking

        # Text-based question detection (model asks in text instead of using ask_user tool)
        self.pending_text_question = False  # Flag when model asks question in response text

    def resume_session(self, task_id: str, log_path: str):
        """Restores session history from a log file."""
        self.current_task_id = task_id
        if not os.path.exists(log_path):
            return False
        
        try:
            # Rebuild history from logs
            restored_msgs = []
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        typ = entry.get("type")
                        content = entry.get("content")
                        # Basic reconstruction mapping
                        if typ == "user_msg":
                            restored_msgs.append({"role": "user", "content": content})
                        elif typ == "text" and entry.get("metadata", {}).get("role") == self.role_name:
                            restored_msgs.append({"role": "assistant", "content": content})
                        elif typ == "tool_call":
                            # Simplification: we don't fully restore tool call objects here as it's complex,
                            # but we can add summary or just last messages.
                            # For better context, we append tool usage as text log for now
                            pass 
                        elif typ == "tool_result":
                            pass
                    except: continue
            
            # Limit restored context to avoid overflow, keep last 20 messages
            if len(restored_msgs) > 20:
                restored_msgs = restored_msgs[-20:]
            
            self.history.extend(restored_msgs)
            
            # Inject Review Prompt with Resilience Warning
            self.history.append({
                "role": "system", 
                "content": """[SYSTEM]: SESSION RESUMED. 
                1. You are continuing a previous task. Review the context above.
                2. WARNING: The environment (files, directories) may have changed (e.g. moved) since this session was saved.
                3. CRITICAL: Before using any file path, VERIFY it exists using `list_directory` or `glob`. 
                4. If a project directory is missing, DO NOT recreate it immediately. SEARCH for it. If not found, ASK the user."""
            })
            return True
        except Exception as e:
            print(f"Resume failed: {e}")
            return False

    def abort(self):
        self.abort_flag = True
        self.logger.log_event("action", "Abort signal received")

    def initialize(self) -> Generator[SessionEvent, None, None]:
        for event in self._initialize_impl():
            self.logger.log_event(event.type, event.content, event.metadata)
            yield event

    def _handle_mcp_notification(self, msg: Dict[str, Any]):
        """Handle incoming JSON-RPC notifications from MCP servers."""
        method = msg.get("method")
        params = msg.get("params", {})
        
        if method == "notifications/tool_progress":
            output = params.get("output", "")
            # Log directly to the streaming queue if possible, or just log event
            # Since this is running in a background thread of JSONRPCClient, 
            # we need to be careful. But Session logger is thread-safe.
            
            # We want this to appear as a 'streaming' event in yield loop?
            # Creating a generator from a callback is tricky.
            # Instead, we'll log it and let the UI poll or use a callback mechanism if Session supports it.
            # BUT, the `initialize()` and `run_iteration()` are generators.
            # A notification happens asynchronously.
            
            # Current Session architecture yields events. 
            # If we are inside `run_iteration`, we are iterating over `process_user_input`.
            # We need a way to inject this event into the stream.
            
            # For this MVP, we will use a queue or a direct TUI callback if available?
            # No, 'Session' should be UI agnostic.
            
            # Let's log it as a special event type that the logger handles?
            self.logger.log_event("streaming", output)
            
            # IMPORTANT: The TUI relies on the generator yielding the event.
            # If the generator is blocked waiting for tool result, it won't yield notification.
            # However, `process_user_input` yields from `_run_step`.
            # `tool_result` is creating by waiting for `client.call_tool`.
            # `client.call_tool` waits for response.
            # While waiting, `_read_response` receives notifications and calls this handler.
            # So this handler runs ON THE MAIN THREAD (or whatever thread called call_tool).
            # So we can yield? No, "yield" is not a function we can call.
            
            # We can use a side-channel callback provided to Session?
            # Or simpler: The Session logger can have a 'on_event' callback?
            if hasattr(self, 'on_event_callback') and self.on_event_callback:
                self.on_event_callback(SessionEvent("streaming", output))

    def _filter_tools_by_role(self, all_tools: List[Dict], role_config: RoleConfig) -> List[Dict]:
        """
        Filtruje listę narzędzi, zwracając tylko te, które są dozwolone dla danej roli
        zgodnie z `role_config.allowed_tools`.
        """
        if not role_config.allowed_tools:
            # If allowed_tools is empty, assume no tools are allowed by default,
            # or handle as per desired strictness (e.g., allow all or none).
            # For now, if empty, no tools are explicitly allowed.
            return []

        filtered_tools = []
        for tool_def in all_tools:
            tool_name = tool_def['function']['name']
            if tool_name in role_config.allowed_tools:
                filtered_tools.append(tool_def)
        return filtered_tools

    def _initialize_impl(self) -> Generator[SessionEvent, None, None]:
        yield SessionEvent("status", "Initializing MCP Servers...")
        
        all_potential_tools = [] # Temporarily store all discovered tools
        
        for server_name in self.role_config.active_mcp_servers:
            server_conf = self.config_store.config.mcp_servers.get(server_name)
            if not server_conf or not server_conf.enabled:
                continue
            
            try:
                cmd = server_conf.command
                if cmd.lower() in ["python", "py", "python3"]:
                    cmd = sys.executable
                
                env = server_conf.env.copy() if server_conf.env else os.environ.copy()
                full_env = os.environ.copy()
                if server_conf.env: full_env.update(server_env)
                
                cwd = os.getcwd()
                current_pythonpath = full_env.get("PYTHONPATH", "")
                full_env["PYTHONPATH"] = f"{cwd}{os.pathsep}{current_pythonpath}"

                current_pythonpath = full_env.get("PYTHONPATH", "")
                full_env["PYTHONPATH"] = f"{cwd}{os.pathsep}{current_pythonpath}"

                client = JSONRPCClient(
                    cmd, 
                    server_conf.args, 
                    env=full_env,
                    notification_handler=self._handle_mcp_notification
                )
                client.start()
                self.mcp_clients[server_name] = client
                
                tools = client.list_tools()
                for tool in tools:
                    self.tools_map[tool.name] = client
                    tool_def = {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": tool.input_schema
                        }
                    }
                    all_potential_tools.append(tool_def)
                        
                yield SessionEvent("status", f"Connected to {server_name} ({len(tools)} tools)")
                
            except Exception as e:
                yield SessionEvent("error", f"Failed to connect to {server_name}: {e}")

        # Filter initial tools based on role configuration
        self.llm_tools = self._filter_tools_by_role(all_potential_tools, self.role_config)
        self._refresh_dynamic_tools() # Apply dynamic tools and final filtering

    def _get_model_adapter(self, model_id: str) -> BaseAdapter:
        """
        Factory method to return the correct protocol adapter for a given model.
        """
        if "gpt" in model_id or "openai" in model_id:
            return OpenAIAdapter()
        elif "mistral" in model_id:
            return OllamaXMLAdapter()
        else:
            # Default to JSON for Qwen and others
            return OllamaJSONAdapter()

    def _refresh_dynamic_tools(self):
        # Start with the already filtered static tools from _initialize_impl
        base_tools = self.llm_tools.copy() 
        
        # Define dynamic tools (delegate_task, ask_user, request_admin_privileges)
        # These are generated based on available roles or special conditions
        dynamic_tools = []

        available_roles = list(self.config_store.config.roles.keys())
        if self.role_name in available_roles: available_roles.remove(self.role_name)
        
        if available_roles:
            dynamic_tools.append({
                "type": "function",
                "function": {
                    "name": "delegate_task",
                    "description": "Delegate a structured task to the Development Team. Provide a clear specification.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "goal": {"type": "string", "description": "High-level goal of the task"},
                            "constraints": {
                                "type": "array", 
                                "items": {"type": "string"},
                                "description": "List of constraints (e.g. 'Use React', 'No external libs')"
                            },
                            "focus_files": {
                                "type": "array", 
                                "items": {"type": "string"},
                                "description": "List of files to modify or focus on"
                            },
                            "verification_steps": {
                                "type": "array", 
                                "items": {"type": "string"},
                                "description": "Steps the Reviewer should take to verify success"
                            }
                        },
                        "required": ["goal", "constraints", "verification_steps"]
                    }
                }
            })

        dynamic_tools.append({
            "type": "function",
            "function": {
                "name": "ask_user",
                "description": """Ask user ONLY for:
- Initial plan approval (ONE time only)
- Strategic decisions (architecture, technology choices)
- Destructive operations (delete critical files, overwrite data)
- Ambiguous requirements needing clarification

DO NOT ask for:
- Technical implementation details
- File paths, naming conventions, code style
- Continuation of approved plan
- Obvious next steps
- Confirmation of routine operations""",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string", "description": "Clear, concise question for the user"},
                        "reason": {
                            "type": "string",
                            "enum": ["plan_approval", "strategic_decision", "destructive_operation", "ambiguous_requirement"],
                            "description": "Why user input is needed - helps enforce autonomy rules"
                        },
                        "options": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of suggested short answers (e.g. ['Yes', 'No', 'Explain'])"
                        }
                    },
                    "required": ["question", "reason"]
                }
            }
        })

        if self.sudo_tools: # `sudo_tools` are added externally if emergency mode is enabled
            dynamic_tools.append({
                "type": "function",
                "function": {
                    "name": "request_admin_privileges",
                    "description": "Unlock write permissions (write_file, run_shell). USE ONLY IF USER APPROVES.",
                    "parameters": {"type": "object", "properties": {}}
                }
            })
        
        # Combine static and dynamic tools, then apply final filtering based on role_config.allowed_tools
        combined_tools = base_tools + dynamic_tools
        self.llm_tools = self._filter_tools_by_role(combined_tools, self.role_config)

    def shutdown(self):
        self.logger.log_event("shutdown", "Session ended")
        for c in self.mcp_clients.values():
            c.stop()

    def _update_stats(self, model_id, usage_obj, role: str = None):
        if not usage_obj: return
        count = getattr(usage_obj, "total_tokens", 0)

        # Track per model
        self.session_stats[model_id] = self.session_stats.get(model_id, 0) + count

        # Track per role+model combination
        if role:
            if "by_role" not in self.session_stats:
                self.session_stats["by_role"] = {}
            key = f"{role}:{model_id}"
            self.session_stats["by_role"][key] = self.session_stats["by_role"].get(key, 0) + count

    def _get_fallback_provider(self, current_name: str, exclude: List[str] = None) -> Any:
        exclude = exclude or []
        for p in self.config_store.config.providers.values():
            if p.name != current_name and p.name not in exclude:
                return p
        return None

    def enable_emergency_tools(self):
        self.logger.log_event("action", "Emergency tools unlocked manually")
        if self.sudo_tools:
            self.llm_tools.extend(self.sudo_tools)
            self.sudo_tools = []
            return True
        return False


    def _run_sub_agent_loop(self, target_role: str, task_spec: TaskSpec, max_retries: int = 3) -> Generator[SessionEvent, None, TaskResult]:
        """
        Executes the Autonomous Hybrid Handoff Loop:
        1. Developer attempts task (with clean context).
        2. Reviewer verifies result.
        3. If rejected, Developer retries (Local Loop).
        4. If approved or max retries reached, returns result.
        """
        
        # 1. Setup Developer Context (Pruned)
        dev_role = "developer"
        dev_cfg = self.config_store.get_role(dev_role)
        dev_prov = self.config_store.get_provider(dev_cfg.provider_name)
        
        base_history = [
            {"role": "system", "content": dev_cfg.system_prompt},
            {"role": "user", "content": f"TASK SPECIFICATION:\n{task_spec.to_prompt()}\n\nExecute this task. Use tools. When done, output a final report."}
        ]
        
        current_history = base_history.copy()
        current_model_id = dev_cfg.model_id
        
        attempt = 1
        last_result = ""
        
        while attempt <= max_retries:
            yield SessionEvent("status", f"Developer Attempt {attempt}/{max_retries}", {
                "role": dev_role, "model_id": current_model_id, "iteration": attempt, "max_iterations": max_retries
            })
            
            # --- Developer Phase ---
            dev_output = ""
            # Simple linear execution for developer (could be loop if needed, but keeping it simple for now)
            # We treat the developer as a single-shot or short-loop agent here.
            # actually we need a small loop here to allow tool usage
            
            # --- New Adapter-based Execution Loop ---

            # 1. Select Adapter
            adapter = self._get_model_adapter(current_model_id)

            # 2. Prepare Messages (System Protocol Injection)
            dev_tools = self._filter_tools_by_role(self.llm_tools + self.sudo_tools, dev_cfg)

            dev_loop_max = 5
            for i in range(dev_loop_max):

                # Update status
                yield SessionEvent("status", f"Developer Attempt {attempt}/{max_retries} (Iter {i+1})", {
                     "role": dev_role, "model_id": current_model_id, "iteration": attempt, "max_iterations": max_retries
                })

                # Prepare context using adapter
                adapter_messages = adapter.prepare_messages(current_history, tools=dev_tools)

                # Streaming Response
                response_msg = None
                usage = None
                dev_output = ""

                try:
                    # Provide TOOLS to llm_manager only if it's OpenAI adapter (native), 
                    # otherwise local models might get confused if we don't hide them.

                    for stream_event in self.llm_manager.chat_complete_stream(
                        dev_prov, current_model_id, adapter_messages, tools=dev_tools
                    ):
                        if stream_event["type"] == "chunk":
                            content = stream_event["content"]
                            dev_output += content
                            yield SessionEvent("streaming", content)
                        elif stream_event["type"] == "done":
                            response_msg = stream_event["message"]
                            usage = stream_event["usage"]
                        elif stream_event["type"] == "error":
                            raise Exception(stream_event["error"])

                    if not response_msg:
                         # If stream ended with no message object (but we have text), construct a dummy one
                         if dev_output:
                             # Dummy object for flow continuity if needed, but we rely on dev_output
                             pass 
                         else:
                            raise Exception("Stream ended without message")

                    self._update_stats(current_model_id, usage, role=dev_role)
                    yield SessionEvent("stats", "", {"stats": self.session_stats})

                    if self.debug_mode:
                        yield SessionEvent("log", f"[DEBUG RAW] {dev_output}", {"style": "dim blue"})

                    # 3. Parse Response via Adapter
                    llm_tool_calls = getattr(response_msg, 'tool_calls', None) if response_msg else None
                    parsed_response = adapter.parse_response(dev_output, tool_calls=llm_tool_calls)

                    if self.debug_mode:
                        yield SessionEvent("log", f"[DEBUG PARSED] {json.dumps(parsed_response.get('tool_calls'), default=str)}", {"style": "dim cyan"})

                    # Add assistant message to history (standardized)
                    current_history.append({
                        "role": "assistant", 
                        "content": parsed_response["content"], 
                        "tool_calls": parsed_response.get("tool_calls") 
                    })

                    # 4. Execute Tools
                    executed_any = False
                    if parsed_response.get("tool_calls"):
                        for tc in parsed_response["tool_calls"]:
                            # Handle standard OpenAI format (nested function)
                            if "function" in tc:
                                fn_name = tc["function"]["name"]
                                fn_args_raw = tc["function"]["arguments"]
                                if isinstance(fn_args_raw, str):
                                    try:
                                        fn_args = json.loads(fn_args_raw)
                                    except json.JSONDecodeError:
                                        fn_args = {}
                                        yield SessionEvent("error", f"Error parsing JSON args for {fn_name}")
                                else:
                                    fn_args = fn_args_raw
                                call_id = tc.get("id", "call_unknown")
                            else:
                                # Fallback (Legacy/Flat)
                                fn_name = tc.get("name")
                                fn_args = tc.get("arguments", {})
                                call_id = tc.get("id", "call_unknown")

                            if not fn_name:
                                continue

                            yield SessionEvent("tool_call", f"{dev_role} calls {fn_name}", {"role": dev_role, "name": fn_name})

                            # Execute
                            tool_res = f"Error: Tool {fn_name} not found"
                            if fn_name in self.tools_map:
                                try:
                                    res_obj = self.tools_map[fn_name].call_tool(fn_name, fn_args)
                                    tool_res = str(res_obj)
                                    tool_res = str(res_obj)
                                except Exception as e:
                                    tool_res = f"Tool Execution Error: {e}"

                            current_history.append({
                                "role": "tool", "tool_call_id": call_id, "name": fn_name, "content": tool_res
                            })
                            yield SessionEvent("tool_result", f"Result: {tool_res[:50]}...", {"role": dev_role})
                            executed_any = True

                    if not executed_any:
                        # No tools called -> Assume completion or request for info
                        break

                except Exception as e:
                    yield SessionEvent("error", f"Developer Error: {e}")
                    break

            last_result = dev_output

            # --- Reviewer Phase ---
            rev_role = "reviewer"
            rev_cfg = self.config_store.get_role(rev_role)

            if not rev_cfg:
                 # No reviewer configured -> Auto-accept
                return TaskResult(status="success", summary=last_result, verification_result="Skipped (No Reviewer)")

            rev_prov = self.config_store.get_provider(rev_cfg.provider_name)

            verification_prompt = (
                f"ORIGINAL SPEC:\n{task_spec.to_prompt()}\n\n"
                f"DEVELOPER OUTPUT:\n{last_result}\n\n"
                "Verify if the goal and constraints are met.\n"
                "If YES, start response with 'APPROVED'.\n"
                "If NO, provided constructive feedback to fix the issues."
            )

            yield SessionEvent("log", "Reviewing work...", {"role": "system", "style": "bold yellow"})

            rev_msgs = [
                {"role": "system", "content": rev_cfg.system_prompt},
                {"role": "user", "content": verification_prompt}
            ]

            try:
                # Streaming Reviewer Response
                rev_resp = None
                rev_usage = None
                feedback = ""
    
                for stream_event in self.llm_manager.chat_complete_stream(
                    rev_prov, rev_cfg.model_id, rev_msgs, tools=self._filter_tools_by_role(self.llm_tools, rev_cfg)
                ):
                    if stream_event["type"] == "chunk":
                        content = stream_event["content"]
                        feedback += content
                        yield SessionEvent("streaming", content)
                    elif stream_event["type"] == "done":
                        rev_resp = stream_event["message"]
                        rev_usage = stream_event["usage"]
                    elif stream_event["type"] == "error":
                         raise Exception(stream_event["error"])

                if not rev_resp:
                     raise Exception("Stream ended without message")

                self._update_stats(rev_cfg.model_id, rev_usage, role=rev_role)
                yield SessionEvent("stats", "", {"stats": self.session_stats})
    
                # feedback = rev_resp.content or "" # Computed during stream
                # yield SessionEvent("text", f"[Reviewer]: {feedback}", {"role": rev_role}) # Removed to keep widget open
    
                if "APPROVED" in feedback.upper():
                    yield SessionEvent("log", "Task Verified & Approved!", {"role": "system", "style": "bold green"})
                    return TaskResult(status="success", summary=last_result, verification_result=feedback)
    
                # Feedback Loop
                yield SessionEvent("log", f"Verification Failed. Retrying ({attempt}/{max_retries})...", {"role": "system", "style": "bold red"})
    
                # Feed feedback back to developer
                current_history.append({
                    "role": "user", 
                    "content": f"[REVIEWER FEEDBACK]: {feedback}\n\nPlease fix these issues and provide the updated output."
                })
                attempt += 1
    
            except Exception as e:
                yield SessionEvent("error", f"Reviewer Error: {e}")
                break

        return TaskResult(status="failure", summary=last_result, verification_result="Max retries reached")









    def process_user_input(self, user_input: str) -> Generator[SessionEvent, None, None]:
        self.abort_flag = False
        self.delegation_counts = {}  # Reset delegation counts for new user message
        self.post_approval_ask_count = 0  # Reset ask_user counter for new user message
        self.logger.log_event("user_msg", user_input)
        for event in self._process_impl(user_input):
            self.logger.log_event(event.type, event.content, event.metadata)
            yield event
            if self.abort_flag:
                yield SessionEvent("error", "🛑 Operation Cancelled by User.")
                break

    def _get_tools_for_mode(self) -> List[Dict]:
        """
        Returns tools available for current session mode (Claude Code style).

        PLAN mode: read-only + ask_user (for plan_approval only)
        EXECUTE mode (architect): read-only + delegate_task ONLY (forces delegation!)
        EXECUTE mode (other roles): all tools EXCEPT ask_user
        REVIEW mode: read-only only
        """
        if self.session_mode == SessionMode.PLAN:
            # Plan mode: read-only tools + ask_user for plan approval
            return [t for t in self.llm_tools
                    if t['function']['name'] in READ_ONLY_TOOLS
                    or t['function']['name'] == 'ask_user']

        elif self.session_mode == SessionMode.EXECUTE:
            # CRITICAL: Architect must DELEGATE, not execute himself!
            if self.role_name == "architect":
                # Architect in EXECUTE mode: only delegate_task + read-only tools
                # This forces the architect to delegate work instead of doing it himself
                allowed_for_architect = READ_ONLY_TOOLS | {"delegate_task"}
                return [t for t in self.llm_tools
                        if t['function']['name'] in allowed_for_architect]
            else:
                # Other roles (developer, etc.): all tools EXCEPT ask_user
                return [t for t in self.llm_tools
                        if t['function']['name'] != 'ask_user']

        elif self.session_mode == SessionMode.REVIEW:
            # Review mode: read-only only
            return [t for t in self.llm_tools
                    if t['function']['name'] in READ_ONLY_TOOLS]

        return self.llm_tools

    def _prune_history(self, history: List[Dict], keep_last_n: int = 6) -> List[Dict]:
        """
        Optimizes history by truncating old tool outputs.
        Keeps system prompts and the last 'keep_last_n' messages intact.
        Increased to 6 for better context retention with local models.
        """
        pruned = []
        total_msgs = len(history)

        for i, msg in enumerate(history):
            # Always keep System prompts
            if msg.get("role") == "system":
                pruned.append(msg)
                continue

            # Keep recent messages intact
            if i >= total_msgs - keep_last_n:
                pruned.append(msg)
                continue

            # Truncate old tool outputs (heavy file reads etc.)
            # Increased threshold to 500 chars for better context
            if msg.get("role") == "tool":
                content = msg.get("content", "")
                if len(content) > 500:
                    new_msg = msg.copy()
                    new_msg["content"] = f"{content[:200]}... [TRUNCATED: {len(content)} chars] ...{content[-200:]}"
                    pruned.append(new_msg)
                else:
                    pruned.append(msg)
            else:
                # Keep user/assistant messages
                pruned.append(msg)

        return pruned

    def _process_impl(self, user_input: str) -> Generator[SessionEvent, None, None]:
        # Handle "Resume after ask_user" logic
        # Handle "Resume after ask_user" logic
        if self.waiting_tool_id:
            # AUTO-APPROVE LOGIC
            if self.auto_approve and self.question_context == "plan_approval":
                user_input = "yes" # Force approval
                yield SessionEvent("log", "[AUTO-APPROVE] Plan automatically approved by flag.", {"style": "green bold"})

            self.history.append({
                "role": "tool",
                "tool_call_id": self.waiting_tool_id,
                "name": "ask_user",
                "content": user_input
            })
            self.waiting_tool_id = None

            # MODE TRANSITION: PLAN → EXECUTE (Claude Code style)
            approval_responses = ["yes", "tak", "ok", "proceed", "go", "start", "approve", "approved", "y"]
            user_response_lower = user_input.strip().lower()

            if self.question_context == "plan_approval" and user_response_lower in approval_responses:
                # Transition to EXECUTE mode
                self.session_mode = SessionMode.EXECUTE
                self.plan_approved = True
                self.question_context = None  # Clear context

                yield SessionEvent("status", "✓ Plan approved. Entering EXECUTE mode.", {"style": "green bold"})
                yield SessionEvent("log", f"[MODE TRANSITION] PLAN → EXECUTE (user said: {user_input})", {"style": "green"})

                # Add strong system instruction for EXECUTE mode
                self.history.append({
                    "role": "system",
                    "content": "[MODE: EXECUTE] Plan approved by user. You are NOW in EXECUTE mode. "
                               "The ask_user tool is DISABLED. Execute the plan step-by-step using delegate_task and other tools. "
                               "DO NOT ask any more questions. Proceed autonomously until completion."
                })
            else:
                # Non-approval response (e.g., user said "no" or asked for changes)
                self.question_context = None
                yield SessionEvent("log", f"User answered: {user_input}", {"style": "dim"})

                # Stay in PLAN mode, let model adjust the plan
                self.history.append({
                    "role": "system",
                    "content": f"[MODE: PLAN] User response: '{user_input}'. Adjust your plan based on this feedback. "
                               "Use ask_user(reason='plan_approval') again when ready to propose an updated plan."
                })
        else:
            # New User Input

            # CHECK FOR TEXT-BASED QUESTION APPROVAL (model asked in text, not via ask_user tool)
            approval_responses = ["yes", "tak", "ok", "proceed", "go", "start", "approve", "approved", "y", "sure", "please", "proszę"]
            user_response_lower = user_input.strip().lower()

            if self.pending_text_question and self.session_mode == SessionMode.PLAN and user_response_lower in approval_responses:
                # User approved a text-based question - transition to EXECUTE mode
                self.session_mode = SessionMode.EXECUTE
                self.plan_approved = True
                self.pending_text_question = False

                yield SessionEvent("status", "✓ Plan approved (via text). Entering EXECUTE mode.", {"style": "green bold"})
                yield SessionEvent("log", f"[MODE TRANSITION] PLAN → EXECUTE (text-question approval: '{user_input}')", {"style": "green"})

                # Add strong system instruction for EXECUTE mode
                self.history.append({"role": "user", "content": user_input})
                self.history.append({
                    "role": "system",
                    "content": "[MODE: EXECUTE] User approved the plan. You are NOW in EXECUTE mode. "
                               "The ask_user tool is DISABLED. DO NOT ask any more questions - neither via tool NOR in text. "
                               "Execute the plan step-by-step using delegate_task and other tools. "
                               "Proceed autonomously until completion."
                })
                # Continue to next iteration - model will now execute in EXECUTE mode
            else:
                self.pending_text_question = False  # Reset flag for non-approval responses

            duplicate_found = False

            # Check similarity only for substantial inputs BEFORE adding new task
            if len(user_input) > 10:
                duplicate = self.task_history.check_similarity(user_input)
                if duplicate:
                    # If duplicate found, warn but don't stop (unless we want strict dedup)
                    # Note: check_similarity checks existing history.
                    yield SessionEvent("text", f"⚠️ **Possible Duplicate Task**\nFound similar task from {duplicate['date']}:\n> {duplicate['prompt']}\n\nStatus: {duplicate['status']}", {"role": "system"})
                    duplicate_found = True

            if not self.current_task_id:
                # Heuristic: Don't create new task history for short answers/confirmations
                clean_input = user_input.strip().lower()
                is_short_answer = len(clean_input) < 5 or clean_input in ["start", "stop", "exit", "quit", "help", "yes", "no", "ok"]
                
                if not is_short_answer:
                    # Start new task tracking
                    log_path = self.logger.log_file
                    self.current_task_id = self.task_history.add_task(user_input, str(log_path), "in_progress")
            
            self.history.append({"role": "user", "content": user_input})
        
        for _ in range(15): 
            if self.abort_flag: return

            yield SessionEvent("status", f"Thinking ({self.active_provider.name})...")
            
            response_msg = None
            usage = None
            tried_providers = set()
            
            while True:
                if self.abort_flag: return
                try:
                    # OPTIMIZATION: Prune history before sending to LLM
                    optimized_history = self._prune_history(self.history)
                    
                    # Inject mode-aware guidance (Claude Code style)
                    current_history = optimized_history.copy()

                    # Mode-specific system prompts
                    mode_prompts = {
                        SessionMode.PLAN: (
                            "[MODE: PLAN] You are in PLAN MODE. "
                            "Research the task using read-only tools (list_directory, read_file, glob, search_file_content). "
                            "Create a brief 3-5 step plan. "
                            "CRITICAL: When ready for approval, you MUST use the ask_user tool with reason='plan_approval'. "
                            "DO NOT ask questions in your text response like 'Would you like to proceed?' - use the ask_user TOOL instead. "
                            "You can ONLY use read-only tools and ask_user in this mode."
                        ),
                        SessionMode.EXECUTE: (
                            "[MODE: EXECUTE] Plan approved. You are in EXECUTE MODE. "
                            "You MUST use delegate_task to assign work to developer - DO NOT execute tasks yourself. "
                            "You only have access to delegate_task and read-only tools. "
                            "The write_file and run_shell_command tools are NOT available to you - the developer has them. "
                            "DO NOT ask questions. Proceed autonomously by delegating work."
                        ),
                        SessionMode.REVIEW: (
                            "[MODE: REVIEW] You are in REVIEW MODE. "
                            "Verify the completed work using read-only tools. "
                            "Report findings and status."
                        )
                    }

                    current_history.append({
                        "role": "system",
                        "content": mode_prompts[self.session_mode]
                    })

                    # Get tools based on current session mode (Claude Code style)
                    active_tools = self._get_tools_for_mode()

                    # Use streaming for slow providers (Ollama) to provide real-time feedback
                    use_streaming = self.active_provider.type == "ollama"

                    if use_streaming:
                        response_msg = None
                        usage = None
                        # XML filtering state dla streamingu
                        xml_buffer = ""
                        inside_xml = False

                        for stream_event in self.llm_manager.chat_complete_stream(
                            self.active_provider, self.active_model_id, current_history,
                            tools=active_tools if active_tools else None,
                            temperature=self.role_config.temperature
                        ):
                            if stream_event["type"] == "chunk":
                                content = stream_event["content"]

                                # Wykryj początek XML bloku <tool_code>
                                if "<tool_code>" in content or "<tool" in content:
                                    inside_xml = True

                                # Jeśli wewnątrz XML - buforuj, nie emituj do UI
                                if inside_xml:
                                    xml_buffer += content
                                    if "</tool_code>" in content:
                                        inside_xml = False
                                        xml_buffer = ""  # Reset bufora
                                    continue  # NIE emituj do UI

                                # Tylko czysty tekst (poza XML) idzie do streaming
                                yield SessionEvent("streaming", content, {
                                    "role": self.role_name,
                                    "model_id": self.active_model_id
                                })
                            elif stream_event["type"] == "done":
                                response_msg = stream_event["message"]
                                usage = stream_event["usage"]
                            elif stream_event["type"] == "error":
                                raise Exception(stream_event["error"])

                        if not response_msg:
                            raise Exception("Streaming completed without final message")
                    else:
                        # Standard non-streaming call for fast providers
                        response_msg, usage = self.llm_manager.chat_complete(
                            self.active_provider, self.active_model_id, current_history,
                            tools=active_tools if active_tools else None,
                            temperature=self.role_config.temperature
                        )



                    self._update_stats(self.active_model_id, usage, role=self.role_name)
                    yield SessionEvent("stats", "", {"stats": self.session_stats})
                    break 
                except Exception as e:
                    yield SessionEvent("error", f"Provider error: {e}")
                    tried_providers.add(self.active_provider.name)
                    
                    fallback = self._get_fallback_provider(self.active_provider.name, exclude=list(tried_providers))
                    if fallback:
                        original_model = self.active_model_id
                        yield SessionEvent("log", f"Failover: Switching provider {self.active_provider.name} -> {fallback.name}, keeping model {original_model}", {
                            "role": "system",
                            "from_provider": self.active_provider.name,
                            "to_provider": fallback.name,
                            "model_id": original_model
                        })
                        self.active_provider = fallback
                        # Don't change model_id - keep the role's configured model
                        continue
                    else:
                        yield SessionEvent("error", "No fallback available (all providers tried).")
                        return

            self.history.append(response_msg)

            if response_msg.content:
                 yield SessionEvent("text", response_msg.content, {
                     "role": self.role_name,
                     "model_id": self.active_model_id,
                     "provider": self.active_provider.name
                 })

                 # DETECT TEXT-BASED QUESTIONS (model asks in text instead of using ask_user)
                 # This is a common issue where models ask "Would you like to proceed?" in text
                 question_patterns = [
                     "would you like to proceed",
                     "shall i proceed",
                     "do you want me to",
                     "should i continue",
                     "can i proceed",
                     "proceed with this plan",
                     "approve this plan",
                     "is this ok",
                     "is that ok",
                     "czy mogę kontynuować",
                     "czy kontynuować",
                     "czy zatwierdzasz",
                     "czy chcesz",
                 ]
                 content_lower = response_msg.content.lower()
                 detected_pattern = None
                 for pattern in question_patterns:
                     if pattern in content_lower:
                         detected_pattern = pattern
                         break

                 if detected_pattern:
                     if self.session_mode == SessionMode.PLAN:
                         # In PLAN mode - flag for user response handling
                         self.pending_text_question = True
                         yield SessionEvent("log", f"Detected text-based question in PLAN mode (pattern: '{detected_pattern}')", {"style": "dim cyan"})

                     elif self.session_mode == SessionMode.EXECUTE:
                         # In EXECUTE mode - block the question and force continuation
                         self.post_approval_ask_count += 1
                         yield SessionEvent("log", f"Blocked text-based question in EXECUTE mode (pattern: '{detected_pattern}')", {"style": "dim yellow"})

                         # Add system message to force execution
                         self.history.append({
                             "role": "system",
                             "content": "[SYSTEM] EXECUTE MODE - Questions are NOT allowed. "
                                        "You asked a question in text which is forbidden. "
                                        "Execute the plan NOW using delegate_task. DO NOT ask anything else."
                         })

                         if self.post_approval_ask_count >= 3:
                             yield SessionEvent("error", "Model keeps asking questions in EXECUTE mode - forcing action", {"style": "red"})
                         # Continue loop to get model's next response
                         continue

            if hasattr(response_msg, 'tool_calls') and response_msg.tool_calls:
                for tc in response_msg.tool_calls:
                    if self.abort_flag: return

                    fn_name = tc.function.name
                    fn_args = json.loads(tc.function.arguments)
                    
                    if fn_name == "ask_user":
                        question = fn_args.get("question")
                        options = fn_args.get("options", [])
                        reason = fn_args.get("reason", "unknown")

                        # MODE-AWARE ask_user handling (Claude Code style)

                        # 1. Block ask_user in EXECUTE mode (physically shouldn't happen but fail-safe)
                        if self.session_mode == SessionMode.EXECUTE:
                            self.post_approval_ask_count += 1
                            if self.post_approval_ask_count >= 3:
                                result_str = "[CRITICAL] EXECUTE MODE - ask_user is DISABLED. You have tried 3 times. Execute the plan NOW using delegate_task."
                                yield SessionEvent("error", f"Model keeps asking in EXECUTE mode - forcing stop", {"style": "red"})
                            else:
                                result_str = "[SYSTEM] You are in EXECUTE MODE. The ask_user tool is disabled. Proceed with the plan using delegate_task or other tools."
                            yield SessionEvent("log", f"Blocked ask_user in EXECUTE mode: {question}", {"style": "dim yellow"})
                            self.history.append({"role": "tool", "tool_call_id": tc.id, "name": fn_name, "content": result_str})
                            continue

                        # 2. Block ask_user in REVIEW mode
                        if self.session_mode == SessionMode.REVIEW:
                            result_str = "[SYSTEM] You are in REVIEW MODE. No questions allowed. Use read-only tools to verify and report findings."
                            yield SessionEvent("log", f"Blocked ask_user in REVIEW mode: {question}", {"style": "dim yellow"})
                            self.history.append({"role": "tool", "tool_call_id": tc.id, "name": fn_name, "content": result_str})
                            continue

                        # 3. In PLAN mode - only allow plan_approval questions
                        if self.session_mode == SessionMode.PLAN:
                            if reason != "plan_approval":
                                result_str = "[SYSTEM] In PLAN MODE, only ask_user(reason='plan_approval') is allowed. Use tools to gather information instead of asking clarifying questions."
                                yield SessionEvent("log", f"Blocked non-plan_approval question: {question}", {"style": "dim yellow"})
                                self.history.append({"role": "tool", "tool_call_id": tc.id, "name": fn_name, "content": result_str})
                                continue

                        # 4. Check autonomy level
                        autonomy = getattr(self.role_config, 'autonomy_level', 'balanced')

                        if autonomy == "autonomous":
                            result_str = "[SYSTEM] Autonomous mode - proceeding without user input. Making best judgment."
                            yield SessionEvent("log", f"Skipped question (autonomous mode): {question}", {"style": "dim yellow"})
                            self.history.append({"role": "tool", "tool_call_id": tc.id, "name": fn_name, "content": result_str})
                            continue

                        # 5. Check question limit
                        self.ask_user_count += 1
                        if self.ask_user_count > self.max_ask_user_per_task:
                            result_str = f"[SYSTEM] Question limit ({self.max_ask_user_per_task}) reached - proceeding with best judgment."
                            yield SessionEvent("log", f"Question limit reached, skipping: {question}", {"style": "dim red"})
                            self.history.append({"role": "tool", "tool_call_id": tc.id, "name": fn_name, "content": result_str})
                            continue

                        # 6. Valid question - ask user and track context
                        self.waiting_tool_id = tc.id
                        self.question_context = reason  # Track what type of question this is
                        yield SessionEvent("question", question, {"role": self.role_name, "options": options, "reason": reason})
                        return 

                    yield SessionEvent("tool_call", f"Using tool: {fn_name}", {
                        "name": fn_name,
                        "role": self.role_name,
                        "model_id": self.active_model_id,
                        "arguments": fn_args
                    })
                    
                    result_str = ""
                    
                    if fn_name == "request_admin_privileges":
                        if self.sudo_tools:
                            self.llm_tools.extend(self.sudo_tools)
                            self.sudo_tools = []
                            self._refresh_dynamic_tools()
                            result_str = "SYSTEM: Admin privileges GRANTED."
                            yield SessionEvent("log", "Admin Privileges Unlocked", {"role": "system", "style": "bold red"})
                        else:
                            result_str = "SYSTEM: You already have admin privileges."

                    if fn_name == "delegate_task":
                        try:
                            # Updated Logic for Hybrid Handoff
                            goal = fn_args.get("goal")
                            constraints = fn_args.get("constraints", [])
                            focus_files = fn_args.get("focus_files", [])
                            verification_steps = fn_args.get("verification_steps", [])
                            
                            target = "developer" # Always delegate to developer first in this architecture
                            
                            self.delegation_counts[target] = self.delegation_counts.get(target, 0) + 1
                            if self.delegation_counts[target] > self.max_delegations_per_role:
                                result_str = f"ERROR: Exceeded maximum delegations to {target} ({self.max_delegations_per_role})."
                                yield SessionEvent("error", f"Delegation limit reached for {target}", {"role": self.role_name})
                                self.history.append({"role": "tool", "tool_call_id": tc.id, "name": fn_name, "content": result_str})
                                continue

                            spec = TaskSpec(
                                id=f"task_{self.delegation_counts[target]}", 
                                goal=goal, 
                                constraints=constraints, 
                                focus_files=focus_files, 
                                verification_steps=verification_steps
                            )
                            
                            yield SessionEvent("log", f"Refining Plan -> Developer: {goal}", {"role": self.role_name, "style": "bold magenta"})

                            task_id_ui = spec.id
                            task_summary = goal[:50] + "..." if len(goal) > 50 else goal
                            yield SessionEvent("todo_add", task_summary, {"id": task_id_ui, "status": "pending"})
                            yield SessionEvent("todo_update", "", {"id": task_id_ui, "status": "in_progress"})

                            # Run Autonomous Loop
                            # Note: We don't pass 'context_msg' anymore as we want PRUNED context.
                            # The Spec contains everything needed.
                            
                            sub_result_obj = yield from self._run_sub_agent_loop(target, spec, 3)
                            
                            self.global_context_memory.append(f"[Task {spec.id} Result]: {sub_result_obj.summary} (Ver.: {sub_result_obj.verification_result})")
                            
                            is_success = sub_result_obj.status == "success"
                            ui_status = "completed" if is_success else "failed"
                            yield SessionEvent("todo_update", "", {"id": task_id_ui, "status": ui_status})
                            
                            result_str = f"Final Report from Developer/Reviewer Team:\n{sub_result_obj.summary}\n\nVerification: {sub_result_obj.verification_result}"
                            yield SessionEvent("text", f"🏁 FINAL REPORT ({target}):\n{sub_result_obj.summary}", {"role": target})

                        except Exception as e:
                            result_str = f"ERROR during delegation: {str(e)}"
                            yield SessionEvent("error", result_str)

                    elif fn_name in self.tools_map:
                        try:
                            res = self.tools_map[fn_name].call_tool(fn_name, fn_args)
                            result_str = str(res)
                        except Exception as e:
                            result_str = f"Error: {e}"
                        yield SessionEvent("tool_result", f"Result: {result_str[:100]}...", {
                            "role": self.role_name,
                            "model_id": self.active_model_id,
                            "name": fn_name,
                            "full_result": result_str
                        })
                    else:
                        result_str = "Error: Tool not found"

                    self.history.append({"role": "tool", "tool_call_id": tc.id, "name": fn_name, "content": result_str})
            else:
                break
        
        if self.current_task_id and not self.waiting_tool_id and not self.abort_flag:
             # Mark the current task as completed in history instead of creating a duplicate
             self.task_history.update_status(self.current_task_id, "completed")
             # Reset current_task_id so subsequent unrelated messages can start new tasks if needed
             # self.current_task_id = None # Uncomment this if you want every interaction to be a separate task
             # For now, we keep it to group conversation under one task until restart.

    def _update_stats(self, model_id: str, usage: Any, role: str = "system"):
        """Updates session statistics with token usage."""
        if not usage:
            return

        # Handle litellm Usage object or dict
        prompt_tokens = 0
        completion_tokens = 0
        
        if hasattr(usage, "prompt_tokens"):
            prompt_tokens = usage.prompt_tokens
            completion_tokens = usage.completion_tokens
        elif isinstance(usage, dict):
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
        
        total_tokens = prompt_tokens + completion_tokens
        
        # Update model stats
        if model_id not in self.session_stats:
            self.session_stats[model_id] = 0
        self.session_stats[model_id] += total_tokens
        
        self.logger.log_event("stats", f"Tokens used: {total_tokens} ({model_id})", {
            "model_id": model_id,
            "prompt": prompt_tokens,
            "completion": completion_tokens,
            "total": total_tokens,
            "role": role
        })
        
        # Emit stats for all models
        self.logger.log_event("stats", "", {"stats": self.session_stats})
    
    def emit_task_complete(self, success: bool, result_summary: str, **metadata):
        """Emit task completion or failure event for UI notification."""
        event_type = "task_complete" if success else "task_failed"
        
        duration = time.time() - self.current_task_start if self.current_task_start else 0
        
        event_data = {
            "success": success,
            "duration": duration,
            "task": self.current_task_description,
            **metadata
        }
        
        self.logger.log_event(event_type, result_summary, event_data)
        
        return SessionEvent(
            type=event_type,
            content=result_summary,
            metadata=event_data
        )
    
    def get_current_status(self) -> Dict[str, Any]:
        """Get current session status for /status command."""
        return {
            "mode": self.session_mode.value,
            "task": self.current_task_description,
            "elapsed": time.time() - self.current_task_start if self.current_task_start else 0,
            "role": self.role_name,
            "model": self.active_model_id,
            "last_error": self.last_error
        }
    
    def abort(self):
        self.abort_flag = True
        # Save trajectory on abort
        try:
            trajectory_file = self.trajectory.save()
            self.logger.log_event("trajectory_saved", f"Trajectory saved to {trajectory_file}")
        except Exception as e:
            self.logger.log_event("trajectory_save_error", f"Failed to save trajectory: {e}")

    def close(self):
        # Save trajectory on normal close
        try:
            trajectory_file = self.trajectory.save()
            self.logger.log_event("trajectory_saved", f"Trajectory saved to {trajectory_file}")
        except Exception as e:
            self.logger.log_event("trajectory_save_error", f"Failed to save trajectory: {e}")
        
        for client in self.mcp_clients.values():
            try:
                client.close()
            except:
                pass
