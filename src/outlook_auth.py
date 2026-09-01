from __future__ import annotations

from src.integrations.microsoft_auth import (
    MicrosoftAuthConfig,
    MicrosoftAuthConfigurationError,
    MicrosoftAuthenticationError,
    interactive_device_login,
)


def main() -> int:
    try:
        config = (
            MicrosoftAuthConfig.from_environment()
        )

        interactive_device_login(
            config
        )

    except (
        MicrosoftAuthConfigurationError,
        MicrosoftAuthenticationError,
    ) as exc:
        code = getattr(
            exc,
            "code",
            "outlook_auth_configuration_invalid",
        )

        print(
            f"Outlook authorization: FAIL ({code})"
        )
        return 2

    print(
        "Outlook authorization cached securely."
    )
    print(
        "Permissions cached: Mail.Read and Mail.Send."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
