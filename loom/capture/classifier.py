"""Classify tool events into actionable categories for session notes."""

from typing import Literal

EventType = Literal[
    "file_edit",
    "bash_command",
    "decision_signal",
    "error_resolution",
    "skip",
]

# Tools that produce file edits
_FILE_EDIT_TOOLS = frozenset({"Write", "Edit", "NotebookEdit"})

# Tools that are purely informational — not captured
_SKIP_TOOLS = frozenset({
    "Read", "Glob", "Grep", "TodoRead", "TaskList", "TaskGet",
    "WebSearch", "WebFetch", "AskUserQuestion",
})

# Keywords that signal an architectural or design decision
_DECISION_KEYWORDS = frozenset({
    "decided",
    "chose",
    "chosen",
    "instead of",
    "because",
    "trade-off",
    "tradeoff",
    "trade off",
    "went with",
    "opted for",
    "alternative",
    "rejected",
    "prefer",
    "preferred",
})


def _contains_decision_signal(text: str) -> bool:
    """Check whether text contains decision-related keywords."""
    lower = text.lower()
    return any(kw in lower for kw in _DECISION_KEYWORDS)


def classify_event(
    tool_name: str,
    tool_input: dict,
    tool_response: dict,
) -> EventType:
    """Classify a tool event into a capture category.

    Args:
        tool_name: Name of the tool that was used.
        tool_input: The input parameters passed to the tool.
        tool_response: The response returned by the tool.

    Returns:
        An EventType indicating how this event should be handled.
    """
    # Skip informational tools
    if tool_name in _SKIP_TOOLS:
        return "skip"

    # Check for decision signals in input/response text
    input_text = " ".join(str(v) for v in tool_input.values())
    response_text = str(tool_response)
    if _contains_decision_signal(input_text) or _contains_decision_signal(response_text):
        return "decision_signal"

    # File edit tools
    if tool_name in _FILE_EDIT_TOOLS:
        return "file_edit"

    # Bash commands
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        # Skip trivial commands
        if _is_trivial_bash(command):
            return "skip"
        return "bash_command"

    # Task management tools that modify state
    if tool_name in {"TaskCreate", "TaskUpdate", "TodoWrite"}:
        return "skip"

    # Default: skip unknown tools rather than pollute notes
    return "skip"


def _is_trivial_bash(command: str) -> bool:
    """Return True for trivial bash commands not worth capturing."""
    stripped = command.strip()
    if not stripped:
        return True

    first_word = stripped.split()[0] if stripped.split() else ""
    trivial_prefixes = {"ls", "pwd", "echo", "cat", "head", "tail", "which", "type", "whoami"}
    return first_word in trivial_prefixes
