from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Literal

MAILBOX_PROVIDER_ENV = "MINAI_MAILBOX_PROVIDER"
MailboxProviderAuthority = Literal["auto", "imap", "outlook"]
_ALLOWED = {"auto", "imap", "outlook"}


class MailboxProviderConfigurationError(ValueError):
    pass


def resolve_mailbox_provider_authority(
    environ: Mapping[str, str] | None = None,
) -> MailboxProviderAuthority:
    env = environ if environ is not None else os.environ
    value = (env.get(MAILBOX_PROVIDER_ENV) or "auto").strip().casefold()
    if value not in _ALLOWED:
        raise MailboxProviderConfigurationError(
            "MINAI_MAILBOX_PROVIDER must be auto, imap, or outlook."
        )
    return value  # type: ignore[return-value]
