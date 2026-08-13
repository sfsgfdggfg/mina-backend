from pydantic import BaseModel
from typing import List, Optional

from src.core.models import Shipment, EquipmentDecision, RiskAssessment
from src.core.missing_info import MissingInfoResult
from src.core.commodity_profile import get_commodity_action_checklist




def _extend_checklist(base_checklist: List[str], extra_checklist: List[str]) -> List[str]:
    result = list(base_checklist)

    for item in extra_checklist:
        if item and item not in result:
            result.append(item)

    return result


class ActionRecommendation(BaseModel):
    action_type: str
    title: str
    message: str
    priority: str = "normal"
    checklist: List[str] = []
    source: str = "workflow_engine"


def generate_action_recommendation(
    shipment: Shipment,
    equipment_decision: EquipmentDecision,
    risk_assessment: RiskAssessment,
    missing_info: MissingInfoResult,
    result_type: str,
) -> ActionRecommendation:
    """
    Action Recommendation v1.

    Workflow sonucuna göre operasyoncuya bir sonraki aksiyonu önerir.
    """

    commodity_action_checklist = get_commodity_action_checklist(shipment.commodity)

    if result_type == "pilot_scope_excluded":
        return ActionRecommendation(
            action_type="pilot_scope_excluded",
            title="Shadow Pilot Kapsamı Dışında",
            message=(
                "Bu taşıma kontrollü shadow pilotun düşük riskli karayolu "
                "kapsamı dışındadır. MINAI tedarikçi RFQ veya müşteri teklifi "
                "oluşturmadan akışı durdurdu."
            ),
            priority="high",
            checklist=_extend_checklist(
                [
                    "Kapsam dışı olma nedenlerini incele.",
                    "Talebi bağımsız gerçek operasyon sürecinde ele al.",
                    "Bu vakayı pilot RFQ veya teklif akışına dahil etme.",
                ],
                commodity_action_checklist,
            ),
            source="pilot_scope_engine",
        )

    if result_type == "data_provenance_blocked":
        return ActionRecommendation(
            action_type="data_provenance_blocked",
            title="Doğrulanmış Operasyon Verisi Gerekli",
            message=(
                "Shadow pilot akışı, pilot için doğrulanmamış operasyonel "
                "master data ile devam edemez. Doğrulanmış tedarikçi verisi "
                "yüklenip provenance kaydı tamamlanmadan RFQ veya müşteri "
                "teklifi oluşturulmaz."
            ),
            priority="high",
            checklist=_extend_checklist(
                [
                    "Pilot firmaya ait güncel tedarikçi master datasını doğrula.",
                    "Veriyi pilot_verified olarak provenance registry'ye kaydet.",
                    "Doğrulayan kişi ve doğrulama zamanını kaydet.",
                    "Doğrulanmamış demo veriyi gerçek operasyonda kullanma.",
                ],
                commodity_action_checklist,
            ),
            source="data_provenance_engine",
        )

    if result_type == "regulatory_blocked":
        return ActionRecommendation(
            action_type="regulatory_blocked",
            title="Zorunlu Belge Bulunmadığı İçin Akış Durduruldu",
            message=(
                "Gerekli düzenleyici belgenin mevcut olmadığı "
                "doğrulandı. MINAI otomatik müşteri teklifi "
                "oluşturamaz veya tamamlayamaz."
            ),
            priority="high",
            checklist=_extend_checklist(
                [
                    "Belge durumunu ve ilgili operasyon kuralını doğrula.",
                    "Belge sağlanmadan otomatik teklif akışını sürdürme.",
                    "Müşteriye blokaj nedenini açıkça bildir.",
                ],
                commodity_action_checklist,
            ),
            source="regulatory_compliance_engine",
        )

    if result_type == "regulatory_review":
        return ActionRecommendation(
            action_type="regulatory_review",
            title="Belge İstisnası İçin İnsan Onayı Gerekli",
            message=(
                "Müşteri zorunlu belgeyi daha sonra sağlayacağını "
                "belirtti. Bu taahhüt MINAI'ye otomatik devam yetkisi "
                "vermez; açık insan kararı gereklidir."
            ),
            priority="high",
            checklist=_extend_checklist(
                [
                    "Müşterinin belge taahhüdünü incele.",
                    "Devam veya ret kararını yetkili kişiyle açıkça kaydet.",
                    "Onay verilmeden teklif veya gönderim oluşturma.",
                ],
                commodity_action_checklist,
            ),
            source="regulatory_compliance_engine",
        )

    if result_type == "supplier_response_required":
        return ActionRecommendation(
            action_type="supplier_response_required",
            title="Kullanılabilir Tedarikçi Teklifi Bekleniyor",
            message=(
                "Seçilen tedarikçilerden fiyatlandırmada kullanılabilir "
                "bir cevap alınamadı. Müşteri teklifi oluşturulmadan önce "
                "yeni cevap beklenmeli veya alternatif tedarikçilere RFQ "
                "gönderilmelidir."
            ),
            priority="high",
            checklist=_extend_checklist(
                [
                    "Tedarikçi cevap durumlarını kontrol et.",
                    "No capacity veya declined cevaplarını incele.",
                    "Needs clarification cevabı varsa gerekli bilgiyi paylaş.",
                    "Gerekirse alternatif tedarikçilere RFQ gönder.",
                    "Geçerli fiyat alınmadan müşteriye teklif oluşturma.",
                ],
                commodity_action_checklist,
            ),
            source="supplier_rfq_engine",
        )

    if result_type == "supplier_rfq_approval_required":
        return ActionRecommendation(
            action_type="supplier_rfq_approval_required",
            title="Tedarikçi RFQ Gönderim Onayı Gerekli",
            message=(
                "Tedarikçi RFQ taslakları hazırlandı. RFQ'lar insan "
                "onayı olmadan gönderilmez ve gönderilmeden tedarikçi "
                "cevabı kabul edilmez."
            ),
            priority="high",
            checklist=_extend_checklist(
                [
                    "RFQ alıcısını, kapsamını ve ekipman bilgisini kontrol et.",
                    "Uygun RFQ'ları açık operatör kimliğiyle onayla.",
                    "Onaylanan RFQ'ları ayrı gönderim adımıyla ilet.",
                    "Gönderimden sonra tedarikçi cevabını bekle.",
                ],
                commodity_action_checklist,
            ),
            source="supplier_rfq_engine",
        )

    if result_type == "blocked":
        return ActionRecommendation(
            action_type="blocked",
            title="Operasyonel Tutarsızlık Nedeniyle Akış Durduruldu",
            message=(
                "Operasyonel tutarlılık kontrolünde hata bulundu. "
                "Fiyat veya teklif oluşturulmadan önce insan kontrolü gereklidir."
            ),
            priority="high",
            checklist=_extend_checklist(
                [
                    "Operational consistency hatalarını incele.",
                    "Ekipman ve supplier kararlarını doğrula.",
                    "Tutarsızlık çözülmeden fiyat paylaşma.",
                ],
                commodity_action_checklist,
            ),
            source="operational_consistency_engine",
        )

    if result_type == "management_review":
        return ActionRecommendation(
            action_type="management_review",
            title="Yönetici / Senior Operasyon Onayı Gerekli",
            message="Bu talep RED risk seviyesinde. Müşteriye teklif veya teyit verilmeden önce yönetici / senior operasyon onayı alınmalı.",
            priority="high",
            checklist=_extend_checklist(
                [
                    "Taşıma kabul kriterlerini kontrol et.",
                    "Tedarikçi uygunluğunu doğrula.",
                    "Sigorta / mevzuat / özel izin gerekliliklerini incele.",
                    "Müşteriye dönüş yapmadan önce iç karar al.",
                ],
                commodity_action_checklist,
            ),
            source="risk_engine",
        )

    if result_type == "clarification":
        return ActionRecommendation(
            action_type="clarification",
            title="Müşteriden Eksik Bilgi İste",
            message="Kritik eksik bilgi bulunduğu için fiyat çalışması durduruldu. Eksik bilgi mail taslağı kontrol edilip müşteriye gönderilmeli.",
            priority="high",
            checklist=_extend_checklist(
                [
                    "Eksik bilgi mail taslağını kontrol et.",
                    "Müşteriden ölçü / ürün / adres / hazır tarih gibi kritik bilgileri iste.",
                    "Bilgi gelmeden fiyat paylaşma.",
                ],
                commodity_action_checklist,
            ),
            source="missing_info_engine",
        )

    if result_type == "quote_with_review":
        return ActionRecommendation(
            action_type="quote_with_review",
            title="Operasyon Kontrolü Sonrası Teklif Gönder",
            message="Teklif taslağı üretildi ancak operasyon kontrolü gerekli.",
            priority="medium",
            checklist=_extend_checklist(
                [
                    "Risk nedenlerini kontrol et.",
                    "Ekipman kararını doğrula.",
                    "Transit süre ve termin uygunluğunu kontrol et.",
                    "Teklif mailini kontrol edip gönderime hazırla.",
                ],
                commodity_action_checklist,
            ),
            source="workflow_engine",
        )

    if result_type == "quote_ready":
        return ActionRecommendation(
            action_type="quote_ready",
            title="Teklif Taslağı Hazır",
            message="Bilgi yeterli ve kritik risk yok. Teklif taslağı kontrol edilip müşteriye gönderilebilir.",
            priority="normal",
            checklist=_extend_checklist(
                [
                    "Fiyatı kontrol et.",
                    "Transit süreyi kontrol et.",
                    "Teklif geçerliliği notunu kontrol et.",
                    "Mail taslağını gönderime hazırla.",
                ],
                commodity_action_checklist,
            ),
            source="workflow_engine",
        )

    return ActionRecommendation(
        action_type="unknown",
        title="Aksiyon Belirlenemedi",
        message="Workflow sonucu beklenen tiplerden biri değil. İnsan kontrolü gerekli.",
        priority="high",
        checklist=[
            "Teknik sonucu kontrol et.",
            "Gerekirse operasyon yöneticisine danış.",
        ],
        source="workflow_engine",
    )
