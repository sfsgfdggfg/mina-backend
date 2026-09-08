"""Cross-cutting regressions for the P2-16.6 pre-pilot safety boundaries."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import src.api as api
from src.core.extraction_confirmation import (
    ShipmentExtractionProposal,
    ShipmentProposalSnapshot,
)
from src.core.mail import InboundMailEnvelope
from src.core.outbound_runtime import OutboundRuntimePolicy
from src.core.pilot_access import PilotAccessConfigurationError
from src.core.pilot_store import SQLitePilotStore
from src.core.privacy import prepare_inbound_mail_for_processing
from src.core.sqlite_repositories import (
    SQLiteExtractionProposalRepository,
    SQLiteMinaJobRepository,
)
from src.integrations.microsoft_auth import MicrosoftAuthConfig
from src.pilot_launcher import validate_controlled_pilot_runtime
from src.pilot_profile_launcher import build_profile_environment
from src.simulation.physical_temp import physical_temporary_directory
from src.simulation.pilot_launcher_regressions import (
    _valid_env,
    _write_pilot_data_pack,
)
from src.workflow.mail_ingestion import process_customer_inquiry_mail


DURABLE_JOB_LIFECYCLE_NAMESPACES = {
    "scheduled_automation_actions",
    "attachment_interpretation_reviews",
    "supplier_rfq_drafts",
    "supplier_rfq_automated_sent_evidence",
    "supplier_rfq_manual_sent_evidence",
    "supplier_rfq_follow_up_drafts",
    "supplier_rfq_follow_up_automated_sent_evidence",
    "supplier_rfq_follow_up_manual_sent_evidence",
    "supplier_rfq_workflows",
    "supplier_rfq_responses",
    "supplier_rfq_acknowledgements",
    "supplier_secondary_dispatch_authorizations",
    "supplier_ingested_messages",
    "quote_approvals",
    "quote_cases",
}


def _write_env(path: Path, values: dict[str, str]) -> None:
    path.write_text(
        "\n".join(
            f"{key}={json.dumps(value)}" for key, value in sorted(values.items())
        )
        + "\n",
        encoding="utf-8",
    )


def _unverified_registry(pack_root: Path) -> None:
    records = {}
    for key, filename in (
        ("customer_memory", "customer_memory.json"),
        ("supplier_capabilities", "supplier_capabilities.json"),
    ):
        records[key] = {
            "path": f"data/{filename}",
            "classification": "internal_reference",
            "operational": False,
            "pilot_usable": False,
        }
    (pack_root / "data" / "provenance_registry.json").write_text(
        json.dumps({"version": 1, "datasets": records}),
        encoding="utf-8",
    )


def evaluate_pre_pilot_hardening_regressions() -> dict[str, object]:
    failures: list[str] = []

    def check(condition: bool, label: str) -> None:
        if not condition:
            failures.append(label)

    with physical_temporary_directory() as temporary:
        root = Path(temporary)

        verified_pack = _write_pilot_data_pack(root / "verified-pack")
        core = _valid_env(verified_pack)
        core["MINAI_OUTBOUND_MODE"] = "shadow"
        core_path = root / "pilot.env"
        _write_env(core_path, core)
        hostile_parent = {
            "PATH": "/synthetic/host/bin",
            "MINAI_OUTBOUND_MODE": "controlled_send",
            "MINAI_PILOT_DB_PATH": str(root / "stale.sqlite3"),
            "MINAI_PILOT_DATA_DIR": str(root / "stale-pack"),
            "MINAI_PILOT_OPERATORS_JSON": '{"Stale":"token"}',
            "MINAI_OUTLOOK_MAILBOX_ID": "stale@example.invalid",
            "DATABASE_URL": "postgresql://stale.invalid/minai",
            "OPENAI_API_KEY": "stale-provider-secret",
        }
        isolated, _ = build_profile_environment(
            core_env_file=core_path,
            base_environment=hostile_parent,
        )
        check(
            isolated["MINAI_OUTBOUND_MODE"] == "shadow"
            and isolated["MINAI_PILOT_DB_PATH"] == core["MINAI_PILOT_DB_PATH"]
            and isolated["MINAI_PILOT_DATA_DIR"] == core["MINAI_PILOT_DATA_DIR"]
            and "MINAI_OUTLOOK_MAILBOX_ID" not in isolated
            and "DATABASE_URL" not in isolated
            and "OPENAI_API_KEY" not in isolated,
            "hostile parent application and provider configuration cannot leak",
        )

        check(
            api.validate_controlled_pilot_startup in api.app.router.on_startup,
            "controlled runtime preflight is registered on FastAPI startup",
        )
        with patch.dict(os.environ, {"MINAI_PILOT_MODE": "1"}, clear=True):
            try:
                api.validate_controlled_pilot_startup()
            except PilotAccessConfigurationError:
                direct_startup_blocked = True
            else:
                direct_startup_blocked = False
        check(
            direct_startup_blocked,
            "direct ASGI startup fails closed for invalid pilot authority",
        )
        with patch.dict(
            os.environ,
            {"MINAI_PILOT_MODE": "tru"},
            clear=True,
        ):
            try:
                api.validate_controlled_pilot_startup()
            except PilotAccessConfigurationError:
                malformed_mode_blocked = True
            else:
                malformed_mode_blocked = False
        check(
            malformed_mode_blocked,
            "malformed pilot mode cannot downgrade direct ASGI startup to non-pilot",
        )
        with patch.dict(
            os.environ,
            {"MINAI_PILOT_MODE": "   "},
            clear=True,
        ):
            try:
                api.validate_controlled_pilot_startup()
            except PilotAccessConfigurationError:
                empty_mode_blocked = True
            else:
                empty_mode_blocked = False
        check(
            empty_mode_blocked,
            "empty explicit pilot mode cannot downgrade startup to non-pilot",
        )

        original_policy = api.outbound_runtime_policy
        original_pilot_mode = api.pilot_mode_enabled
        original_factory = api.outlook_graph_sender_from_environment
        provider_calls: list[bool] = []
        try:
            api.outbound_runtime_policy = OutboundRuntimePolicy(mode="shadow")
            api.pilot_mode_enabled = lambda: False
            api.outlook_graph_sender_from_environment = (
                lambda: provider_calls.append(True)
            )
            shadow_sender = api._build_outbound_mail_sender_if_enabled()
        finally:
            api.outbound_runtime_policy = original_policy
            api.pilot_mode_enabled = original_pilot_mode
            api.outlook_graph_sender_from_environment = original_factory
        check(
            shadow_sender is None
            and not provider_calls
            and OutboundRuntimePolicy().delivery_enabled is False,
            "default non-pilot shadow runtime has no provider send path",
        )

        original_policy = api.outbound_runtime_policy
        original_pilot_mode = api.pilot_mode_enabled
        original_factory = api.outlook_graph_sender_from_environment
        original_sender = api.outbound_mail_sender
        original_scheduler = api.automation_scheduler

        class _StartupScheduler:
            def __init__(self):
                self.sender = None
                self.starts = 0

            def start(self):
                self.starts += 1

        startup_scheduler = _StartupScheduler()
        try:
            api.outbound_runtime_policy = OutboundRuntimePolicy(
                mode="controlled_send"
            )
            api.pilot_mode_enabled = lambda: True
            api.outbound_mail_sender = None
            api.automation_scheduler = startup_scheduler

            def invalid_sender_factory():
                raise api.MicrosoftAuthConfigurationError(
                    "synthetic missing Outlook config"
                )

            api.outlook_graph_sender_from_environment = invalid_sender_factory
            try:
                api.start_controlled_automation_scheduler()
            except PilotAccessConfigurationError:
                controlled_send_startup_blocked = True
            else:
                controlled_send_startup_blocked = False
        finally:
            api.outbound_runtime_policy = original_policy
            api.pilot_mode_enabled = original_pilot_mode
            api.outlook_graph_sender_from_environment = original_factory
            api.outbound_mail_sender = original_sender
            api.automation_scheduler = original_scheduler
        check(
            controlled_send_startup_blocked
            and startup_scheduler.starts == 0,
            "controlled send cannot boot without a configured Outlook sender",
        )

        original_policy = api.outbound_runtime_policy
        original_pilot_mode = api.pilot_mode_enabled
        original_factory = api.outlook_graph_sender_from_environment
        original_token_acquirer = api.acquire_silent_access_token
        original_sender = api.outbound_mail_sender
        original_scheduler = api.automation_scheduler
        startup_scheduler = _StartupScheduler()
        auth_config = MicrosoftAuthConfig(
            tenant_id="11111111-1111-1111-1111-111111111111",
            client_id="22222222-2222-2222-2222-222222222222",
            mailbox_id="operations@example.invalid",
            token_cache_path=root / "missing-controlled-send-cache.json",
            scopes=("Mail.Read", "Mail.Send"),
        )

        class _ConfiguredSender:
            def __init__(self, config):
                self.config = config

        try:
            api.outbound_runtime_policy = OutboundRuntimePolicy(
                mode="controlled_send"
            )
            api.pilot_mode_enabled = lambda: True
            api.outbound_mail_sender = _ConfiguredSender(auth_config)
            api.automation_scheduler = startup_scheduler
            api.outlook_graph_sender_from_environment = (
                lambda: _ConfiguredSender(auth_config)
            )

            def unauthenticated_sender(_config):
                raise api.MicrosoftAuthenticationError(
                    "outlook_reauthentication_required"
                )

            api.acquire_silent_access_token = unauthenticated_sender
            try:
                api.start_controlled_automation_scheduler()
            except PilotAccessConfigurationError:
                unauthenticated_send_blocked = True
            else:
                unauthenticated_send_blocked = False
        finally:
            api.outbound_runtime_policy = original_policy
            api.pilot_mode_enabled = original_pilot_mode
            api.outlook_graph_sender_from_environment = original_factory
            api.acquire_silent_access_token = original_token_acquirer
            api.outbound_mail_sender = original_sender
            api.automation_scheduler = original_scheduler
        check(
            unauthenticated_send_blocked
            and startup_scheduler.starts == 0,
            "controlled send cannot boot without cached Mail.Send authorization",
        )

        cache_path = root / "outlook-cache.json"
        auth_env = {
            "MINAI_OUTLOOK_TENANT_ID": "11111111-1111-1111-1111-111111111111",
            "MINAI_OUTLOOK_CLIENT_ID": "22222222-2222-2222-2222-222222222222",
            "MINAI_OUTLOOK_MAILBOX_ID": "operations@example.invalid",
            "MINAI_OUTLOOK_TOKEN_CACHE_PATH": str(cache_path),
        }
        shadow_auth = MicrosoftAuthConfig.from_environment(auth_env)
        send_auth = MicrosoftAuthConfig.from_environment(
            {**auth_env, "MINAI_OUTBOUND_MODE": "controlled_send"}
        )
        check(
            shadow_auth.scopes == ("Mail.Read",)
            and send_auth.scopes == ("Mail.Read", "Mail.Send"),
            "Outlook delegated scopes are shadow-read-only and send-policy-aware",
        )

        unverified_pack = _write_pilot_data_pack(
            root / "unverified-pack",
            verify=False,
        )
        _unverified_registry(unverified_pack)
        try:
            validate_controlled_pilot_runtime(_valid_env(unverified_pack))
        except PilotAccessConfigurationError:
            unverified_blocked = True
        else:
            unverified_blocked = False
        check(
            unverified_blocked,
            "structurally valid unverified pilot data pack is rejected at boot",
        )

        tampered_pack = _write_pilot_data_pack(root / "tampered-pack")
        supplier_path = tampered_pack / "data" / "supplier_capabilities.json"
        supplier_path.write_text(
            supplier_path.read_text(encoding="utf-8") + "\n",
            encoding="utf-8",
        )
        try:
            validate_controlled_pilot_runtime(_valid_env(tampered_pack))
        except PilotAccessConfigurationError:
            tampered_blocked = True
        else:
            tampered_blocked = False
        check(
            tampered_blocked,
            "verified pilot data pack modified afterward is rejected at boot",
        )
        with patch.dict(
            os.environ,
            _valid_env(tampered_pack),
            clear=True,
        ):
            try:
                api.bootstrap_master_data_from_legacy(None)
            except api.HTTPException as exc:
                tampered_bootstrap_blocked = (
                    exc.status_code == 409
                    and exc.detail == "legacy_master_data_provenance_invalid"
                )
            else:
                tampered_bootstrap_blocked = False
        check(
            tampered_bootstrap_blocked,
            "legacy bootstrap revalidates verified fingerprints at action time",
        )

        bootstrap_race_pack = _write_pilot_data_pack(
            root / "bootstrap-race-pack"
        )
        original_supplier_validator = api.validate_supplier_capabilities_file

        def validate_then_mutate_supplier(path):
            result = original_supplier_validator(path)
            path.write_bytes(path.read_bytes() + b"\n")
            return result

        with patch.dict(
            os.environ,
            _valid_env(bootstrap_race_pack),
            clear=True,
        ), patch.object(
            api,
            "validate_supplier_capabilities_file",
            validate_then_mutate_supplier,
        ):
            try:
                api.bootstrap_master_data_from_legacy(None)
            except api.HTTPException as exc:
                bootstrap_race_blocked = (
                    exc.status_code == 409
                    and exc.detail == "legacy_master_data_provenance_invalid"
                )
            else:
                bootstrap_race_blocked = False
        check(
            bootstrap_race_blocked,
            "legacy bootstrap imports only the exact fingerprint-verified bytes",
        )

        store = SQLitePilotStore(
            root / "retention.sqlite3",
            retention_days=1,
        )
        proposals = SQLiteExtractionProposalRepository(store)
        jobs = SQLiteMinaJobRepository(store)
        incoming = InboundMailEnvelope(
            external_message_id="old-message-1",
            provider_name="microsoft_graph",
            mailbox_id="operations@example.invalid",
            sender_address="customer@example.invalid",
            body_text="Please quote Istanbul to Berlin.",
            source="email",
        )
        safe_mail, _ = prepare_inbound_mail_for_processing(incoming)
        proposal = proposals.save(
            ShipmentExtractionProposal(
                inbound_mail=safe_mail,
                proposed_shipment=ShipmentProposalSnapshot(
                    customer_name="Durable Customer"
                ),
            )
        )
        opened_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
        job, _ = jobs.create_for_proposal(
            proposal_id=proposal.proposal_id,
            shipment=proposal.proposed_shipment,
            opened_by="Synthetic Operator",
            opened_at=opened_at,
            sequence_year=2020,
            lifecycle_version=1,
            job_kind="price_request",
        )
        for namespace in DURABLE_JOB_LIFECYCLE_NAMESPACES:
            store.upsert(
                namespace=namespace,
                record_key=f"retention-marker:{namespace}",
                payload={"job_id": job.job_id},
                event_type="retention_marker_created",
                entity_type="retention_marker",
            )
        store.upsert(
            namespace="raw_email_bodies",
            record_key="old-raw-body",
            payload={"body_text": "must expire"},
            event_type="raw_body_marker_created",
            entity_type="raw_body_marker",
        )
        with sqlite3.connect(store.db_path) as connection:
            connection.execute(
                "UPDATE state_records SET updated_at = ?",
                ("2020-01-01T00:00:00+00:00",),
            )
        store.purge_expired(now=datetime(2026, 9, 8, tzinfo=timezone.utc))
        retained = all(
            store.exists(
                namespace=namespace,
                record_key=f"retention-marker:{namespace}",
            )
            for namespace in DURABLE_JOB_LIFECYCLE_NAMESPACES
        )
        parser_calls: list[bool] = []

        def unexpected_parser(_safe_text):
            parser_calls.append(True)
            return ShipmentProposalSnapshot(customer_name="Unexpected")

        duplicate = process_customer_inquiry_mail(
            mail=incoming,
            shipment_parser=unexpected_parser,
            proposal_repository=proposals,
        )
        check(
            retained
            and jobs.get(job.job_id) is not None
            and proposals.get(proposal.proposal_id) is not None,
            "durable job workflow lifecycle and idempotency state survives retention",
        )
        check(
            duplicate["ingestion_status"] == "duplicate_existing_proposal"
            and not parser_calls,
            "old inbound message is not re-proposed after retention purge",
        )
        check(
            store.get(namespace="raw_email_bodies", record_key="old-raw-body")
            is None,
            "raw email body namespace remains subject to ordinary retention",
        )

    return {
        "name": "Pre-pilot hardening",
        "passed": not failures,
        "failures": failures,
    }


if __name__ == "__main__":
    result = evaluate_pre_pilot_hardening_regressions()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    raise SystemExit(0 if result["passed"] else 1)
