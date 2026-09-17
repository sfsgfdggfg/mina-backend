from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from src.integrations.imap_mail import ImapMailboxError, ImapReadClient
from src.core.mailbox_provider import (
    MailboxProviderConfigurationError,
    resolve_mailbox_provider_authority,
)
from src.integrations.mailbox_credentials import (
    ImapMailboxCredential,
    MailboxCredentialConfigurationError,
    MailboxCredentialStore,
    MailboxCredentialStoreError,
    resolve_imap_setup_defaults,
)
from src.paths import REPO_ROOT
from src.simulation.physical_temp import physical_temporary_directory


MAILBOX = "ops@example.invalid"
PASSWORD = "regression-only-imap-secret"
HEADER_TEMPLATE = b"""From: Customer <customer@example.invalid>\r
To: Ops <ops@example.invalid>\r
Date: Tue, 15 Sep 2026 10:30:00 +0300\r
Message-ID: <case-{uid}@example.invalid>\r
Subject: Road freight request\r
\r
"""
PLAIN_BODY = b"Pickup Adana, delivery Hamburg, 20 pallets, 18000 kg.\r\n"
PLAIN_STRUCTURE = (
    b'1 (BODYSTRUCTURE ("TEXT" "PLAIN" ("CHARSET" "UTF-8") '
    b'NIL NIL "7BIT" 56 1 NIL NIL NIL NIL))'
)
ATTACHMENT_STRUCTURE = (
    b'2 (BODYSTRUCTURE (("TEXT" "PLAIN" ("CHARSET" "UTF-8") '
    b'NIL NIL "7BIT" 56 1 NIL NIL NIL NIL) '
    b'("APPLICATION" "PDF" ("NAME" "quote.pdf") NIL NIL "BASE64" '
    b'1024 NIL ("ATTACHMENT" ("FILENAME" "quote.pdf")) NIL NIL) '
    b'"MIXED" ("BOUNDARY" "x") NIL NIL NIL))'
)



class _FakeSock:
    def __init__(self, certificate: bytes = b"fake-regression-certificate") -> None:
        self.certificate = certificate

    def getpeercert(self, *, binary_form=False):
        return self.certificate if binary_form else {}


class _FakeImap:
    instances: list["_FakeImap"] = []

    def __init__(self, host, port, *, ssl_context, timeout):
        self.host = host
        self.port = port
        self.ssl_context = ssl_context
        self.timeout = timeout
        self.sock = _FakeSock()
        self.selected: list[tuple[str, bool]] = []
        self.login_values: list[tuple[str, str]] = []
        self.folder = ""
        self.closed = False
        self.fetch_queries: list[tuple[bytes, str]] = []
        self.__class__.instances.append(self)

    def login(self, username, password):
        self.login_values.append((username, password))
        return "OK", [b"authenticated"]

    def select(self, mailbox="INBOX", readonly=False):
        self.folder = mailbox
        self.selected.append((mailbox, readonly))
        return "OK", [b"2"]

    def response(self, code):
        assert code == "UIDVALIDITY"
        return "UIDVALIDITY", [b"42"]

    def list(self):
        return "OK", [
            b'(\\HasNoChildren) "/" "INBOX"',
            b'(\\HasNoChildren \\Sent) "/" "Sent"',
        ]

    def uid(self, command, *args):
        if command == "search":
            return "OK", [b"1 2"]
        if command == "fetch":
            uid = args[0]
            query = args[1]
            self.fetch_queries.append((uid, str(query)))
            if query == "(BODY.PEEK[HEADER])":
                raw = HEADER_TEMPLATE.replace(b"{uid}", uid)
                return "OK", [(b"1 (BODY[HEADER] {180}", raw), b")"]
            if query == "(BODYSTRUCTURE)":
                return "OK", [PLAIN_STRUCTURE if uid == b"1" else ATTACHMENT_STRUCTURE]
            if query in {"(BODY.PEEK[TEXT])", "(BODY.PEEK[1])"}:
                return "OK", [(b"1 (BODY[1] {56}", PLAIN_BODY), b")"]
            raise AssertionError(f"unexpected IMAP fetch query: {query}")
        raise AssertionError(f"unexpected IMAP UID command: {command}")

    def logout(self):
        self.closed = True
        return "BYE", [b"logout"]

    def shutdown(self):
        self.closed = True


def _credential(*, fingerprint: str | None = None) -> ImapMailboxCredential:
    return ImapMailboxCredential(
        mailbox_id=MAILBOX,
        host="mail.example.invalid",
        port=993,
        username=MAILBOX,
        password=PASSWORD,
        certificate_sha256=fingerprint,
    )


def evaluate_imap_mailbox_regressions():
    failures: list[str] = []
    passes: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    defaults = resolve_imap_setup_defaults(
        "ops@example.com", {"MINAI_IMAP_DEFAULT_PORT": "993"}
    )
    check(
        defaults["host"] == "mail.example.com"
        and defaults["username"] == "ops@example.com"
        and defaults["port"] == 993
        and defaults["certificate_sha256"] is None
        and defaults["host_source"] == "mailbox_domain_fallback",
        "IMAP simple setup derives conservative host and username defaults without inventing a certificate pin",
    )
    explicit = resolve_imap_setup_defaults(
        "ops@example.com",
        {
            "MINAI_IMAP_DEFAULT_HOST": "imap.example.net",
            "MINAI_IMAP_DEFAULT_PORT": "1993",
            "MINAI_IMAP_DEFAULT_USERNAME": "mail-user",
        },
    )
    check(
        explicit["host"] == "imap.example.net"
        and explicit["port"] == 1993
        and explicit["username"] == "mail-user"
        and explicit["host_source"] == "deployment_default",
        "deployment IMAP defaults override mailbox-domain fallback without exposing secrets",
    )

    check(
        resolve_mailbox_provider_authority({}) == "auto"
        and resolve_mailbox_provider_authority({"MINAI_MAILBOX_PROVIDER": " IMAP "}) == "imap"
        and resolve_mailbox_provider_authority({"MINAI_MAILBOX_PROVIDER": "Outlook"}) == "outlook",
        "mailbox provider authority normalizes explicit runtime selection",
    )
    invalid_provider_rejected = False
    try:
        resolve_mailbox_provider_authority({"MINAI_MAILBOX_PROVIDER": "smtp"})
    except MailboxProviderConfigurationError:
        invalid_provider_rejected = True
    check(invalid_provider_rejected, "invalid mailbox provider authority fails closed")

    with physical_temporary_directory() as temp:
        root = Path(temp)
        path = root / "mailbox-credentials.enc"
        key = Fernet.generate_key().decode("ascii")
        store = MailboxCredentialStore.from_environment(
            {
                "MINAI_MAILBOX_CREDENTIAL_KEY": key,
                "MINAI_MAILBOX_CREDENTIAL_PATH": str(path),
            }
        )
        credential = _credential()
        store.save_imap(credential)
        ciphertext = path.read_bytes()
        loaded = store.load_imap()
        check(
            PASSWORD.encode() not in ciphertext
            and MAILBOX.encode() not in ciphertext
            and loaded.password.get_secret_value() == PASSWORD
            and loaded.mailbox_id == MAILBOX,
            "IMAP credential store encrypts secrets at rest and round-trips safely",
        )
        check(
            os.name != "posix" or (path.stat().st_mode & 0o077) == 0,
            "IMAP credential file is owner-only",
        )
        check(
            "password" not in loaded.safe_summary()
            and loaded.safe_summary().get("password_exposed") is False,
            "IMAP credential status never returns password material",
        )

        wrong_key_rejected = False
        wrong_store = MailboxCredentialStore.from_environment(
            {
                "MINAI_MAILBOX_CREDENTIAL_KEY": Fernet.generate_key().decode("ascii"),
                "MINAI_MAILBOX_CREDENTIAL_PATH": str(path),
            }
        )
        try:
            wrong_store.load_imap()
        except MailboxCredentialStoreError:
            wrong_key_rejected = True
        check(wrong_key_rejected, "wrong IMAP encryption key fails closed")

        repo_path_rejected = False
        try:
            MailboxCredentialStore.from_environment(
                {
                    "MINAI_MAILBOX_CREDENTIAL_KEY": key,
                    "MINAI_MAILBOX_CREDENTIAL_PATH": str(REPO_ROOT / "imap-secret.enc"),
                }
            )
        except MailboxCredentialConfigurationError:
            repo_path_rejected = True
        check(repo_path_rejected, "IMAP credentials cannot be stored inside repository")

    _FakeImap.instances.clear()
    with patch("src.integrations.imap_mail._safe_host_addresses", return_value=["203.0.113.10"]):
        client = ImapReadClient(
            credential=_credential(),
            connection_factory=_FakeImap,
        )
        client.test_connection()
        inbox = client.list_inbox_messages(limit=2)
        now = datetime(2026, 9, 16, tzinfo=timezone.utc)
        history = client.list_relationship_history(
            start_at=now - timedelta(days=10),
            end_at=now + timedelta(days=1),
            max_messages=4,
        )
    all_readonly = all(
        readonly
        for instance in _FakeImap.instances
        for _, readonly in instance.selected
    )
    check(
        all_readonly
        and len(inbox) == 2
        and all(item.provider_name == "imap" for item in inbox)
        and all(item.mailbox_id == MAILBOX for item in inbox),
        "IMAP client uses read-only mailbox selection and provider-neutral envelopes",
    )
    check(
        len(history) == 4
        and all(item.source == "authorized_mailbox" for item in history),
        "IMAP history maps transient Inbox and Sent messages to provider-neutral history",
    )
    check(
        all(instance.login_values == [(MAILBOX, PASSWORD)] for instance in _FakeImap.instances),
        "IMAP password is used only at provider authentication boundary",
    )
    fetch_queries = [
        query
        for instance in _FakeImap.instances
        for _, query in instance.fetch_queries
    ]
    attachment_envelopes = [item for item in inbox if item.has_attachments]
    check(
        len(attachment_envelopes) == 1
        and attachment_envelopes[0].attachment_manifest
        and attachment_envelopes[0].attachment_manifest[0].name == "quote.pdf"
        and not any("BODY.PEEK[]" in query for query in fetch_queries)
        and not any("BODY.PEEK[2]" in query for query in fetch_queries),
        "IMAP attachment metadata is detected without fetching attachment or full-message bytes",
    )

    pin_rejected = False
    fingerprint = "00" * 32
    with patch("src.integrations.imap_mail._safe_host_addresses", return_value=["203.0.113.10"]):
        try:
            ImapReadClient(
                credential=_credential(fingerprint=fingerprint),
                connection_factory=_FakeImap,
            ).test_connection()
        except ImapMailboxError as exc:
            pin_rejected = exc.code == "imap_certificate_pin_mismatch"
    check(pin_rejected, "IMAP certificate pin mismatch fails closed before mailbox use")

    root = Path(__file__).resolve().parents[2]
    api_text = (root / "src" / "api.py").read_text(encoding="utf-8")
    ui_text = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    access_text = (root / "src" / "core" / "pilot_access.py").read_text(encoding="utf-8")
    launcher_text = (root / "src" / "pilot_launcher.py").read_text(encoding="utf-8")
    check(
        "/mailbox/imap/configure" in api_text
        and "/inbound/mailbox/pull" in api_text
        and "/relationship-onboarding/mailbox/analyze" in api_text
        and "E-posta Bağlantısı" in ui_text
        and "Yeni mailleri kontrol et" in ui_text
        and "mailbox/imap/configure" in access_text,
        "browser/API controlled-pilot mailbox onboarding contract is wired",
    )
    check(
        'authority == "imap"' in api_text
        and "imap_mailbox_not_configured" in api_text
        and "outlook_provider_not_authorized_by_runtime" in api_text
        and "imap_provider_not_authorized_by_runtime" in api_text
        and "resolve_mailbox_provider_authority(env)" in launcher_text,
        "explicit mailbox provider authority blocks cross-provider fallback and is preflight-validated",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_imap_mailbox_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    raise SystemExit(0 if result["passed"] else 1)
