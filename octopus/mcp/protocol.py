import json
import subprocess
import threading
import os
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

@dataclass
class ToolDefinition:
    name: str
    description: str
    input_schema: Dict[str, Any]

class JSONRPCClient:
    def __init__(self, command: str, args: List[str], env: Dict[str, str] = None):
        self.command = command
        self.args = args
        self.env = env if env else os.environ.copy()
        
        # Capture current working directory of the main app
        self._initial_cwd = os.getcwd() 
        self.process = None
        self._lock = threading.Lock()
        self._request_id = 0

    def start(self):
        full_cmd = [self.command] + self.args
        self.process = subprocess.Popen(
            full_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=self.env,
            cwd=self._initial_cwd # Ensure sub-process starts in the correct directory
        )
        
        # Initialize
        init_req = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "octopus", "version": "4.0"}
            },
            "id": self._next_id()
        }
        self._send(init_req)
        self._read_response(init_req["id"])
        
        self._send({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {}
        })

    def _next_id(self):
        with self._lock:
            self._request_id += 1
            return self._request_id

    def _send(self, msg: Dict[str, Any]):
        if not self.process:
            raise RuntimeError("Process not started")
        
        json_str = json.dumps(msg)
        self.process.stdin.write(json_str + "\n")
        self.process.stdin.flush()

    def _read_response(self, expect_id: int) -> Dict[str, Any]:
        """
        Naive synchronous reader. Reads lines until it finds the response with matching ID.
        Ignores notifications or logs on stderr.
        """
        while True:
            line = self.process.stdout.readline()
            if not line:
                stderr_output = ""
                if self.process.stderr:
                    stderr_output = self.process.stderr.read()
                raise RuntimeError(f"Process exited unexpectedly. Stderr: {stderr_output}")
            
            try:
                msg = json.loads(line)
                # If it's a response to our request
                if msg.get("id") == expect_id:
                    if "error" in msg:
                        raise RuntimeError(f"MCP Error: {msg['error']}")
                    return msg.get("result")
                
                # If it's a notification or log, we just ignore for now in this MVP
                # In full prod, we would handle logging notifications
            except json.JSONDecodeError:
                continue # Skip malformed lines

    def list_tools(self) -> List[ToolDefinition]:
        req_id = self._next_id()
        msg = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "params": {},
            "id": req_id
        }
        self._send(msg)
        result = self._read_response(req_id)
        
        tools = []
        for t in result.get("tools", []):
            tools.append(ToolDefinition(
                name=t["name"],
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {})
            ))
        return tools

    def call_tool(self, name: str, args: Dict[str, Any]) -> Any:
        req_id = self._next_id()
        msg = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": args
            },
            "id": req_id
        }
        self._send(msg)
        result = self._read_response(req_id)
        
        # MCP tool call result structure usually has "content" list
        content = result.get("content", [])
        # Join text parts
        text_output = ""
        for item in content:
            if item.get("type") == "text":
                text_output += item.get("text", "")
        
        return text_output

    def stop(self):
        if self.process:
            self.process.terminate()
