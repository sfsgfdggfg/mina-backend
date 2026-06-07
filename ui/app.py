import sys
from pathlib import Path

import requests
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

from src.simulation.ai_email_test_cases import AI_EMAIL_TEST_CASES


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
    if result_type == "quote":
        return "Teklif taslağı hazırlandı."
    if result_type == "clarification":
        return "Eksik bilgi var. Müşteriden bilgi istenmeli."
    if result_type == "management_review":
        return "RED risk var. Yönetici / senior operasyon onayı gerekli."
    return "Sonuç tipi belirlenemedi."


def get_result_label(result_type: str) -> str:
    if result_type == "quote":
        return "Teklif Hazır"
    if result_type == "clarification":
        return "Eksik Bilgi Gerekli"
    if result_type == "management_review":
        return "Yönetici Onayı Gerekli"
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


def render_summary(result: dict):
    shipment = result.get("shipment") or {}
    equipment = result.get("equipment_decision") or {}
    risk = result.get("risk_assessment") or {}
    missing = result.get("missing_info") or {}

    result_type = result.get("result_type")
    result_label = get_result_label(result_type)
    action_text = get_action_text(result_type)

    st.markdown("## Operasyon Özeti")

    if result_type == "quote":
        st.success(result_label)
    elif result_type == "clarification":
        st.warning(result_label)
    elif result_type == "management_review":
        st.error(result_label)
    else:
        st.info(result_label)

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Risk", (risk.get("risk_level") or "-").upper())

    with col2:
        st.metric("Servis", shipment.get("service_type") or "-")

    with col3:
        st.metric("Araç", equipment.get("selected_equipment") or "-")

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
        for reason in risk_reasons:
            st.write(f"- {reason}")

    missing_fields = missing.get("missing_fields") or []
    if missing_fields:
        st.markdown("### Eksik Bilgiler")
        for field in missing_fields:
            st.write(f"- {field}")


def render_draft(result: dict):
    result_type = result.get("result_type")

    if result_type == "quote":
        title = "Teklif Mail Taslağı"
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

def render_test_suite_runner():
    st.markdown("---")
    st.markdown("## Test Suite")

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

st.title("MINAI Freight OS")
st.subheader("AI Freight Operations Assistant")

st.write(
    "Müşteri mailini yapıştırın. MINAI shipment bilgilerini çıkarır, riskleri değerlendirir ve uygun aksiyonu üretir."
)

example_options = get_example_email_options()

selected_example = st.selectbox(
    "Hazır Senaryo Seç",
    options=list(example_options.keys()),
)

selected_email = example_options[selected_example]

if selected_example == "Custom Email":
    selected_email = ""

email_text = st.text_area(
    "Müşteri Email Metni",
    value=selected_email,
    height=220,
)

if st.button("Process Email"):
    if not email_text.strip():
        st.warning("Lütfen bir email metni girin.")
    else:
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
render_test_suite_runner()