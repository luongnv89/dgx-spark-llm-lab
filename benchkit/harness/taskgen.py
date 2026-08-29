"""Deterministic benchmark-task generator targeting specific surface tools.

Given a list of ``SurfaceTool`` objects, a campaign ID, and a seed, this
module produces reproducible task bundles — each with a workspace, a natural-
language prompt, a deterministic check predicate, and an oracle that
demonstrates how the expected surface tool solves the task.

Task templates are grouped by capability class so that every tool in the
harness surface gets at least one task exercising its unique behaviour.
"""
from __future__ import annotations

import hashlib
import random
from typing import Callable

from .surface import SurfaceTool

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

#: Capability-class labels that map surface-tool sources to template families.
_CAPABILITY_MAP: dict[str, str] = {
    "extension": "advisor/subagent",
    "skill":     "advisor/subagent",
    "mcp":       "search/retrieval",
    "plugin":    "code-analysis",
    "builtin":   None,  # builtins are never the *target* of a surface task
}

#: Difficulty labels used by the harness scoring pipeline.
_DIFFICULTIES = ("easy", "medium", "hard")

# ---------------------------------------------------------------------------
# Deterministic ID generation
# ---------------------------------------------------------------------------

def _task_id(surface_id: str, index: int) -> str:
    """Return a stable, human-readable task ID from a surface ID and index."""
    # Strip the harness prefix to keep IDs short and portable.
    short = surface_id.split(":", 1)[-1] if ":" in surface_id else surface_id
    return f"{short}-{index:03d}"


def _seeded_hash(campaign_id: str, surface_id: str, index: int, seed: int) -> str:
    """Deterministic token for workspace content variation."""
    raw = f"{campaign_id}:{surface_id}:{index}:{seed}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Task templates per capability class
# ---------------------------------------------------------------------------

def _template_advisor_subagent(
    tool: SurfaceTool, campaign_id: str, seed: int, index: int,
) -> dict:
    """Task requiring reasoning beyond the model's default capability.

    The workspace presents a problem that looks solvable with basic tools
    but actually requires the structured reasoning / delegation that an
    advisor or subagent tool provides.
    """
    sid = _task_id(tool.surface_id, index)
    h = _seeded_hash(campaign_id, tool.surface_id, index, seed)
    difficulty = _DIFFICULTIES[index % len(_DIFFICULTIES)]

    files: dict[str, str] = {
        "README.md": (
            f"# Project {h[:6]}\n\n"
            f"Goal: implement a small CLI tool that analyses code quality.\n"
            f"Seed: {seed}\n\n"
            "The team wants an automated review that checks for:\n"
            "- functions longer than 20 lines\n"
            "- missing docstrings on public functions\n"
            "- lines exceeding 120 characters\n"
            "Start by reading the existing source files, then produce a report.\n"
        ),
        "src/engine.py": (
            "# Core analysis engine\n\n"
            "This module contains the analysis logic.\n\n"
            "TODO: implement the quality checker.\n\n"
            "def check_file(path):\n"
            "    pass\n\n"
            "def generate_report(files):\n"
            "    pass\n"
        ),
        "src/__init__.py": "",
    }

    prompt = (
        f"Read the README.md in this workspace. The project needs a code-quality "
        f"review tool. The existing codebase has a stub in src/engine.py. "
        f"Use the {tool.tool_name} tool to reason about the best architecture "
        f"for this tool, then implement the quality checker in src/engine.py "
        f"so that running 'python -m src.engine' produces a summary report. "
        f"Do not change README.md."
    )

    def check(ws):
        engine = ws.files.get("src/engine.py", "")
        has_check = "def check_file" in engine
        has_report = "def generate_report" in engine
        readme_unchanged = ws.files.get("README.md") == ws.initial.get("README.md")
        if not (has_check and has_report and readme_unchanged):
            missing = []
            if not has_check:
                missing.append("check_file")
            if not has_report:
                missing.append("generate_report")
            return (False, f"missing: {', '.join(missing)}; readme changed: {not readme_unchanged}")
        return (True, "engine.py implements both required functions; README untouched")

    def oracle(ws):
        from .env import call
        return [
            call(ws, "read_file", {"path": "README.md"}),
            call(ws, "read_file", {"path": "src/engine.py"}),
            call(ws, tool.surface_id, {
                "task": "design a code-quality checker that finds long functions, missing docstrings, and long lines",
                "context": ws.files.get("src/engine.py", ""),
            }),
            call(ws, "edit_file", {
                "path": "src/engine.py",
                "old_text": "def check_file(path):\n    pass\n\n",
                "new_text": (
                    "def check_file(path):\n"
                    "    issues = []\n"
                    "    with open(path) as f:\n"
                    "        lines = f.readlines()\n"
                    "    for i, line in enumerate(lines, 1):\n"
                    "        if len(line.rstrip()) > 120:\n"
                    "            issues.append(f'line {i}: exceeds 120 chars')\n"
                    "    return issues\n\n"
                ),
            }),
            call(ws, "edit_file", {
                "path": "src/engine.py",
                "old_text": "def generate_report(files):\n    pass\n",
                "new_text": (
                    "def generate_report(files):\n"
                    "    for f in files:\n"
                    "        issues = check_file(f)\n"
                    "        print(f'{f}: {len(issues)} issues')\n"
                ),
            }),
            call(ws, "finish", {"summary": f"implemented code-quality checker via {tool.tool_name}"}),
        ]

    return {
        "id": sid,
        "prompt": prompt,
        "files": files,
        "check": check,
        "oracle": oracle,
        "expected_tools": [tool.surface_id],
        "difficulty": difficulty,
        "mode": "capability-gated",
    }


def _template_search_retrieval(
    tool: SurfaceTool, campaign_id: str, seed: int, index: int,
) -> dict:
    """Task requiring external knowledge or documentation lookup.

    The workspace contains fragmented documentation; the model must use the
    search/retrieval tool to find the right piece of information.
    """
    sid = _task_id(tool.surface_id, index)
    h = _seeded_hash(campaign_id, tool.surface_id, index, seed)
    difficulty = _DIFFICULTIES[index % len(_DIFFICULTIES)]

    files: dict[str, str] = {
        "docs/api.md": (
            "## API Reference\n\n"
            f"v{h[:3]}.0 — internal\n\n"
            "### /auth/login\n"
            "POST /auth/login — authenticates a user. Returns a JWT token.\n\n"
            "### /auth/logout\n"
            "POST /auth/logout — invalidates the current session.\n\n"
            "### /users\n"
            "GET /users — returns paginated user list.\n"
        ),
        "docs/config.md": (
            "## Configuration\n\n"
            f"Build {h[3:9]}\n\n"
            "Environment variables:\n"
            "- `DB_URL`: PostgreSQL connection string\n"
            "- `JWT_SECRET`: signing key for auth tokens\n"
            "- `RATE_LIMIT`: requests per minute (default 60)\n"
        ),
        "app/server.py": (
            "# Main server stub\n\n"
            "from fastapi import FastAPI\n\n"
            "app = FastAPI()\n\n"
            "# TODO: wire up /auth/login, /auth/logout, /users\n"
            "# See docs/api.md for endpoint specs.\n"
            "# See docs/config.md for required env vars.\n"
        ),
    }

    prompt = (
        f"Read the API docs in docs/api.md and the config docs in docs/config.md. "
        f"Implement the three endpoints in app/server.py using the specifications "
        f"from the docs. Use the {tool.tool_name} tool to search for best practices "
        f"on JWT authentication and rate limiting, then wire everything together. "
        f"Do not modify the documentation files."
    )

    def check(ws):
        server = ws.files.get("app/server.py", "")
        api_doc = ws.files.get("docs/api.md", "")
        config_doc = ws.files.get("docs/config.md", "")
        has_login = "/auth/login" in server
        has_logout = "/auth/logout" in server
        has_users = "/users" in server
        docs_untouched = (
            ws.files.get("docs/api.md") == ws.initial.get("docs/api.md")
            and ws.files.get("docs/config.md") == ws.initial.get("docs/config.md")
        )
        if not (has_login and has_logout and has_users and docs_untouched):
            missing = []
            if not has_login:
                missing.append("/auth/login")
            if not has_logout:
                missing.append("/auth/logout")
            if not has_users:
                missing.append("/users")
            return (False, f"missing endpoints: {', '.join(missing)}; docs changed: {not docs_untouched}")
        return (True, "all three endpoints implemented; docs untouched")

    def oracle(ws):
        from .env import call
        return [
            call(ws, "read_file", {"path": "docs/api.md"}),
            call(ws, "read_file", {"path": "docs/config.md"}),
            call(ws, tool.surface_id, {
                "query": "JWT authentication best practices FastAPI",
                "scope": "authentication",
            }),
            call(ws, "edit_file", {
                "path": "app/server.py",
                "old_text": "# TODO: wire up /auth/login, /auth/logout, /users\n",
                "new_text": (
                    "@app.post('/auth/login')\n"
                    "def login():\n"
                    "    pass\n\n"
                    "@app.post('/auth/logout')\n"
                    "def logout():\n"
                    "    pass\n\n"
                    "@app.get('/users')\n"
                    "def list_users():\n"
                    "    pass\n\n"
                ),
            }),
            call(ws, "finish", {"summary": f"wired endpoints using {tool.tool_name} for research"}),
        ]

    return {
        "id": sid,
        "prompt": prompt,
        "files": files,
        "check": check,
        "oracle": oracle,
        "expected_tools": [tool.surface_id],
        "difficulty": difficulty,
        "mode": "capability-gated",
    }


def _template_code_analysis(
    tool: SurfaceTool, campaign_id: str, seed: int, index: int,
) -> dict:
    """Task requiring codebase-wide analysis.

    The workspace has multiple files with a hidden issue that requires
    searching across the entire codebase to find.
    """
    sid = _task_id(tool.surface_id, index)
    h = _seeded_hash(campaign_id, tool.surface_id, index, seed)
    difficulty = _DIFFICULTIES[index % len(_DIFFICULTIES)]

    files: dict[str, str] = {
        "app/models.py": (
            "# Data models\n\n"
            "class User:\n"
            "    def __init__(self, name, email):\n"
            "        self.name = name\n"
            "        self.email = email\n\n"
            "class Order:\n"
            "    def __init__(self, user_id, total):\n"
            "        self.user_id = user_id\n"
            "        self.total = total\n"
        ),
        "app/service.py": (
            "# Business logic\n\n"
            "from app.models import User, Order\n\n"
            "def process_order(user_name, email, total):\n"
            "    user = User(user_name, email)\n"
            "    order = Order(user.name, total)  # BUG: should be user.id\n"
            "    return order\n\n"
            "def get_user_orders(user_id):\n"
            "    # fetch from DB\n"
            "    return []\n"
        ),
        "app/utils.py": (
            "# Shared utilities\n\n"
            "def format_currency(amount):\n"
            "    return f\"${amount:.2f}\"\n\n"
            "def validate_email(email):\n"
            "    return '@' in email\n\n"
            "# TODO: add phone validation\n"
        ),
        "tests/test_service.py": (
            "from app.service import process_order\n\n"
            "def test_process_order():\n"
            "    order = process_order('Alice', 'alice@example.com', 42.50)\n"
            "    assert order.total == 42.50\n"
            "    assert order.user_id == 'alice@example.com'\n"
            "    print('OK')\n"
        ),
    }

    prompt = (
        f"Run the tests in tests/test_service.py. One of the tests is silently "
        f"passing because of a design flaw — `user_id` is set to `user.name` "
        f"instead of a proper ID. Use the {tool.tool_name} tool to analyse the "
        f"entire codebase and find where this inconsistency lives, then fix it "
        f"so that `user_id` is properly derived. Do not change the test file."
    )

    def check(ws):
        service = ws.files.get("app/service.py", "")
        test = ws.files.get("tests/test_service.py", "")
        # The fix should reference a proper user_id, not user.name
        has_bug = "user.name" in service and "self.id" in service
        no_bug = "self.id" in service and "user.name" not in service
        test_unchanged = ws.files.get("tests/test_service.py") == ws.initial.get("tests/test_service.py")
        if not test_unchanged:
            return (False, "tests/test_service.py was modified")
        if has_bug:
            return (False, "user.name still used instead of proper user.id")
        if no_bug:
            return (True, "user_id properly derived from user.id; tests untouched")
        return (False, "unclear state — neither fixed nor clearly buggy")

    def oracle(ws):
        from .env import call
        return [
            call(ws, "search", {"pattern": "user\\.name"}),
            call(ws, "read_file", {"path": "app/models.py"}),
            call(ws, "read_file", {"path": "app/service.py"}),
            call(ws, tool.surface_id, {
                "query": "find all places where user_id is assigned from user.name",
                "scope": "app",
            }),
            call(ws, "edit_file", {
                "path": "app/models.py",
                "old_text": "class User:\n    def __init__(self, name, email):\n        self.name = name\n        self.email = email\n",
                "new_text": (
                    "class User:\n"
                    "    def __init__(self, name, email):\n"
                    "        self.id = f'{name[:3]}-{hash(email) % 10000}'\n"
                    "        self.name = name\n"
                    "        self.email = email\n"
                ),
            }),
            call(ws, "edit_file", {
                "path": "app/service.py",
                "old_text": "    order = Order(user.name, total)  # BUG: should be user.id\n",
                "new_text": "    order = Order(user.id, total)\n",
            }),
            call(ws, "finish", {"summary": f"fixed user_id assignment via {tool.tool_name} analysis"}),
        ]

    return {
        "id": sid,
        "prompt": prompt,
        "files": files,
        "check": check,
        "oracle": oracle,
        "expected_tools": [tool.surface_id],
        "difficulty": difficulty,
        "mode": "capability-gated",
    }


def _template_documentation(
    tool: SurfaceTool, campaign_id: str, seed: int, index: int,
) -> dict:
    """Task requiring reading/creating documentation.

    The workspace has code without documentation; the model must create
    proper docs using the documentation tool.
    """
    sid = _task_id(tool.surface_id, index)
    h = _seeded_hash(campaign_id, tool.surface_id, index, seed)
    difficulty = _DIFFICULTIES[index % len(_DIFFICULTIES)]

    files: dict[str, str] = {
        "calculator.py": (
            "# A simple calculator module\n\n"
            "def add(a, b):\n"
            "    return a + b\n\n"
            "def subtract(a, b):\n"
            "    return a - b\n\n"
            "def multiply(a, b):\n"
            "    return a * b\n\n"
            "def divide(a, b):\n"
            "    if b == 0:\n"
            "        raise ValueError('Cannot divide by zero')\n"
            "    return a / b\n\n"
            "def power(a, b):\n"
            "    return a ** b\n"
        ),
        "tests/test_calculator.py": (
            "from calculator import add, subtract, multiply, divide, power\n\n"
            "assert add(2, 3) == 5\n"
            "assert subtract(5, 3) == 2\n"
            "assert multiply(4, 3) == 12\n"
            "assert divide(10, 2) == 5.0\n"
            "try:\n"
            "    divide(1, 0)\n"
            "    assert False\n"
            "except ValueError:\n"
            "    pass\n"
            "assert power(2, 10) == 1024\n"
            "print('OK')\n"
        ),
    }

    prompt = (
        f"This workspace has a calculator module with no documentation. "
        f"Create a comprehensive API documentation file at docs/api.md that "
        f"describes every function in calculator.py with its parameters, "
        f"return type, and any exceptions. Also write a README.md at the "
        f"workspace root with a quick-start guide. Use the {tool.tool_name} "
        f"tool to ensure the documentation follows best practices. "
        f"Do not modify calculator.py or the test file."
    )

    def check(ws):
        api_doc = ws.files.get("docs/api.md", "")
        readme = ws.files.get("README.md", "")
        calc_unchanged = ws.files.get("calculator.py") == ws.initial.get("calculator.py")
        test_unchanged = ws.files.get("tests/test_calculator.py") == ws.initial.get("tests/test_calculator.py")
        if not calc_unchanged or not test_unchanged:
            return (False, "source or test file was modified")
        # Check that all four functions are documented
        for fn in ("add", "subtract", "multiply", "divide"):
            if fn not in api_doc:
                return (False, f"{fn} not documented in docs/api.md")
        # Check README has a quick-start section
        if "quick" not in readme.lower() and "start" not in readme.lower():
            return (False, "README missing quick-start section")
        return (True, "all functions documented; README has quick-start; source untouched")

    def oracle(ws):
        from .env import call
        return [
            call(ws, "read_file", {"path": "calculator.py"}),
            call(ws, "read_file", {"path": "tests/test_calculator.py"}),
            call(ws, tool.surface_id, {
                "task": "generate API documentation for a Python calculator module",
                "format": "markdown",
                "sections": ["parameters", "returns", "exceptions", "examples"],
            }),
            call(ws, "write_file", {
                "path": "docs/api.md",
                "content": (
                    "# Calculator API\n\n"
                    "## Functions\n\n"
                    "### `add(a, b)`\n"
                    "Returns the sum of `a` and `b`.\n\n"
                    "**Parameters:**\n"
                    "- `a`: first number\n"
                    "- `b`: second number\n\n"
                    "**Returns:** `a + b`\n\n"
                    "---\n\n"
                    "### `subtract(a, b)`\n"
                    "Returns `a - b`.\n\n"
                    "---\n\n"
                    "### `multiply(a, b)`\n"
                    "Returns `a * b`.\n\n"
                    "---\n\n"
                    "### `divide(a, b)`\n"
                    "Returns `a / b`. Raises `ValueError` if `b` is zero.\n\n"
                    "---\n\n"
                    "### `power(a, b)`\n"
                    "Returns `a ** b`.\n"
                ),
            }),
            call(ws, "write_file", {
                "path": "README.md",
                "content": (
                    "# Calculator\n\n"
                    "A simple calculator module.\n\n"
                    "## Quick Start\n\n"
                    "```python\n"
                    "from calculator import add, divide\n\n"
                    "print(add(2, 3))   # 5\n"
                    "print(divide(10, 2))  # 5.0\n"
                    "```\n\n"
                    "## Tests\n\n"
                    "Run `python tests/test_calculator.py`.\n"
                ),
            }),
            call(ws, "finish", {"summary": f"created API docs via {tool.tool_name}"}),
        ]

    return {
        "id": sid,
        "prompt": prompt,
        "files": files,
        "check": check,
        "oracle": oracle,
        "expected_tools": [tool.surface_id],
        "difficulty": difficulty,
        "mode": "assistive",
    }


def _template_issue_tracker(
    tool: SurfaceTool, campaign_id: str, seed: int, index: int,
) -> dict:
    """Task requiring GitHub/issue interaction.

    The workspace simulates an issue-tracking workflow — the model must
    use the issue-tracker tool to create, reference, or update issues.
    """
    sid = _task_id(tool.surface_id, index)
    h = _seeded_hash(campaign_id, tool.surface_id, index, seed)
    difficulty = _DIFFICULTIES[index % len(_DIFFICULTIES)]

    files: dict[str, str] = {
        "app.py": (
            "# Web application stub\n\n"
            "from flask import Flask\n\n"
            "app = Flask(__name__)\n\n"
            "@app.route('/')\n"
            "def index():\n"
            "    return 'Hello, World!'\n\n"
            "@app.route('/health')\n"
            "def health():\n"
            "    return {'status': 'ok'}\n\n"
            "if __name__ == '__main__':\n"
            "    app.run(debug=True)\n"
        ),
        "ISSUES.md": (
            "# Open Issues\n\n"
            "## #1 — Add authentication endpoint\n"
            "Status: open\n"
            "Priority: high\n"
            "Description: The app needs a /auth/login endpoint with JWT support.\n\n"
            "## #2 — Add health check test\n"
            "Status: open\n"
            "Priority: medium\n"
            "Description: Create a test for the /health endpoint.\n"
        ),
    }

    prompt = (
        f"This workspace has an open Flask app and an issues tracker in ISSUES.md. "
        f"Implement the authentication endpoint from issue #1 in app.py. "
        f"Use the {tool.tool_name} tool to look up the issue details and mark "
        f"it as resolved after implementation. Also create a new issue #3 for "
        f"adding rate limiting. Do not modify ISSUES.md manually."
    )

    def check(ws):
        app = ws.files.get("app.py", "")
        app_unchanged_initial = ws.initial.get("app.py", "")
        has_login = "/auth/login" in app
        has_jwt = "jwt" in app.lower() or "token" in app.lower()
        # The issue file should be updated by the tool, not manually
        issues = ws.files.get("ISSUES.md", "")
        has_issue3 = "#3" in issues and "rate limit" in issues.lower()
        if not has_login or not has_jwt:
            return (False, f"missing auth endpoint (has_login={has_login}, has_jwt={has_jwt})")
        if not has_issue3:
            return (False, "issue #3 not created in ISSUES.md")
        return (True, "auth endpoint implemented; issue #3 created")

    def oracle(ws):
        from .env import call
        return [
            call(ws, "read_file", {"path": "ISSUES.md"}),
            call(ws, tool.surface_id, {
                "action": "get",
                "issue_number": 1,
                "repo": "current",
            }),
            call(ws, "read_file", {"path": "app.py"}),
            call(ws, "edit_file", {
                "path": "app.py",
                "old_text": "@app.route('/health')\n",
                "new_text": (
                    "@app.route('/auth/login', methods=['POST'])\n"
                    "def login():\n"
                    "    import jwt\n"
                    "    return {'token': 'fake-jwt-token'}\n\n"
                    "@app.route('/health')\n"
                ),
            }),
            call(ws, tool.surface_id, {
                "action": "close",
                "issue_number": 1,
                "repo": "current",
                "resolution": "implemented /auth/login with JWT",
            }),
            call(ws, tool.surface_id, {
                "action": "create",
                "title": "Add rate limiting middleware",
                "body": "Implement rate limiting for all API endpoints.",
                "labels": ["enhancement", "security"],
            }),
            call(ws, "finish", {"summary": f"resolved issue #1 and created #3 via {tool.tool_name}"}),
        ]

    return {
        "id": sid,
        "prompt": prompt,
        "files": files,
        "check": check,
        "oracle": oracle,
        "expected_tools": [tool.surface_id],
        "difficulty": difficulty,
        "mode": "capability-gated",
    }


# Map capability classes to their template functions.
_TEMPLATES: dict[str, Callable] = {
    "advisor/subagent":  _template_advisor_subagent,
    "search/retrieval":  _template_search_retrieval,
    "code-analysis":     _template_code_analysis,
    "documentation":     _template_documentation,
    "issue-tracker":     _template_issue_tracker,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_tasks(
    tools: list[SurfaceTool],
    campaign_id: str,
    seed: int = 42,
) -> list[dict]:
    """Generate benchmark tasks targeting the given surface tools.

    Parameters
    ----------
    tools:
        List of ``SurfaceTool`` objects to target.
    campaign_id:
        Opaque campaign identifier used for deterministic ID generation.
    seed:
        Random seed for reproducibility.

    Returns
    -------
    ``list[dict]`` — each dict has keys ``id``, ``prompt``, ``files``,
    ``check``, ``oracle``, ``expected_tools``, ``difficulty``, ``mode``.

    Notes
    -----
    - Tasks are generated deterministically for the same ``(tools, campaign_id, seed)``.
    - Each tool gets exactly one task per capability class that maps to its source.
    - Tools with ``source == "builtin"`` are skipped (they are never the
      *target* of a surface-layer task).
    """
    rng = random.Random(seed)
    tasks: list[dict] = []
    index_by_tool: dict[str, int] = {}

    # Sort tools by surface_id for deterministic ordering.
    sorted_tools = sorted(tools, key=lambda t: t.surface_id)

    for tool in sorted_tools:
        # Skip builtins — they are never the *target* of a surface task.
        if tool.source == "builtin":
            continue

        capability = _CAPABILITY_MAP.get(tool.source)
        if capability is None:
            continue

        template_fn = _TEMPLATES.get(capability)
        if template_fn is None:
            continue

        idx = index_by_tool.get(tool.surface_id, 0)
        index_by_tool[tool.surface_id] = idx + 1

        task = template_fn(tool, campaign_id, seed, idx)
        tasks.append(task)

    # Shuffle with the seeded RNG so campaigns with many tools get a
    # non-trivial ordering while remaining fully reproducible.
    rng.shuffle(tasks)

    return tasks


def validate_pack(tasks: list[dict]) -> tuple[bool, list[str]]:
    """Validate a pack of generated tasks.

    Parameters
    ----------
    tasks:
        List of task dicts as returned by ``generate_tasks``.

    Returns
    -------
    ``(valid, errors)`` — ``valid`` is ``True`` when all checks pass;
    ``errors`` is a list of human-readable failure descriptions.
    """
    errors: list[str] = []
    seen_ids: set[str] = set()

    required_keys = {"id", "prompt", "files", "check", "oracle",
                     "expected_tools", "difficulty", "mode"}
    valid_difficulties = {"easy", "medium", "hard"}
    valid_modes = {"assistive", "capability-gated"}

    for i, task in enumerate(tasks):
        prefix = f"task[{i}] ({task.get('id', '<missing id>')})"

        # Check structure
        missing = required_keys - set(task.keys())
        if missing:
            errors.append(f"{prefix}: missing keys {sorted(missing)}")
            continue  # can't validate further without the keys

        # Check for duplicate IDs
        tid = task["id"]
        if tid in seen_ids:
            errors.append(f"{prefix}: duplicate task ID {tid!r}")
        seen_ids.add(tid)

        # Check callable fields
        if not callable(task["check"]):
            errors.append(f"{prefix}: 'check' is not callable")
        if not callable(task["oracle"]):
            errors.append(f"{prefix}: 'oracle' is not callable")

        # Check expected_tools is a non-empty list
        et = task.get("expected_tools")
        if not isinstance(et, list) or len(et) == 0:
            errors.append(f"{prefix}: 'expected_tools' must be a non-empty list")

        # Check difficulty
        if task.get("difficulty") not in valid_difficulties:
            errors.append(f"{prefix}: invalid difficulty {task.get('difficulty')!r}")

        # Check mode
        if task.get("mode") not in valid_modes:
            errors.append(f"{prefix}: invalid mode {task.get('mode')!r}")

        # Check files is a dict
        if not isinstance(task.get("files"), dict):
            errors.append(f"{prefix}: 'files' must be a dict of path->content")

        # Check prompt is a non-empty string
        if not isinstance(task.get("prompt"), str) or not task["prompt"].strip():
            errors.append(f"{prefix}: 'prompt' must be a non-empty string")

    return (len(errors) == 0, errors)


def coverage_report(
    tools: list[SurfaceTool],
    tasks: list[dict],
) -> dict:
    """Produce a coverage report for the given tools and tasks.

    Parameters
    ----------
    tools:
        The full list of surface tools available to the harness.
    tasks:
        The generated task list.

    Returns
    -------
    ``dict`` with keys:
    - ``tools_with_tasks``: list of surface IDs that have at least one task.
    - ``tools_without_tasks``: list of surface IDs with zero tasks.
    - ``by_difficulty``: dict mapping difficulty to count.
    - ``by_mode``: dict mapping mode to count.
    - ``total_tasks``: total number of tasks.
    - ``total_tools``: total number of tools considered.
    """
    # Build sets for quick lookup.
    tools_with: set[str] = set()
    for task in tasks:
        for sid in task.get("expected_tools", []):
            tools_with.add(sid)

    all_surface_ids = {t.surface_id for t in tools}
    tools_without = all_surface_ids - tools_with

    by_difficulty: dict[str, int] = {}
    by_mode: dict[str, int] = {}
    for task in tasks:
        d = task.get("difficulty", "unknown")
        by_difficulty[d] = by_difficulty.get(d, 0) + 1
        m = task.get("mode", "unknown")
        by_mode[m] = by_mode.get(m, 0) + 1

    return {
        "tools_with_tasks": sorted(tools_with),
        "tools_without_tasks": sorted(tools_without),
        "by_difficulty": by_difficulty,
        "by_mode": by_mode,
        "total_tasks": len(tasks),
        "total_tools": len(all_surface_ids),
    }
