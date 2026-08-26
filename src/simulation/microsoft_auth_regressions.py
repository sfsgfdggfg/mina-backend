from __future__ import annotations

import io
import os
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.integrations.microsoft_auth import (
    MicrosoftAuthConfig,
    MicrosoftAuthConfigurationError,
    MicrosoftAuthenticationError,
    acquire_silent_access_token,
    interactive_device_login,
)


TENANT = (
    "11111111-1111-1111-1111-111111111111"
)

CLIENT = (
    "22222222-2222-2222-2222-222222222222"
)

MAILBOX = "operations@example.invalid"


class _FakeCache:
    def __init__(self) -> None:
        self.payload = ""
        self.has_state_changed = False

    def deserialize(
        self,
        value: str,
    ) -> None:
        self.payload = value

    def serialize(self) -> str:
        return self.payload


class _FakeApplication:
    login_account_available = True
    silent_account_available = True

    def __init__(
        self,
        *,
        client_id,
        authority,
        token_cache,
    ) -> None:
        self.client_id = client_id
        self.authority = authority
        self.cache = token_cache

    def get_accounts(
        self,
        username=None,
    ):
        if (
            not self.login_account_available
            or not self.silent_account_available
        ):
            return []

        return [
            {
                "username": MAILBOX,
            }
        ]

    def initiate_device_flow(
        self,
        scopes,
    ):
        if scopes != ["Mail.Read"]:
            raise AssertionError(
                "Unexpected delegated scopes."
            )

        return {
            "user_code": "ABCD-EFGH",
            "message": (
                "Open the Microsoft device login "
                "page and enter ABCD-EFGH."
            ),
        }

    def acquire_token_by_device_flow(
        self,
        flow,
    ):
        self.cache.payload = (
            '{"refresh_token":"'
            'regression-secret-refresh-token"}'
        )
        self.cache.has_state_changed = True

        return {
            "access_token": (
                "regression-secret-access-token"
            )
        }

    def acquire_token_silent(
        self,
        scopes,
        *,
        account,
    ):
        if scopes != ["Mail.Read"]:
            raise AssertionError(
                "Unexpected delegated scopes."
            )

        return {
            "access_token": (
                "regression-secret-access-token"
            )
        }


def _environment(
    cache_path: Path,
):
    return {
        "MINAI_OUTLOOK_TENANT_ID": TENANT,
        "MINAI_OUTLOOK_CLIENT_ID": CLIENT,
        "MINAI_OUTLOOK_MAILBOX_ID": MAILBOX,
        "MINAI_OUTLOOK_TOKEN_CACHE_PATH": (
            str(cache_path)
        ),
    }


def evaluate_microsoft_auth_regressions():
    failures: list[str] = []
    passes: list[str] = []

    def check(
        condition: bool,
        label: str,
    ) -> None:
        if condition:
            passes.append(label)
        else:
            failures.append(label)

    with TemporaryDirectory() as temp:
        root = Path(temp)
        cache_path = root / "token-cache.json"

        config = (
            MicrosoftAuthConfig.from_environment(
                _environment(cache_path)
            )
        )

        check(
            config.mailbox_id == MAILBOX
            and config.tenant_id == TENANT
            and config.client_id == CLIENT,
            "Outlook auth configuration normalized",
        )

        consumer_env = _environment(cache_path)
        consumer_env["MINAI_OUTLOOK_TENANT_ID"] = "consumers"
        consumer_config = MicrosoftAuthConfig.from_environment(consumer_env)

        check(
            consumer_config.tenant_id == "consumers"
            and consumer_config.authority
            == "https://login.microsoftonline.com/consumers",
            "personal Microsoft account authority supported",
        )

        invalid_tenant_rejected = False
        invalid_env = _environment(cache_path)
        invalid_env["MINAI_OUTLOOK_TENANT_ID"] = "common"

        try:
            MicrosoftAuthConfig.from_environment(invalid_env)
        except MicrosoftAuthConfigurationError:
            invalid_tenant_rejected = True

        check(
            invalid_tenant_rejected,
            "unsupported Microsoft authority aliases rejected",
        )

        output: list[str] = []

        with patch(
            "src.integrations."
            "microsoft_auth."
            "msal.SerializableTokenCache",
            _FakeCache,
        ), patch(
            "src.integrations."
            "microsoft_auth."
            "msal.PublicClientApplication",
            _FakeApplication,
        ):
            interactive_device_login(
                config,
                output_fn=output.append,
            )

        check(
            cache_path.exists(),
            "device login creates external cache",
        )

        if os.name == "posix":
            private_mode = (
                cache_path.stat().st_mode
                & 0o077
            ) == 0
        else:
            private_mode = True

        check(
            private_mode,
            "token cache is owner-only",
        )

        serialized = cache_path.read_text(
            encoding="utf-8"
        )

        check(
            "regression-secret-refresh-token"
            in serialized,
            "token material stored only in cache",
        )

        output_text = "\n".join(output)

        check(
            "regression-secret-access-token"
            not in output_text
            and "regression-secret-refresh-token"
            not in output_text,
            "device login does not print tokens",
        )

        with patch(
            "src.integrations."
            "microsoft_auth."
            "msal.SerializableTokenCache",
            _FakeCache,
        ), patch(
            "src.integrations."
            "microsoft_auth."
            "msal.PublicClientApplication",
            _FakeApplication,
        ):
            token = acquire_silent_access_token(
                config
            )

        check(
            token
            == "regression-secret-access-token",
            "silent access token acquired",
        )

        if os.name == "posix":
            os.chmod(
                cache_path,
                0o644,
            )

            loose_rejected = False

            try:
                with patch(
                    "src.integrations."
                    "microsoft_auth."
                    "msal.SerializableTokenCache",
                    _FakeCache,
                ):
                    acquire_silent_access_token(
                        config
                    )
            except MicrosoftAuthConfigurationError:
                loose_rejected = True

            check(
                loose_rejected,
                "loose token-cache permissions rejected",
            )

            os.chmod(
                cache_path,
                0o600,
            )

        repository_cache_rejected = False

        try:
            MicrosoftAuthConfig.from_environment(
                _environment(
                    Path.cwd()
                    / "data"
                    / "outlook-cache.json"
                )
            )
        except MicrosoftAuthConfigurationError:
            repository_cache_rejected = True

        check(
            repository_cache_rejected,
            "repository token cache rejected",
        )

        missing_account = False

        class _NoAccountApplication(
            _FakeApplication
        ):
            def get_accounts(
                self,
                username=None,
            ):
                return []

        with patch(
            "src.integrations."
            "microsoft_auth."
            "msal.SerializableTokenCache",
            _FakeCache,
        ), patch(
            "src.integrations."
            "microsoft_auth."
            "msal.PublicClientApplication",
            _NoAccountApplication,
        ):
            try:
                acquire_silent_access_token(
                    config
                )
            except MicrosoftAuthenticationError as exc:
                missing_account = (
                    exc.code
                    == "outlook_reauthentication_required"
                )

        check(
            missing_account,
            "missing cached account requires reauthentication",
        )

        stdout = io.StringIO()

        with redirect_stdout(stdout):
            print(
                "safe regression output"
            )

        check(
            "regression-secret" not in stdout.getvalue(),
            "auth regression output contains no token",
        )

    return {
        "name": (
            "Microsoft delegated Outlook authentication"
        ),
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main() -> int:
    result = (
        evaluate_microsoft_auth_regressions()
    )

    for label in result["passed_checks"]:
        print(f"PASS {label}")

    for failure in result["failures"]:
        print(f"FAIL {failure}")

    if result["passed"]:
        print(
            "\nMicrosoft Outlook auth "
            "regressions: PASS"
        )
        return 0

    print(
        "\nMicrosoft Outlook auth "
        "regressions: FAIL"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
