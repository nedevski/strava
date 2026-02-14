import os
import subprocess
import sys
import unittest
from unittest import mock


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS_DIR = os.path.join(ROOT_DIR, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import setup_auth  # noqa: E402


def _completed_process(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class SetupAuthPreflightTests(unittest.TestCase):
    def test_extract_gh_token_scopes_parses_status_output(self) -> None:
        output = """
        Logged in to github.com account user
          - Token scopes: 'repo', 'workflow', 'read:org'
        """

        scopes = setup_auth._extract_gh_token_scopes(output)

        self.assertEqual(scopes, {"repo", "workflow", "read:org"})

    def test_build_actions_secret_access_error_mentions_missing_scopes(self) -> None:
        message = setup_auth._build_actions_secret_access_error(
            repo="owner/repo",
            detail="HTTP 403: Resource not accessible by integration",
            status_output="  - Token scopes: 'repo'",
        )

        self.assertIn("Missing token scopes: workflow.", message)
        self.assertIn("gh auth refresh -s workflow,repo", message)
        self.assertIn("correct repository", message)

    def test_assert_actions_secret_access_succeeds_when_public_key_is_readable(self) -> None:
        with mock.patch(
            "setup_auth._run",
            return_value=_completed_process(returncode=0, stdout='{"key":"abc"}'),
        ) as run_mock:
            setup_auth._assert_actions_secret_access("owner/repo")

        run_mock.assert_called_once_with(
            ["gh", "api", "repos/owner/repo/actions/secrets/public-key"],
            check=False,
        )

    def test_assert_actions_secret_access_raises_targeted_fix_for_integration_403(self) -> None:
        responses = [
            _completed_process(
                returncode=1,
                stderr="gh: Resource not accessible by integration (HTTP 403)\n",
            ),
            _completed_process(
                returncode=0,
                stderr="  - Token scopes: 'repo'\n",
            ),
        ]

        with mock.patch("setup_auth._run", side_effect=responses):
            with self.assertRaises(RuntimeError) as exc_ctx:
                setup_auth._assert_actions_secret_access("owner/repo")

        message = str(exc_ctx.exception)
        self.assertIn("gh auth refresh -s workflow,repo", message)
        self.assertIn("Missing token scopes: workflow.", message)
        self.assertIn("organization fork", message)

    def test_assert_actions_secret_access_raises_generic_error_for_non_403_failures(self) -> None:
        with mock.patch(
            "setup_auth._run",
            return_value=_completed_process(returncode=1, stderr="gh: Not Found (HTTP 404)\n"),
        ):
            with self.assertRaises(RuntimeError) as exc_ctx:
                setup_auth._assert_actions_secret_access("owner/repo")

        self.assertIn("Unable to access Actions secrets API", str(exc_ctx.exception))

    def test_assert_actions_secret_access_raises_guidance_for_generic_403(self) -> None:
        with mock.patch(
            "setup_auth._run",
            return_value=_completed_process(returncode=1, stderr="gh: Forbidden (HTTP 403)\n"),
        ):
            with self.assertRaises(RuntimeError) as exc_ctx:
                setup_auth._assert_actions_secret_access("owner/repo")

        message = str(exc_ctx.exception)
        self.assertIn("gh auth refresh -s workflow,repo", message)
        self.assertIn("authorize SSO", message)


class SetupAuthDispatchTests(unittest.TestCase):
    def test_existing_dashboard_source_normalizes_supported_values(self) -> None:
        with mock.patch(
            "setup_auth._get_variable",
            return_value=" Strava ",
        ):
            value = setup_auth._existing_dashboard_source("owner/repo")
        self.assertEqual(value, "strava")

    def test_existing_dashboard_source_ignores_unknown_values(self) -> None:
        with mock.patch(
            "setup_auth._get_variable",
            return_value="something-else",
        ):
            value = setup_auth._existing_dashboard_source("owner/repo")
        self.assertIsNone(value)

    def test_try_dispatch_sync_uses_full_backfill_when_supported(self) -> None:
        with mock.patch(
            "setup_auth._run",
            return_value=_completed_process(returncode=0),
        ) as run_mock:
            ok, detail = setup_auth._try_dispatch_sync(
                "owner/repo",
                "strava",
                full_backfill=True,
            )

        self.assertTrue(ok)
        self.assertIn("full_backfill=true", detail)
        run_mock.assert_called_once_with(
            [
                "gh",
                "workflow",
                "run",
                "sync.yml",
                "--repo",
                "owner/repo",
                "-f",
                "source=strava",
                "-f",
                "full_backfill=true",
            ],
            check=False,
        )

    def test_try_dispatch_sync_falls_back_when_full_backfill_input_missing(self) -> None:
        responses = [
            _completed_process(
                returncode=1,
                stderr="could not create workflow dispatch event: HTTP 422: Unexpected inputs provided: [full_backfill]\n",
            ),
            _completed_process(returncode=0),
        ]
        with mock.patch("setup_auth._run", side_effect=responses):
            ok, detail = setup_auth._try_dispatch_sync(
                "owner/repo",
                "garmin",
                full_backfill=True,
            )

        self.assertTrue(ok)
        self.assertIn("full_backfill input is not declared", detail)

    def test_try_dispatch_sync_falls_back_when_source_input_missing(self) -> None:
        responses = [
            _completed_process(
                returncode=1,
                stderr="could not create workflow dispatch event: HTTP 422: Unexpected inputs provided: [source]\n",
            ),
            _completed_process(returncode=0),
        ]
        with mock.patch("setup_auth._run", side_effect=responses):
            ok, detail = setup_auth._try_dispatch_sync(
                "owner/repo",
                "strava",
                full_backfill=False,
            )

        self.assertTrue(ok)
        self.assertIn("workflow does not declare 'source' input", detail)


if __name__ == "__main__":
    unittest.main()
