import os

SESSION_PATH = "octopus/core/session.py"
SUB_AGENT_METHOD = """
    def _run_sub_agent_loop(self, target_role: str, instruction: str, context_str: str, max_iterations: int = 5) -> Generator[SessionEvent, None, str]:
        target_cfg = self.config_store.get_role(target_role)
        target_prov = self.config_store.get_provider(target_cfg.provider_name)
        
        result_file = "_task_result.txt"
        if os.path.exists(result_file): os.remove(result_file)
        
        augmented_instr = f"{instruction}\\n\\n[SYSTEM]: Write FINAL output to '{result_file}'."
        
        sub_msgs = [
            {"role": "system", "content": target_cfg.system_prompt},
            {"role": "user", "content": f"{context_str}\\n\\nTASK: {augmented_instr}"}
        ]
        
        captured_stdout = ""
        placeholder_detected = False
        final_result = ""

        for iteration in range(max_iterations):
            if self.abort_flag: break

            yield SessionEvent("status", f"{target_role} ({target_cfg.model_id}) iteration {iteration+1}/{max_iterations}", {
                "role": target_role,
                "model_id": target_cfg.model_id,
                "iteration": iteration + 1,
                "max_iterations": max_iterations
            })

            excluded_tools = ['ask_user', 'request_admin_privileges']
            if target_role == 'reviewer': excluded_tools.append('delegate_task')
            if target_role == 'developer': excluded_tools.append('delegate_task')

            target_allowed = set(target_cfg.allowed_tools) if target_cfg.allowed_tools else set()
            sub_tools = [
                t for t in (self.llm_tools + self.sudo_tools)
                if t['function']['name'] not in excluded_tools
                and t['function']['name'] in target_allowed
            ]

            try:
                sub_resp, sub_use = self.llm_manager.chat_complete(
                    target_prov, target_cfg.model_id, sub_msgs, tools=sub_tools,
                    temperature=target_cfg.temperature
                )
            except Exception as e:
                yield SessionEvent("error", f"LLM Error: {e}", {"role": target_role})
                break

            self._update_stats(target_cfg.model_id, sub_use, role=target_role)
            yield SessionEvent("stats", "", {"stats": self.session_stats})
            sub_msgs.append(sub_resp)

            if sub_resp.content:
                yield SessionEvent("reasoning", sub_resp.content, {"role": target_role, "model_id": target_cfg.model_id})

            if not (hasattr(sub_resp, 'tool_calls') and sub_resp.tool_calls):
                if iteration == max_iterations - 1:
                   final_result = sub_resp.content
                continue

            for stc in sub_resp.tool_calls:
                if self.abort_flag: break
                
                if isinstance(stc, dict):
                    s_name = stc.get("function", {}).get("name")
                    s_arg_str = stc.get("function", {}).get("arguments")
                    tool_id = stc.get("id")
                else:
                    s_name = stc.function.name
                    s_arg_str = stc.function.arguments
                    tool_id = stc.id
                
                try: s_arg = json.loads(s_arg_str)
                except: s_arg = {}

                yield SessionEvent("log", f"{target_role} → {s_name}", {"role": target_role, "style": "dim cyan"})
                yield SessionEvent("tool_call", f"Using: {s_name}", {"role": target_role, "name": s_name, "arguments": s_arg})

                s_res = "Error"
                if s_name in self.tools_map:
                    try: s_res = self.tools_map[s_name].call_tool(s_name, s_arg)
                    except Exception as ex: s_res = f"Error: {ex}"
                
                if s_name == "read_file" and s_res:
                    PATTERNS = ["hello world", "todo:", "fixme:", "placeholder", "your content here"]
                    if any(p in str(s_res).lower() for p in PATTERNS):
                        placeholder_detected = True
                        yield SessionEvent("log", "⚠️ Placeholder content detected!", {"role": "system", "style": "red bold"})

                if s_name == "run_shell_command" and "STDOUT" in str(s_res):
                    captured_stdout = str(s_res)
                
                yield SessionEvent("tool_result", f"Result: {str(s_res)[:100]}...", {"role": target_role, "name": s_name})
                sub_msgs.append({"role": "tool", "tool_call_id": tool_id, "name": s_name, "content": str(s_res)})

        if os.path.exists(result_file):
            try:
                with open(result_file, "r", encoding="utf-8") as f: final_result = f.read()
            except: pass
        
        if not final_result and captured_stdout: final_result = captured_stdout
        if not final_result and sub_msgs and sub_msgs[-1].get("content"): final_result = sub_msgs[-1]["content"]

        if placeholder_detected: return "[BLOCKED] Placeholder content detected. Work REJECTED."
        return final_result if final_result else "No result produced."

"""

NEW_DELEGATE_TASK = """                    elif fn_name == "delegate_task":
                        target = fn_args.get("role")
                        instr = fn_args.get("instruction")

                        self.delegation_counts[target] = self.delegation_counts.get(target, 0) + 1
                        if self.delegation_counts[target] > self.max_delegations_per_role:
                            result_str = f"ERROR: Exceeded maximum delegations to {target} ({self.max_delegations_per_role})."
                            yield SessionEvent("error", f"Delegation limit reached for {target}", {"role": self.role_name})
                            self.history.append({"role": "tool", "tool_call_id": tc.id, "name": fn_name, "content": result_str})
                            continue

                        yield SessionEvent("log", f"Delegating to {target}: {instr}", {"role": self.role_name, "style": "bold magenta"})

                        task_id_ui = f"task_{target}_{self.delegation_counts[target]}"
                        task_summary = instr[:50] + "..." if len(instr) > 50 else instr
                        yield SessionEvent("todo_add", task_summary, {"id": task_id_ui, "status": "pending"})
                        yield SessionEvent("todo_update", "", {"id": task_id_ui, "status": "in_progress"})

                        memory_str = "\\n".join(self.global_context_memory)
                        context_msg = f"[SYSTEM: CONTEXT FROM PREVIOUS STEPS]\\n{memory_str}" if memory_str else ""
                        
                        sub_result = yield from self._run_sub_agent_loop(target, instr, context_msg, 5)
                        
                        self.global_context_memory.append(f"[{target}]: {sub_result}")
                        
                        is_success = "[BLOCKED]" not in sub_result
                        ui_status = "completed" if is_success else "pending"
                        yield SessionEvent("todo_update", "", {"id": task_id_ui, "status": ui_status})
                        
                        result_str = f"Output from {target}:\\n{sub_result}"
                        yield SessionEvent("text", f"🏁 FINAL REPORT ({target}):\\n{sub_result}", {"role": target})

                        if is_success and target == "developer":
                            reviewer_role = "reviewer"
                            reviewer_cfg = self.config_store.get_role(reviewer_role)
                            if reviewer_cfg:
                                yield SessionEvent("log", "Initiating Autonomous Review...", {"role": "system", "style": "bold orange"})
                                review_instr = f"Review Developer work.\\nTask: {instr}\\nReport:\\n{sub_result}\\nVerify requirements."
                                review_result = yield from self._run_sub_agent_loop(reviewer_role, review_instr, "", 3)
                                self.global_context_memory.append(f"[Auto-Reviewer]: {review_result}")
                                result_str += f"\\n\\n[AUTO-REVIEWER FEEDBACK]:\\n{review_result}"
                                yield SessionEvent("text", f"🔍 REVIEW REPORT:\\n{review_result}", {"role": "reviewer"})

                        if is_success:
                             self.history.append({
                                "role": "system",
                                "content": f"[SYSTEM] Sub-task finished. Reviewer feedback is attached above. Verify results."
                             })
"""

with open(SESSION_PATH, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
inserted_method = False
replaced_delegate = False
skip_mode = False

for line in lines:
    # 1. Insert Method
    if "def process_user_input" in line and not inserted_method:
        new_lines.append(SUB_AGENT_METHOD + "\n")
        inserted_method = True
        new_lines.append(line)
        continue

    # 2. Replace Delegate Task
    if 'elif fn_name == "delegate_task":' in line and not replaced_delegate:
        new_lines.append(NEW_DELEGATE_TASK)
        replaced_delegate = True
        skip_mode = True
        continue
    
    if skip_mode:
        if 'elif fn_name in self.tools_map:' in line:
            skip_mode = False
            new_lines.append(line)
        continue
    
    new_lines.append(line)

with open(SESSION_PATH, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
    
print("Success")
