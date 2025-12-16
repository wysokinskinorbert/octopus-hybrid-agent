import sys
import os
import json
import traceback
# Ensure project root is in path
sys.path.append(os.getcwd())

from octopus.core.session import OctopusSession

def run_headless():
    print("🚀 OCTOPUS HEADLESS RUNNER")
    print("==========================")
    
    # Task: Analyze the current project structure and creating a summary file.
    # This exercises: Architect, Tools (list, read), and Developer (write).
    prompt = "Analyze the 'demo_project' directory. List all files, read 'main.py' if it exists, and create a file 'analysis_report.md' in the root with a summary."
    
    print(f"Task: {prompt}\n")
    
    session = None
    try:
        session = OctopusSession(role_name="architect")
        print("[Status] Initializing Session...")
        for msg in session.initialize():
            # print(f"  [Init]: {msg}") # verbose
            pass
        print("[Status] Session Initialized.")
        
        generator = session.process_user_input(prompt)
        
        print("[Status] Processing Task...")
        step = 0
        while True:
            try:
                event = next(generator)
                step += 1
                
                # Simple event logging
                if event.type == "text":
                    role = event.metadata.get('role', 'unknown')
                    content_preview = event.content[:100].replace('\n', ' ')
                    print(f"  [{role}]: {content_preview}...")
                    
                elif event.type == "tool_call":
                    print(f"  [Tool]: {event.content}")
                    
                elif event.type == "tool_result":
                    # print(f"    -> Result: {event.content[:50]}...")
                    pass
                    
                elif event.type == "question":
                    print(f"\n  [❓ QUESTION]: {event.content}")
                    print("  [ACTION]: Auto-approving (Yes)")
                    generator = session.process_user_input("Yes")
                    
                elif event.type == "error":
                    print(f"  [❌ ERROR]: {event.content}")
                    
                elif event.type == "status":
                    # print(f"  [Status]: {event.content}")
                    pass

            except StopIteration:
                print("\n[Status] Workflow Finished.")
                break
                
    except Exception as e:
        print(f"\n[CRITICAL FAILURE]: {e}")
        traceback.print_exc()
    finally:
        if session:
            session.shutdown()
            print("[Status] Cleanup Complete.")

if __name__ == "__main__":
    run_headless()
