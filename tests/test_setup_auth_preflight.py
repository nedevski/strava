import os
import subprocess
import sys
import unittest
from argparse import Namespace
from contextlib import ExitStack
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

    def test_resolve_source_non_interactive_prefers_existing_source(self) -> None:
        args = Namespace(source=None)
        self.assertEqual(setup_auth._resolve_source(args, interactive=False, previous_source="garmin"), "garmin")

    def test_resolve_source_non_interactive_uses_default_without_existing_source(self) -> None:
        args = Namespace(source=None)
        self.assertEqual(setup_auth._resolve_source(args, interactive=False, previous_source=None), "strava")

    def test_normalize_strava_profile_url_accepts_strava_host(self) -> None:
        value = setup_auth._normalize_strava_profile_url("www.strava.com/athletes/123")
        self.assertEqual(value, "https://www.strava.com/athletes/123")

    def test_normalize_strava_profile_url_rejects_non_strava_host(self) -> None:
        with self.assertRaises(ValueError):
            setup_auth._normalize_strava_profile_url("https://example.com/athletes/123")

    def test_detect_strava_profile_url_from_token_payload(self) -> None:
        value = setup_auth._detect_strava_profile_url({"athlete": {"id": 42}})
        self.assertEqual(value, "https://www.strava.com/athletes/42")

    def test_resolve_strava_profile_url_non_interactive_uses_existing_variable(self) -> None:
        args = Namespace(strava_profile_url=None)
        with (
            mock.patch("setup_auth._detect_strava_profile_url", return_value=""),
            mock.patch("setup_auth._get_variable", return_value="https://www.strava.com/athletes/456"),
        ):
            value = setup_auth._resolve_strava_profile_url(args, interactive=False, repo="owner/repo")
        self.assertEqual(value, "https://www.strava.com/athletes/456")

    def test_resolve_strava_profile_url_interactive_uses_detected_when_enabled(self) -> None:
        args = Namespace(strava_profile_url=None)
        with (
            mock.patch("setup_auth._get_variable", return_value=""),
            mock.patch("setup_auth._detect_strava_profile_url", return_value="https://www.strava.com/athletes/789"),
            mock.patch("setup_auth._prompt_use_strava_profile_link", return_value=True) as prompt_mock,
        ):
            value = setup_auth._resolve_strava_profile_url(
                args,
                interactive=True,
                repo="owner/repo",
                tokens={"athlete": {"id": 789}},
            )
        self.assertEqual(value, "https://www.strava.com/athletes/789")
        prompt_mock.assert_called_once_with(default_enabled=True)

    def test_clear_variable_ignores_not_found(self) -> None:
        with mock.patch(
            "setup_auth._run",
            return_value=_completed_process(returncode=1, stderr="HTTP 404: Not Found"),
        ):
            setup_auth._clear_variable("DASHBOARD_STRAVA_PROFILE_URL", "owner/repo")

    def test_clear_variable_raises_on_other_errors(self) -> None:
        with mock.patch(
            "setup_auth._run",
            return_value=_completed_process(returncode=1, stderr="HTTP 403: Forbidden"),
        ):
            with self.assertRaises(RuntimeError):
                setup_auth._clear_variable("DASHBOARD_STRAVA_PROFILE_URL", "owner/repo")

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


class SetupAuthMainFlowTests(unittest.TestCase):
    @staticmethod
    def _default_args() -> Namespace:
        return Namespace(
            source=None,
            no_bootstrap_env=False,
            env_bootstrapped=False,
            client_id=None,
            client_secret=None,
            garmin_token_store_b64=None,
            garmin_email=None,
            garmin_password=None,
            store_garmin_password_secrets=False,
            repo=None,
            unit_system=None,
            port=setup_auth.DEFAULT_PORT,
            timeout=setup_auth.DEFAULT_TIMEOUT,
            scope="read,activity:read_all",
            strava_profile_url=None,
            no_browser=True,
            no_auto_github=False,
            no_watch=True,
        )

    def _run_main_for_source(self, previous_source: str, source: str, full_backfill_prompt_result: bool) -> tuple[
        int,
        mock.MagicMock,
        mock.MagicMock,
    ]:
        args = self._default_args()
        with (
            mock.patch("setup_auth.parse_args", return_value=args),
            mock.patch("setup_auth._bootstrap_env_and_reexec"),
            mock.patch("setup_auth._isatty", return_value=True),
            mock.patch("setup_auth._assert_gh_ready"),
            mock.patch("setup_auth._resolve_repo_slug", return_value="owner/repo"),
            mock.patch("setup_auth._assert_repo_access"),
            mock.patch("setup_auth._assert_actions_secret_access"),
            mock.patch("setup_auth._existing_dashboard_source", return_value=previous_source),
            mock.patch("setup_auth._resolve_source", return_value=source),
            mock.patch("setup_auth._prompt_full_backfill_choice", return_value=full_backfill_prompt_result) as prompt_mock,
            mock.patch("setup_auth._resolve_units", return_value=("mi", "ft")),
            mock.patch(
                "setup_auth._resolve_garmin_auth_values",
                return_value=("garmin-token-b64", "user@example.com", "password"),
            ),
            mock.patch("setup_auth._set_secret"),
            mock.patch("setup_auth._set_variable"),
            mock.patch("setup_auth._try_enable_actions_permissions", return_value=(True, "ok")),
            mock.patch("setup_auth._try_enable_workflows", return_value=(True, "ok")),
            mock.patch("setup_auth._try_configure_pages", return_value=(True, "ok")),
            mock.patch("setup_auth._try_dispatch_sync", return_value=(True, "ok")) as dispatch_mock,
            mock.patch("setup_auth._find_latest_workflow_run", return_value=(123, "https://example.test/run/123")),
        ):
            return setup_auth.main(), prompt_mock, dispatch_mock

    def test_main_prompts_full_backfill_on_same_source_rerun(self) -> None:
        result, prompt_mock, dispatch_mock = self._run_main_for_source(
            previous_source="garmin",
            source="garmin",
            full_backfill_prompt_result=True,
        )
        self.assertEqual(result, 0)
        prompt_mock.assert_called_once_with("garmin")
        dispatch_mock.assert_called_once_with("owner/repo", "garmin", full_backfill=True)

    def test_main_skips_full_backfill_prompt_when_switching_source(self) -> None:
        result, prompt_mock, dispatch_mock = self._run_main_for_source(
            previous_source="strava",
            source="garmin",
            full_backfill_prompt_result=True,
        )
        self.assertEqual(result, 0)
        prompt_mock.assert_not_called()
        dispatch_mock.assert_called_once_with("owner/repo", "garmin", full_backfill=False)

    def test_main_sets_optional_strava_profile_variable(self) -> None:
        args = self._default_args()
        args.client_id = "client-id"
        args.client_secret = "client-secret"

        with ExitStack() as stack:
            stack.enter_context(mock.patch("setup_auth.parse_args", return_value=args))
            stack.enter_context(mock.patch("setup_auth._bootstrap_env_and_reexec"))
            stack.enter_context(mock.patch("setup_auth._isatty", return_value=True))
            stack.enter_context(mock.patch("setup_auth._assert_gh_ready"))
            stack.enter_context(mock.patch("setup_auth._resolve_repo_slug", return_value="owner/repo"))
            stack.enter_context(mock.patch("setup_auth._assert_repo_access"))
            stack.enter_context(mock.patch("setup_auth._assert_actions_secret_access"))
            stack.enter_context(mock.patch("setup_auth._existing_dashboard_source", return_value="strava"))
            stack.enter_context(mock.patch("setup_auth._resolve_source", return_value="strava"))
            stack.enter_context(mock.patch("setup_auth._prompt_full_backfill_choice", return_value=False))
            stack.enter_context(mock.patch("setup_auth._resolve_units", return_value=("mi", "ft")))
            stack.enter_context(mock.patch("setup_auth._authorize_and_get_code", return_value="auth-code"))
            stack.enter_context(
                mock.patch(
                    "setup_auth._exchange_code_for_tokens",
                    return_value={"refresh_token": "refresh-token", "athlete": {}},
                )
            )
            stack.enter_context(mock.patch("setup_auth._set_secret"))
            stack.enter_context(mock.patch("setup_auth._try_set_strava_secret_update_token", return_value=(True, "ok")))
            resolve_profile_mock = stack.enter_context(
                mock.patch(
                    "setup_auth._resolve_strava_profile_url",
                    return_value="https://www.strava.com/athletes/123",
                )
            )
            set_variable_mock = stack.enter_context(mock.patch("setup_auth._set_variable"))
            stack.enter_context(mock.patch("setup_auth._try_enable_actions_permissions", return_value=(True, "ok")))
            stack.enter_context(mock.patch("setup_auth._try_enable_workflows", return_value=(True, "ok")))
            stack.enter_context(mock.patch("setup_auth._try_configure_pages", return_value=(True, "ok")))
            stack.enter_context(mock.patch("setup_auth._try_dispatch_sync", return_value=(True, "ok")))
            stack.enter_context(
                mock.patch(
                    "setup_auth._find_latest_workflow_run",
                    return_value=(123, "https://example.test/run/123"),
                )
            )
            result = setup_auth.main()

        self.assertEqual(result, 0)
        resolve_profile_mock.assert_called_once_with(
            args,
            True,
            "owner/repo",
            tokens={"refresh_token": "refresh-token", "athlete": {}},
        )
        self.assertIn(
            mock.call(
                "DASHBOARD_STRAVA_PROFILE_URL",
                "https://www.strava.com/athletes/123",
                "owner/repo",
            ),
            set_variable_mock.mock_calls,
        )


if __name__ == "__main__":
    unittest.main()
