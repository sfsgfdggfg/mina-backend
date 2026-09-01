from __future__ import annotations

import argparse
import ipaddress
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import requests


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = 10.0


class OperatorConfigurationError(ValueError):
    pass


class OperatorAPIError(RuntimeError):
    pass


_STATUS_MESSAGES = {
    401: "Authentication failed. Check MINAI_PILOT_TOKEN.",
    403: "Access denied by the pilot network boundary.",
    404: "Resource was not found or this route is disabled in pilot mode.",
    426: "Secure HTTPS transport is required for this pilot connection.",
    409: "Lifecycle conflict or stale attempt. Refresh state before acting.",
    428: "Outlook authorization is required on the pilot host.",
    422: "Input or correction was rejected. Review the supplied values.",
    503: "Pilot configuration, provenance, or system safety block.",
}


def validate_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    try:
        parsed = urlsplit(normalized)
        port = parsed.port
    except ValueError as exc:
        raise OperatorConfigurationError(
            "MINAI_PILOT_BASE_URL is not a valid URL."
        ) from exc
    if parsed.scheme not in {"http", "https"}:
        raise OperatorConfigurationError(
            "MINAI_PILOT_BASE_URL must use http or https."
        )
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or port is None and ":" in parsed.netloc and not parsed.netloc.endswith("]")
        or port is not None and not 1 <= port <= 65535
    ):
        raise OperatorConfigurationError(
            "MINAI_PILOT_BASE_URL must contain only a host and optional port."
        )

    host = parsed.hostname
    if host.lower() == "localhost":
        return normalized
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise OperatorConfigurationError(
            "Pilot API host must be localhost or an explicit private/loopback IP."
        ) from exc
    if (
        address.is_unspecified
        or address.is_multicast
        or not (address.is_private or address.is_loopback)
    ):
        raise OperatorConfigurationError(
            "Pilot API host must be a specific private or loopback address."
        )

    if (
        not address.is_loopback
        and parsed.scheme != "https"
    ):
        raise OperatorConfigurationError(
            "Private-network pilot API URLs "
            "must use https."
        )

    return normalized


class PilotOperatorClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        session: requests.Session | None = None,
    ) -> None:
        normalized_token = token.strip()
        if not normalized_token:
            raise OperatorConfigurationError("MINAI_PILOT_TOKEN is required.")
        if timeout <= 0:
            raise OperatorConfigurationError("Pilot API timeout must be positive.")
        self.base_url = validate_base_url(base_url)
        self.__token = normalized_token
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.trust_env = False

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        session: requests.Session | None = None,
    ) -> "PilotOperatorClient":
        env = environ if environ is not None else os.environ
        return cls(
            base_url=env.get("MINAI_PILOT_BASE_URL", DEFAULT_BASE_URL),
            token=env.get("MINAI_PILOT_TOKEN", ""),
            session=session,
        )

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        try:
            response = self.session.request(
                method,
                self.base_url + path,
                headers={"Authorization": f"Bearer {self.__token}"},
                json=payload,
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise OperatorAPIError("Could not reach the pilot API.") from exc

        if 300 <= response.status_code < 400:
            raise OperatorAPIError(
                "Pilot API redirect refused to protect operator credentials."
            )
        if response.status_code >= 400:
            message = _STATUS_MESSAGES.get(
                response.status_code,
                f"Pilot API request failed with status {response.status_code}.",
            )
            raise OperatorAPIError(message)
        try:
            return response.json()
        except (ValueError, requests.exceptions.JSONDecodeError) as exc:
            raise OperatorAPIError("Pilot API returned an invalid response.") from exc

    @staticmethod
    def _id(value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise OperatorConfigurationError("Resource identifier is required.")
        return quote(normalized, safe="")

    def status(self) -> Any:
        health = self._request("GET", "/health")
        self._request("GET", "/supplier-rfqs")
        return {"health": health, "authentication": "ok"}

    def runtime_release(self) -> Any:
        return self._request(
            "GET",
            "/runtime/release",
        )

    def process_email(self, **payload: Any) -> Any:
        return self._request("POST", "/process-email", payload)

    def pull_outlook(
        self,
        *,
        limit: int = 10,
    ) -> Any:
        return self._request(
            "POST",
            "/inbound/outlook/pull",
            {"limit": limit},
        )

    def get_proposal(self, proposal_id: str) -> Any:
        return self._request(
            "GET", f"/extraction-proposals/{self._id(proposal_id)}"
        )

    def confirm_proposal(
        self,
        proposal_id: str,
        corrections: dict[str, Any],
    ) -> Any:
        return self._request(
            "POST",
            f"/extraction-proposals/{self._id(proposal_id)}/confirm",
            {"corrections": corrections},
        )

    def resume_proposal(self, proposal_id: str) -> Any:
        return self._request(
            "POST", f"/extraction-proposals/{self._id(proposal_id)}/resume"
        )

    def list_rfqs(self) -> Any:
        return self._request("GET", "/supplier-rfqs")

    def get_rfq(self, rfq_id: str) -> Any:
        return self._request("GET", f"/supplier-rfqs/{self._id(rfq_id)}")

    def approve_rfq(self, rfq_id: str) -> Any:
        return self._request(
            "POST", f"/supplier-rfqs/{self._id(rfq_id)}/approve", {}
        )

    def send_rfq(self, rfq_id: str) -> Any:
        return self._request(
            "POST", f"/supplier-rfqs/{self._id(rfq_id)}/send", {}
        )

    def record_rfq_manually_sent(self, rfq_id: str) -> Any:
        return self._request(
            "POST",
            f"/supplier-rfqs/{self._id(rfq_id)}/record-manually-sent",
            {},
        )

    def list_rfq_follow_ups(self, rfq_id: str) -> Any:
        return self._request(
            "GET",
            f"/supplier-rfqs/{self._id(rfq_id)}/follow-ups",
        )

    def get_rfq_follow_up(self, follow_up_id: str) -> Any:
        return self._request(
            "GET",
            f"/supplier-rfq-follow-ups/{self._id(follow_up_id)}",
        )

    def approve_rfq_follow_up(self, follow_up_id: str) -> Any:
        return self._request(
            "POST",
            f"/supplier-rfq-follow-ups/{self._id(follow_up_id)}/approve",
            {},
        )

    def send_rfq_follow_up(self, follow_up_id: str) -> Any:
        return self._request(
            "POST",
            f"/supplier-rfq-follow-ups/{self._id(follow_up_id)}/send",
            {},
        )

    def record_rfq_follow_up_manually_sent(self, follow_up_id: str) -> Any:
        return self._request(
            "POST",
            (
                f"/supplier-rfq-follow-ups/{self._id(follow_up_id)}"
                "/record-manually-sent"
            ),
            {},
        )

    def record_rfq_response(self, rfq_id: str, **payload: Any) -> Any:
        return self._request(
            "POST", f"/supplier-rfqs/{self._id(rfq_id)}/responses", payload
        )

    def resume_quote_workflow(
        self,
        workflow_id: str,
        quote_pricing_override: dict[str, Any] | None = None,
    ) -> Any:
        payload = (
            {"quote_pricing_override": quote_pricing_override}
            if quote_pricing_override is not None
            else None
        )
        return self._request(
            "POST",
            f"/supplier-rfq-workflows/{self._id(workflow_id)}/resume-quote",
            payload,
        )

    def list_approvals(self) -> Any:
        return self._request("GET", "/quote-approvals")

    def get_approval(self, approval_id: str) -> Any:
        return self._request(
            "GET", f"/quote-approvals/{self._id(approval_id)}"
        )

    def approve_quote(self, approval_id: str) -> Any:
        return self._request(
            "POST", f"/quote-approvals/{self._id(approval_id)}/approve", {}
        )

    def reject_quote(self, approval_id: str, reason: str) -> Any:
        return self._request(
            "POST",
            f"/quote-approvals/{self._id(approval_id)}/reject",
            {"rejection_reason": reason},
        )

    def invalidate_quote(self, approval_id: str) -> Any:
        return self._request(
            "POST", f"/quote-approvals/{self._id(approval_id)}/invalidate"
        )

    def list_cases(self) -> Any:
        return self._request("GET", "/quote-cases")

    def get_case(self, case_id: str) -> Any:
        return self._request("GET", f"/quote-cases/{self._id(case_id)}")

    def get_case_final_output(self, case_id: str) -> Any:
        return self._request(
            "GET",
            f"/quote-cases/{self._id(case_id)}/final-output",
        )

    def record_case_manually_sent(
        self,
        case_id: str,
        *,
        expected_approval_id: str,
        recipient_email: str,
    ) -> Any:
        return self._request(
            "POST",
            f"/quote-cases/{self._id(case_id)}/record-manually-sent",
            {
                "expected_approval_id": expected_approval_id,
                "recipient_email": recipient_email,
            },
        )

    def send_case(
        self,
        case_id: str,
        *,
        expected_approval_id: str,
        recipient_email: str,
    ) -> Any:
        return self._request(
            "POST",
            f"/quote-cases/{self._id(case_id)}/send",
            {
                "expected_approval_id": expected_approval_id,
                "recipient_email": recipient_email,
            },
        )

    def revise_case(
        self,
        case_id: str,
        *,
        expected_approval_id: str,
        subject: str,
        body: str,
        final_price: float | None = None,
        operator_note: str | None = None,
    ) -> Any:
        payload = {
            "expected_approval_id": expected_approval_id,
            "subject": subject,
            "body": body,
        }

        if final_price is not None:
            payload["final_price"] = final_price

        if operator_note is not None:
            payload["operator_note"] = operator_note

        return self._request(
            "POST",
            (
                f"/quote-cases/"
                f"{self._id(case_id)}/revise"
            ),
            payload,
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Authenticated MINAI shadow-pilot operator client."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")

    process = commands.add_parser("process-email")
    body = process.add_mutually_exclusive_group(required=True)
    body.add_argument("--body")
    body.add_argument("--body-file")
    process.add_argument("--sender-address", required=True)
    process.add_argument("--sender-name")
    process.add_argument("--subject", required=True)
    process.add_argument("--external-message-id")

    outlook = commands.add_parser(
        "outlook"
    ).add_subparsers(
        dest="action",
        required=True,
    )

    outlook_pull = outlook.add_parser(
        "pull"
    )
    outlook_pull.add_argument(
        "--limit",
        type=int,
        default=10,
        choices=range(1, 51),
        metavar="1-50",
    )

    proposal = commands.add_parser("proposal").add_subparsers(
        dest="action", required=True
    )
    proposal.add_parser("get").add_argument("proposal_id")
    confirm = proposal.add_parser("confirm")
    confirm.add_argument("proposal_id")
    confirm.add_argument("--corrections", default="{}")
    proposal.add_parser("resume").add_argument("proposal_id")

    rfq = commands.add_parser("rfq").add_subparsers(
        dest="action", required=True
    )
    rfq.add_parser("list")
    rfq.add_parser("get").add_argument("rfq_id")
    rfq.add_parser("approve").add_argument("rfq_id")
    rfq.add_parser("send").add_argument("rfq_id")
    rfq.add_parser("manual-sent").add_argument("rfq_id")
    rfq.add_parser("follow-up-list").add_argument("rfq_id")
    rfq.add_parser("follow-up-get").add_argument("follow_up_id")
    rfq.add_parser("follow-up-approve").add_argument("follow_up_id")
    rfq.add_parser("follow-up-send").add_argument("follow_up_id")
    rfq.add_parser("follow-up-manual-sent").add_argument("follow_up_id")
    response = rfq.add_parser("response")
    response.add_argument("rfq_id")
    response.add_argument("--supplier-name", required=True)
    response.add_argument("--priority", required=True, type=int)
    response.add_argument(
        "--status",
        required=True,
        choices=("quoted", "no_capacity", "declined", "needs_clarification"),
    )
    response.add_argument("--cost", type=float)
    response.add_argument("--currency")
    response.add_argument("--transit-time")
    response.add_argument("--validity-date")
    response.add_argument("--equipment-type")
    response.add_argument("--notes")

    workflow = commands.add_parser("workflow").add_subparsers(
        dest="action", required=True
    )
    resume_quote = workflow.add_parser("resume-quote")
    resume_quote.add_argument("workflow_id")
    resume_quote.add_argument(
        "--pricing-method",
        choices=[
            "cost_markup_percentage",
            "gross_margin_percentage",
            "fixed_profit",
            "manual_sell_price",
        ],
    )
    resume_quote.add_argument("--pricing-value", type=float)

    approval = commands.add_parser("approval").add_subparsers(
        dest="action", required=True
    )
    approval.add_parser("list")
    approval.add_parser("get").add_argument("approval_id")
    approval.add_parser("approve").add_argument("approval_id")
    reject = approval.add_parser("reject")
    reject.add_argument("approval_id")
    reject.add_argument("--reason", required=True)
    approval.add_parser("invalidate").add_argument("approval_id")

    case = commands.add_parser("case").add_subparsers(
        dest="action", required=True
    )
    case.add_parser("list")
    case.add_parser("get").add_argument("case_id")
    case.add_parser("final").add_argument("case_id")
    manual_sent = case.add_parser("manual-sent")
    manual_sent.add_argument("case_id")
    manual_sent.add_argument("--approval-id", required=True)
    manual_sent.add_argument("--recipient-email", required=True)
    send = case.add_parser("send")
    send.add_argument("case_id")
    send.add_argument("--approval-id", required=True)
    send.add_argument("--recipient-email", required=True)

    revise = case.add_parser("revise")
    revise.add_argument("case_id")
    revise.add_argument(
        "--approval-id",
        required=True,
    )
    revise.add_argument(
        "--subject",
        required=True,
    )

    revise_body = (
        revise.add_mutually_exclusive_group(
            required=True
        )
    )
    revise_body.add_argument("--body")
    revise_body.add_argument("--body-file")

    revise.add_argument(
        "--final-price",
        type=float,
    )
    revise.add_argument("--note")

    return parser


def _load_corrections(raw: str) -> dict[str, Any]:
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise OperatorConfigurationError("Corrections must be a JSON object.")
    return parsed


def _read_email_body(args: argparse.Namespace) -> str:
    if args.body is not None:
        return args.body
    if args.body_file == "-":
        return sys.stdin.read()
    return Path(args.body_file).read_text(encoding="utf-8")


def _compact(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _execute(client: PilotOperatorClient, args: argparse.Namespace) -> Any:
    if args.command == "status":
        return client.status()
    if args.command == "process-email":
        return client.process_email(
            **_compact(
                {
                    "email_text": _read_email_body(args),
                    "sender_address": args.sender_address,
                    "sender_name": args.sender_name,
                    "subject": args.subject,
                    "external_message_id": args.external_message_id,
                }
            )
        )
    if args.command == "outlook":
        return client.pull_outlook(
            limit=args.limit
        )
    if args.command == "proposal":
        if args.action == "get":
            return client.get_proposal(args.proposal_id)
        if args.action == "confirm":
            return client.confirm_proposal(
                args.proposal_id, _load_corrections(args.corrections)
            )
        return client.resume_proposal(args.proposal_id)
    if args.command == "rfq":
        if args.action == "list":
            return client.list_rfqs()
        if args.action == "get":
            return client.get_rfq(args.rfq_id)
        if args.action == "approve":
            return client.approve_rfq(args.rfq_id)
        if args.action == "send":
            return client.send_rfq(args.rfq_id)
        if args.action == "manual-sent":
            return client.record_rfq_manually_sent(args.rfq_id)
        if args.action == "follow-up-list":
            return client.list_rfq_follow_ups(args.rfq_id)
        if args.action == "follow-up-get":
            return client.get_rfq_follow_up(args.follow_up_id)
        if args.action == "follow-up-approve":
            return client.approve_rfq_follow_up(args.follow_up_id)
        if args.action == "follow-up-send":
            return client.send_rfq_follow_up(args.follow_up_id)
        if args.action == "follow-up-manual-sent":
            return client.record_rfq_follow_up_manually_sent(args.follow_up_id)
        return client.record_rfq_response(
            args.rfq_id,
            **_compact(
                {
                    "supplier_name": args.supplier_name,
                    "rfq_priority": args.priority,
                    "status": args.status,
                    "cost": args.cost,
                    "currency": args.currency,
                    "transit_time": args.transit_time,
                    "validity_date": args.validity_date,
                    "equipment_type": args.equipment_type,
                    "notes": args.notes,
                    "source": "manual",
                }
            ),
        )
    if args.command == "workflow":
        if (args.pricing_method is None) != (args.pricing_value is None):
            raise PilotOpsError(
                "--pricing-method and --pricing-value must be provided together."
            )
        quote_pricing_override = (
            {
                "method": args.pricing_method,
                "value": args.pricing_value,
            }
            if args.pricing_method is not None
            else None
        )
        return client.resume_quote_workflow(
            args.workflow_id,
            quote_pricing_override=quote_pricing_override,
        )
    if args.command == "approval":
        if args.action == "list":
            return client.list_approvals()
        if args.action == "get":
            return client.get_approval(args.approval_id)
        if args.action == "approve":
            return client.approve_quote(args.approval_id)
        if args.action == "reject":
            return client.reject_quote(args.approval_id, args.reason)
        return client.invalidate_quote(args.approval_id)
    if args.action == "list":
        return client.list_cases()

    if args.action == "get":
        return client.get_case(args.case_id)

    if args.action == "final":
        return client.get_case_final_output(args.case_id)

    if args.action == "manual-sent":
        return client.record_case_manually_sent(
            args.case_id,
            expected_approval_id=args.approval_id,
            recipient_email=args.recipient_email,
        )

    if args.action == "send":
        return client.send_case(
            args.case_id,
            expected_approval_id=args.approval_id,
            recipient_email=args.recipient_email,
        )

    return client.revise_case(
        args.case_id,
        expected_approval_id=(
            args.approval_id
        ),
        subject=args.subject,
        body=_read_email_body(args),
        final_price=args.final_price,
        operator_note=args.note,
    )


def main(argv: list[str] | None = None) -> int:
    try:
        args = _build_parser().parse_args(argv)
        client = PilotOperatorClient.from_environment()
        result = _execute(client, args)
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return 0
    except (OperatorConfigurationError, OperatorAPIError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
