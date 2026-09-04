from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import requests
import streamlit as st


STAGE_LABELS = {
    "inquiry_confirmed": "Talep doğrulandı",
    "pricing": "Fiyat çalışması",
    "quote_ready": "Teklif hazır",
    "quote_sent": "Teklif gönderildi",
    "negotiation": "Revizyon / görüşme",
    "accepted": "Müşteri kabul etti",
    "operations": "Operasyon (legacy)",
    "operation_opened": "Operasyon açıldı",
    "supplier_confirmation_pending": "Tedarikçi teyidi bekleniyor",
    "vehicle_details_pending": "Araç bilgileri bekleniyor",
    "vehicle_assigned": "Araç atandı",
    "pre_loading_check": "Yükleme öncesi kontrol",
    "ready_for_loading": "Yüklemeye hazır",
    "loaded": "Yüklendi",
    "in_transit": "Yolda",
    "delivery": "Teslimat",
    "delivered": "Teslim edildi",
    "pod_cmr_pending": "POD / CMR bekleniyor",
    "closing_review": "Kapanış kontrolü",
    "completed": "Tamamlandı",
    "lost": "Kaybedildi",
    "cancelled": "İptal edildi",
}

ISTANBUL = ZoneInfo("Europe/Istanbul")

SUPPLIER_STATUS_LABELS = {
    "draft": "Taslak",
    "approved": "Onaylandı",
    "awaiting_response": "Cevap bekleniyor",
    "responded": "Yanıt geldi",
}

EVENT_LABELS = {
    "job_opened": "MINA işi açıldı",
    "operational_resume_recorded": "Operasyon akışı değerlendirildi",
    "supplier_workflow_linked": "Supplier fiyat çalışması açıldı",
    "quote_case_linked": "Teklif dosyası oluşturuldu",
    "customer_quote_sent": "Müşteriye teklif gönderildi",
    "quote_revised": "Teklif revize edildi",
    "automation_override_changed": "İş otomasyon ayarı değiştirildi",
    "supplier_reminder_sent_early": "Supplier reminder erken gönderildi",
    "stage_changed": "İş aşaması değiştirildi",
}

V1_MANUAL_STAGE_ACTIONS = {
    "quote_sent": [("accepted", "Müşteri kabul etti")],
    "negotiation": [("accepted", "Müşteri kabul etti")],
    "accepted": [("operations", "Operasyonu başlat")],
    "operations": [("in_transit", "Araç yola çıktı")],
    "in_transit": [("delivered", "Teslim edildi")],
}

V2_MANUAL_STAGE_ACTIONS = {
    "pricing": [("operation_opened", "Operasyonu başlat")],
    "quote_sent": [("accepted", "Müşteri kabul etti")],
    "negotiation": [("accepted", "Müşteri kabul etti")],
    "accepted": [("operation_opened", "Operasyonu başlat")],
    "operation_opened": [("supplier_confirmation_pending", "Tedarikçi teyidi bekleniyor")],
    "supplier_confirmation_pending": [("vehicle_details_pending", "Araç bilgilerini bekle")],
    "vehicle_details_pending": [("vehicle_assigned", "Araç atandı")],
    "vehicle_assigned": [("pre_loading_check", "Yükleme öncesi kontrol")],
    "pre_loading_check": [("ready_for_loading", "Yüklemeye hazır")],
    "ready_for_loading": [("loaded", "Yüklendi")],
    "loaded": [("in_transit", "Transit başlat")],
    "in_transit": [("delivery", "Teslimat aşamasına geç")],
    "delivery": [("delivered", "Teslim edildi")],
    "delivered": [("pod_cmr_pending", "POD / CMR bekleniyor")],
    "pod_cmr_pending": [("closing_review", "Kapanış kontrolü")],
    "closing_review": [("completed", "Operasyonu tamamla")],
}


def _error_detail(response: requests.Response) -> str:
    try:
        detail = response.json().get("detail")
        return str(detail or response.text or response.status_code)
    except Exception:
        return response.text or f"HTTP {response.status_code}"


def _get_json(api_base_url: str, path: str) -> dict[str, Any]:
    response = requests.get(f"{api_base_url}{path}", timeout=20)
    if response.status_code >= 400:
        raise RuntimeError(_error_detail(response))
    return response.json()


def _post_json(
    api_base_url: str, path: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    response = requests.post(
        f"{api_base_url}{path}", json=payload or {}, timeout=30
    )
    if response.status_code >= 400:
        raise RuntimeError(_error_detail(response))
    return response.json()


def _format_time(value: Any) -> str:
    if not value:
        return "-"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(ISTANBUL).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(value)


def _stage_label(stage: str | None) -> str:
    return STAGE_LABELS.get(stage or "", stage or "-")


def _status_icon(job: dict[str, Any]) -> str:
    if job.get("is_closed"):
        return "✅" if job.get("stage") in {"delivered", "completed"} else "⚪"
    if job.get("stage") in {"quote_ready", "quote_sent", "negotiation"}:
        return "🟡"
    if job.get("stage") in {"accepted", "operations", "in_transit"}:
        return "🔵"
    return "🟠"


def _select_job(job_id: str) -> None:
    st.session_state["selected_mina_job_id"] = job_id
    st.rerun()


def _clear_selected_job() -> None:
    st.session_state.pop("selected_mina_job_id", None)
    st.session_state.pop("mina_reminder_preview", None)
    st.rerun()


def render_mina_operations(api_base_url: str) -> None:
    selected_job_id = st.session_state.get("selected_mina_job_id")
    if selected_job_id:
        render_mina_job_detail(api_base_url, selected_job_id)
        return
    render_mina_job_list(api_base_url)


def render_mina_job_list(api_base_url: str) -> None:
    st.subheader("MINA İşleri")
    st.caption(
        "Her MINA kodu tek lojistik işi temsil eder ve teslimata kadar aynı dosyada izlenir."
    )
    try:
        jobs = _get_json(api_base_url, "/mina-jobs").get("jobs") or []
    except (requests.RequestException, RuntimeError) as exc:
        st.error("MINA iş listesi alınamadı.")
        st.caption(str(exc))
        return

    open_jobs = [job for job in jobs if not job.get("is_closed")]
    delivered = [job for job in jobs if job.get("stage") == "delivered"]
    closed_other = [
        job for job in jobs
        if job.get("is_closed") and job.get("stage") != "delivered"
    ]
    c1, c2, c3 = st.columns(3)
    c1.metric("Açık İş", len(open_jobs))
    c2.metric("Teslim Edilen", len(delivered))
    c3.metric("Diğer Kapanan", len(closed_other))

    filter_col, search_col = st.columns([1, 2])
    with filter_col:
        status_filter = st.selectbox(
            "Göster",
            ["Açık işler", "Tüm işler", "Kapanan işler"],
            key="mina_job_status_filter",
        )
    with search_col:
        search_text = st.text_input(
            "MINA kodu, müşteri veya güzergah ara",
            key="mina_job_search",
        ).strip().casefold()

    visible = jobs
    if status_filter == "Açık işler":
        visible = open_jobs
    elif status_filter == "Kapanan işler":
        visible = [job for job in jobs if job.get("is_closed")]
    if search_text:
        visible = [
            job for job in visible
            if search_text in " ".join([
                str(job.get("mina_code") or ""),
                str(job.get("customer_name") or ""),
                str(job.get("route") or ""),
            ]).casefold()
        ]

    if not visible:
        st.info("Bu filtrede gösterilecek MINA işi yok.")
        return

    for job in visible:
        icon = _status_icon(job)
        with st.container(border=True):
            left, middle, right = st.columns([2, 4, 1])
            with left:
                st.markdown(f"### {icon} {job.get('mina_code', '-')}")
                st.caption(_stage_label(job.get("stage")))
            with middle:
                st.write(f"**{job.get('customer_name') or 'Müşteri belirtilmemiş'}**")
                st.write(job.get("route") or "Güzergah net değil")
                st.caption(
                    f"Son güncelleme: {_format_time(job.get('updated_at'))}"
                )
            with right:
                if st.button(
                    "İşi Aç",
                    key=f"open_mina_job_{job.get('job_id')}",
                    use_container_width=True,
                ):
                    _select_job(str(job.get("job_id")))


def render_mina_job_detail(api_base_url: str, job_id: str) -> None:
    if st.button("← İş listesine dön", key="mina_back_to_jobs"):
        _clear_selected_job()

    try:
        detail = _get_json(api_base_url, f"/mina-jobs/{job_id}")
    except (requests.RequestException, RuntimeError) as exc:
        st.error("MINA iş detayı alınamadı.")
        st.caption(str(exc))
        return

    summary = detail.get("summary") or {}
    st.markdown(f"## {summary.get('mina_code') or 'MINA işi'}")
    st.caption(_stage_label(summary.get("stage")))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Müşteri", summary.get("customer_name") or "-")
    c2.metric("Güzergah", summary.get("route") or "-")
    c3.metric("Taşıma", str(summary.get("transport_mode") or "-").upper())
    c4.metric(
        "Teklif Deadline",
        _format_time(summary.get("customer_quote_deadline_at")),
    )

    overview_tab, supplier_tab, quote_tab, timeline_tab, controls_tab = st.tabs(
        ["Genel", "Tedarikçiler", "Teklif", "Zaman Çizelgesi", "Kontroller"]
    )
    with overview_tab:
        _render_job_overview(detail)
    with supplier_tab:
        _render_suppliers(api_base_url, job_id, detail)
    with quote_tab:
        _render_quote(detail)
    with timeline_tab:
        _render_timeline(detail)
    with controls_tab:
        _render_job_controls(api_base_url, job_id, detail)


def _render_job_overview(detail: dict[str, Any]) -> None:
    job = detail.get("job") or {}
    shipment = job.get("shipment") or {}
    automation = detail.get("automation") or {}

    st.markdown("### İş Durumu")
    st.write(f"**Aşama:** {_stage_label(job.get('stage'))}")
    st.write(f"**Açılış:** {_format_time(job.get('opened_at'))}")
    st.write(f"**Son güncelleme:** {_format_time(job.get('updated_at'))}")
    if job.get("closed_at"):
        st.write(f"**Kapanış:** {_format_time(job.get('closed_at'))}")

    st.markdown("### Yük Özeti")
    columns = st.columns(3)
    columns[0].write(f"**Ürün:** {shipment.get('commodity') or '-'}")
    columns[1].write(f"**Ağırlık:** {shipment.get('gross_weight_kg') or '-'} kg")
    columns[2].write(f"**Ekipman:** {shipment.get('equipment_type') or '-'}")

    st.markdown("### Otomasyon Özeti")
    supplier_effective = automation.get("supplier_reminders_effective")
    customer_effective = automation.get("customer_deadline_updates_effective")
    supplier_policy = automation.get("supplier_reminder_policy") or {}
    customer_policy = automation.get("customer_deadline_update_policy") or {}
    mode_labels = {
        "automatic": "Otomatik",
        "approval_required": "Onay Gerekli",
        "manual": "Manuel",
    }
    source_labels = {
        "job": "İş", "job_legacy_disable": "İş (eski kapatma)",
        "customer": "Müşteri", "agency": "Acenta", "legacy_dispatch": "Mevcut varsayılan",
    }
    a1, a2 = st.columns(2)
    supplier_mode = supplier_policy.get("effective_mode")
    customer_mode = customer_policy.get("effective_mode")
    a1.metric("Supplier Reminder", mode_labels.get(supplier_mode, "-"))
    a2.metric("Müşteri Deadline Bilgisi", mode_labels.get(customer_mode, "-"))
    if supplier_policy.get("resolved_from"):
        a1.caption(f"Kaynak: {source_labels.get(supplier_policy.get('resolved_from'), supplier_policy.get('resolved_from'))}")
    if customer_policy.get("resolved_from"):
        a2.caption(f"Kaynak: {source_labels.get(customer_policy.get('resolved_from'), customer_policy.get('resolved_from'))}")
    customer_plan = automation.get("customer_deadline_plan") or {}
    if customer_plan.get("state"):
        st.caption(
            "Müşteri deadline aksiyonu: "
            f"{customer_plan.get('state')}"
        )


def _render_suppliers(
    api_base_url: str, job_id: str, detail: dict[str, Any]
) -> None:
    _render_supplier_prices(api_base_url, job_id, detail)
    st.divider()
    st.markdown("### RFQ Takibi")
    suppliers = detail.get("suppliers") or []
    if not suppliers:
        st.info("Bu iş için henüz supplier RFQ kaydı yok.")
        return

    for supplier in suppliers:
        name = supplier.get("supplier_name") or "Supplier"
        tier = supplier.get("dispatch_tier") or "-"
        status = SUPPLIER_STATUS_LABELS.get(
            supplier.get("status"), supplier.get("status") or "-"
        )
        with st.expander(f"{name} — {status} — {tier}", expanded=True):
            c1, c2, c3 = st.columns(3)
            c1.write(f"**Gönderildi:** {_format_time(supplier.get('sent_at'))}")
            c2.write(
                "**Teyit:** "
                f"{_format_time(supplier.get('latest_acknowledgement_at'))}"
            )
            c3.write(f"**Yanıt:** {_format_time(supplier.get('responded_at'))}")

            commercial = supplier.get("commercial_response") or {}
            if commercial:
                price = commercial.get("cost")
                currency = commercial.get("currency") or ""
                st.success(
                    f"Ticari sonuç: {commercial.get('status') or '-'}"
                    + (f" — {price} {currency}" if price is not None else "")
                )
                if commercial.get("transit_time"):
                    st.caption(f"Transit: {commercial.get('transit_time')}")

            _render_supplier_reminder_controls(
                api_base_url, job_id, supplier
            )


def _render_supplier_prices(
    api_base_url: str, job_id: str, detail: dict[str, Any]
) -> None:
    price_view = detail.get("supplier_prices") or {}
    offers = price_view.get("price_offers") or []
    fixed_rates = price_view.get("applicable_fixed_rates") or []
    controls = detail.get("controls") or {}
    entry_allowed = bool(controls.get("supplier_price_entry_available"))

    st.markdown("### Tedarikçi Fiyatları")
    if offers:
        rows = []
        source_labels = {
            "rfq_email": "RFQ / E-posta", "rfq_portal": "RFQ / Portal",
            "rfq_api": "RFQ / API", "rfq_manual": "RFQ / Manuel",
            "email": "E-posta", "phone": "Telefon", "whatsapp": "WhatsApp",
            "portal": "Portal", "api": "API", "manual": "Manuel",
            "fixed_rate": "Sabit / Anlaşmalı",
        }
        for offer in offers:
            rows.append({
                "Tedarikçi": offer.get("supplier_name"),
                "Kaynak": source_labels.get(offer.get("source_type"), offer.get("source_type")),
                "Fiyat": offer.get("cost"),
                "Döviz": offer.get("currency"),
                "Transit": offer.get("transit_time") or "-",
                "Geçerlilik": offer.get("validity_date") or "-",
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("Henüz kullanılabilir tedarikçi fiyatı kaydedilmedi.")

    if fixed_rates:
        st.markdown("#### Uygun Sabit Fiyatlar")
        for item in fixed_rates:
            rate = item.get("rate") or {}
            cols = st.columns([3, 2, 2])
            cols[0].write(
                f"**{rate.get('supplier_name') or '-'}** — "
                f"{rate.get('origin_country') or '-'} → {rate.get('destination_country') or '-'}"
            )
            cols[1].write(f"**{rate.get('cost')} {rate.get('currency')}**")
            cols[1].caption(f"{rate.get('valid_from')} – {rate.get('valid_to')}")
            if entry_allowed and cols[2].button(
                "Bu Fiyatı Kullan", key=f"use_fixed_{job_id}_{rate.get('rate_id')}"
            ):
                try:
                    _post_json(
                        api_base_url,
                        f"/mina-jobs/{job_id}/supplier-prices/fixed-rate/{rate.get('rate_id')}",
                        {"entry_id": str(uuid4())},
                    )
                    st.success("Sabit fiyat işe eklendi.")
                    st.rerun()
                except (requests.RequestException, RuntimeError) as exc:
                    st.warning(str(exc))

    if not entry_allowed:
        return

    with st.expander("Manuel / Harici Fiyat Gir", expanded=False):
        with st.form(f"supplier_price_form_{job_id}"):
            supplier_name = st.text_input("Tedarikçi")
            source_label = st.selectbox(
                "Kaynak", ["Telefon", "WhatsApp", "E-posta", "Portal", "Manuel"]
            )
            c1, c2 = st.columns(2)
            cost = c1.number_input("Fiyat", min_value=0.01, step=50.0)
            currency = c2.text_input("Döviz", value="EUR", max_chars=3)
            transit = st.text_input("Transit", placeholder="Örn. 4 gün")
            equipment = st.text_input("Ekipman", placeholder="Örn. Tenteli")
            notes = st.text_area("Not")
            submitted = st.form_submit_button("Fiyatı Kaydet")
        if submitted:
            source_map = {
                "Telefon": "phone", "WhatsApp": "whatsapp", "E-posta": "email",
                "Portal": "portal", "Manuel": "manual",
            }
            try:
                _post_json(
                    api_base_url, f"/mina-jobs/{job_id}/supplier-prices/manual",
                    {
                        "entry_id": str(uuid4()), "supplier_name": supplier_name,
                        "source_type": source_map[source_label], "cost": cost,
                        "currency": currency, "transit_time": transit or None,
                        "equipment_type": equipment or None, "notes": notes or None,
                    },
                )
                st.success("Tedarikçi fiyatı kaydedildi.")
                st.rerun()
            except (requests.RequestException, RuntimeError) as exc:
                st.warning(str(exc))


def _render_supplier_reminder_controls(
    api_base_url: str, job_id: str, supplier: dict[str, Any]
) -> None:
    reminder = supplier.get("reminder") or {}
    rfq_id = str(supplier.get("rfq_id") or "")
    state = reminder.get("state")
    if state:
        st.write(f"**Reminder durumu:** {state}")
    if reminder.get("due_at"):
        st.caption(f"Planlanan zaman: {_format_time(reminder.get('due_at'))}")
    if reminder.get("resume_at"):
        st.caption(f"Tekrar değerlendir: {_format_time(reminder.get('resume_at'))}")
    if reminder.get("reason"):
        st.caption(str(reminder.get("reason")))

    if supplier.get("status") != "awaiting_response" or not rfq_id:
        return
    if state in {"human_contact_required", "automation_delivery_attention"}:
        st.info("Bu aşamada otomatik tekrar mail yerine insan takibi gerekiyor.")
        return

    if st.button("Reminder Önizle", key=f"preview_reminder_{rfq_id}"):
        try:
            preview = _get_json(
                api_base_url,
                f"/mina-jobs/{job_id}/supplier-rfqs/{rfq_id}/reminder-preview",
            )
            st.session_state["mina_reminder_preview"] = preview
        except (requests.RequestException, RuntimeError) as exc:
            st.warning(str(exc))

    preview = st.session_state.get("mina_reminder_preview") or {}
    if preview.get("rfq_id") != rfq_id:
        return

    st.markdown("**Gönderilecek reminder**")
    st.code(preview.get("subject") or "", language=None)
    st.text_area(
        "Mail içeriği",
        value=preview.get("body_text") or "",
        height=150,
        disabled=True,
        key=f"preview_body_{rfq_id}",
    )
    if preview.get("planned_due_at"):
        st.caption(
            f"Normal plan: {_format_time(preview.get('planned_due_at'))}"
        )
    if preview.get("send_now_allowed"):
        if st.button(
            "Reminder'ı Şimdi Gönder",
            key=f"send_reminder_{rfq_id}",
            type="primary",
        ):
            try:
                _post_json(
                    api_base_url,
                    f"/mina-jobs/{job_id}/supplier-rfqs/{rfq_id}/reminder-now",
                )
                st.session_state.pop("mina_reminder_preview", None)
                st.success("Reminder gönderildi ve planlı reminder tüketildi.")
                st.rerun()
            except (requests.RequestException, RuntimeError) as exc:
                st.error(str(exc))
    else:
        next_open = preview.get("next_supplier_open_at")
        st.warning(
            "Supplier iletişim penceresi kapalı; MINAI şimdi gönderime izin vermiyor."
        )
        if next_open:
            st.caption(f"Sonraki açılış: {_format_time(next_open)}")


def _render_quote(detail: dict[str, Any]) -> None:
    quote = detail.get("quote")
    if not quote:
        st.info("Bu iş için henüz müşteri teklif dosyası oluşmadı.")
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Revizyon", quote.get("current_revision_number") or 0)
    c2.metric("Onay", quote.get("approval_status") or "-")
    sent_count = (
        int(quote.get("manual_send_count") or 0)
        + int(quote.get("automated_send_count") or 0)
    )
    c3.metric("Gönderim", sent_count)
    st.caption(f"Quote case: {quote.get('case_id') or '-'}")


def _render_timeline(detail: dict[str, Any]) -> None:
    timeline = list(detail.get("timeline") or [])
    if not timeline:
        st.info("Henüz timeline olayı yok.")
        return

    for event in reversed(timeline):
        event_type = str(event.get("event_type") or "")
        label = EVENT_LABELS.get(event_type, event_type.replace("_", " ").title())
        actor = event.get("actor")
        metadata = event.get("metadata") or {}
        with st.container(border=True):
            st.write(f"**{label}**")
            line = _format_time(event.get("occurred_at"))
            if actor:
                line += f" · {actor}"
            st.caption(line)
            if event_type == "stage_changed":
                st.write(
                    f"{_stage_label(metadata.get('from_stage'))} → "
                    f"{_stage_label(metadata.get('to_stage'))}"
                )
            elif event_type == "quote_revised":
                st.write(f"Revizyon: {metadata.get('revision_number') or '-'}")
            elif event_type == "supplier_reminder_sent_early":
                st.write("Planlanan süreden önce insan tarafından gönderildi.")


def _render_job_controls(
    api_base_url: str, job_id: str, detail: dict[str, Any]
) -> None:
    job = detail.get("job") or {}
    controls = detail.get("controls") or {}
    if job.get("is_closed"):
        st.info("Bu iş kapalı. Geçmiş kayıtları salt okunur olarak korunur.")
        return

    if controls.get("automation_overrides_editable"):
        _render_automation_overrides(api_base_url, job_id, detail)
    st.divider()
    if controls.get("stage_transition_available"):
        _render_stage_actions(api_base_url, job_id, detail)


def _render_automation_overrides(
    api_base_url: str, job_id: str, detail: dict[str, Any]
) -> None:
    automation = detail.get("automation") or {}
    overrides = automation.get("overrides") or {}
    st.markdown("### Bu İşe Özel Otomasyon")
    st.caption(
        "Buradaki değişiklik yalnız bu MINA işini etkiler; ajans genel ayarını değiştirmez."
    )
    mode_options = ["inherit", "automatic", "approval_required", "manual"]
    mode_labels = {
        "inherit": "Üst politikadan devral", "automatic": "Otomatik",
        "approval_required": "Onay Gerekli", "manual": "Manuel",
    }
    supplier_current = overrides.get("supplier_reminder_mode") or "inherit"
    customer_current = overrides.get("customer_deadline_update_mode") or "inherit"
    m1, m2 = st.columns(2)
    supplier_mode = m1.selectbox(
        "Supplier reminder modu", mode_options,
        index=mode_options.index(supplier_current) if supplier_current in mode_options else 0,
        format_func=lambda value: mode_labels[value], key=f"supplier_mode_{job_id}",
    )
    customer_mode = m2.selectbox(
        "Müşteri deadline modu", mode_options,
        index=mode_options.index(customer_current) if customer_current in mode_options else 0,
        format_func=lambda value: mode_labels[value], key=f"customer_mode_{job_id}",
    )
    disable_supplier = st.checkbox(
        "Bu işte otomatik supplier reminder'larını kapat",
        value=bool(overrides.get("disable_supplier_reminders")),
        key=f"disable_supplier_{job_id}",
    )
    disable_customer = st.checkbox(
        "Bu işte otomatik müşteri deadline bilgilendirmesini kapat",
        value=bool(overrides.get("disable_customer_deadline_updates")),
        key=f"disable_customer_{job_id}",
    )

    if automation.get("supplier_reminders_effective") is False and not disable_supplier:
        st.caption("Supplier reminder genel politika nedeniyle zaten kapalı olabilir.")
    if st.button("İş Otomasyon Ayarını Kaydet", key=f"save_auto_{job_id}"):
        try:
            _post_json(
                api_base_url,
                f"/mina-jobs/{job_id}/automation-overrides",
                {
                    "disable_supplier_reminders": (
                        disable_supplier if supplier_mode == "inherit" else False
                    ),
                    "disable_customer_deadline_updates": (
                        disable_customer if customer_mode == "inherit" else False
                    ),
                    "supplier_reminder_mode": None if supplier_mode == "inherit" else supplier_mode,
                    "customer_deadline_update_mode": None if customer_mode == "inherit" else customer_mode,
                },
            )
            st.success("Bu işe özel otomasyon ayarı kaydedildi.")
            st.rerun()
        except (requests.RequestException, RuntimeError) as exc:
            st.error(str(exc))


def _render_stage_actions(
    api_base_url: str, job_id: str, detail: dict[str, Any]
) -> None:
    job = detail.get("job") or {}
    controls = detail.get("controls") or {}
    stage = str(job.get("stage") or "")
    allowed_next = set(controls.get("allowed_next_stages") or [])
    st.markdown("### Operasyon Aşaması")
    lifecycle_version = int(job.get("lifecycle_version") or 1)
    if lifecycle_version == 2:
        actions = V2_MANUAL_STAGE_ACTIONS.get(stage, [])
        if stage == "pricing" and job.get("job_kind") != "approved_job":
            actions = []
    else:
        actions = V1_MANUAL_STAGE_ACTIONS.get(stage, [])
    actions = [
        (target_stage, label)
        for target_stage, label in actions
        if target_stage in allowed_next
    ]
    if actions:
        for target_stage, label in actions:
            if st.button(label, key=f"stage_{job_id}_{target_stage}"):
                _transition_stage(api_base_url, job_id, target_stage)

    close_allowed = bool({"lost", "cancelled"} & allowed_next)
    if not job.get("is_closed") and close_allowed:
        st.markdown("#### İşi kapat")
        close_reason = st.text_input(
            "Kapatma nedeni",
            key=f"close_reason_{job_id}",
            help="Kaybedilen veya iptal edilen işte neden zorunludur.",
        )
        close_columns = st.columns(2)
        if "lost" in allowed_next:
            if close_columns[0].button("Teklif / İş Kaybedildi", key=f"lost_{job_id}"):
                _transition_stage(
                    api_base_url, job_id, "lost", reason=close_reason
                )
        if "cancelled" in allowed_next:
            if close_columns[1].button("İşi İptal Et", key=f"cancel_{job_id}"):
                _transition_stage(
                    api_base_url, job_id, "cancelled", reason=close_reason
                )


def _transition_stage(
    api_base_url: str,
    job_id: str,
    target_stage: str,
    reason: str | None = None,
) -> None:
    payload: dict[str, Any] = {"target_stage": target_stage}
    if reason and reason.strip():
        payload["reason"] = reason.strip()
    try:
        _post_json(api_base_url, f"/mina-jobs/{job_id}/stage", payload)
        st.success(f"İş aşaması güncellendi: {_stage_label(target_stage)}")
        st.rerun()
    except (requests.RequestException, RuntimeError) as exc:
        st.error(str(exc))
