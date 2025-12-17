import sys
import os
import asyncio
from typing import Optional

# Add project root to sys.path
sys.path.append(os.getcwd())

from octopus.core.session import OctopusSession
from octopus.core.config_store import ConfigStore
from octopus.core.logger import SessionLogger 
from octopus.core.session import SessionEvent

class HeadlessLogger(SessionLogger):
    def __init__(self):
        super().__init__() # Default logs dir
        self.log_file_txt = "headless_output.txt"
        with open(self.log_file_txt, "w", encoding="utf-8") as f:
            f.write("--- Headless Validation Log ---\n")

    def log_event(self, event_type: str, content: str, metadata: Optional[dict] = None):
        super().log_event(event_type, content, metadata)
        # Also write to text file for immediate feedback checking
        with open(self.log_file_txt, "a", encoding="utf-8") as f:
             if event_type == "log" and "DEBUG" in content:
                 f.write(f"[DEBUG] {content}\n")
             elif event_type in ["tool_call", "tool_result", "error", "status", "text"]:
                 f.write(f"[{event_type.upper()}] {content}\n")

def run_test():
    print("--- STARTING HEADLESS VERIFICATION ---")
    
    # Setup dependencies
    config_store = ConfigStore()
    logger = HeadlessLogger()
    
    # Initialize Session
    session = OctopusSession(config_store, logger)
    session.debug_mode = True 
    
    # Task to run
    user_input = "uruchom aplikację pogoda-dashboard"
    
    print(f"\nUser Input: {user_input}")
    
    try:
        for event in session.process_user_input(user_input):
            # Also print to stdout for redundancy
            if event.type == "text":
                print(f"\n[AI]: {event.content}\n", flush=True)
            elif event.type == "tool_call":
                print(f"[TOOL CALL] {event.content}", flush=True)
            elif event.type == "tool_result":
                print(f"[TOOL RESULT] {event.content}", flush=True)
            elif event.type == "status":
                print(f"[STATUS] {event.content}", flush=True)
            elif event.type == "error":
                print(f"[ERROR] {event.content}", flush=True)
            
            # Simple exit condition: if we see list_directory success or failure
            if event.type == "tool_call" and "list_directory" in event.content:
                print(">> LIST_DIRECTORY CALLED <<", flush=True)
            
            if event.type == "tool_result" and "list_directory" in event.content:
                 print(">> LIST_DIRECTORY RESULT RECEIVED - SUCCESS! <<", flush=True)
                 # We can break early if we just wanted to verify this step
                 # break 
                
    except KeyboardInterrupt:
        print("\nTest cancelled by user.", flush=True)
    except Exception as e:
        print(f"\nCRITICAL ERROR: {e}", flush=True)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run_test()
