import sys
import json
import os
import subprocess
import shutil
import glob
import re
import difflib
from pathlib import Path

# A minimal MCP Server Implementation in Python (No dependencies)

def log(msg):
    sys.stderr.write(f"[InternalFS] {msg}\n")
    sys.stderr.flush()

def read_message():
    line = sys.stdin.readline()
    if not line: return None
    try:
        return json.loads(line)
    except:
        return None

def send_message(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()

def handle_list_tools():
    return {
        "tools": [
            {
                "name": "read_file",
                "description": "Read file content from the filesystem",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"}
                    },
                    "required": ["path"]
                }
            },
            {
                "name": "write_file",
                "description": "Write content to a file",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"}
                    },
                    "required": ["path", "content"]
                }
            },
            {
                "name": "list_directory",
                "description": "List files in directory. If path not found, attempts to find similar directories.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"}
                    },
                    "required": ["path"]
                }
            },
            {
                "name": "glob",
                "description": "Find files matching a glob pattern (e.g., '**/*.py')",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string"}
                    },
                    "required": ["pattern"]
                }
            },
            {
                "name": "search_file_content",
                "description": "Search for a string or regex pattern in files within the current directory.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string"},
                        "path": {"type": "string", "description": "Optional path to search in (default: .)"}
                    },
                    "required": ["pattern"]
                }
            },
            {
                "name": "run_shell_command",
                "description": "Execute a shell command. Use 'background=True' for long-running servers (e.g. npm start). output/errors will be lost/discarded for background tasks.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "background": {"type": "boolean", "description": "Set to true for long-running processes"}
                    },
                    "required": ["command"]
                }
            }
        ]
    }

def resolve_python_command(cmd_str):
    parts = cmd_str.split()
    if not parts:
        return cmd_str
    
    prog = parts[0]
    args = parts[1:]
    
    if prog in ["python", "python3"]:
        if shutil.which("python"):
            return cmd_str
        if shutil.which("py"):
            return " ".join(["py"] + args)
        if shutil.which("python3"):
            return " ".join(["python3"] + args)
        return " ".join([sys.executable] + args)
        
    return cmd_str

def clean_arg(arg):
    """Aggressively clean arguments from LLM artifacts (quotes, whitespace)."""
    if not arg:
        return ""
    s = str(arg).strip()

    sq = "'"
    dq = '"'

    # Remove surrounding quotes if present
    if (s.startswith(dq) and s.endswith(dq)) or (s.startswith(sq) and s.endswith(sq)):
        s = s[1:-1]
    s = s.strip()

    # Normalize Windows paths - resolve and convert to proper path
    if s and (s[1:3] == ':\\' or s[1:3] == ':/' or s.startswith('/')):
        try:
            # Use pathlib to normalize the path
            normalized = Path(s).resolve()
            if normalized.exists():
                s = str(normalized)
        except Exception:
            pass  # Keep original if normalization fails

    return s

def handle_call_tool(params):
    name = params.get("name")
    args = params.get("arguments", {})
    
    result_text = ""
    is_error = False

    try:
        if name == "read_file":
            path = clean_arg(args.get("path", ""))
            if os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8', errors='replace') as f:
                        result_text = f.read()
                except Exception as e:
                    result_text = "Error reading file '{}': {} (Raw: {})".format(path, e, repr(path))
                    is_error = True
            else:
                result_text = "Error: File '{}' not found (Raw: {})".format(path, repr(path))
                is_error = True
        
        elif name == "write_file":
            path = clean_arg(args.get("path", ""))
            content = str(args.get("content", ""))
            
            try:
                p = Path(path)
                p.parent.mkdir(parents=True, exist_ok=True)
                
                # --- DIFF GENERATION START ---
                diff_output = ""
                if p.exists():
                    try:
                        with open(p, 'r', encoding='utf-8', errors='ignore') as f:
                            old_content = f.read()
                        
                        # Generate Unified Diff
                        diff = difflib.unified_diff(
                            old_content.splitlines(),
                            content.splitlines(),
                            fromfile=f"a/{p.name}",
                            tofile=f"b/{p.name}",
                            lineterm=""
                        )
                        diff_text = "\n".join(list(diff))
                        
                        if diff_text:
                            diff_output = f"\n\n**File Changes:**\n```diff\n{diff_text}\n```"
                        else:
                            diff_output = "\n\n(No changes detected in file content)"
                    except Exception as diff_err:
                        diff_output = f"\n\n(Could not generate diff: {diff_err})"
                else:
                    diff_output = "\n\n**New File Created**"
                # --- DIFF GENERATION END ---

                with open(p, 'w', encoding='utf-8') as f:
                    f.write(content)
                
                result_text = f"Successfully wrote to {path}{diff_output}"
                
            except Exception as e:
                result_text = "Error writing file '{}': {} (Raw: {})".format(path, e, repr(path))
                is_error = True
        
        elif name == "list_directory":
            path = clean_arg(args.get("path", "."))
            if not path: path = "."
            
            if os.path.exists(path):
                try:
                    items = os.listdir(path)
                    result_text = "\n".join(items)
                except Exception as e:
                    result_text = "Error listing dir '{}': {} (Raw: {})".format(path, e, repr(path))
                    is_error = True
            else:
                # --- SMART RECOVERY LOGIC ---
                missing_name = os.path.basename(path.rstrip("/\\"))
                parent_dir = os.path.dirname(path.rstrip("/\\"))
                
                candidates = []
                
                # 1. Search in current directory (recursive depth 2)
                try:
                    for root, dirs, _ in os.walk("."):
                        if root.count(os.sep) - ".".count(os.sep) > 2: continue # Limit depth
                        for d in dirs:
                            if missing_name.lower() in d.lower():
                                candidates.append(os.path.join(root, d))
                except: pass

                # 2. Search in immediate parent if accessible
                if not candidates and parent_dir and os.path.exists(parent_dir):
                     try:
                        for d in os.listdir(parent_dir):
                            if missing_name.lower() in d.lower() and os.path.isdir(os.path.join(parent_dir, d)):
                                candidates.append(os.path.join(parent_dir, d))
                     except: pass

                if candidates:
                    result_text = "Error: Directory '{}' not found.\n\nHowever, I found similar directories that might match:\n{}.".format(path, "\n".join(candidates))
                    is_error = True 
                else:
                    result_text = "Error: Directory '{}' not found (Raw: {})".format(path, repr(path))
                    is_error = True

        elif name == "glob":
            pattern = clean_arg(args.get("pattern", "*"))
            try:
                files = glob.glob(pattern, recursive=True)
                if not files:
                    result_text = "No files found matching pattern."
                else:
                    # Limit output
                    result_text = "\n".join(files[:100])
                    if len(files) > 100: result_text += f"\n... ({len(files)-100} more)"
            except Exception as e:
                result_text = f"Glob Error: {e}"
                is_error = True

        elif name == "search_file_content":
            pattern = clean_arg(args.get("pattern", ""))
            search_path = clean_arg(args.get("path", "."))
            if not pattern:
                result_text = "Error: Pattern is required"
                is_error = True
            else:
                try:
                    matches = []
                    # Simple grep-like implementation
                    for root, _, files in os.walk(search_path):
                        if '.git' in root or '__pycache__' in root or 'node_modules' in root: continue
                        for file in files:
                            try:
                                fp = os.path.join(root, file)
                                with open(fp, 'r', encoding='utf-8', errors='ignore') as f:
                                    content = f.read()
                                    if re.search(pattern, content):
                                        matches.append(fp)
                                    if len(matches) > 20: break
                            except: continue
                        if len(matches) > 20: break
                    
                    if matches:
                        result_text = "Found matches in:\n" + "\n".join(matches)
                    else:
                        result_text = "No matches found."
                except Exception as e:
                    result_text = f"Search Error: {e}"
                    is_error = True

        elif name == "run_shell_command":
            raw_cmd = clean_arg(args.get("command", ""))
            is_background = args.get("background", False)
            
            cmd = resolve_python_command(raw_cmd)
            
            try:
                if is_background:
                     # Start and detach
                     proc = subprocess.Popen(
                        cmd,
                        shell=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        stdin=subprocess.DEVNULL
                     )
                     result_text = f"Started background process. PID: {proc.pid}"
                else:
                    proc = subprocess.run(
                        cmd, 
                        shell=True, 
                        capture_output=True, 
                        text=True, 
                        timeout=60
                    )
                    stdout = proc.stdout
                    stderr = proc.stderr
                    exit_code = proc.returncode
                    result_text = f"Exit Code: {exit_code}\nSTDOUT:\n{stdout.strip()}\nSTDERR:\n{stderr.strip()}"
                    
                    if exit_code != 0 and "not recognized" in stderr:
                         result_text += "\n[System Hint]: Check PATH or command spelling."
                     
            except subprocess.TimeoutExpired:
                result_text = "Error: Command timed out (60s limit)"
                is_error = True
            except Exception as e:
                result_text = "Execution Error for '{}': {} (Raw: {})".format(cmd, e, repr(raw_cmd))
                is_error = True

        else:
            result_text = f"Unknown tool: {name}"
            is_error = True
            
    except Exception as e:
        result_text = f"System Error: {str(e)}"
        is_error = True

    return {
        "content": [
            {
                "type": "text",
                "text": result_text
            }
        ],
        "isError": is_error
    }

def main():
    log("Server Started")
    while True:
        msg = read_message()
        if not msg: break
        
        method = msg.get("method")
        msg_id = msg.get("id")
        
        response = {
            "jsonrpc": "2.0",
            "id": msg_id
        }

        if method == "initialize":
            response["result"] = {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "serverInfo": {"name": "InternalFS", "version": "1.0"}
            }
        elif method == "tools/list":
            response["result"] = handle_list_tools()
        elif method == "tools/call":
            response["result"] = handle_call_tool(msg.get("params", {}))
        elif method == "notifications/initialized":
            continue 
        else:
            continue

        if msg_id is not None:
            send_message(response)

if __name__ == "__main__":
    main()
