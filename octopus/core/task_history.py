import json
import os
import time
from pathlib import Path
from difflib import SequenceMatcher

class TaskHistory:
    def __init__(self, history_file: str = "task_history.json"):
        self.history_file = Path(history_file)
        self.history = self._load()

    def _load(self):
        if not self.history_file.exists():
            return []
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return []

    def _save(self):
        try:
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(self.history, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Failed to save history: {e}")

    def add_task(self, prompt: str, log_path: str = "", status: str = "in_progress") -> str:
        task_id = str(int(time.time() * 1000))
        entry = {
            "id": task_id,
            "timestamp": time.time(),
            "date": time.strftime("%Y-%m-%d %H:%M:%S"),
            "prompt": prompt,
            "status": status,
            "log_path": log_path,
            "result_summary": ""
        }
        self.history.append(entry)
        # Keep last 50 tasks
        if len(self.history) > 50:
            self.history = self.history[-50:]
        self._save()
        return task_id

    def update_status(self, task_id: str, status: str, summary: str = None):
        for task in self.history:
            if task.get("id") == task_id:
                task["status"] = status
                if summary:
                    task["result_summary"] = summary[:200] + "..." if len(summary) > 200 else summary
                self._save()
                return

    def get_incomplete_tasks(self):
        """Returns list of tasks that are 'in_progress'."""
        return [t for t in reversed(self.history) if t.get("status") == "in_progress"]

    def delete_task(self, task_id: str):
        """Removes a task by ID."""
        self.history = [t for t in self.history if t.get("id") != task_id and str(t.get("timestamp")) != task_id]
        self._save()

    def clear_history(self):
        """Clears all tasks."""
        self.history = []
        self._save()

    def check_similarity(self, new_prompt: str, threshold: float = 0.85):
        """Returns the most similar task if similarity > threshold."""
        best_match = None
        highest_ratio = 0.0

        for task in reversed(self.history): # Check newest first
            ratio = SequenceMatcher(None, new_prompt.lower(), task["prompt"].lower()).ratio()
            if ratio > highest_ratio:
                highest_ratio = ratio
                best_match = task

        if highest_ratio >= threshold:
            return best_match
        return None
