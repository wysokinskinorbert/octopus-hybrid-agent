import time
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from octopus.core.session import OctopusSession

TASKS = [
    {
        "name": "Simple: Hello World File",
        "prompt": "Create a python script 'hello.py' that prints 'Hello Benchmark' and run it."
    },
    {
        "name": "Medium: Class Implementation",
        "prompt": "Create a file 'inventory.py'. Implement a class 'Item' with name/price. Implement 'Inventory' class with add_item and total_value methods. Create a main block to add 3 items and print total value. Run it."
    }
]

def run_benchmark():
    print("🚀 STARTING PERFORMANCE BENCHMARK (Local Models)")
    print("="*60)
    
    overall_start = time.time()
    
    for task in TASKS:
        print(f"\n📋 Task: {task['name']}")
        print(f"   Prompt: {task['prompt']}")
        print("-" * 40)
        
        session = OctopusSession(role_name="architect")
        # Initialize session (connect tools etc)
        list(session.initialize())
        
        start_time = time.time()
        
        # Inject the task
        generator = session.process_user_input(task['prompt'])
        
        step_count = 0
        user_answered = False
        
        try:
            while True:
                try:
                    event = next(generator)
                    step_count += 1
                    
                    if event.type == "question":
                        print(f"\n[BENCHMARK] Detected Question: {event.content[:100]}...")
                        print("[BENCHMARK] Auto-answering: 'Tak, realizuj plan.'")
                        # Restart generator with answer
                        generator = session.process_user_input("Tak, realizuj plan.")
                        user_answered = True
                        
                    elif event.type == "text":
                        role = event.metadata.get('role', 'unknown')
                        print(f"   [{role}]: {len(event.content)} chars")
                        
                    elif event.type == "tool_call":
                        print(f"   [Tool]: {event.content}")
                        
                    elif event.type == "error":
                        print(f"   [ERROR]: {event.content}")

                except StopIteration:
                    break
                    
        except Exception as e:
            print(f"   [EXCEPTION]: {e}")
        finally:
            session.shutdown()

        duration = time.time() - start_time
        print("-" * 40)
        print(f"✅ Task Completed in: {duration:.2f} seconds")
        print(f"   Steps processed: {step_count}")
    
    total_duration = time.time() - overall_start
    print("="*60)
    print(f"🏁 BENCHMARK COMPLETE. Total Time: {total_duration:.2f} seconds")

if __name__ == "__main__":
    run_benchmark()
