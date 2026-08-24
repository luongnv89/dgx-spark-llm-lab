"""Regression guards for the vLLM launcher scripts (start-*.sh, configs/*.sh).

These scripts are the deployment artifact: `./bench apply` copies one into place
and systemd execs it. Nothing in CI used to run or lint them, so a launcher that
could not even assemble its own `docker run` shipped to main.

On 2026-08-24 that cost the endpoint a morning. Commit 87e784c added an inline
comment to a backslash-continued line:

    --network host   # required: vLLM needs host networking for GPU direct \\

The `#` comment swallows the backslash, so the command ends there and docker is
invoked with no IMAGE argument. `vllm-qwen.service` crash-looped ~600 times and
`montimage-dgx-spark` vanished from /v1/models. `bash -n` does not catch this --
the script is syntactically valid, just truncated -- so the real check is
`test_docker_run_is_complete`, which executes each launcher against a fake
`docker` and inspects the argv that actually comes out. That catches any cause
of truncation, not only this one.
"""

import os
import re
import stat
import subprocess
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Launchers that build a `docker run ... serve <model>` vLLM invocation.
VLLM_LAUNCHERS = [
    "serve-qwen38-4bit.sh",
    "start-gemma.sh",
    "start-qwen.sh",
    "configs/gemma4-12b-w4a16.sh",
    "configs/ornith-1.5-35b-a3b-nvfp4.sh",
    "configs/qwen3.6-35b-a3b-nvfp4.sh",
    "configs/qwen3.8-27b-nvfp4-dspark.sh",
    "configs/qwen3.8-27b-nvfp4-tunable.sh",
]

# A `#` comment here eats the line continuation and truncates the command.
INLINE_COMMENT_ON_CONTINUED_LINE = re.compile(r"^\s*\S.*\s#\s.*\\$")

# Prints its argv NUL-separated for `docker run`, and stays silent otherwise so
# the `docker ps` readiness polls in the detached launchers fall through fast.
DOCKER_SHIM = """#!/bin/sh
if [ "$1" = "run" ]; then
  : > "$DOCKER_ARGV_FILE"
  for a in "$@"; do printf '%s\\0' "$a" >> "$DOCKER_ARGV_FILE"; done
fi
exit 0
"""


def all_shell_scripts():
    """Every tracked *.sh in the repo, as paths relative to REPO_ROOT."""
    out = subprocess.run(
        ["git", "ls-files", "*.sh"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    )
    return [p for p in out.stdout.split("\n") if p]


class TestShellScriptSyntax(unittest.TestCase):
    """Cheap static checks that apply to every shell script in the repo."""

    def test_scripts_are_found(self):
        """Guard the guard: an empty file list would make every test vacuous."""
        self.assertGreaterEqual(len(all_shell_scripts()), len(VLLM_LAUNCHERS))

    def test_bash_syntax(self):
        for rel in all_shell_scripts():
            with self.subTest(script=rel):
                proc = subprocess.run(
                    ["bash", "-n", os.path.join(REPO_ROOT, rel)],
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_no_inline_comment_on_continued_line(self):
        """`flag  # why \\` — the comment eats the backslash (shellcheck SC1143)."""
        for rel in all_shell_scripts():
            path = os.path.join(REPO_ROOT, rel)
            with open(path, encoding="utf-8") as f:
                for lineno, line in enumerate(f, start=1):
                    line = line.rstrip("\n")
                    if INLINE_COMMENT_ON_CONTINUED_LINE.match(line):
                        self.fail(
                            f"{rel}:{lineno} has an inline comment on a "
                            f"continued line, which swallows the backslash and "
                            f"truncates the command:\n    {line}\n"
                            f"Move the comment above the command instead."
                        )

    def test_no_comment_line_inside_continued_command(self):
        """A comment on its own line inside a continued command truncates it too."""
        for rel in all_shell_scripts():
            path = os.path.join(REPO_ROOT, rel)
            with open(path, encoding="utf-8") as f:
                lines = [line.rstrip("\n") for line in f]
            for lineno, line in enumerate(lines[1:], start=2):
                previous = lines[lineno - 2]
                if previous.rstrip().endswith("\\") and line.lstrip().startswith("#"):
                    self.fail(
                        f"{rel}:{lineno} is a comment inside a continued "
                        f"command, which ends it early:\n    {line}\n"
                        f"Move the comment above the command instead."
                    )


class TestVllmLaunchersAssemble(unittest.TestCase):
    """Run each launcher against a fake docker and inspect the real argv."""

    def _capture_docker_run(self, rel):
        """Execute *rel* with a shimmed docker; return the `docker run` argv."""
        with tempfile.TemporaryDirectory() as tmp:
            shim_dir = os.path.join(tmp, "bin")
            os.makedirs(shim_dir)
            shim = os.path.join(shim_dir, "docker")
            with open(shim, "w", encoding="utf-8") as f:
                f.write(DOCKER_SHIM)
            os.chmod(shim, os.stat(shim).st_mode | stat.S_IEXEC | stat.S_IXGRP)

            argv_file = os.path.join(tmp, "argv")
            env = dict(os.environ)
            env.update({
                "PATH": shim_dir + os.pathsep + env["PATH"],
                "DOCKER_ARGV_FILE": argv_file,
                # Keep every host path the scripts mkdir inside the sandbox.
                "HF_HOME_DIR": os.path.join(tmp, "hf"),
                "HF_CACHE": os.path.join(tmp, "hf"),
                "VLLM_CACHE": os.path.join(tmp, "vllm"),
                "VLLM_CACHE_DIR": os.path.join(tmp, "vllm"),
            })
            subprocess.run(
                ["bash", os.path.join(REPO_ROOT, rel)],
                env=env, capture_output=True, text=True, timeout=120, check=False,
            )
            self.assertTrue(
                os.path.exists(argv_file),
                f"{rel} never reached `docker run` at all",
            )
            with open(argv_file, encoding="utf-8") as f:
                # Each arg is NUL-terminated, so the split leaves one trailing
                # empty element. Drop only that one: an empty *argument* is
                # meaningful here (`--allowed-media-domains ""` is the bug).
                raw = f.read().split("\0")
                self.assertEqual(raw[-1], "")
                return raw[:-1]

    def test_docker_run_is_complete(self):
        """Each launcher must reach `docker run` with an IMAGE before `serve`.

        This is the check that would have caught the 2026-08-24 truncation.
        """
        for rel in VLLM_LAUNCHERS:
            with self.subTest(script=rel):
                argv = self._capture_docker_run(rel)
                self.assertEqual(argv[0], "run")
                self.assertIn(
                    "serve", argv,
                    f"{rel}: `docker run` argv has no `serve` subcommand, so "
                    f"the command was truncated: {argv}",
                )
                image = argv[argv.index("serve") - 1]
                self.assertFalse(
                    image.startswith("-"),
                    f"{rel}: expected an IMAGE before `serve`, got the flag "
                    f"{image!r}; the command is truncated or misordered",
                )
                self.assertRegex(
                    image, r"^[A-Za-z0-9][\w.\-/]*(:[\w.\-]+|@sha256:[0-9a-f]{64})$",
                    f"{rel}: {image!r} does not look like an image reference",
                )

    def test_no_empty_allowed_media_domains(self):
        """`--allowed-media-domains ""` makes vLLM refuse to start.

        vLLM parses the empty string as [None] and pydantic rejects it, so the
        server dies at startup. Multimodal is disabled with
        `--limit-mm-per-prompt '{"image":0}'` instead, which also removes the
        SSRF surface (F-SEC-002) rather than merely narrowing it.
        """
        for rel in VLLM_LAUNCHERS:
            with self.subTest(script=rel):
                argv = self._capture_docker_run(rel)
                if "--allowed-media-domains" not in argv:
                    continue
                value = argv[argv.index("--allowed-media-domains") + 1]
                self.assertNotEqual(
                    value, "",
                    f"{rel}: --allowed-media-domains \"\" is rejected by vLLM at "
                    f"startup; disable multimodal with --limit-mm-per-prompt "
                    f"'{{\"image\":0}}' or name an explicit host allowlist",
                )


if __name__ == "__main__":
    unittest.main()
