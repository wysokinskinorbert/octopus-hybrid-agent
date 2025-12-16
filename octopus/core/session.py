import os
import sys
import json
from dataclasses import dataclass, field
from typing import List, Dict, Any, Generator, Callable
from enum import Enum

from .config_store import ConfigStore, RoleConfig, ProviderConfig
from .logger import SessionLogger
from .task_history import TaskHistory
from ..mcp.protocol import JSONRPCClient
from ..llm.provider_manager import ProviderManager


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
    def __init__(self, role_name: str = None):
        self.config_store = ConfigStore()
        self.role_name = role_name if role_name else self.config_store.config.active_role
        self.role_config = self.config_store.get_role(self.role_name)
        self.provider_config = self.config_store.get_provider(self.role_config.provider_name)
        
        self.logger = SessionLogger()
        self.logger.log_event("init", f"Session initialized for role: {self.role_name}", {"provider": self.provider_config.name})
        
        self.task_history = TaskHistory()
        
        self.llm_manager = ProviderManager()
        self.history = [{"role": "system", "content": self.role_config.system_prompt}]
        
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

                client = JSONRPCClient(cmd, server_conf.args, env=full_env)
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
                    "description": f"Delegate sub-task. Available agents: {', '.join(available_roles)}.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "role": {"type": "string", "enum": available_roles},
                            "instruction": {"type": "string"}
                        },
                        "required": ["role", "instruction"]
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

    def _get_fallback_provider(self, current_name: str) -> Any:
        for p in self.config_store.config.providers.values():
            if p.name != current_name:
                return p
        return None

    def enable_emergency_tools(self):
        self.logger.log_event("action", "Emergency tools unlocked manually")
        if self.sudo_tools:
            self.llm_tools.extend(self.sudo_tools)
            self.sudo_tools = []
            return True
        return False

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
        if self.waiting_tool_id:
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
                    fallback = self._get_fallback_provider(self.active_provider.name)
                    if fallback:
                        original_model = self.active_model_id
                        yield SessionEvent("log", f"Failover: Switching provider {self.active_provider.name} → {fallback.name}, keeping model {original_model}", {
                            "role": "system",
                            "from_provider": self.active_provider.name,
                            "to_provider": fallback.name,
                            "model_id": original_model
                        })
                        self.active_provider = fallback
                        # Don't change model_id - keep the role's configured model
                        continue
                    else:
                        yield SessionEvent("error", "No fallback available.")
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

                    elif fn_name == "delegate_task":
                        target = fn_args.get("role")
                        instr = fn_args.get("instruction")

                        # Check delegation limit
                        self.delegation_counts[target] = self.delegation_counts.get(target, 0) + 1
                        if self.delegation_counts[target] > self.max_delegations_per_role:
                            result_str = f"ERROR: Exceeded maximum delegations to {target} ({self.max_delegations_per_role}). Try a different approach or do the task yourself."
                            yield SessionEvent("error", f"Delegation limit reached for {target}", {"role": self.role_name})
                            self.history.append({"role": "tool", "tool_call_id": tc.id, "name": fn_name, "content": result_str})
                            continue

                        yield SessionEvent("log", f"Delegating to {target}: {instr}", {"role": self.role_name, "style": "bold magenta"})

                        # Emit todo_add event for UI (Claude Code style)
                        task_id = f"task_{target}_{self.delegation_counts[target]}"
                        task_summary = instr[:50] + "..." if len(instr) > 50 else instr
                        yield SessionEvent("todo_add", task_summary, {"id": task_id, "status": "pending"})
                        yield SessionEvent("todo_update", "", {"id": task_id, "status": "in_progress"})

                        target_cfg = self.config_store.get_role(target)
                        target_prov = self.config_store.get_provider(target_cfg.provider_name)
                        
                        memory_str = "\n".join(self.global_context_memory)
                        context_msg = f"[SYSTEM: CONTEXT FROM PREVIOUS STEPS]\n{memory_str}" if memory_str else ""

                        result_file = "_task_result.txt"
                        if os.path.exists(result_file): os.remove(result_file)
                        augmented_instr = f"{instr}\n\n[SYSTEM]: Write FINAL output to '{result_file}'."

                        sub_msgs = [
                            {"role": "system", "content": target_cfg.system_prompt},
                            {"role": "user", "content": f"{context_msg}\n\nTASK: {augmented_instr}"}
                        ]
                        
                        try:
                            captured_stdout = ""
                            placeholder_detected = False  # Flag to block false success reports

                            # Dynamic iterations: more for local models (need debugging loops)
                            sub_iterations = 10 if target_prov.type == "ollama" else 5

                            for iteration in range(sub_iterations):
                                if self.abort_flag: return

                                yield SessionEvent("status", f"{target} ({target_cfg.model_id}) iteration {iteration+1}/{sub_iterations}", {
                                    "role": target,
                                    "model_id": target_cfg.model_id,
                                    "iteration": iteration + 1,
                                    "max_iterations": sub_iterations
                                })

                                # Filter out dynamic tools based on target role
                                # Developer can delegate to reviewer, but reviewer cannot delegate further
                                excluded_tools = ['ask_user', 'request_admin_privileges']
                                if target == 'reviewer':
                                    excluded_tools.append('delegate_task')  # Reviewer ends the workflow
                                # Developer should NOT have delegate_task (only MCP tools)
                                if target == 'developer':
                                    excluded_tools.append('delegate_task')

                                # KRYTYCZNE: Filtruj po allowed_tools TARGET roli, nie architekta!
                                target_allowed = set(target_cfg.allowed_tools) if target_cfg.allowed_tools else set()

                                sub_tools = [
                                    t for t in (self.llm_tools + self.sudo_tools)
                                    if t['function']['name'] not in excluded_tools
                                    and t['function']['name'] in target_allowed
                                ]

                                # FAZA N4: WYŁĄCZONY streaming dla delegacji
                                # Streaming w sub-tasks powoduje problemy z wydajnością i XML tagami
                                # Lepiej pokazać status update i poczekać na wynik
                                use_sub_streaming = False  # Zawsze wyłączony dla stabilności

                                if use_sub_streaming:
                                    # Kod streaming zostawiony dla ewentualnego przyszłego użycia
                                    sub_resp = None
                                    sub_use = None
                                    for stream_event in self.llm_manager.chat_complete_stream(
                                        target_prov, target_cfg.model_id, sub_msgs, tools=sub_tools,
                                        temperature=target_cfg.temperature
                                    ):
                                        if stream_event["type"] == "chunk":
                                            yield SessionEvent("streaming", stream_event["content"], {
                                                "role": target,
                                                "model_id": target_cfg.model_id
                                            })
                                        elif stream_event["type"] == "done":
                                            sub_resp = stream_event["message"]
                                            sub_use = stream_event["usage"]
                                        elif stream_event["type"] == "error":
                                            raise Exception(stream_event["error"])
                                    if not sub_resp:
                                        raise Exception("Streaming completed without final message")
                                else:
                                    # Non-streaming call - stabilniejsze dla delegacji
                                    sub_resp, sub_use = self.llm_manager.chat_complete(
                                        target_prov, target_cfg.model_id, sub_msgs, tools=sub_tools,
                                        temperature=target_cfg.temperature
                                    )

                                self._update_stats(target_cfg.model_id, sub_use, role=target)
                                yield SessionEvent("stats", "", {"stats": self.session_stats})
                                sub_msgs.append(sub_resp)
                                
                                if sub_resp.content:
                                    # Change: Emit intermediate content as 'reasoning' to keep it inside the ActivityWidget
                                    yield SessionEvent("reasoning", sub_resp.content, {
                                        "role": target,
                                        "model_id": target_cfg.model_id
                                    })

                                if hasattr(sub_resp, 'tool_calls') and sub_resp.tool_calls:
                                    for stc in sub_resp.tool_calls:
                                        if self.abort_flag: return

                                        if isinstance(stc, dict):
                                            s_name = stc.get("function", {}).get("name")
                                            s_arg_str = stc.get("function", {}).get("arguments")
                                        else:
                                            s_name = stc.function.name
                                            s_arg_str = stc.function.arguments

                                        s_arg = json.loads(s_arg_str)

                                        # LOG przed tool call - pokazuj co developer/reviewer będzie robić
                                        arg_preview = ", ".join(f"{k}={str(v)[:25]}" for k, v in list(s_arg.items())[:2])
                                        yield SessionEvent("log", f"{target} → {s_name}({arg_preview})", {
                                            "role": target,
                                            "model_id": target_cfg.model_id,
                                            "style": "dim cyan"
                                        })

                                        yield SessionEvent("tool_call", f"[{target_cfg.model_id}] Using: {s_name}", {
                                            "role": target,
                                            "name": s_name,
                                            "model_id": target_cfg.model_id,
                                            "arguments": s_arg
                                        })
                                        
                                        s_res = "Error"
                                        if s_name in self.tools_map:
                                            try:
                                                s_res = self.tools_map[s_name].call_tool(s_name, s_arg)
                                            except Exception as ex: s_res = f"Error: {ex}"
                                        else:
                                            s_res = "Tool not found"

                                        # PLACEHOLDER DETECTION (Goal-Oriented Verification System)
                                        # Detect common placeholder content in file reads
                                        if s_name == "read_file" and s_res and s_res != "Error":
                                            PLACEHOLDER_PATTERNS = [
                                                "hello world", "lorem ipsum", "todo:", "fixme:",
                                                "placeholder", "template content", "sample text",
                                                "your content here", "add your", "replace this"
                                            ]
                                            content_lower = str(s_res).lower()
                                            detected_placeholders = []
                                            for pattern in PLACEHOLDER_PATTERNS:
                                                if pattern in content_lower:
                                                    detected_placeholders.append(pattern)

                                            if detected_placeholders:
                                                placeholder_detected = True  # SET FLAG - will block success report
                                                placeholder_warning = f"""[CRITICAL: PLACEHOLDER DETECTED - SUCCESS WILL BE BLOCKED]
The file contains placeholder content: {', '.join(detected_placeholders)}
This file has NOT been properly implemented for the task goal.

YOUR SUCCESS REPORT WILL BE REJECTED unless you fix this NOW.

MANDATORY ACTIONS:
1. Use write_file to REPLACE placeholder content with REAL implementation
2. Implement the ACTUAL functionality requested in the task
3. Use read_file to VERIFY your changes removed ALL placeholders
4. Only then can you complete the task

WARNING: If you report success without fixing placeholders, your work will be REJECTED."""
                                                sub_msgs.append({
                                                    "role": "system",
                                                    "content": placeholder_warning
                                                })
                                                yield SessionEvent("log", f"[PLACEHOLDER BLOCK] Found: {detected_placeholders} - Success blocked until fixed", {"role": "system", "style": "red bold"})

                                        if s_name == "run_shell_command" and "STDOUT" in str(s_res):
                                            captured_stdout = str(s_res)
                                            
                                        yield SessionEvent("tool_result", f"Result: {str(s_res)[:100]}...", {
                                            "role": target,
                                            "model_id": target_cfg.model_id,
                                            "name": s_name,
                                            "full_result": str(s_res)
                                        })

                                        # LOG po tool result - podsumowanie sukces/błąd
                                        is_error = "Error" in str(s_res) or "not found" in str(s_res).lower()
                                        if is_error:
                                            yield SessionEvent("log", f"  ✗ {s_name} failed", {
                                                "role": target,
                                                "model_id": target_cfg.model_id,
                                                "style": "dim red"
                                            })
                                        else:
                                            # Inteligentne podsumowanie wyniku
                                            summary = "done"
                                            if s_name == "read_file":
                                                lines = str(s_res).count('\n') + 1
                                                summary = f"read {lines} lines"
                                            elif s_name == "write_file":
                                                summary = "file written"
                                            elif s_name == "list_directory":
                                                items = str(s_res).count('\n')
                                                summary = f"found {items} items"
                                            elif s_name == "run_shell_command":
                                                if "STDOUT:" in str(s_res):
                                                    summary = "executed"
                                                else:
                                                    summary = "no output"
                                            yield SessionEvent("log", f"  ✓ {s_name} {summary}", {
                                                "role": target,
                                                "model_id": target_cfg.model_id,
                                                "style": "dim green"
                                            })

                                        tool_id = stc.get("id") if isinstance(stc, dict) else stc.id
                                        sub_msgs.append({"role": "tool", "tool_call_id": tool_id, "name": s_name, "content": str(s_res)})
                                else:
                                    # Model nie wygenerował tool_calls - zaloguj co się dzieje
                                    if sub_resp.content:
                                        content_preview = sub_resp.content[:150].replace('\n', ' ')
                                        yield SessionEvent("log", f"[{target}] No tool calls. Response: {content_preview}...", {
                                            "role": target,
                                            "model_id": target_cfg.model_id,
                                            "style": "dim yellow"
                                        })
                                    else:
                                        yield SessionEvent("log", f"[{target}] Empty response, no tool calls", {
                                            "role": target,
                                            "model_id": target_cfg.model_id,
                                            "style": "dim red"
                                        })
                                    break

                            if self.abort_flag: return

                            final_data = ""
                            source_info = ""

                            # 1. Try to read the explicit result file (Highest Priority)
                            if os.path.exists(result_file):
                                try:
                                    with open(result_file, "r", encoding="utf-8") as f:
                                        final_data = f.read()
                                    source_info = "file '_task_result.txt'"
                                    yield SessionEvent("log", f"Read result file: {final_data[:100]}...", {"role": "system", "style": "green"})
                                except Exception as e:
                                    yield SessionEvent("error", f"Failed to read result file: {e}", {"role": "system"})
                            
                            # 2. If file missing, fallback to captured STDOUT (Smart Capture)
                            if not final_data and captured_stdout:
                                final_data = captured_stdout
                                source_info = "auto-captured STDOUT"
                                yield SessionEvent("log", "Using auto-captured STDOUT as result.", {"role": "system", "style": "yellow"})

                            # 3. Last Resort: Use the last text response content (Fix for Reviewer/Conversational roles)
                            if not final_data and sub_msgs:
                                last_msg = sub_msgs[-1]
                                if last_msg.get("content"):
                                    final_data = last_msg["content"]
                                    source_info = "last text response"
                                    yield SessionEvent("log", "Using last text response as result.", {"role": "system", "style": "dim"})

                            # 4. Final Report Generation
                            if final_data:
                                # CHECK: Block success if placeholders were detected
                                if placeholder_detected:
                                    result_str = f"[BLOCKED - PLACEHOLDER CONTENT DETECTED]\nDeveloper attempted to report success but placeholder content was found in files.\nOriginal report:\n{final_data}\n\nThis work is REJECTED. Placeholder content must be replaced with real implementation."
                                    yield SessionEvent("error", f"Developer report BLOCKED: placeholder content detected", {"role": target, "style": "red bold"})
                                    # Inject strong rejection message for architect
                                    self.history.append({
                                        "role": "system",
                                        "content": f"[CRITICAL REJECTION] Developer's work was REJECTED because placeholder content (e.g., 'Hello World') was detected in files. The actual functionality was NOT implemented. You MUST delegate again with specific instructions to FIX the placeholder content and implement REAL functionality. Do NOT accept this result."
                                    })
                                else:
                                    result_str = f"Output from {target} (via {source_info}):\n{final_data}"
                                    yield SessionEvent("text", f"🏁 FINAL REPORT ({target}):\n{final_data}", {"role": target})
                                    # Mark TODO as completed (Claude Code style)
                                    yield SessionEvent("todo_update", "", {"id": task_id, "status": "completed"})
                            else:
                                # 5. If absolutely nothing produced
                                result_str = f"Output from {target}: No result file created, no shell output captured, and no text response."
                                yield SessionEvent("error", "Developer finished without producing results.", {"role": target})
                                # Mark TODO as failed (keep in_progress but log error)
                                yield SessionEvent("todo_update", "", {"id": task_id, "status": "pending"})
                            
                            self.global_context_memory.append(f"[{target}]: {result_str}")

                            # POST-DELEGATION VERIFICATION (Goal-Oriented Verification System)
                            # Inject verification prompt to force architect to independently verify developer's output
                            if final_data and target == "developer":
                                verification_prompt = f"""[VERIFICATION REQUIRED - DO NOT SKIP]
Developer reported completion. Their report:
{final_data[:500]}{"..." if len(final_data) > 500 else ""}

CRITICAL: Before accepting this result, you MUST:
1. Use read_file to INDEPENDENTLY check the actual code/files created
2. Look for placeholder content ("Hello World", "TODO", "Lorem ipsum", template defaults)
3. Compare against the original goal: {instr[:300] if instr else "Unknown"}
4. If mismatch found → delegate_task AGAIN with specific fix instructions
5. ONLY declare success if ACTUAL OUTPUT matches EXPECTED GOAL

DO NOT trust the developer's "success" claim without verification.
If you find placeholders or missing functionality → FIX IT via delegation."""
                                self.history.append({
                                    "role": "system",
                                    "content": verification_prompt
                                })
                                yield SessionEvent("log", "[Verification] Injected post-delegation verification prompt", {"role": "system"})

                        except Exception as e:
                            err_msg = f"Delegation Error: {e}"
                            yield SessionEvent("error", err_msg, {"role": target})
                            result_str = err_msg

                        # Reset to original role after delegation completes
                        self.active_provider = self.provider_config
                        self.active_model_id = self.role_config.model_id
                        yield SessionEvent("status", f"Returned to {self.role_name} ({self.active_model_id})")

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