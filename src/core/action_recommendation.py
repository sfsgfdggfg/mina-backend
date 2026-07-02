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

    if result_type == "quote":
        if risk_assessment.risk_level == "yellow":
            return ActionRecommendation(
                action_type="quote_with_review",
                title="Operasyon Kontrolü Sonrası Teklif Gönder",
                message="Teklif taslağı üretildi ancak sarı risk var. Gönderimden önce operasyon kontrolü yapılmalı.",
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

        return ActionRecommendation(
            action_type="quote_ready",
            title="Teklif Taslağı Hazır",
            message="Bilgi yeterli ve kritik risk yok. Teklif taslağı kontrol edilip müşteriye gönderilebilir.",
            priority="normal",
            checklist=[
                "Fiyatı kontrol et.",
                "Transit süreyi kontrol et.",
                "Teklif geçerliliği notunu kontrol et.",
                "Mail taslağını gönderime hazırla.",
            ],
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