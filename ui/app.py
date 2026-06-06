import requests
import streamlit as st


API_BASE_URL = "http://127.0.0.1:8000"


st.set_page_config(
    page_title="MINAI Freight OS",
    page_icon="🚛",
    layout="wide",
)

st.title("MINAI Freight OS")
st.subheader("AI Freight Operations Assistant")

st.write(
    "Müşteri mailini aşağıya yapıştırın. MINAI shipment bilgilerini çıkarır, riskleri değerlendirir ve uygun aksiyonu üretir."
)

default_email = """Merhaba,

Adana OSB'den Stuttgart Almanya'ya 1 adet makine için komple araç fiyat rica ederiz.
Yaklaşık 3000 kg. Ölçüleri henüz net değil.
Yük 23.06.2026 tarihinde hazır olacaktır.

Teşekkürler.
"""

email_text = st.text_area(
    "Müşteri Email Metni",
    value=default_email,
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

                result_type = result.get("result_type")

                st.markdown("## Sonuç")
                st.write(f"**Result Type:** `{result_type}`")

                col1, col2 = st.columns(2)

                with col1:
                    st.markdown("### Shipment")
                    st.json(result.get("shipment"))

                    st.markdown("### Equipment Decision")
                    st.json(result.get("equipment_decision"))

                with col2:
                    st.markdown("### Risk Assessment")
                    st.json(result.get("risk_assessment"))

                    st.markdown("### Missing Info")
                    st.json(result.get("missing_info"))

                if result_type == "quote":
                    st.markdown("## Quote Draft")
                    quote = result.get("quote_draft")

                    if quote:
                        st.write(f"**Subject:** {quote.get('subject')}")
                        st.text_area(
                            "Quote Email Body",
                            value=quote.get("body", ""),
                            height=300,
                        )

                elif result_type == "clarification":
                    st.markdown("## Clarification Draft")
                    draft = result.get("clarification_draft")

                    if draft:
                        st.write(f"**Subject:** {draft.get('subject')}")
                        st.text_area(
                            "Clarification Email Body",
                            value=draft.get("body", ""),
                            height=300,
                        )

                elif result_type == "management_review":
                    st.markdown("## Management Review Draft")
                    draft = result.get("management_review_draft")

                    if draft:
                        st.write(f"**Subject:** {draft.get('subject')}")
                        st.text_area(
                            "Management Review Body",
                            value=draft.get("body", ""),
                            height=300,
                        )

                else:
                    st.warning("Sonuç tipi belirlenemedi.")

            except requests.exceptions.RequestException as error:
                st.error("API çağrısı başarısız oldu.")
                st.code(str(error))