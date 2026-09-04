from __future__ import annotations

from datetime import datetime, timezone

from src.core.automation_policy import (
    AgencyAutomationPolicy,
    AutomationMode,
    AutomationPolicyAction,
    EffectiveAutomationPolicy,
)
from src.core.automation_policy_repository import AgencyAutomationPolicyRepository
from src.core.master_data import CustomerMasterProfile, normalize_master_text
from src.core.master_data_repository import MasterDataRepository
from src.core.mina_job_repository import MinaJobRepository


def _aware_utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Automation policy timestamp must be timezone-aware.")
    return current.astimezone(timezone.utc)


def _actor(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("Operator identity is required.")
    return normalized


def save_agency_automation_policy(
    *,
    repository: AgencyAutomationPolicyRepository,
    updated_by: str,
    supplier_reminder_mode: AutomationMode | None,
    customer_deadline_update_mode: AutomationMode | None,
    occurred_at: datetime | None = None,
) -> AgencyAutomationPolicy:
    policy = AgencyAutomationPolicy(
        supplier_reminder_mode=supplier_reminder_mode,
        customer_deadline_update_mode=customer_deadline_update_mode,
        updated_at=_aware_utc(occurred_at),
        updated_by=_actor(updated_by),
    )
    return repository.save(policy)


def _customer_matches(profile: CustomerMasterProfile, customer_name: str) -> bool:
    target = normalize_master_text(customer_name)
    candidates = {
        normalize_master_text(value)
        for value in [profile.customer_name, *profile.aliases]
        if value and normalize_master_text(value)
    }
    return target in candidates


def find_customer_policy_profile(
    repository: MasterDataRepository | None,
    customer_name: str | None,
) -> CustomerMasterProfile | None:
    if repository is None or not customer_name or not customer_name.strip():
        return None
    direct = repository.find_customer_by_name(customer_name)
    if direct is not None and direct.active:
        return direct
    matches = [
        profile
        for profile in repository.list_customers()
        if profile.active and _customer_matches(profile, customer_name)
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def _mode_for_action(container, action: AutomationPolicyAction) -> AutomationMode | None:
    if container is None:
        return None
    if action == "supplier_reminder":
        return getattr(container, "supplier_reminder_mode", None)
    return getattr(container, "customer_deadline_update_mode", None)


def _legacy_disabled(job, action: AutomationPolicyAction) -> bool:
    if job is None:
        return False
    if action == "supplier_reminder":
        return bool(job.automation_overrides.disable_supplier_reminders)
    return bool(job.automation_overrides.disable_customer_deadline_updates)


def resolve_effective_automation_policy(
    *,
    action: AutomationPolicyAction,
    legacy_dispatch_enabled: bool,
    mina_job_repository: MinaJobRepository | None = None,
    job_id: str | None = None,
    master_data_repository: MasterDataRepository | None = None,
    agency_policy_repository: AgencyAutomationPolicyRepository | None = None,
) -> EffectiveAutomationPolicy:
    job = (
        mina_job_repository.get(job_id)
        if mina_job_repository is not None and job_id
        else None
    )
    job_mode = _mode_for_action(
        None if job is None else job.automation_overrides,
        action,
    )
    legacy_job_disabled = _legacy_disabled(job, action)
    customer = find_customer_policy_profile(
        master_data_repository,
        None if job is None else job.shipment.customer_name,
    )
    customer_mode = _mode_for_action(customer, action)
    agency_policy = (
        agency_policy_repository.get()
        if agency_policy_repository is not None
        else None
    )
    agency_mode = _mode_for_action(agency_policy, action)

    if job_mode is not None:
        mode = job_mode
        resolved_from = "job"
    elif legacy_job_disabled:
        mode = "manual"
        resolved_from = "job_legacy_disable"
    elif customer_mode is not None:
        mode = customer_mode
        resolved_from = "customer"
    elif agency_mode is not None:
        mode = agency_mode
        resolved_from = "agency"
    else:
        mode = "automatic" if legacy_dispatch_enabled else "manual"
        resolved_from = "legacy_dispatch"

    return EffectiveAutomationPolicy(
        action=action,
        effective_mode=mode,
        resolved_from=resolved_from,
        job_mode=job_mode,
        legacy_job_disabled=legacy_job_disabled,
        customer_mode=customer_mode,
        customer_id=None if customer is None else customer.customer_id,
        agency_mode=agency_mode,
        legacy_dispatch_enabled=legacy_dispatch_enabled,
    )
