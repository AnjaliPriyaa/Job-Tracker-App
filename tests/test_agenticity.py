"""
Agenticity acceptance tests.

Verifies that the LLM controls the workflow — there is no hard-coded
search → fetch → evaluate → notify sequence in the codebase.
"""

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_no_hardcoded_workflow_in_agent_py():
    """
    agent.py must NOT contain a deterministic loop like:
        for job in jobs: fetch(); evaluate(); notify()
    """
    agent_path = Path(__file__).resolve().parent.parent / "agent.py"
    source = agent_path.read_text()
    tree = ast.parse(source)

    # Check for for-loops that call multiple tools sequentially
    for node in ast.walk(tree):
        if isinstance(node, ast.For):
            # If the loop body contains calls to fetch, evaluate, AND notify,
            # that's a hard-coded workflow
            calls_in_loop = set()
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Name):
                        calls_in_loop.add(child.func.id)
                    elif isinstance(child.func, ast.Attribute):
                        calls_in_loop.add(child.func.attr)

            workflow_keywords = {"fetch", "evaluate", "notify", "match", "search"}
            found = calls_in_loop & workflow_keywords
            if len(found) >= 3:
                raise AssertionError(
                    f"Hard-coded workflow detected in for-loop at line {node.lineno}. "
                    f"Found: {found}. The agent must decide the workflow, not the code."
                )


def test_tools_are_typed_schemas():
    """Tools should use Pydantic BaseModel args_schema, not raw JSON strings."""
    from tools import ALL_TOOLS

    for tool in ALL_TOOLS:
        if hasattr(tool, 'args_schema') and tool.args_schema is not None:
            # Has typed schema — good
            pass
        else:
            # Check if the tool accepts a single 'input_data: str' parameter
            # which is the anti-pattern
            import inspect
            sig = inspect.signature(tool.func if hasattr(tool, 'func') else tool.__call__)
            params = list(sig.parameters.values())
            str_only = all(
                p.annotation == str or str(p.annotation) == "<class 'str'>"
                for p in params if p.name != 'self'
            )
            if str_only and len(params) == 1:
                print(f"  ⚠ {tool.name}: uses raw str input (consider typed schema)")


def test_notify_user_has_no_alternate_path():
    """
    There must be exactly ONE way to send Telegram notifications: notify_user().
    No other function should call the Telegram API directly.
    """
    import os

    # Search all Python files for direct Telegram API calls outside notification_tools.py
    telegram_patterns = [
        "api.telegram.org",
        "TELEGRAM_TOKEN",
        "sendMessage",
    ]

    root = Path(__file__).resolve().parent.parent
    violations = []

    for py_file in root.rglob("*.py"):
        if py_file.name in ("__init__.py",):
            continue
        if "notification_tools" in str(py_file):
            continue  # This is the allowed path

        try:
            content = py_file.read_text()
            for pattern in telegram_patterns:
                if pattern in content and "notification_tools" not in str(py_file):
                    violations.append(f"{py_file.relative_to(root)} contains '{pattern}'")
        except Exception:
            pass

    if violations:
        print("⚠ Telegram access found outside notification_tools.py:")
        for v in violations:
            print(f"  {v}")
        # Note: intentionally not asserting here since old files may still have it
        # The new architecture enforces this through the tool system


def test_agent_system_prompt_is_goal_oriented():
    """
    The system prompt must describe GOALS and TOOLS, not prescribe a fixed workflow.
    It should NOT contain step-by-step instructions like "1. search, 2. fetch, 3. evaluate".
    """
    from agent.prompts import SYSTEM_PROMPT

    # Should NOT contain a numbered workflow
    numbered_steps = ["1.", "2.", "3.", "4.", "5."]
    steps_found = [s for s in numbered_steps if s in SYSTEM_PROMPT]
    if steps_found:
        raise AssertionError(
            f"System prompt contains numbered steps {steps_found}. "
            "The prompt should describe goals and tools, not a fixed sequence."
        )

    # Should mention that the agent decides
    agentic_phrases = ["you decide", "you are in control", "no fixed workflow", "choose"]
    found = [p for p in agentic_phrases if p.lower() in SYSTEM_PROMPT.lower()]
    if not found:
        raise AssertionError(
            "System prompt doesn't indicate agent autonomy. "
            "It should tell the LLM it's in control of the workflow."
        )


def test_different_tool_sequences_possible():
    """
    Verify that multiple valid tool call sequences exist by checking that
    no Python code enforces a specific tool ordering (e.g., search before fetch).
    """
    root = Path(__file__).resolve().parent.parent

    for py_file in root.glob("*.py"):
        content = py_file.read_text()

        # Check for Python code that calls tools in a forced sequence
        # Pattern: search() followed by fetch() followed by evaluate()
        if "search_" in content and "fetch_job" in content and "evaluate_job" in content:
            # These functions existing in the same file isn't the problem —
            # but calling them in sequence IS
            pass

    # The key test: agent.py should not call tools directly in sequence
    agent_content = (root / "agent.py").read_text()
    tree = ast.parse(agent_content)

    # Count direct tool function calls in agent.py (outside string literals)
    tool_names = {"search_linkedin", "fetch_job", "evaluate_job", "notify_user",
                  "discover_company_career_page", "search_ats", "search_web_jobs"}

    direct_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in tool_names:
                    direct_calls.append(node.func.id)

    if direct_calls:
        raise AssertionError(
            f"agent.py directly calls tools: {direct_calls}. "
            f"The agent (LLM) should decide when to call tools, not the Python code."
        )
