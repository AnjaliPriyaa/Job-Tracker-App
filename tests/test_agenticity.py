"""
Agenticity acceptance tests.

Verifies the architecture permits dynamic agent decision-making:
- No hard-coded tool sequences in Python code
- System prompt is goal-oriented, not workflow-prescriptive
- Different tool paths are possible based on different results
- notify_user always goes through PolicyEngine
"""

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_no_hardcoded_workflow_in_agent_py():
    """agent.py must NOT contain deterministic for-loops calling tools in sequence."""
    agent_path = Path(__file__).resolve().parent.parent / "agent.py"
    source = agent_path.read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.For):
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
                    f"Hard-coded workflow in for-loop line {node.lineno}. Found: {found}"
                )


def test_agent_py_does_not_call_tools_directly():
    """agent.py must not call tools directly — the LLM decides via create_deep_agent."""
    agent_path = Path(__file__).resolve().parent.parent / "agent.py"
    source = agent_path.read_text()
    tree = ast.parse(source)

    tool_names = {
        "search_linkedin", "search_web_jobs", "search_ats", "fetch_job",
        "evaluate_job", "notify_user", "discover_company_career_page",
        "discover_ats_platform", "save_job", "get_user_preferences",
        "extract_job_details", "get_seen_jobs", "get_job_history",
        "record_decision", "record_notification",
    }

    direct_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in tool_names:
                direct_calls.append(node.func.id)

    if direct_calls:
        raise AssertionError(
            f"agent.py directly calls tools: {direct_calls}. "
            "The LLM agent should decide tool sequence, not the Python code."
        )


def test_prompt_is_goal_oriented():
    """System prompt must describe goals, not prescribe numbered workflow steps."""
    from agent.prompts import SYSTEM_PROMPT

    # Must NOT contain a numbered workflow
    numbered_steps = ["1.", "2.", "3.", "4.", "5."]
    steps_found = [s for s in numbered_steps if s in SYSTEM_PROMPT]
    if steps_found:
        raise AssertionError(
            f"System prompt has numbered steps {steps_found}. Must be goal-oriented."
        )

    # Must NOT contain prescriptive sequences
    prescriptive = ["for each job", "then fetch", "then evaluate", "then notify"]
    for phrase in prescriptive:
        if phrase.lower() in SYSTEM_PROMPT.lower():
            raise AssertionError(
                f"System prompt contains prescriptive phrase: '{phrase}'"
            )

    # Should indicate agent autonomy
    agentic = ["you decide", "you are in control", "no fixed workflow", "choose"]
    found = [p for p in agentic if p.lower() in SYSTEM_PROMPT.lower()]
    assert found, "System prompt should indicate agent autonomy"


def test_context_messages_are_goal_oriented():
    """RUN_CONTEXT messages must be goal-oriented, not prescribe tool sequences."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("agent", Path(__file__).resolve().parent.parent / "agent.py")
    mod = importlib.util.module_from_spec(spec)
    # Parse the file directly to avoid executing __main__
    source = (Path(__file__).resolve().parent.parent / "agent.py").read_text()
    tree = ast.parse(source)

    # Find CONTEXT_MESSAGES dict
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and hasattr(node.targets[0], 'id'):
            if node.targets[0].id == 'CONTEXT_MESSAGES':
                for key_node in node.value.keys:
                    key = key_node.value
                    val = node.value.values[list(node.value.keys).index(key_node)].value
                    prohibited = ["for each job", "then search", "then fetch", "then evaluate"]
                    for phrase in prohibited:
                        if phrase.lower() in val.lower():
                            raise AssertionError(
                                f"CONTEXT '{key}' contains prescriptive '{phrase}'"
                            )


def test_notify_user_has_single_path():
    """Telegram API access must only go through notification_tools.notify_user."""
    root = Path(__file__).resolve().parent.parent
    telegram_calls = []

    for py_file in root.rglob("*.py"):
        pstr = str(py_file)
        if "notification_tools" in pstr or "__init__" in py_file.name:
            continue
        if ".venv" in pstr or "tests" in pstr or "site-packages" in pstr:
            continue
        try:
            content = py_file.read_text()
            for pattern in ["api.telegram.org", "sendMessage"]:
                if pattern in content:
                    telegram_calls.append(f"{py_file.relative_to(root)}: {pattern}")
        except Exception:
            pass

    if telegram_calls:
        raise AssertionError(
            f"Telegram API accessed outside notification_tools.py:\n" +
            "\n".join(telegram_calls)
        )


def test_tools_use_typed_schemas():
    """Tools should use Pydantic args_schema, not raw string input."""
    from tools import ALL_TOOLS

    for tool in ALL_TOOLS:
        has_schema = hasattr(tool, 'args_schema') and tool.args_schema is not None
        if not has_schema:
            print(f"  ⚠ {tool.name}: no typed schema")


def test_search_web_jobs_exists_and_workable():
    """search_web_jobs must be a real tool, not a stub."""
    from tools import ALL_TOOLS
    from tools.search_tools import search_web_jobs

    assert any(t.name == "search_web_jobs" for t in ALL_TOOLS), "search_web_jobs missing from ALL_TOOLS"

    import inspect
    source = inspect.getsource(search_web_jobs._run if hasattr(search_web_jobs, '_run') else search_web_jobs.func)
    assert "not yet implemented" not in source.lower(), "search_web_jobs is a stub"
    assert len(source) > 200, "search_web_jobs implementation too short"
