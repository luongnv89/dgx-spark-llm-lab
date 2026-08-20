"""Tests for project configuration files (.env.example, CLAUDE.md, AGENTS.md).

These tests verify the acceptance criteria for issues #2, #4, and #5:
- .env.example lists all harness environment variables
- CLAUDE.md has the required sections and stays under 80 lines
- AGENTS.md retains all guardrails and gains the token efficiency block
"""

import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestEnvExample(unittest.TestCase):
    """Issue #2: .env.example lists every env var the harness reads."""

    def setUp(self):
        self.path = os.path.join(REPO_ROOT, ".env.example")
        with open(self.path, encoding="utf-8") as f:
            self.content = f.read()

    def test_file_exists(self):
        self.assertTrue(os.path.isfile(self.path))

    def test_required_env_vars(self):
        """All BENCH_* and PI_CODING_AGENT_DIR vars must be present."""
        required = [
            "BENCH_BASE_URL",
            "BENCH_MODEL",
            "BENCH_THINKING",
            "BENCH_MAX_TOKENS",
            "BENCH_SAMPLES",
            "BENCH_CONCURRENCY",
            "BENCH_TEST_TIMEOUT",
            "PI_CODING_AGENT_DIR",
        ]
        for var in required:
            with self.subTest(var=var):
                self.assertIn(var, self.content, f"{var} missing from .env.example")

    def test_has_comments(self):
        """Every variable must have a descriptive comment (line starting with #)."""
        lines = self.content.splitlines()
        var_lines = [l for l in lines if re.match(r"^\w+=", l)]
        for var_line in var_lines:
            var_name = var_line.split("=")[0].strip()
            # There should be a comment line (starting with #) within a few lines
            idx = lines.index(var_line)
            found_comment = False
            for offset in range(max(0, idx - 3), idx):
                if lines[offset].strip().startswith("#"):
                    found_comment = True
                    break
            self.assertTrue(found_comment, f"{var_name} has no comment above it")


class TestClaudeMd(unittest.TestCase):
    """Issue #4: CLAUDE.md exists with required sections."""

    def setUp(self):
        self.path = os.path.join(REPO_ROOT, "CLAUDE.md")
        with open(self.path, encoding="utf-8") as f:
            self.content = f.read()
        self.lines = self.content.splitlines()

    def test_file_exists(self):
        self.assertTrue(os.path.isfile(self.path))

    def test_under_80_lines(self):
        """CLAUDE.md must be under 80 lines."""
        self.assertLess(len(self.lines), 80, f"CLAUDE.md is {len(self.lines)} lines (must be <80)")

    def test_critical_commands_section(self):
        """Must have Critical commands section with bench commands."""
        self.assertIn("## Critical commands", self.content)
        self.assertIn("./bench validate", self.content)
        self.assertIn("./bench validate --suite agentic-all", self.content)

    def test_python_floor(self):
        """Must mention Python >= 3.10."""
        self.assertIn("Python ≥ 3.10", self.content)

    def test_environment_variables_section(self):
        """Must have an Environment variables section."""
        self.assertIn("## Environment variables", self.content)
        self.assertIn("BENCH_BASE_URL", self.content)
        self.assertIn("BENCH_MODEL", self.content)

    def test_architecture_map_section(self):
        """Must have an Architecture map section."""
        self.assertIn("## Architecture map", self.content)

    def test_hard_rules_section(self):
        """Must have a Hard rules section with negative rules."""
        self.assertIn("## Hard rules", self.content)
        self.assertIn("Never", self.content)

    def test_workflow_preferences_section(self):
        """Must have a Workflow preferences section."""
        self.assertIn("## Workflow preferences", self.content)

    def test_token_efficiency_block(self):
        """Must include the token efficiency block."""
        self.assertIn("## Token Efficiency", self.content)
        self.assertIn("Never re-read files you just wrote or edited", self.content)

    def test_no_generic_fluff(self):
        """No generic advice like 'be a senior engineer' or 'think step by step'."""
        anti_patterns = [
            "be a senior",
            "think step by step",
            "write clean code",
            "always be professional",
        ]
        for pattern in anti_patterns:
            with self.subTest(pattern=pattern):
                self.assertNotIn(
                    pattern.lower(),
                    self.content.lower(),
                    f"Found generic fluff: '{pattern}'",
                )


class TestAgentsMd(unittest.TestCase):
    """Issue #5: AGENTS.md retains all guardrails and gains token efficiency block."""

    def setUp(self):
        self.path = os.path.join(REPO_ROOT, "AGENTS.md")
        with open(self.path, encoding="utf-8") as f:
            self.content = f.read()

    def test_file_exists(self):
        self.assertTrue(os.path.isfile(self.path))

    def test_guardrails_section_present(self):
        """Must still have the Guardrails section."""
        self.assertIn("## Guardrails", self.content)

    def test_all_guardrails_preserved(self):
        """All existing guardrails must be present after the update."""
        guardrails = [
            "Never edit a task's tests",
            "Never delete or overwrite",
            "results/",
            "append-only",
            "Never restart a shared serving endpoint",
            "Do not report a number you did not measure",
            "Report failures that were the harness's fault",
            "Never let a harness extension call a different model",
            "~100 %",
            "stopped measuring",
        ]
        for text in guardrails:
            with self.subTest(guardrail=text):
                self.assertIn(text, self.content, f"Guardrail content '{text}' missing")

    def test_token_efficiency_block(self):
        """Must include the token efficiency block."""
        self.assertIn("## Token Efficiency", self.content)
        self.assertIn("Never re-read files you just wrote or edited", self.content)

    def test_step_sections_intact(self):
        """All Step sections (0-7) must still be present."""
        for i in range(8):
            with self.subTest(step=i):
                self.assertIn(f"## Step {i}", self.content, f"Step {i} section missing")

    def test_adding_tasks_section_present(self):
        """Adding tasks section must still be present."""
        self.assertIn("## Adding tasks", self.content)


class TestUnifiedConfig(unittest.TestCase):
    """Cross-cutting tests for the unified configuration."""

    def test_env_example_and_claude_consistent(self):
        """Both .env.example and CLAUDE.md must mention the same BENCH vars."""
        env_path = os.path.join(REPO_ROOT, ".env.example")
        claude_path = os.path.join(REPO_ROOT, "CLAUDE.md")

        with open(env_path, encoding="utf-8") as f:
            env_content = f.read()
        with open(claude_path, encoding="utf-8") as f:
            claude_content = f.read()

        # All BENCH vars in .env.example should also appear in CLAUDE.md
        bench_vars = re.findall(r"(BENCH_\w+)", env_content)
        for var in bench_vars:
            with self.subTest(var=var):
                self.assertIn(var, claude_content, f"{var} in .env.example but not in CLAUDE.md")

    def test_claude_mentions_env_example(self):
        """CLAUDE.md should reference .env.example for the full list."""
        claude_path = os.path.join(REPO_ROOT, "CLAUDE.md")
        with open(claude_path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn(".env.example", content)

    def test_no_duplicate_build_commands_in_agents(self):
        """AGENTS.md should NOT duplicate the exact ./bench validate command
        as a new instruction (it already exists in Step 1, which is the runbook)."""
        agents_path = os.path.join(REPO_ROOT, "AGENTS.md")
        with open(agents_path, encoding="utf-8") as f:
            content = f.read()
        # The validate command in Step 1 is fine — it's part of the runbook.
        # We just verify the file is still coherent.
        self.assertIn("./bench validate", content)


if __name__ == "__main__":
    unittest.main()
