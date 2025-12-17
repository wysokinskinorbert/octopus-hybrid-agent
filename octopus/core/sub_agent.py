
    def _run_sub_agent_loop(self, target_role: str, instruction: str, context_str: str, max_iterations: int = 5) -> Generator[SessionEvent, None, str]:
        """
        Executes a sub-agent autonomous loop.
        Returns the final result string (or error reason).
        """
        target_cfg = self.config_store.get_role(target_role)
        target_prov = self.config_store.get_provider(target_cfg.provider_name)
        
        result_file = "_task_result.txt"
        if os.path.exists(result_file): os.remove(result_file)
        
        augmented_instr = f"{instruction}\n\n[SYSTEM]: Write FINAL output to '{result_file}'."
        
        sub_msgs = [
            {"role": "system", "content": target_cfg.system_prompt},
            {"role": "user", "content": f"{context_str}\n\nTASK: {augmented_instr}"}
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

            # Filter tools
            excluded_tools = ['ask_user', 'request_admin_privileges']
            if target_role == 'reviewer': excluded_tools.append('delegate_task')
            if target_role == 'developer': excluded_tools.append('delegate_task')

            target_allowed = set(target_cfg.allowed_tools) if target_cfg.allowed_tools else set()
            sub_tools = [
                t for t in (self.llm_tools + self.sudo_tools)
                if t['function']['name'] not in excluded_tools
                and t['function']['name'] in target_allowed
            ]

            # LLM Call (Non-streaming for stability in sub-loops)
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
                # No tools used - maybe finished?
                if iteration == max_iterations - 1:
                   final_result = sub_resp.content # Accept text if it's the last turn
                continue

            # Tool Execution
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
                
                try:
                    s_arg = json.loads(s_arg_str)
                except:
                    s_arg = {}

                # Log
                arg_preview = ", ".join(f"{k}={str(v)[:25]}" for k, v in list(s_arg.items())[:2])
                yield SessionEvent("log", f"{target_role} → {s_name}({arg_preview})", {
                    "role": target_role, "style": "dim cyan"
                })
                yield SessionEvent("tool_call", f"Using: {s_name}", {
                     "role": target_role, "name": s_name, "arguments": s_arg
                })

                # Execution
                s_res = "Error"
                if s_name in self.tools_map:
                    try:
                        s_res = self.tools_map[s_name].call_tool(s_name, s_arg)
                    except Exception as ex: s_res = f"Error: {ex}"
                
                # Placeholder Detection
                if s_name == "read_file" and s_res:
                    PATTERNS = ["hello world", "todo:", "fixme:", "placeholder", "your content here"]
                    if any(p in str(s_res).lower() for p in PATTERNS):
                        placeholder_detected = True
                        yield SessionEvent("log", "⚠️ Placeholder content detected!", {"role": "system", "style": "red bold"})

                if s_name == "run_shell_command" and "STDOUT" in str(s_res):
                    captured_stdout = str(s_res)
                
                yield SessionEvent("tool_result", f"Result: {str(s_res)[:100]}...", {
                    "role": target_role, "name": s_name
                })
                
                sub_msgs.append({"role": "tool", "tool_call_id": tool_id, "name": s_name, "content": str(s_res)})

        # --- Sub-loop finished, collect result ---
        
        # 1. Try file
        if os.path.exists(result_file):
            try:
                with open(result_file, "r", encoding="utf-8") as f:
                    final_result = f.read()
            except: pass
        
        # 2. Try stdout
        if not final_result and captured_stdout:
            final_result = captured_stdout
        
        # 3. Try last msg
        if not final_result and sub_msgs and sub_msgs[-1].get("content"):
             final_result = sub_msgs[-1]["content"]

        if placeholder_detected:
            return "[BLOCKED] Placeholder content detected. Work REJECTED."
        
        return final_result if final_result else "No result produced."
