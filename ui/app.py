import sys
from pathlib import Path
from datetime import datetime

import requests
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

from src.simulation.ai_email_test_cases import AI_EMAIL_TEST_CASES
from src.core.data_health_labels import get_data_health_check_label
from ui.mina_operations import render_mina_operations


API_BASE_URL = "http://127.0.0.1:8000"


st.set_page_config(
    page_title="MINAI Freight OS",
    page_icon="🚛",
    layout="wide",
)


def get_example_email_options() -> dict:
    examples = {
        test_case["name"]: test_case["email"].strip()
        for test_case in AI_EMAIL_TEST_CASES
    }

    examples["Custom Email"] = ""

    return examples


def get_action_text(result_type: str) -> str:
    if result_type == "extraction_confirmation_required":
        return "AI çıkarımı operasyonel işleme alınmadan önce insan teyidi bekliyor."
    if result_type == "quote_ready":
        return "Teklif taslağı hazır ve gönderim öncesi son kontrol yapılabilir."
    if result_type == "quote_with_review":
        return "Teklif taslağı hazırlandı ancak operasyon kontrolü gerekli."
    if result_type == "clarification":
        return "Eksik bilgi var. Müşteriden bilgi istenmeli."
    if result_type == "management_review":
        return "RED risk var. Yönetici / senior operasyon onayı gerekli."
    if result_type == "blocked":
        return "Operasyonel tutarsızlık nedeniyle teklif akışı durduruldu."
    return "Sonuç tipi belirlenemedi."


def get_result_label(result_type: str) -> str:
    if result_type == "extraction_confirmation_required":
        return "Çıkarım Teyidi Gerekli"
    if result_type == "quote_ready":
        return "Teklif Hazır"
    if result_type == "quote_with_review":
        return "Teklif Hazır — Operasyon Kontrolü Gerekli"
    if result_type == "clarification":
        return "Eksik Bilgi Gerekli"
    if result_type == "management_review":
        return "Yönetici Onayı Gerekli"
    if result_type == "blocked":
        return "Operasyonel Tutarsızlık — Akış Durduruldu"
    return "Bilinmeyen Sonuç"


def build_route_text(shipment: dict) -> str:
    pickup_parts = [
        shipment.get("pickup_area"),
        shipment.get("pickup_city"),
        shipment.get("pickup_country"),
    ]
    delivery_parts = [
        shipment.get("delivery_city"),
        shipment.get("delivery_country"),
    ]

    pickup = ", ".join(part for part in pickup_parts if part)
    delivery = ", ".join(part for part in delivery_parts if part)

    if pickup and delivery:
        return f"{pickup} → {delivery}"

    return "Güzergah net değil"



def translate_missing_field_for_ui(field: str) -> str:
    mapping = {
        "pickup location": "Yükleme adresi / yükleme bölgesi",
        "delivery location": "Teslimat adresi / teslimat bölgesi",
        "commodity": "Ürün cinsi",
        "cargo ready date": "Yük hazır tarihi",
        "machine dimensions": "Makine ölçüleri (en / boy / yükseklik)",
        "msds/sds document": "MSDS/SDS belgesi",
        "adr status": "Yükün ADR kapsamında olup olmadığı",
        "chemical packaging type": "Kimyasal ürünün ambalaj tipi ve ambalaj uygunluğu",
        "frozen temperature requirement": "Dondurulmuş ürün için gerekli sıcaklık derecesi",
        "reefer confirmation": "Reefer araç gereksiniminin teyidi",
        "cold chain sensitivity": "Ürünün soğuk zincir hassasiyeti",
        "pharma temperature requirement": "İlaç / pharma yükü için sıcaklık gereksinimi",
        "pharma compliance document": "İlaç / pharma uygunluk veya ruhsat belgeleri",
        "pharma special transport requirements": "İlaç / pharma özel taşıma şartları",
        "medical product type": "Medikal ürün tipi ve kullanım amacı",
        "medical compliance document": "Medikal ürün uygunluk / belge gereklilikleri",
        "medical temperature sensitivity": "Medikal ürünün sıcaklık hassasiyeti olup olmadığı",
        "fragile packaging type": "Kırılabilir ürün ambalaj tipi",
        "fragile stackability": "Ürünün istiflenebilir olup olmadığı",
        "fragile lashing requirement": "Sabitleme / lashing gerekip gerekmediği",
        "electronic cargo value": "Elektronik ürün yaklaşık değeri",
        "electronic packaging sensitivity": "Elektronik ürün ambalajı ve darbe hassasiyeti",
        "secure transport requirement": "Güvenli taşıma / kapalı kasa ihtiyacı",
    }

    return mapping.get(field, field)


def render_commodity_profile(commodity_profile: dict):
    if not commodity_profile:
        return

    commodity = commodity_profile.get("canonical_commodity") or "-"
    profile = commodity_profile.get("operational_profile") or {}
    notes = commodity_profile.get("notes") or []
    operational_notes = profile.get("operational_notes") or []
    missing_info_fields = profile.get("missing_info_fields") or []
    critical_missing_fields = profile.get("critical_missing_info_fields") or []
    action_checklist = profile.get("action_checklist") or []

    st.markdown("### Commodity Profile / Operasyonel Profil")
    st.info(f"Ürün profili: {commodity}")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric(
            "Human Review",
            "Evet" if profile.get("requires_human_review") else "Hayır",
        )

    with col2:
        st.metric(
            "Reefer",
            "Evet" if profile.get("requires_reefer") else "Hayır",
        )

    with col3:
        st.metric(
            "High Value",
            "Evet" if profile.get("high_value_candidate") else "Hayır",
        )

    if profile.get("default_equipment") or profile.get("default_temperature_requirement"):
        st.markdown("**Profil Varsayılanları:**")
        if profile.get("default_equipment"):
            st.write(f"- Varsayılan ekipman: {profile.get('default_equipment')}")
        if profile.get("default_temperature_requirement"):
            st.write(f"- Varsayılan sıcaklık: {profile.get('default_temperature_requirement')}")

    if profile.get("risk_reason"):
        st.markdown("**Risk Profili:**")
        st.warning(profile.get("risk_reason"))

    if notes or operational_notes:
        st.markdown("**Operasyon Notları:**")
        for note in notes:
            st.write(f"- {note}")
        for note in operational_notes:
            st.write(f"- {note}")

    if missing_info_fields:
        st.markdown("**Profile Kaynaklı Eksik Bilgiler:**")
        for field in missing_info_fields:
            label = translate_missing_field_for_ui(field)
            if field in critical_missing_fields:
                st.write(f"- 🔴 {label}")
            else:
                st.write(f"- 🟡 {label}")

    if action_checklist:
        st.markdown("**Profile Action Checklist:**")
        for item in action_checklist:
            st.write(f"- {item}")


def render_customer_memory(customer_memory: dict):
    if not customer_memory:
        return

    if not customer_memory.get("matched"):
        return

    profile = customer_memory.get("profile") or {}
    notes = customer_memory.get("notes_applied") or []

    st.markdown("### Customer Memory")

    st.success(f"Customer Memory Match: {profile.get('customer_name', '-')}")
    st.write(f"**Source:** {customer_memory.get('source') or '-'}")
    st.write(f"**Matched By:** {customer_memory.get('matched_by') or '-'}")

    col1, col2 = st.columns(2)

    with col1:
        st.write(f"**Default Commodity:** {profile.get('default_commodity') or '-'}")
        st.write(f"**Default Equipment:** {profile.get('default_equipment_type') or '-'}")

    with col2:
        st.write(f"**Price Sensitivity:** {profile.get('price_sensitivity') or '-'}")
        st.write(f"**Time Sensitivity:** {profile.get('time_sensitivity') or '-'}")

    if notes:
        st.markdown("**Operational Notes:**")
        for note in notes:
            st.write(f"- {note}")


def render_action_recommendation(action: dict):
    if not action:
        return

    st.markdown("## Önerilen Aksiyon")

    priority = action.get("priority") or "normal"
    action_type = action.get("action_type") or "-"
    title = action.get("title") or "Aksiyon"
    message = action.get("message") or ""

    if priority == "high":
        st.error(title)
    elif priority == "medium":
        st.warning(title)
    else:
        st.success(title)

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Priority", priority.upper())

    with col2:
        st.metric("Action Type", action_type)

    with col3:
        st.metric("Source", action.get("source") or "-")

    st.write(message)

    checklist = action.get("checklist") or []
    if checklist:
        st.markdown("### Operasyon Kontrol Listesi")
        st.caption(
            "Bu liste genel operasyon kontrollerini ve varsa ürün tipine özel commodity profile kontrollerini birlikte gösterir."
        )

        st.metric("Checklist Maddesi", len(checklist))

        for index, item in enumerate(checklist, start=1):
            st.checkbox(
                item,
                value=False,
                key=f"action_check_{action_type}_{index}",
            )


def render_summary(result: dict):
    shipment = result.get("shipment") or {}
    equipment = result.get("equipment_decision") or {}
    risk = result.get("risk_assessment") or {}
    missing = result.get("missing_info") or {}
    customer_memory = result.get("customer_memory") or {}
    commodity_profile = result.get("commodity_profile") or {}
    operational_consistency = result.get("operational_consistency") or {}
    quote_readiness = result.get("quote_readiness") or {}
    action_recommendation = result.get("action_recommendation") or {}

    result_type = result.get("result_type")
    result_label = get_result_label(result_type)
    action_text = get_action_text(result_type)

    st.markdown("## Operasyon Özeti")

    if result_type == "quote_ready":
        st.success(result_label)
    elif result_type in {"quote_with_review", "clarification"}:
        st.warning(result_label)
    elif result_type in {"management_review", "blocked"}:
        st.error(result_label)
    else:
        st.info(result_label)

    if quote_readiness:
        st.markdown("### Quote Readiness")

        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric(
                "Durum",
                quote_readiness.get("result_type") or "-",
            )

        with col2:
            st.metric(
                "Teklif Üretilebilir",
                "Evet" if quote_readiness.get("can_generate_quote") else "Hayır",
            )

        with col3:
            st.metric(
                "Human Review",
                "Evet"
                if quote_readiness.get("requires_human_review")
                else "Hayır",
            )

        readiness_reasons = quote_readiness.get("reasons") or []
        if readiness_reasons:
            st.markdown("**Karar Nedenleri:**")
            for reason in readiness_reasons:
                st.write(f"- {reason}")

    consistency_errors = operational_consistency.get("errors") or []
    consistency_warnings = operational_consistency.get("warnings") or []

    if consistency_errors or consistency_warnings:
        st.markdown("### Operational Consistency")

        for error in consistency_errors:
            st.error(error)

        for warning in consistency_warnings:
            st.warning(warning)

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Risk", (risk.get("risk_level") or "-").upper())

    with col2:
        st.metric("Servis", shipment.get("service_type") or "-")

    with col3:
        st.metric("Araç", equipment.get("selected_equipment") or "-")

    if equipment.get("explanation"):
        st.markdown("### Ekipman Karar Açıklaması")
        st.info(equipment.get("explanation"))

    if equipment.get("source"):
        st.write(f"**Ekipman Karar Kaynağı:** {equipment.get('source')}")

    st.markdown("### Temel Bilgiler")

    summary_rows = {
        "Müşteri": shipment.get("customer_name") or "-",
        "Güzergah": build_route_text(shipment),
        "Yük": shipment.get("commodity") or "-",
        "Ağırlık": f"{shipment.get('gross_weight_kg')} kg" if shipment.get("gross_weight_kg") else "-",
        "Yük Hazır Tarihi": shipment.get("cargo_ready_date") or "-",
        "Aksiyon": action_text,
    }

    for label, value in summary_rows.items():
        st.write(f"**{label}:** {value}")

    risk_reasons = risk.get("risk_reasons") or []
    if risk_reasons:
        st.markdown("### Risk Nedenleri")
        st.caption("Bu maddeler risk engine ve commodity profile tarafından üretilen operasyonel uyarılardır.")

        for reason in risk_reasons:
            st.write(f"- {reason}")

    missing_fields = missing.get("missing_fields") or []
    if missing_fields:
        st.markdown("### Eksik Bilgiler")

        missing_reason = missing.get("reason")
        if missing_reason:
            st.warning(missing_reason)

        for field in missing_fields:
            st.write(f"- {translate_missing_field_for_ui(field)}")

    render_commodity_profile(commodity_profile)
    render_customer_memory(customer_memory)
    render_action_recommendation(action_recommendation)


def render_draft(result: dict):
    result_type = result.get("result_type")

    if result_type == "extraction_confirmation_required":
        proposal = result.get("extraction_proposal") or {}
        st.markdown("## AI Çıkarım Önerisi")
        st.warning(
            "Bu bilgiler henüz operasyonel yetkiye sahip değildir. "
            "Teyit/düzeltme backend API yaşam döngüsü üzerinden yapılmalıdır."
        )
        st.json(proposal)
        return

    if result_type in {"quote_ready", "quote_with_review"}:
        title = "Teklif Mail Taslağı"
        supplier_selection = result.get("supplier_selection")
        if supplier_selection:
            st.subheader("Supplier Selection")

            selected_suppliers = supplier_selection.get("selected_suppliers", [])

            if selected_suppliers:
                for supplier in selected_suppliers:
                    priority = supplier.get("priority", "-")
                    name = supplier.get("supplier_name", "Unknown Supplier")
                    total_score = supplier.get("total_score", "-")
                    reason = supplier.get("reason", "")

                    with st.expander(f"{priority}. {name} — Score: {total_score}"):
                        st.write(reason)
                        st.json({
                            "route_score": supplier.get("route_score"),
                            "equipment_score": supplier.get("equipment_score"),
                            "risk_score": supplier.get("risk_score"),
                            "price_score": supplier.get("price_score"),
                            "speed_score": supplier.get("speed_score"),
                        })
            else:
                st.info("Uygun supplier bulunamadı.")

        supplier_rfq_drafts = result.get("supplier_rfq_drafts") or []

        if supplier_rfq_drafts:
            st.markdown("## Supplier RFQ Taslakları")
            st.caption(
                "Bu taslaklar seçilen en fazla 3 tedarikçi için hazırlanmıştır. "
                "Henüz gönderilmemiştir."
            )

            for rfq in supplier_rfq_drafts:
                supplier_name = rfq.get("supplier_name") or "Tedarikçi"
                priority = rfq.get("priority") or "-"
                subject = rfq.get("subject") or ""
                body = rfq.get("body") or ""

                with st.expander(
                    f"{priority}. {supplier_name} — RFQ Taslağı"
                ):
                    st.write(f"**Subject:** {subject}")
                    st.text_area(
                        f"RFQ Metni — {supplier_name}",
                        value=body,
                        height=280,
                        key=f"supplier_rfq_{priority}_{supplier_name}",
                    )

        draft = result.get("quote_draft")

    elif result_type == "clarification":
        title = "Eksik Bilgi Mail Taslağı"
        draft = result.get("clarification_draft")

    elif result_type == "management_review":
        title = "Yönetici İnceleme Taslağı"
        draft = result.get("management_review_draft")

    else:
        title = "Taslak"
        draft = None

    if not draft:
        st.warning("Taslak üretilemedi.")
        return

    st.markdown(f"## {title}")
    st.write(f"**Subject:** {draft.get('subject')}")

    st.text_area(
        "Mail / İnceleme Metni",
        value=draft.get("body", ""),
        height=320,
    )


def render_debug(result: dict):
    with st.expander("Teknik JSON Detayları"):
        st.json(result)


def render_test_suite_runner_content():
    st.markdown("### Test Suite")

    st.write(
        "MINAI'nin temel senaryolarda doğru çalışıp çalışmadığını kontrol eder."
    )

    if st.button("Run Test Suite"):
        with st.spinner("Test suite çalışıyor..."):
            try:
                response = requests.get(
                    f"{API_BASE_URL}/run-test-suite",
                    timeout=120,
                )

                response.raise_for_status()
                report = response.json()

                summary = report.get("summary", {})
                results = report.get("results", [])

                passed = summary.get("passed", 0)
                failed = summary.get("failed", 0)
                total = summary.get("total", 0)

                if failed == 0:
                    st.success(f"Test sonucu: {passed}/{total} passed, {failed} failed")
                else:
                    st.error(f"Test sonucu: {passed}/{total} passed, {failed} failed")

                for index, test_result in enumerate(results, start=1):
                    status = "PASS" if test_result.get("passed") else "FAIL"
                    name = test_result.get("name")

                    if test_result.get("passed"):
                        st.write(f"✅ AI TEST {index}: {status} - {name}")
                    else:
                        st.write(f"❌ AI TEST {index}: {status} - {name}")

                        failures = test_result.get("failures") or []
                        for failure in failures:
                            st.write(f"   - {failure}")

            except requests.exceptions.RequestException as error:
                st.error("Test suite API çağrısı başarısız oldu.")
                st.code(str(error))


def render_commodity_dictionary_validation_content():
    st.markdown("### Commodity Dictionary")

    st.caption(
        "Commodity dictionary validation sonucu. Bu panel sadece okuma amaçlıdır; dictionary edit etmez."
    )

    if not st.button("Commodity Dictionary Kontrol Et"):
        return

    with st.spinner("Commodity dictionary kontrol ediliyor..."):
        try:
            response = requests.get(
                f"{API_BASE_URL}/commodity-dictionary/validation",
                timeout=30,
            )
            response.raise_for_status()
            result = response.json()

        except requests.exceptions.RequestException as error:
            st.error("Commodity dictionary validation API çağrısı başarısız oldu.")
            st.code(str(error))
            return

    valid = result.get("valid") is True
    errors = result.get("errors") or []
    warnings = result.get("warnings") or []

    if valid:
        st.success("Commodity dictionary geçerli.")
    else:
        st.error("Commodity dictionary hatalı.")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Valid", "Evet" if valid else "Hayır")

    with col2:
        st.metric("Commodity", result.get("commodity_count", 0))

    with col3:
        st.metric("Keyword", result.get("unique_keyword_count", 0))

    with col4:
        st.metric("Hata / Uyarı", f"{len(errors)} / {len(warnings)}")

    st.write(f"**Source:** {result.get('source') or '-'}")

    if errors:
        st.markdown("### Hatalar")
        for error in errors:
            st.error(error)

    if warnings:
        st.markdown("### Uyarılar")
        for warning in warnings:
            st.warning(warning)

    with st.expander("Raw Validation Result", expanded=False):
        st.json(result)


def render_supplier_capabilities_validation_content():
    st.markdown("### Supplier Capability Matrix")

    st.caption(
        "Supplier capability matrix validation sonucu. Bu panel sadece okuma amaçlıdır; supplier datasını edit etmez."
    )

    if not st.button("Supplier Capability Matrix Kontrol Et"):
        return

    with st.spinner("Supplier capability matrix kontrol ediliyor..."):
        try:
            response = requests.get(
                f"{API_BASE_URL}/supplier-capabilities/validation",
                timeout=30,
            )
            response.raise_for_status()
            result = response.json()

        except requests.exceptions.RequestException as error:
            st.error("Supplier capability validation API çağrısı başarısız oldu.")
            st.code(str(error))
            return

    valid = result.get("valid") is True
    errors = result.get("errors") or []
    warnings = result.get("warnings") or []

    if valid:
        st.success("Supplier capability matrix geçerli.")
    else:
        st.error("Supplier capability matrix hatalı.")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Valid", "Evet" if valid else "Hayır")

    with col2:
        st.metric("Supplier", result.get("supplier_count", 0))

    with col3:
        st.metric("Active Supplier", result.get("active_supplier_count", 0))

    with col4:
        st.metric("Hata / Uyarı", f"{len(errors)} / {len(warnings)}")

    coverage_col1, coverage_col2, coverage_col3, coverage_col4 = st.columns(4)

    with coverage_col1:
        st.metric("Active FTL", result.get("active_ftl_count", 0))

    with coverage_col2:
        st.metric("Active LTL", result.get("active_ltl_count", 0))

    with coverage_col3:
        st.metric("Active Reefer", result.get("active_reefer_count", 0))

    with coverage_col4:
        st.metric("Active ADR", result.get("active_adr_count", 0))

    st.write(f"**Source:** {result.get('source') or '-'}")

    if errors:
        st.markdown("### Hatalar")
        for error in errors:
            st.error(error)

    if warnings:
        st.markdown("### Uyarılar")
        for warning in warnings:
            st.warning(warning)

    with st.expander("Raw Supplier Validation Result", expanded=False):
        st.json(result)



def render_customer_memory_validation_content():
    st.markdown("### Customer Memory")

    st.caption(
        "Customer memory validation sonucu. Bu panel sadece okuma amaçlıdır; müşteri hafızasını edit etmez."
    )

    if not st.button("Customer Memory Kontrol Et"):
        return

    with st.spinner("Customer memory kontrol ediliyor..."):
        try:
            response = requests.get(
                f"{API_BASE_URL}/customer-memory/validation",
                timeout=30,
            )
            response.raise_for_status()
            result = response.json()

        except requests.exceptions.RequestException as error:
            st.error("Customer memory validation API çağrısı başarısız oldu.")
            st.code(str(error))
            return

    valid = result.get("valid") is True
    errors = result.get("errors") or []
    warnings = result.get("warnings") or []

    if valid:
        st.success("Customer memory geçerli.")
    else:
        st.error("Customer memory hatalı.")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Valid", "Evet" if valid else "Hayır")

    with col2:
        st.metric("Profile", result.get("profile_count", 0))

    with col3:
        st.metric("Active Profile", result.get("active_profile_count", 0))

    with col4:
        st.metric("Hata / Uyarı", f"{len(errors)} / {len(warnings)}")

    alias_col1, alias_col2 = st.columns(2)

    with alias_col1:
        st.metric("Alias", result.get("alias_count", 0))

    with alias_col2:
        st.write(f"**Source:** {result.get('source') or '-'}")

    if errors:
        st.markdown("### Hatalar")
        for error in errors:
            st.error(error)

    if warnings:
        st.markdown("### Uyarılar")
        for warning in warnings:
            st.warning(warning)

    with st.expander("Raw Customer Memory Validation Result", expanded=False):
        st.json(result)


def render_hs_commodity_map_validation_content():
    st.markdown("### HS / GTIP Mapping")

    st.caption(
        "HS / GTIP commodity mapping validation sonucu. Bu panel sadece okuma amaçlıdır; mapping datasını edit etmez."
    )

    if not st.button("HS / GTIP Mapping Kontrol Et"):
        return

    with st.spinner("HS / GTIP mapping kontrol ediliyor..."):
        try:
            response = requests.get(
                f"{API_BASE_URL}/hs-commodity-map/validation",
                timeout=30,
            )
            response.raise_for_status()
            result = response.json()

        except requests.exceptions.RequestException as error:
            st.error("HS / GTIP mapping validation API çağrısı başarısız oldu.")
            st.code(str(error))
            return

    valid = result.get("valid") is True
    errors = result.get("errors") or []
    warnings = result.get("warnings") or []

    if valid:
        st.success("HS / GTIP mapping geçerli.")
    else:
        st.error("HS / GTIP mapping hatalı.")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Valid", "Evet" if valid else "Hayır")

    with col2:
        st.metric("Mapping", result.get("mapping_count", 0))

    with col3:
        st.metric("Canonical Commodity", result.get("canonical_commodity_count", 0))

    with col4:
        st.metric("Hata / Uyarı", f"{len(errors)} / {len(warnings)}")

    hs_col1, hs_col2, hs_col3 = st.columns(3)

    with hs_col1:
        st.metric("Chapter", result.get("chapter_count", 0))

    with hs_col2:
        st.metric("Heading", result.get("heading_count", 0))

    with hs_col3:
        st.metric("Subheading", result.get("subheading_count", 0))

    st.write(f"**Source:** {result.get('source') or '-'}")

    if errors:
        st.markdown("### Hatalar")
        for error in errors:
            st.error(error)

    if warnings:
        st.markdown("### Uyarılar")
        for warning in warnings:
            st.warning(warning)

    with st.expander("Raw HS / GTIP Validation Result", expanded=False):
        st.json(result)


def fetch_data_health_summary() -> dict:
    response = requests.get(
        f"{API_BASE_URL}/data-health/summary",
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def render_data_health_summary():
    st.markdown("### Genel Data Sağlığı Özeti")

    col_refresh, col_checked = st.columns([1, 3])

    with col_refresh:
        refresh_requested = st.button("Özeti Yenile")

    should_fetch = (
        refresh_requested
        or "data_health_summary" not in st.session_state
    )

    if should_fetch:
        with st.spinner("Data health özeti alınıyor..."):
            try:
                summary = fetch_data_health_summary()
                st.session_state["data_health_summary"] = summary
                st.session_state["data_health_summary_checked_at"] = datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

            except requests.exceptions.RequestException as error:
                st.error("Data health summary API çağrısı başarısız oldu.")
                st.code(str(error))
                return
    else:
        summary = st.session_state.get("data_health_summary") or {}

    checked_at = st.session_state.get("data_health_summary_checked_at")

    with col_checked:
        if checked_at:
            st.caption(f"Son kontrol: {checked_at}")
        else:
            st.caption("Son kontrol: henüz kontrol edilmedi.")

    overall_valid = summary.get("overall_valid") is True
    total_checks = summary.get("total_checks", 0)
    valid_checks = summary.get("valid_checks", 0)
    invalid_checks = summary.get("invalid_checks", 0)
    total_errors = summary.get("total_errors", 0)
    total_warnings = summary.get("total_warnings", 0)

    if overall_valid:
        st.success("Genel data sağlığı geçerli.")
    else:
        st.error("Genel data sağlığında hata var.")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Genel Durum", "Geçerli" if overall_valid else "Hatalı")

    with col2:
        st.metric("Geçen Kontrol", f"{valid_checks}/{total_checks}")

    with col3:
        st.metric("Hata", total_errors)

    with col4:
        st.metric("Uyarı", total_warnings)

    if invalid_checks:
        st.warning(f"{invalid_checks} data health kontrolü başarısız.")

    checks = summary.get("checks") or {}

    if checks:
        st.markdown("### Kontrol Özeti")

        for check_name, result in checks.items():
            valid = result.get("valid") is True
            errors = result.get("errors") or []
            warnings = result.get("warnings") or []

            status_icon = "✅" if valid else "❌"
            readable_name = result.get("label") or get_data_health_check_label(check_name)

            st.write(
                f"{status_icon} **{readable_name}** — "
                f"hata: {len(errors)}, uyarı: {len(warnings)}"
            )

    issue_checks = {
        check_name: result
        for check_name, result in checks.items()
        if (result.get("errors") or result.get("warnings"))
    }

    if issue_checks:
        st.markdown("### Data Sağlığı Uyarı / Hata Detayları")
        st.caption(
            "Özet içindeki hata ve uyarı detayları. Detay sekmelerine girmeden hızlı kontrol için gösterilir."
        )

        for check_name, result in issue_checks.items():
            readable_name = result.get("label") or get_data_health_check_label(check_name)
            errors = result.get("errors") or []
            warnings = result.get("warnings") or []

            with st.expander(
                f"{readable_name} — hata: {len(errors)}, uyarı: {len(warnings)}",
                expanded=False,
            ):
                if errors:
                    st.error("Hatalar")
                    for error in errors:
                        st.markdown(f"- ❌ {error}")

                if warnings:
                    st.warning("Uyarılar")
                    for warning in warnings:
                        st.markdown(f"- ⚠️ {warning}")

    elif checks:
        st.info("Data sağlığı özetinde hata veya uyarı bulunmuyor.")

    with st.expander("Ham Data Sağlığı Özeti", expanded=False):
        st.json(summary)

def render_data_health_dashboard():
    st.markdown("---")
    st.markdown("## Data Sağlığı Dashboard")

    st.caption(
        "Test suite ve kritik operasyonel data kaynaklarının sağlığını tek yerden kontrol eder. Bu bölüm read-only'dir."
    )

    render_data_health_summary()

    test_tab, commodity_tab, supplier_tab, customer_memory_tab, hs_tab = st.tabs(
        [
            "Test Suite",
            "Commodity Dictionary",
            "Supplier Capability Matrix",
            "Customer Memory",
            "HS / GTIP Mapping",
        ]
    )

    with test_tab:
        render_test_suite_runner_content()

    with commodity_tab:
        render_commodity_dictionary_validation_content()

    with supplier_tab:
        render_supplier_capabilities_validation_content()

    with customer_memory_tab:
        render_customer_memory_validation_content()

    with hs_tab:
        render_hs_commodity_map_validation_content()

def render_customer_memory_edit_form(profile: dict):
    customer_name = profile.get("customer_name") or ""
    active = profile.get("active", True)

    with st.expander(f"Edit {customer_name}"):
        edited_customer_name = st.text_input(
            "Edit Customer Name",
            value=customer_name,
            key=f"edit_customer_name_{customer_name}",
        )

        edited_active = st.checkbox(
            "Edit Active",
            value=active,
            key=f"edit_active_{customer_name}",
        )

        aliases_text = "\n".join(profile.get("aliases") or [])
        edited_aliases_text = st.text_area(
            "Edit Aliases",
            value=aliases_text,
            height=100,
            key=f"edit_aliases_{customer_name}",
        )

        edited_default_commodity = st.text_input(
            "Edit Default Commodity",
            value=profile.get("default_commodity") or "",
            key=f"edit_default_commodity_{customer_name}",
        )

        edited_default_equipment_type = st.text_input(
            "Edit Default Equipment Type",
            value=profile.get("default_equipment_type") or "",
            key=f"edit_default_equipment_type_{customer_name}",
        )

        col1, col2 = st.columns(2)

        price_options = ["", "low", "medium", "high"]
        time_options = ["", "low", "medium", "high"]

        current_price = profile.get("price_sensitivity") or ""
        current_time = profile.get("time_sensitivity") or ""

        with col1:
            edited_price_sensitivity = st.selectbox(
                "Edit Price Sensitivity",
                options=price_options,
                index=price_options.index(current_price) if current_price in price_options else 0,
                key=f"edit_price_sensitivity_{customer_name}",
            )

        with col2:
            edited_time_sensitivity = st.selectbox(
                "Edit Time Sensitivity",
                options=time_options,
                index=time_options.index(current_time) if current_time in time_options else 0,
                key=f"edit_time_sensitivity_{customer_name}",
            )

        st.markdown("### Edit Default Pickup")

        pickup_col1, pickup_col2, pickup_col3 = st.columns(3)

        with pickup_col1:
            edited_default_pickup_city = st.text_input(
                "Edit Default Pickup City",
                value=profile.get("default_pickup_city") or "",
                key=f"edit_pickup_city_{customer_name}",
            )

        with pickup_col2:
            edited_default_pickup_area = st.text_input(
                "Edit Default Pickup Area",
                value=profile.get("default_pickup_area") or "",
                key=f"edit_pickup_area_{customer_name}",
            )

        with pickup_col3:
            edited_default_pickup_country = st.text_input(
                "Edit Default Pickup Country",
                value=profile.get("default_pickup_country") or "",
                key=f"edit_pickup_country_{customer_name}",
            )

        st.markdown("### Edit Default Delivery")

        delivery_col1, delivery_col2 = st.columns(2)

        with delivery_col1:
            edited_default_delivery_city = st.text_input(
                "Edit Default Delivery City",
                value=profile.get("default_delivery_city") or "",
                key=f"edit_delivery_city_{customer_name}",
            )

        with delivery_col2:
            edited_default_delivery_country = st.text_input(
                "Edit Default Delivery Country",
                value=profile.get("default_delivery_country") or "",
                key=f"edit_delivery_country_{customer_name}",
            )

        notes_text = "\n".join(profile.get("operational_notes") or [])
        edited_notes_text = st.text_area(
            "Edit Operational Notes",
            value=notes_text,
            height=120,
            key=f"edit_notes_{customer_name}",
        )
        edited_change_note = st.text_input(
            "Edit Change Note",
            value="Customer profile updated from UI.",
            key=f"edit_change_note_{customer_name}",
        )

        if st.button("Update Customer Profile", key=f"update_customer_{customer_name}"):
            if not edited_customer_name.strip():
                st.warning("Customer Name zorunludur.")
                return

            aliases = [
                line.strip()
                for line in edited_aliases_text.splitlines()
                if line.strip()
            ]

            operational_notes = [
                line.strip()
                for line in edited_notes_text.splitlines()
                if line.strip()
            ]

            payload = {
                "original_customer_name": customer_name,
                "customer_name": edited_customer_name.strip(),
                "active": edited_active,
                "aliases": aliases,
                "default_commodity": edited_default_commodity.strip() or None,
                "default_equipment_type": edited_default_equipment_type.strip() or None,
                "price_sensitivity": edited_price_sensitivity or None,
                "time_sensitivity": edited_time_sensitivity or None,
                "default_pickup_city": edited_default_pickup_city.strip() or None,
                "default_pickup_area": edited_default_pickup_area.strip() or None,
                "default_pickup_country": edited_default_pickup_country.strip() or None,
                "default_delivery_city": edited_default_delivery_city.strip() or None,
                "default_delivery_country": edited_default_delivery_country.strip() or None,
                "last_updated_by": "ui",
                "change_note": edited_change_note.strip() or "Customer profile updated from UI.",
                "operational_notes": operational_notes,
            }

            try:
                response = requests.put(
                    f"{API_BASE_URL}/customer-memory",
                    json=payload,
                    timeout=30,
                )

                response.raise_for_status()
                result = response.json()

                st.success(
                    f"Müşteri profili güncellendi: {result['profile']['customer_name']}"
                )
                st.rerun()

            except requests.exceptions.HTTPError as error:
                st.error("Customer memory güncellemesi reddedildi.")

                try:
                    error_detail = error.response.json().get("detail")
                    st.warning(error_detail)
                except Exception:
                    st.code(str(error))

            except requests.exceptions.RequestException as error:
                st.error("Customer memory güncellemesi başarısız oldu.")
                st.code(str(error))

def render_customer_memory_export():
    st.markdown("---")
    st.markdown("## Customer Memory Export")

    st.write(
        "Customer memory verisini JSON formatında dışa aktarın."
    )

    if st.button("Export Customer Memory"):
        try:
            response = requests.get(
                f"{API_BASE_URL}/customer-memory/export",
                timeout=30,
            )

            response.raise_for_status()
            export_data = response.json()

            profile_count = export_data.get("profile_count", 0)

            st.success(f"Customer memory export hazır. Profil sayısı: {profile_count}")

            st.download_button(
                label="Download customer_memory_export.json",
                data=response.text,
                file_name="customer_memory_export.json",
                mime="application/json",
            )

            with st.expander("Export JSON Preview"):
                st.json(export_data)

        except requests.exceptions.RequestException as error:
            st.error("Customer memory export başarısız oldu.")
            st.code(str(error))

def render_customer_memory_import_preview():
    st.markdown("---")
    st.markdown("## Customer Memory Import Preview")

    st.write(
        "Export edilmiş customer memory JSON dosyasını geri yüklemeden önce ön izleyin. "
        "Bu işlem mevcut customer_memory.json dosyasını değiştirmez."
    )

    uploaded_file = st.file_uploader(
        "Upload customer_memory_export.json",
        type=["json"],
        key="customer_memory_import_preview",
    )

    if not uploaded_file:
        return

    try:
        import json

        raw_content = uploaded_file.read().decode("utf-8")
        import_data = json.loads(raw_content)

    except Exception as error:
        st.error("JSON dosyası okunamadı.")
        st.code(str(error))
        return

    try:
        response = requests.post(
            f"{API_BASE_URL}/customer-memory/import/validate",
            json={"import_data": import_data},
            timeout=30,
        )
        response.raise_for_status()
        validation_result = response.json()

    except requests.exceptions.RequestException as error:
        st.error("Import validation API başarısız oldu.")
        st.code(str(error))
        return
    
    try:
        dry_run_response = requests.post(
            f"{API_BASE_URL}/customer-memory/import/dry-run",
            json={"import_data": import_data},
            timeout=30,
        )
        dry_run_response.raise_for_status()
        dry_run_result = dry_run_response.json()

    except requests.exceptions.RequestException as error:
        st.error("Import dry run API başarısız oldu.")
        st.code(str(error))
        return

    profile_count = validation_result.get("profile_count", 0)
    customer_names = validation_result.get("customer_names", [])
    errors = validation_result.get("errors", [])
    warnings = validation_result.get("warnings", [])

    if validation_result.get("valid"):
        st.success(f"Import validation başarılı. Profil sayısı: {profile_count}")
    else:
        st.error(f"Import validation başarısız. Profil sayısı: {profile_count}")

    st.markdown("### Customer Names")

    for name in customer_names:
        st.write(f"- {name}")

    if errors:
        st.error("Validation errors bulundu.")
        for error in errors:
            st.write(f"- {error}")
    else:
        st.success("Validation error yok.")

    if warnings:
        st.warning("Validation warnings bulundu.")
        for warning in warnings:
            st.write(f"- {warning}")
    else:
        st.success("Validation warning yok.")
    
        st.markdown("### Import Dry Run Report")

    st.write(
        f"Current profile count: {dry_run_result.get('current_profile_count', 0)}"
    )

    st.write(
        f"Import profile count: {dry_run_result.get('profile_count', 0)}"
    )

    will_add = dry_run_result.get("will_add", [])
    will_update = dry_run_result.get("will_update", [])
    will_skip = dry_run_result.get("will_skip", [])
    alias_conflicts = dry_run_result.get("alias_conflicts", [])
    name_conflicts = dry_run_result.get("name_conflicts", [])

    if will_add:
        st.success("Will add:")
        for name in will_add:
            st.write(f"- {name}")
    else:
        st.info("Will add: none")

    if will_update:
        st.warning("Will update existing profiles:")
        for name in will_update:
            st.write(f"- {name}")
    else:
        st.info("Will update: none")

    if will_skip:
        st.warning("Will skip:")
        for item in will_skip:
            st.write(f"- {item}")
    else:
        st.success("Will skip: none")

    if name_conflicts:
        st.warning("Name conflicts:")
        for item in name_conflicts:
            st.write(
                f"- Import: {item.get('import_customer_name')} | "
                f"Existing: {item.get('existing_customer_name')}"
            )
    else:
        st.success("Name conflict yok.")

    if alias_conflicts:
        st.error("Alias conflicts:")
        for item in alias_conflicts:
            st.write(
                f"- Alias: {item.get('alias')} | "
                f"Import customer: {item.get('import_customer_name')} | "
                f"Existing customer: {item.get('existing_customer_name')}"
            )
    else:
        st.success("Alias conflict yok.")

    with st.expander("Dry Run Result"):
        st.json(dry_run_result)

    with st.expander("Validation Result"):
        st.json(validation_result)
    
        st.markdown("### Apply Import")

    can_apply_import = (
        validation_result.get("valid")
        and not dry_run_result.get("alias_conflicts")
        and not dry_run_result.get("errors")
    )

    if not can_apply_import:
        st.warning(
            "Import uygulanamaz. Önce validation error veya alias conflict sorunlarını düzeltin."
        )
    else:
        st.warning(
            "Bu işlem mevcut customer_memory.json dosyasını günceller. "
            "İşlem öncesi otomatik backup oluşturulur."
        )

        confirm_apply = st.checkbox(
            "I understand this will update customer_memory.json",
            key="confirm_customer_memory_import_apply",
        )

        if confirm_apply and st.button("Apply Customer Memory Import"):
            try:
                apply_response = requests.post(
                    f"{API_BASE_URL}/customer-memory/import/apply",
                    json={"import_data": import_data},
                    timeout=30,
                )
                apply_response.raise_for_status()
                apply_result = apply_response.json()

                if apply_result.get("success"):
                    st.success("Customer memory import başarıyla uygulandı.")
                    st.json(apply_result)
                else:
                    st.error("Customer memory import uygulanamadı.")
                    st.json(apply_result)

            except requests.exceptions.RequestException as error:
                st.error("Customer memory import apply API başarısız oldu.")
                st.code(str(error))

    with st.expander("Raw Import Preview"):
        st.json(import_data)

def render_customer_memory_backup_restore_preview():
    st.markdown("---")
    st.markdown("## Customer Memory Backup / Restore Preview")


    st.write(
        "Import işlemleri öncesinde oluşturulan customer memory backup dosyalarını görüntüleyin. "
        "Bu bölüm seçilen backup dosyasını preview eder ve istenirse restore uygular."
    )

    try:
        response = requests.get(
            f"{API_BASE_URL}/customer-memory/backups",
            timeout=30,
        )
        response.raise_for_status()
        backups_data = response.json()

    except requests.exceptions.RequestException as error:
        st.error("Backup listesi alınamadı.")
        st.code(str(error))
        return

    backups = backups_data.get("backups", [])

    if not backups:
        st.info("Henüz customer memory backup dosyası yok.")
        return

    backup_options = [
        backup.get("file_name")
        for backup in backups
    ]

    selected_backup = st.selectbox(
        "Select backup file",
        backup_options,
        key="customer_memory_backup_select",
    )

    selected_backup_data = next(
        (
            backup
            for backup in backups
            if backup.get("file_name") == selected_backup
        ),
        None,
    )

    if selected_backup_data:
        st.write(f"Size: {selected_backup_data.get('size_bytes')} bytes")
        st.write(f"Path: {selected_backup_data.get('path')}")

    preview_key = f"backup_preview_{selected_backup}"
    dry_run_key = f"backup_dry_run_{selected_backup}"

    if st.button(
        "Preview Selected Backup",
        key=f"preview_selected_backup_{selected_backup}",
    ):
        try:
            backup_response = requests.get(
                f"{API_BASE_URL}/customer-memory/backups/{selected_backup}",
                timeout=30,
            )
            backup_response.raise_for_status()
            backup_data = backup_response.json()

        except requests.exceptions.RequestException as error:
            st.error("Backup preview alınamadı.")
            st.code(str(error))
            return

        backup_import_data = {
            "profiles": backup_data.get("profiles", [])
        }

        try:
            dry_run_response = requests.post(
                f"{API_BASE_URL}/customer-memory/import/dry-run",
                json={"import_data": backup_import_data},
                timeout=30,
            )
            dry_run_response.raise_for_status()
            dry_run_result = dry_run_response.json()

        except requests.exceptions.RequestException as error:
            st.error("Backup dry run alınamadı.")
            st.code(str(error))
            return

        st.session_state[preview_key] = backup_data
        st.session_state[dry_run_key] = dry_run_result

    backup_data = st.session_state.get(preview_key)
    dry_run_result = st.session_state.get(dry_run_key)

    if not backup_data or not dry_run_result:
        st.info("Restore preview görmek için önce Preview Selected Backup butonuna basın.")
        return

    st.success(
        f"Backup preview hazır. Profil sayısı: {backup_data.get('profile_count', 0)}"
    )

    st.markdown("### Restore Dry Run Report")

    st.write(
        f"Current profile count: {dry_run_result.get('current_profile_count', 0)}"
    )

    st.write(
        f"Backup profile count: {dry_run_result.get('profile_count', 0)}"
    )

    will_add = dry_run_result.get("will_add", [])
    will_update = dry_run_result.get("will_update", [])
    will_skip = dry_run_result.get("will_skip", [])
    alias_conflicts = dry_run_result.get("alias_conflicts", [])

    if will_add:
        st.success("Restore would add:")
        for name in will_add:
            st.write(f"- {name}")
    else:
        st.info("Restore would add: none")

    if will_update:
        st.warning("Restore would update existing profiles:")
        for name in will_update:
            st.write(f"- {name}")
    else:
        st.info("Restore would update: none")

    if will_skip:
        st.warning("Restore would skip:")
        for item in will_skip:
            st.write(f"- {item}")
    else:
        st.success("Restore would skip: none")

    if alias_conflicts:
        st.error("Alias conflicts:")
        for item in alias_conflicts:
            st.write(
                f"- Alias: {item.get('alias')} | "
                f"Backup customer: {item.get('import_customer_name')} | "
                f"Existing customer: {item.get('existing_customer_name')}"
            )
    else:
        st.success("Alias conflict yok.")

    st.markdown("### Apply Restore")

    can_restore = (
        dry_run_result.get("valid")
        and not dry_run_result.get("alias_conflicts")
        and not dry_run_result.get("errors")
    )

    if not can_restore:
        st.warning(
            "Restore uygulanamaz. Önce validation error veya alias conflict sorunlarını düzeltin."
        )
    else:
        st.warning(
            "Bu işlem mevcut customer_memory.json dosyasını seçilen backup ile değiştirir. "
            "İşlem öncesi mevcut dosyanın yeni bir backup'ı otomatik oluşturulur."
        )

        confirm_restore = st.checkbox(
            "I understand this will replace current customer_memory.json with the selected backup",
            key=f"confirm_customer_memory_restore_apply_{selected_backup}",
        )

        if confirm_restore and st.button(
            "Restore Selected Backup",
            key=f"restore_selected_backup_{selected_backup}",
        ):
            try:
                restore_response = requests.post(
                    f"{API_BASE_URL}/customer-memory/backups/restore",
                    json={"file_name": selected_backup},
                    timeout=30,
                )
                restore_response.raise_for_status()
                restore_result = restore_response.json()

                if restore_result.get("success"):
                    st.success("Customer memory restore başarıyla uygulandı.")
                    st.json(restore_result)

                    # Restore sonrası eski preview artık geçersiz olabileceği için temizliyoruz.
                    st.session_state.pop(preview_key, None)
                    st.session_state.pop(dry_run_key, None)

                else:
                    st.error("Customer memory restore uygulanamadı.")
                    st.json(restore_result)

            except requests.exceptions.RequestException as error:
                st.error("Customer memory restore API başarısız oldu.")
                st.code(str(error))

    with st.expander("Backup Dry Run Result", expanded=True):
        st.json(dry_run_result)

    with st.expander("Raw Backup Preview", expanded=False):
        st.json(backup_data)

def render_customer_memory_backup_cleanup_preview():
    st.markdown("---")
    st.markdown("## Customer Memory Backup Cleanup Preview")

    st.write(
        "Customer memory backup dosyaları için cleanup ön izlemesi. "
        "Bu bölüm henüz hiçbir backup dosyasını silmez."
    )

    keep_latest = st.number_input(
        "Keep latest backup count",
        min_value=1,
        max_value=100,
        value=10,
        step=1,
        key="customer_memory_backup_keep_latest",
    )

    if not st.button("Preview Backup Cleanup"):
        return

    try:
        response = requests.get(
            f"{API_BASE_URL}/customer-memory/backups/cleanup-preview",
            params={"keep_latest": keep_latest},
            timeout=30,
        )
        response.raise_for_status()
        cleanup_preview = response.json()

    except requests.exceptions.RequestException as error:
        st.error("Backup cleanup preview alınamadı.")
        st.code(str(error))
        return

    total_backup_count = cleanup_preview.get("total_backup_count", 0)
    keep_count = cleanup_preview.get("keep_count", 0)
    cleanup_candidate_count = cleanup_preview.get("cleanup_candidate_count", 0)

    st.success("Backup cleanup preview hazır.")

    st.write(f"Total backup count: {total_backup_count}")
    st.write(f"Backups to keep: {keep_count}")
    st.write(f"Cleanup candidates: {cleanup_candidate_count}")

    backups_to_keep = cleanup_preview.get("backups_to_keep", [])
    cleanup_candidates = cleanup_preview.get("cleanup_candidates", [])

    st.markdown("### Backups to Keep")

    if backups_to_keep:
        for backup in backups_to_keep:
            st.write(
                f"- {backup.get('file_name')} "
                f"({backup.get('size_bytes')} bytes)"
            )
    else:
        st.info("Keep listesi boş.")

    st.markdown("### Cleanup Candidates")

    if cleanup_candidates:
        st.warning(
            "Aşağıdaki dosyalar ileride cleanup için aday olabilir. "
            "Bu görevde henüz silme yapılmaz."
        )

        for backup in cleanup_candidates:
            st.write(
                f"- {backup.get('file_name')} "
                f"({backup.get('size_bytes')} bytes)"
            )
    else:
        st.success("Cleanup candidate yok.")

    with st.expander("Cleanup Preview Raw Result", expanded=False):
        st.json(cleanup_preview)

def render_customer_memory_list():
    st.markdown("---")
    st.markdown("## Customer Memory Profiles")

    st.write(
        "Sistemde kayıtlı müşteri hafızası profillerini görüntüleyin."
    )

    if st.button("Refresh Customer Memory List"):
        st.session_state["customer_memory_list_refresh"] = True

    try:
        response = requests.get(
            f"{API_BASE_URL}/customer-memory",
            timeout=30,
        )

        response.raise_for_status()
        result = response.json()

        profiles = result.get("profiles", [])
        count = result.get("count", 0)

        st.write(f"**Toplam profil:** {count}")

        if not profiles:
            st.info("Henüz müşteri hafızası profili bulunmuyor.")
            return

        for profile in profiles:
            customer_name = profile.get("customer_name") or "-"
            active = profile.get("active", True)

            status_label = "ACTIVE" if active else "PASSIVE"
            expander_title = f"{customer_name} — {status_label}"

            with st.expander(expander_title):
                col1, col2 = st.columns(2)

                with col1:
                    st.write(f"**Status:** {'Active' if active else 'Passive'}")
                    st.write(f"**Default Commodity:** {profile.get('default_commodity') or '-'}")
                    st.write(f"**Default Equipment:** {profile.get('default_equipment_type') or '-'}")
                    st.write(f"**Price Sensitivity:** {profile.get('price_sensitivity') or '-'}")
                    st.write(f"**Time Sensitivity:** {profile.get('time_sensitivity') or '-'}")

                with col2:
                    pickup_parts = [
                        profile.get("default_pickup_area"),
                        profile.get("default_pickup_city"),
                        profile.get("default_pickup_country"),
                    ]
                    delivery_parts = [
                        profile.get("default_delivery_city"),
                        profile.get("default_delivery_country"),
                    ]

                    pickup = ", ".join(part for part in pickup_parts if part) or "-"
                    delivery = ", ".join(part for part in delivery_parts if part) or "-"

                    st.write(f"**Default Pickup:** {pickup}")
                    st.write(f"**Default Delivery:** {delivery}")

                aliases = profile.get("aliases") or []
                if aliases:
                    st.markdown("**Aliases:**")
                    for alias in aliases:
                        st.write(f"- {alias}")

                notes = profile.get("operational_notes") or []
                if notes:
                    st.markdown("**Operational Notes:**")
                    for note in notes:
                        st.write(f"- {note}")
                        
                st.markdown("**Audit:**")
                st.write(f"- Created At: {profile.get('created_at') or '-'}")
                st.write(f"- Last Updated At: {profile.get('last_updated_at') or '-'}")
                st.write(f"- Last Updated By: {profile.get('last_updated_by') or '-'}")
                st.write(f"- Change Note: {profile.get('change_note') or '-'}")

                target_active = not active
                render_customer_memory_edit_form(profile)
                button_label = "Set Passive" if active else "Set Active"

                if st.button(button_label, key=f"toggle_active_{customer_name}"):
                    try:
                        response = requests.patch(
                            f"{API_BASE_URL}/customer-memory/status",
                            json={
                                "customer_name": customer_name,
                                "active": target_active,
                            },
                            timeout=30,
                        )

                        response.raise_for_status()

                        st.success(
                            f"{customer_name} status updated to {'Active' if target_active else 'Passive'}."
                        )
                        st.rerun()

                    except requests.exceptions.RequestException as error:
                        st.error("Customer status güncellenemedi.")
                        st.code(str(error))

    except requests.exceptions.RequestException as error:
        st.error("Customer memory listesi alınamadı.")
        st.code(str(error))


def render_customer_memory_editor():
    st.markdown("---")
    st.markdown("## Customer Memory Editor")

    st.write(
        "Yeni müşteri hafızası profili eklemek için bu formu kullanın."
    )

    with st.expander("Yeni Müşteri Profili Ekle"):
        customer_name = st.text_input("Customer Name")
        active = st.checkbox("Active", value=True)

        aliases_text = st.text_area(
            "Aliases",
            placeholder="Her satıra bir alias yazın. Örn:\noguz gida\noğuz gıda",
            height=100,
        )

        default_commodity = st.text_input("Default Commodity")
        default_equipment_type = st.text_input("Default Equipment Type")

        col1, col2 = st.columns(2)

        with col1:
            price_sensitivity = st.selectbox(
                "Price Sensitivity",
                options=["", "low", "medium", "high"],
            )

        with col2:
            time_sensitivity = st.selectbox(
                "Time Sensitivity",
                options=["", "low", "medium", "high"],
            )

        st.markdown("### Default Pickup")

        pickup_col1, pickup_col2, pickup_col3 = st.columns(3)

        with pickup_col1:
            default_pickup_city = st.text_input("Default Pickup City")

        with pickup_col2:
            default_pickup_area = st.text_input("Default Pickup Area")

        with pickup_col3:
            default_pickup_country = st.text_input("Default Pickup Country")

        st.markdown("### Default Delivery")

        delivery_col1, delivery_col2 = st.columns(2)

        with delivery_col1:
            default_delivery_city = st.text_input("Default Delivery City")

        with delivery_col2:
            default_delivery_country = st.text_input("Default Delivery Country")

        operational_notes_text = st.text_area(
            "Operational Notes",
            placeholder="Her satıra bir operasyon notu yazın.",
            height=120,
        )

        if st.button("Save Customer Profile"):
            if not customer_name.strip():
                st.warning("Customer Name zorunludur.")
                return

            aliases = [
                line.strip()
                for line in aliases_text.splitlines()
                if line.strip()
            ]

            operational_notes = [
                line.strip()
                for line in operational_notes_text.splitlines()
                if line.strip()
            ]

            change_note = st.text_input(
                "Change Note",
                value="Customer profile created from UI.",
            )

            payload = {
                "customer_name": customer_name.strip(),
                "active": active,
                "aliases": aliases,
                "default_commodity": default_commodity.strip() or None,
                "default_equipment_type": default_equipment_type.strip() or None,
                "price_sensitivity": price_sensitivity or None,
                "time_sensitivity": time_sensitivity or None,
                "default_pickup_city": default_pickup_city.strip() or None,
                "default_pickup_area": default_pickup_area.strip() or None,
                "default_pickup_country": default_pickup_country.strip() or None,
                "default_delivery_city": default_delivery_city.strip() or None,
                "default_delivery_country": default_delivery_country.strip() or None,
                "last_updated_by": "ui",
                "change_note": change_note.strip() or "Customer profile created from UI.",
                "operational_notes": operational_notes,
            }

            try:
                response = requests.post(
                    f"{API_BASE_URL}/customer-memory",
                    json=payload,
                    timeout=30,
                )

                response.raise_for_status()
                result = response.json()

                st.success(f"Müşteri profili eklendi: {result['profile']['customer_name']}")

            except requests.exceptions.HTTPError as error:
                st.error("Customer memory kaydı reddedildi.")

                try:
                    error_detail = error.response.json().get("detail")
                    st.warning(error_detail)
                except Exception:
                    st.code(str(error))

            except requests.exceptions.RequestException as error:
                st.error("Customer memory kaydı başarısız oldu.")
                st.code(str(error))


def render_new_inquiry_page():
    st.subheader("Yeni Talep")
    st.write("Müşteri mailini yapıştırın. MINAI bilgileri çıkarır ve insan teyidine hazırlar.")
    example_options = get_example_email_options()
    selected_example = st.selectbox("Hazır Senaryo Seç", options=list(example_options.keys()))
    selected_email = "" if selected_example == "Custom Email" else example_options[selected_example]
    email_text = st.text_area("Müşteri Email Metni", value=selected_email, height=220)
    if st.button("Process Email"):
        if not email_text.strip():
            st.warning("Lütfen bir email metni girin.")
            return
        with st.spinner("MINAI emaili işliyor..."):
            try:
                response = requests.post(
                    f"{API_BASE_URL}/process-email",
                    json={"email_text": email_text},
                    timeout=60,
                )
                response.raise_for_status()
                result = response.json()
                st.success("Email işlendi.")
                render_summary(result)
                render_draft(result)
                render_debug(result)
            except requests.exceptions.RequestException as error:
                st.error("API çağrısı başarısız oldu.")
                st.code(str(error))


def render_data_management_page():
    st.subheader("Veri & Rehber")
    render_data_health_dashboard()
    render_customer_memory_list()
    render_customer_memory_editor()
    render_customer_memory_export()
    render_customer_memory_import_preview()
    render_customer_memory_backup_restore_preview()
    render_customer_memory_backup_cleanup_preview()


st.title("MINAI Freight OS")
st.caption("Freight Operations Workspace")
page = st.sidebar.radio(
    "Çalışma Alanı",
    ["MINA İşleri", "Yeni Talep", "Veri & Rehber"],
    index=0,
)
if page == "MINA İşleri":
    render_mina_operations(API_BASE_URL)
elif page == "Yeni Talep":
    render_new_inquiry_page()
else:
    render_data_management_page()
