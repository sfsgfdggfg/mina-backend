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
render_customer_memory_list()
render_customer_memory_editor()
render_customer_memory_export()
render_customer_memory_import_preview()
render_customer_memory_backup_restore_preview()