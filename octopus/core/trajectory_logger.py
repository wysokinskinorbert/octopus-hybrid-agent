"""
Trajectory Logger for Octopus Session Observability.
Tracks agent decision-making for post-mortem analysis.
"""

import time
import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict


@dataclass
class TrajectoryStep:
    """Single decision point in agent trajectory."""
    timestamp: float
    decision_point: str
    options: List[str]
    chosen: str
    reasoning: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class TrajectoryLogger:
    """Logs agent decision trajectory for debugging and analysis."""
    
    def __init__(self, session_id: str, log_dir: str = "logs"):
        self.session_id = session_id
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        
        self.trajectory: List[TrajectoryStep] = []
        self.session_start = time.time()
    
    def log_decision(
        self,
        decision_point: str,
        options: List[str],
        chosen: str,
        reasoning: str = "",
        **metadata
    ):
        """Log a decision point in agent trajectory."""
        step = TrajectoryStep(
            timestamp=time.time(),
            decision_point=decision_point,
            options=options,
            chosen=chosen,
            reasoning=reasoning,
            metadata=metadata
        )
        self.trajectory.append(step)
    
    def log_tool_call(self, tool_name: str, arguments: Dict[str, Any], metadata: Optional[Dict] = None):
        """Convenience method for logging tool calls."""
        self.log_decision(
            decision_point="tool_selection",
            options=[tool_name],  # In practice, could show all available tools
            chosen=tool_name,
            reasoning="",
            arguments=arguments,
            **(metadata or {})
        )
    
    def log_error(self, error_type: str, error_msg: str, recovery_action: str = ""):
        """Log error occurrences and recovery attempts."""
        self.log_decision(
            decision_point="error_handling",
            options=["retry", "skip", "abort", "escalate"],
            chosen=recovery_action or "unknown",
            reasoning=error_msg,
            error_type=error_type
        )
    
    def save(self) -> Path:
        """Save trajectory to JSON file."""
        filepath = self.log_dir / f"trajectory_{self.session_id}.json"
        
        trajectory_data = {
            "session_id": self.session_id,
            "session_start": self.session_start,
            "session_duration": time.time() - self.session_start,
            "total_steps": len(self.trajectory),
            "trajectory": [asdict(step) for step in self.trajectory]
        }
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(trajectory_data, f, indent=2)
        
        return filepath
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics of trajectory."""
        if not self.trajectory:
            return {"total_steps": 0}
        
        decision_counts = {}
        for step in self.trajectory:
            decision_counts[step.decision_point] = decision_counts.get(step.decision_point, 0) + 1
        
        return {
            "total_steps": len(self.trajectory),
            "duration": time.time() - self.session_start,
            "decision_types": decision_counts,
            "first_step": self.trajectory[0].decision_point if self.trajectory else None,
            "last_step": self.trajectory[-1].decision_point if self.trajectory else None
        }
