from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class WorkflowRunner:
    """Loads and executes named workflows from JSON definition files."""

    def __init__(self, workflows_dir: Path, action_map: dict[str, Any]) -> None:
        self._dir = workflows_dir
        self._action_map = action_map

    def list_workflows(self) -> None:
        """List all available workflows from the workflows directory."""
        if not self._dir.is_dir():
            print("No workflows directory found.")
            return

        workflow_files = sorted(self._dir.glob("*.json"))
        if not workflow_files:
            print("No workflows found.")
            return

        print("\nAvailable workflows:\n")
        for i, wf_path in enumerate(workflow_files, 1):
            try:
                data = json.loads(wf_path.read_text(encoding="utf-8"))
                name = data.get("name", wf_path.stem)
                description = data.get("description", "")
                print(f"  {i}. {wf_path.stem} — {name}")
                if description:
                    print(f"     {description}")
                print()
            except (json.JSONDecodeError, OSError) as e:
                logger.error(f"Failed to read workflow {wf_path.name}: {e}")

        print("Run a workflow: main.py --workflow <name>")

    def run_workflow(self, name: str) -> None:
        """Load and execute a named workflow from the workflows directory."""
        workflow_path = self._dir / f"{name}.json"

        if not workflow_path.is_file():
            logger.error(f"Workflow '{name}' not found at {workflow_path}")
            print(f"\nWorkflow '{name}' not found.")
            print("Use --workflow (without a name) to list available workflows.")
            return

        try:
            data = json.loads(workflow_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to load workflow '{name}': {e}")
            return

        workflow_name = data.get("name", name)
        steps = data.get("steps", [])

        if not steps:
            logger.warning(f"Workflow '{workflow_name}' has no steps")
            return

        logger.info(f"Running workflow: {workflow_name} ({len(steps)} steps)")

        for i, step in enumerate(steps, 1):
            action = step.get("action")
            if not action:
                logger.warning(f"Step {i} has no action, skipping")
                continue

            method = self._action_map.get(action)
            if not method:
                logger.error(f"Step {i}: unknown action '{action}', skipping")
                continue

            logger.info(f"Step {i}/{len(steps)}: {action}")
            try:
                params = step.get("params", {})
                if params:
                    method(**params)
                else:
                    method()
            except Exception as e:
                logger.error(f"Step {i} ({action}) failed: {e}")

        logger.info(f"Workflow '{workflow_name}' completed")
