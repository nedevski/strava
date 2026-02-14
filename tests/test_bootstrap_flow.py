import os
import stat
import subprocess
import tempfile
import unittest


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BOOTSTRAP_PATH = os.path.join(ROOT_DIR, "scripts", "bootstrap.sh")


def _write_executable(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    mode = os.stat(path).st_mode
    os.chmod(path, mode | stat.S_IXUSR)


class BootstrapFlowTests(unittest.TestCase):
    def _make_fake_bin(self, root: str) -> tuple[str, str, str]:
        fake_bin = os.path.join(root, "fake-bin")
        os.makedirs(fake_bin, exist_ok=True)
        git_log = os.path.join(root, "git.log")
        gh_log = os.path.join(root, "gh.log")
        py_log = os.path.join(root, "python.log")

        _write_executable(
            os.path.join(fake_bin, "git"),
            """#!/usr/bin/env bash
set -euo pipefail
echo "$*" >> "${FAKE_GIT_LOG}"
if [[ "${1:-}" == "rev-parse" && "${2:-}" == "--is-inside-work-tree" ]]; then
  if [[ "${FAKE_GIT_INSIDE_WORKTREE:-0}" == "1" ]]; then
    echo "true"
    exit 0
  fi
  exit 1
fi
if [[ "${1:-}" == "rev-parse" && "${2:-}" == "--show-toplevel" ]]; then
  if [[ -n "${FAKE_GIT_TOPLEVEL:-}" ]]; then
    echo "${FAKE_GIT_TOPLEVEL}"
    exit 0
  fi
  exit 1
fi
if [[ "${1:-}" == "clone" ]]; then
  target="${3:-}"
  mkdir -p "${target}/.git" "${target}/scripts"
  : > "${target}/scripts/setup_auth.py"
  exit 0
fi
if [[ "${1:-}" == "-C" ]]; then
  exit 0
fi
exit 0
""",
        )

        _write_executable(
            os.path.join(fake_bin, "gh"),
            """#!/usr/bin/env bash
set -euo pipefail
echo "$*" >> "${FAKE_GH_LOG}"
if [[ "${1:-}" == "auth" && "${2:-}" == "status" ]]; then
  exit 0
fi
if [[ "${1:-}" == "auth" && "${2:-}" == "login" ]]; then
  exit 0
fi
if [[ "${1:-}" == "api" && "${2:-}" == "user" ]]; then
  echo "tester"
  exit 0
fi
if [[ "${1:-}" == "repo" && "${2:-}" == "fork" ]]; then
  exit 0
fi
if [[ "${1:-}" == "repo" && "${2:-}" == "view" ]]; then
  exit 0
fi
exit 0
""",
        )

        _write_executable(
            os.path.join(fake_bin, "python3"),
            """#!/usr/bin/env bash
set -euo pipefail
echo "${PWD}|$*" >> "${FAKE_PY_LOG}"
exit 0
""",
        )

        return fake_bin, git_log, py_log

    def test_bootstrap_can_reuse_explicit_existing_clone_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_bin, git_log, py_log = self._make_fake_bin(tmpdir)
            run_dir = os.path.join(tmpdir, "runner")
            existing_clone = os.path.join(tmpdir, "existing-clone")
            os.makedirs(run_dir, exist_ok=True)
            os.makedirs(os.path.join(existing_clone, ".git"), exist_ok=True)
            os.makedirs(os.path.join(existing_clone, "scripts"), exist_ok=True)
            with open(os.path.join(existing_clone, "scripts", "setup_auth.py"), "w", encoding="utf-8") as f:
                f.write("# test\n")

            env = os.environ.copy()
            env["PATH"] = f"{fake_bin}:{env['PATH']}"
            env["FAKE_GIT_LOG"] = git_log
            env["FAKE_GH_LOG"] = os.path.join(tmpdir, "gh.log")
            env["FAKE_PY_LOG"] = py_log

            # Existing clone path? yes -> provide path -> run setup yes
            proc = subprocess.run(
                ["bash", BOOTSTRAP_PATH],
                input=f"y\n{existing_clone}\ny\n",
                text=True,
                capture_output=True,
                cwd=run_dir,
                env=env,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=f"{proc.stdout}\n{proc.stderr}")

            with open(git_log, "r", encoding="utf-8") as f:
                git_calls = f.read()
            self.assertNotIn("clone ", git_calls)

            with open(py_log, "r", encoding="utf-8") as f:
                py_calls = f.read()
            self.assertIn(f"{existing_clone}|scripts/setup_auth.py", py_calls)

    def test_bootstrap_detects_local_clone_and_runs_setup_without_clone_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_bin, git_log, py_log = self._make_fake_bin(tmpdir)
            local_clone = os.path.join(tmpdir, "local-clone")
            nested_dir = os.path.join(local_clone, "nested")
            os.makedirs(os.path.join(local_clone, ".git"), exist_ok=True)
            os.makedirs(os.path.join(local_clone, "scripts"), exist_ok=True)
            os.makedirs(nested_dir, exist_ok=True)
            with open(os.path.join(local_clone, "scripts", "setup_auth.py"), "w", encoding="utf-8") as f:
                f.write("# test\n")

            env = os.environ.copy()
            env["PATH"] = f"{fake_bin}:{env['PATH']}"
            env["FAKE_GIT_LOG"] = git_log
            env["FAKE_GH_LOG"] = os.path.join(tmpdir, "gh.log")
            env["FAKE_PY_LOG"] = py_log
            env["FAKE_GIT_INSIDE_WORKTREE"] = "1"
            env["FAKE_GIT_TOPLEVEL"] = local_clone

            proc = subprocess.run(
                ["bash", BOOTSTRAP_PATH],
                input="y\n",
                text=True,
                capture_output=True,
                cwd=nested_dir,
                env=env,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=f"{proc.stdout}\n{proc.stderr}")

            with open(git_log, "r", encoding="utf-8") as f:
                git_calls = f.read()
            self.assertIn("rev-parse --is-inside-work-tree", git_calls)
            self.assertIn("rev-parse --show-toplevel", git_calls)
            self.assertNotIn("clone ", git_calls)

            with open(py_log, "r", encoding="utf-8") as f:
                py_calls = f.read()
            self.assertIn(f"{local_clone}|scripts/setup_auth.py", py_calls)

    def test_bootstrap_keeps_fresh_clone_default_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_bin, git_log, py_log = self._make_fake_bin(tmpdir)
            run_dir = os.path.join(tmpdir, "runner")
            os.makedirs(run_dir, exist_ok=True)

            env = os.environ.copy()
            env["PATH"] = f"{fake_bin}:{env['PATH']}"
            env["FAKE_GIT_LOG"] = git_log
            env["FAKE_GH_LOG"] = os.path.join(tmpdir, "gh.log")
            env["FAKE_PY_LOG"] = py_log

            # Existing clone path? no -> fork? no -> clone upstream? yes -> run setup? no
            proc = subprocess.run(
                ["bash", BOOTSTRAP_PATH],
                input="n\nn\ny\nn\n",
                text=True,
                capture_output=True,
                cwd=run_dir,
                env=env,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=f"{proc.stdout}\n{proc.stderr}")

            expected_target = os.path.join(run_dir, "git-sweaty")
            with open(git_log, "r", encoding="utf-8") as f:
                git_calls = f.read()
            clone_lines = [line for line in git_calls.splitlines() if line.startswith("clone ")]
            self.assertEqual(len(clone_lines), 1)
            self.assertIn("clone https://github.com/aspain/git-sweaty.git ", clone_lines[0])
            clone_target = clone_lines[0].split(" ", 2)[2]
            self.assertEqual(os.path.basename(clone_target), "git-sweaty")
            self.assertEqual(os.path.basename(os.path.dirname(clone_target)), "runner")
            self.assertEqual(
                os.path.realpath(clone_target),
                os.path.realpath(expected_target),
            )

            self.assertFalse(os.path.exists(py_log), "setup_auth should not run when user skips setup")


if __name__ == "__main__":
    unittest.main()
