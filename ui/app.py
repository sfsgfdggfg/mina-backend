import sys
from pathlib import Path

import requests
import streamlit as st # type: ignore

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
        st.markdown("### Kontrol Listesi")

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
    action_recommendation = result.get("action_recommendation") or {}
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
        for reason in risk_reasons:
            st.write(f"- {reason}")

    missing_fields = missing.get("missing_fields") or []
    if missing_fields:
        st.markdown("### Eksik Bilgiler")
        for field in missing_fields:
            st.write(f"- {field}")
            
    render_customer_memory(customer_memory)
    render_action_recommendation(action_recommendation)


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

            with st.expander(customer_name):
                col1, col2 = st.columns(2)

                with col1:
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

            payload = {
                "customer_name": customer_name.strip(),
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

            except requests.exceptions.RequestException as error:
                st.error("Customer memory kaydı başarısız oldu.")
                st.code(str(error))

render_test_suite_runner()
render_customer_memory_list()
render_customer_memory_editor()