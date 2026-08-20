"""OpenAI-style tool schemas for the agentic suite.

Descriptions are deliberately plain: the benchmark measures whether a model can
pick and call the right tool, not whether it can decode clever prompt wording.
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List the files in the workspace, optionally under a directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string",
                             "description": "Directory to list. Defaults to the whole workspace."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file. Output is prefixed with line numbers.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create a file or replace its entire contents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string", "description": "The complete new file body."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": ("Replace one exact occurrence of old_text with new_text in a file. "
                            "old_text must appear exactly once, including indentation."),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search every file for a Python regular expression. Returns path:line: text.",
            "parameters": {
                "type": "object",
                "properties": {"pattern": {"type": "string"}},
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": "Run a Python file in the workspace and return its exit code, stdout and stderr.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": ("Call this when the task is complete. Do not call it before you have "
                            "verified your work."),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "One sentence on what you did."},
                },
                "required": ["summary"],
            },
        },
    },
]

SYSTEM = (
    "You are a software engineer working in a small workspace through tools. "
    "Use the tools to inspect and change files; do not ask the user questions and do not "
    "guess at file contents you have not read. Verify your work by running the relevant "
    "file before you finish. When the task is done, call finish."
)
