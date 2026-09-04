from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any

import requests
import streamlit as st


def _error_detail(response: requests.Response) -> str:
    try:
        return str(response.json().get("detail") or response.text or response.status_code)
    except Exception:
        return response.text or f"HTTP {response.status_code}"


def _fetch_report(api_base_url: str, *, start_date: date | None, end_date: date | None) -> dict[str, Any]:
    params: dict[str, str] = {}
    if start_date is not None:
        params["start_date"] = start_date.isoformat()
    if end_date is not None:
        params["end_date"] = end_date.isoformat()
    response = requests.get(f"{api_base_url}/reports", params=params, timeout=30)
    if response.status_code >= 400:
        raise RuntimeError(_error_detail(response))
    return response.json()


def _pct(value: Any) -> str:
    return "-" if value is None else f"%{float(value):.1f}"


def _hours(value: Any) -> str:
    return "-" if value is None else f"{float(value):.1f} saat"


def _rows_without_money(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        item = {key: value for key, value in row.items() if key != "financial_by_currency"}
        currencies = sorted((row.get("financial_by_currency") or {}).keys())
        item["financial_currencies"] = ", ".join(currencies) if currencies else "-"
        result.append(item)
    return result


def _render_overview(report: dict[str, Any]) -> None:
    overview = report.get("overview") or {}
    st.subheader("Genel Bakış")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Toplam İş", overview.get("job_count", 0))
    c2.metric("Açık İş", overview.get("open_job_count", 0))
    c3.metric("Teklif → Kabul", _pct(overview.get("quote_to_accept_conversion_percent")))
    c4.metric("Tamamlanan", overview.get("completed_job_count", 0))
    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Teklif Hazırlama", _hours(overview.get("average_quote_turnaround_hours")))
    c6.metric("Operasyon Çevrim", _hours(overview.get("average_operation_cycle_hours")))
    c7.metric("Teklif SLA", _pct(overview.get("quote_deadline_sla_percent")))
    c8.metric("Zamanında Teslim", _pct(overview.get("on_time_delivery_percent")))
    if overview.get("open_exception_count"):
        st.warning(
            f"Açık istisna: {overview.get('open_exception_count')} · "
            f"Gerçek gecikme kaydı: {overview.get('actual_delay_count', 0)}"
        )


def _render_people(report: dict[str, Any], key: str, title: str) -> None:
    section = report.get(key) or {}
    st.subheader(title)
    if section.get("unassigned_job_count"):
        st.warning(f"Sorumlusu atanmamış iş: {section.get('unassigned_job_count')}")
    rows = section.get("rows") or []
    if rows:
        st.dataframe(_rows_without_money(rows), use_container_width=True, hide_index=True)
    else:
        st.info("Bu dönem için veri yok.")


def _render_group_table(report: dict[str, Any], key: str, title: str) -> None:
    st.subheader(title)
    rows = (report.get(key) or {}).get("rows") or []
    if rows:
        st.dataframe(_rows_without_money(rows), use_container_width=True, hide_index=True)
    else:
        st.info("Bu dönem için veri yok.")


def _render_suppliers(report: dict[str, Any]) -> None:
    st.subheader("Tedarikçiler")
    rows = (report.get("suppliers") or {}).get("rows") or []
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("Bu dönem için tedarikçi aktivitesi yok.")


def _render_financial(report: dict[str, Any]) -> None:
    section = report.get("financial") or {}
    st.subheader("Finansal")
    c1, c2, c3 = st.columns(3)
    c1.metric("Finansal Kapsam", _pct(section.get("financial_coverage_percent")))
    c2.metric("Kanıtlı İş", section.get("financially_covered_job_count", 0))
    c3.metric("Eksik Finansal Kanıt", section.get("uncovered_job_count", 0))
    rows = []
    for currency, values in sorted((section.get("by_currency") or {}).items()):
        rows.append({"currency": currency, **values})
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    st.caption(section.get("note") or "")


def _render_minai(report: dict[str, Any]) -> None:
    section = report.get("minai") or {}
    st.subheader("MINAI Performansı")
    status = section.get("learning_fact_status_counts") or {}
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Önerilen Öğrenim", status.get("proposed", 0))
    c2.metric("Onaylı Öğrenim", status.get("confirmed", 0))
    c3.metric("Reddedilen", status.get("rejected", 0))
    c4.metric("Inference Onay Oranı", _pct(section.get("minai_inference_confirmation_percent")))
    s1, s2, s3 = st.columns(3)
    s1.metric("Otomatik Supplier Gönderimi", section.get("supplier_automated_send_count", 0))
    s2.metric("Otomatik Müşteri Teklifi", section.get("customer_quote_automated_send_count", 0))
    s3.metric("Dış Gönderim Otomasyon Payı", _pct(section.get("tracked_external_send_automation_share_percent")))
    st.caption(
        f"Learning dönem temeli: {section.get('learning_period_basis', '-')} · "
        f"Otomasyon kanıt kapsamı: {section.get('tracked_send_scope', '-')}"
    )


def _render_exceptions(report: dict[str, Any]) -> None:
    section = report.get("exceptions") or {}
    st.subheader("İstisnalar & Gecikmeler")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Toplam", section.get("total_count", 0))
    c2.metric("Etkilenen İş", section.get("affected_job_count", 0))
    c3.metric("Açık", (section.get("status_counts") or {}).get("open", 0))
    c4.metric("Ort. Çözüm", _hours(section.get("average_resolution_hours")))
    impact = section.get("impact_counts") or {}
    st.write(
        f"**Sapma:** {impact.get('deviation', 0)} · "
        f"**Teslim Riski:** {impact.get('delivery_risk', 0)} · "
        f"**Gerçek Gecikme:** {impact.get('actual_delay', 0)}"
    )
    type_rows = [
        {"exception_type": key, "count": value}
        for key, value in (section.get("type_counts") or {}).items()
    ]
    if type_rows:
        st.dataframe(type_rows, use_container_width=True, hide_index=True)


def _render_quality(report: dict[str, Any]) -> None:
    section = report.get("data_quality") or {}
    st.subheader("Veri Kalitesi / KPI Coverage")
    rows = [{"metric": key, "value": value} for key, value in section.items()]
    st.dataframe(rows, use_container_width=True, hide_index=True)
    if section.get("financially_uncovered_job_count"):
        st.warning("Finansal kanıtı eksik işler toplam kârlılık hesabında sıfır kabul edilmez; kapsam dışında gösterilir.")


def render_reporting(api_base_url: str) -> None:
    st.header("Raporlar")
    st.caption("KPI'lar durable MINA, teklif, tedarikçi, operasyon, istisna ve learning kanıtlarından okunur.")

    all_period = st.checkbox("Tüm dönem", value=True, key="report_all_period")
    start_date = end_date = None
    if not all_period:
        today = datetime.now(ZoneInfo("Europe/Istanbul")).date()
        cols = st.columns(2)
        start_date = cols[0].date_input("Başlangıç", value=today - timedelta(days=30), key="report_start")
        end_date = cols[1].date_input("Bitiş", value=today, key="report_end")
    try:
        report = _fetch_report(api_base_url, start_date=start_date, end_date=end_date)
    except (requests.RequestException, RuntimeError) as exc:
        st.error("Rapor verisi alınamadı.")
        st.caption(str(exc))
        return

    period = report.get("period") or {}
    st.caption(
        f"Dönem temeli: {period.get('basis', '-')} · İş sayısı: {period.get('job_count', 0)} · "
        f"Saat dilimi: {period.get('timezone', '-')}"
    )

    tabs = st.tabs([
        "Genel", "Satış", "Operasyon", "Müşteriler", "Tedarikçiler",
        "Rotalar", "Finansal", "MINAI", "İstisnalar", "Veri Kalitesi",
    ])
    with tabs[0]:
        _render_overview(report)
    with tabs[1]:
        _render_people(report, "sales", "Satış Personeli")
    with tabs[2]:
        _render_people(report, "operations", "Operasyon Personeli")
    with tabs[3]:
        _render_group_table(report, "customers", "Müşteriler")
    with tabs[4]:
        _render_suppliers(report)
    with tabs[5]:
        _render_group_table(report, "routes", "Rotalar & Ülkeler")
    with tabs[6]:
        _render_financial(report)
    with tabs[7]:
        _render_minai(report)
    with tabs[8]:
        _render_exceptions(report)
    with tabs[9]:
        _render_quality(report)
