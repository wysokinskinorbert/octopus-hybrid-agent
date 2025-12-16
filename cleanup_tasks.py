import json
import shutil
from pathlib import Path

HISTORY_FILE = "task_history.json"
BACKUP_FILE = "task_history.bak"

IGNORE_KEYWORDS = {
    "tak", "nie", "yes", "no", "y", "n", "ok", "okay", "confirm", "cancel", "continue", 
    "start", "stop", "exit", "quit", "help", "menu", "a", "b", "c", "1", "2", "3"
}

def cleanup():
    path = Path(HISTORY_FILE)
    if not path.exists():
        print("No history file found.")
        return

    # Backup
    shutil.copy(path, BACKUP_FILE)
    print(f"Backup created: {BACKUP_FILE}")

    with open(path, "r", encoding="utf-8") as f:
        tasks = json.load(f)

    cleaned_tasks = []
    removed_count = 0

    for task in tasks:
        prompt = task.get("prompt", "").strip()
        lower_prompt = prompt.lower()
        
        # Heurystyka: Krótkie odpowiedzi to nie zadania
        is_trash = False
        if len(prompt) < 4:
            is_trash = True
        elif lower_prompt in IGNORE_KEYWORDS:
            is_trash = True
        elif lower_prompt.startswith("odp"):
            is_trash = True
        
        if not is_trash:
            cleaned_tasks.append(task)
        else:
            removed_count += 1
            print(f"Removing: '{prompt}'")

    with open(path, "w", encoding="utf-8") as f:
        json.dump(cleaned_tasks, f, indent=2, ensure_ascii=False)

    print(f"Cleanup complete. Removed {removed_count} items. Kept {len(cleaned_tasks)} items.")

if __name__ == "__main__":
    cleanup()
