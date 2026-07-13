AI_EMAIL_TEST_CASES = [
    {
        "name": "Standard textile FTL",
        "email": """
Merhaba,

Adana Organize Sanayi Bölgesi'nden Hamburg Almanya'ya 20 ton tekstil yükümüz için komple araç fiyatı rica ederiz.
Yük 15.06.2026 tarihinde hazır olacaktır.

Teşekkürler.
""",
        "expected": {
            "result_type": "quote",
            "equipment": "Tenteli / Curtainsider",
            "service_type": "FTL",
            "risk_level": "yellow",
            "action_type": "quote_with_review",
        },
    },
    {
        "name": "Machine missing dimensions",
        "email": """
Merhaba,

Adana OSB'den Stuttgart Almanya'ya 1 adet makine için komple araç fiyat rica ederiz.
Yaklaşık 3000 kg. Ölçüleri henüz net değil.
Yük 23.06.2026 tarihinde hazır olacaktır.

Teşekkürler.
""",
        "expected": {
            "result_type": "clarification",
            "service_type": "FTL",
            "risk_level": "yellow",
            "missing_fields": ["machine dimensions"],
            "action_type": "clarification",
        },
    },
    {
        "name": "Temperature controlled food",
        "email": """
Merhaba,

Mersin'den Münih Almanya'ya 33 palet gıda ürünü için fiyat rica ederiz.
Yük +4 derecede taşınmalıdır.
Toplam ağırlık yaklaşık 18 ton.
Yük 18.06.2026 tarihinde hazırdır.

İyi çalışmalar.
""",
        "expected": {
            "result_type": "quote",
            "equipment": "Reefer",
            "service_type": "FTL",
            "risk_level": "yellow",
            "action_type": "quote_with_review",
        },
    },
    {
        "name": "ADR Class 7",
        "email": """
Merhaba,

Gebze'den Viyana Avusturya'ya ADR Class 7 kapsamındaki yükümüz için taşıma imkanı ve fiyat rica ederiz.
Toplam 4 sandık, yaklaşık 5000 kg.
Yük 22.06.2026 tarihinde hazır olacaktır.

Saygılar.
""",
        "expected": {
            "result_type": "management_review",
            "equipment": "Special ADR Equipment",
            "service_type": "FTL",
            "risk_level": "red",
            "action_type": "management_review",
        },
    },
    {
        "name": "Partial shipment request",
        "email": """
Merhaba,

İstanbul'dan Berlin Almanya'ya parsiyel taşıma fiyatı rica ederiz.
3 palet tekstil ürünümüz var.
Toplam ağırlık yaklaşık 900 kg.
Yük 19.06.2026 tarihinde hazır.

Teşekkürler.
""",
        "expected": {
            "result_type": "quote",
            "equipment": "Tenteli / Curtainsider",
            "service_type": "LTL",
            "risk_level": "yellow",
            "action_type": "quote_with_review",
        },
    },
    {
        "name": "Machine height 2.90m",
        "email": """
Merhaba,

Konya'dan Bükreş Romanya'ya 1 adet makine taşıması için fiyat rica ederiz.
Ölçüler: 250 x 120 x 290 cm.
Ağırlık: 7000 kg.
Yük 20.06.2026 tarihinde hazır olacaktır.

Teşekkürler.
""",
        "expected": {
            "result_type": "quote",
            "equipment": "Mega Trailer",
            "service_type": "FTL",
            "risk_level": "yellow",
            "action_type": "quote_with_review",
        },
    },
        {
        "name": "Known customer Oğuz Gıda default equipment",
        "email": """
Merhaba,

Oğuz Gıda için Adana'dan İstanbul'a içecek yükümüz için fiyat rica ederiz.
Yük 24.06.2026 tarihinde hazır olacaktır.
Toplam yaklaşık 18 ton.

Teşekkürler.
""",
        "expected": {
            "result_type": "quote",
            "equipment": "Kapalı Kasa / Box Trailer",
            "service_type": "FTL",
            "risk_level": "green",
            "customer_memory_matched": True,
            "action_type": "quote_ready",
            "expected_supplier_name": "Anatolia Domestic",
        },
    },
        {
        "name": "Customer recognition from email content",
        "email": """
Merhaba,

Bu taşıma Oğuz Gıda içindir.
Adana'dan Ankara'ya içecek yükümüz için fiyat rica ederiz.
Toplam 18 ton.
Yük 25.06.2026 tarihinde hazır olacaktır.

Teşekkürler.
""",
        "expected": {
            "result_type": "quote",
            "equipment": "Kapalı Kasa / Box Trailer",
            "service_type": "FTL",
            "risk_level": "green",
            "customer_memory_matched": True,
            "action_type": "quote_ready",
            "expected_supplier_name": "Anatolia Domestic",
        },
    },
        {
        "name": "Known customer Beta Enerji transformer",
        "email": """
Merhaba,

Beta Enerji için Adana'dan Stuttgart Almanya'ya elektrik transformatörü taşıması için fiyat rica ederiz.
1 adet trafo, ölçüler 240 x 120 x 180 cm.
Ağırlık yaklaşık 5000 kg.
Yük 26.06.2026 tarihinde hazır olacaktır.

Teşekkürler.
""",
        "expected": {
            "result_type": "quote",
            "equipment": "Tenteli / Curtainsider",
            "service_type": "FTL",
            "risk_level": "green",
            "customer_memory_matched": True,
            "action_type": "quote_ready",
        },
    },
    {
        "name": "Known customer Temsa time sensitive automotive",
        "email": """
Merhaba,

Temsa için Adana'dan Münih Almanya'ya otomotiv parçası taşıması için komple araç fiyat rica ederiz.
Toplam yaklaşık 12 ton.
Yük 27.06.2026 tarihinde hazır olacaktır.
Teslimat süresi bizim için önemlidir.

Teşekkürler.
""",
        "expected": {
            "result_type": "quote",
            "equipment": "Tenteli / Curtainsider",
            "service_type": "FTL",
            "risk_level": "yellow",
            "customer_memory_matched": True,
            "action_type": "quote_with_review",
        },
    },
    {
        "name": "GTIP beverage classification",
        "email": """
Merhaba,

Adana'dan İstanbul'a GTİP: 2202.10.00.00.00 olan meşrubat yükümüz için fiyat rica ederiz.
Toplam 20 palet, yaklaşık 10000 kg.
Yük 28.06.2026 tarihinde hazır olacaktır.

Teşekkürler.
""",
        "expected": {
            "result_type": "quote",
            "service_type": "FTL",
            "commodity": "İçecek / Meşrubat",
            "gtip_code": "220210000000",
            "hs_chapter": "22",
            "hs_heading": "2202",
            "hs_subheading": "220210",
            "gtip_detected_from_email": True,
        },
    },

    {
        "name": "GTIP commodity conflict warning",
        "email": """
Merhaba,

Adana'dan İstanbul'a GTİP: 8504.21.00.00.00 olan plastik poşet yükümüz için fiyat rica ederiz.
Toplam 15 palet, yaklaşık 8000 kg.
Yük 29.06.2026 tarihinde hazır olacaktır.

Teşekkürler.
""",
        "expected": {
            "result_type": "quote",
            "service_type": "FTL",
            "commodity": "Plastik Ürünler",
            "gtip_code": "850421000000",
            "hs_chapter": "85",
            "hs_heading": "8504",
            "hs_subheading": "850421",
            "gtip_detected_from_email": True,
            "operational_warning_contains": "GTIP kodu ile ürün açıklaması uyumsuz",
        },
    },

    {
        "name": "Frozen food commodity profile",
        "email": """
Merhaba,

Adana'dan Berlin Almanya'ya dondurulmuş gıda yükümüz için fiyat rica ederiz.
Toplam 18 palet, yaklaşık 9000 kg.
Yük 30.06.2026 tarihinde hazır olacaktır.

Teşekkürler.
""",
        "expected": {
            "result_type": "quote",
            "equipment": "Reefer",
            "service_type": "FTL",
            "commodity": "Dondurulmuş Gıda",
            "risk_level": "yellow",
            "action_type": "quote_with_review",
        },
    },

    {
        "name": "Chemical commodity profile missing info",
        "email": """
Merhaba,

Gebze'den Hamburg Almanya'ya kimyasal ürün taşıması için komple araç fiyat rica ederiz.
Toplam 12 palet, yaklaşık 6000 kg.
Yük 01.07.2026 tarihinde hazır olacaktır.

Teşekkürler.
""",
        "expected": {
            "result_type": "clarification",
            "service_type": "FTL",
            "commodity": "Kimyasal Ürün",
            "risk_level": "yellow",
            "missing_fields": [
                "msds/sds document",
                "adr status",
                "chemical packaging type"
            ],
            "action_type": "clarification",
        },
    },

    {
        "name": "Pharma commodity profile missing info",
        "email": """
Merhaba,

İstanbul'dan Paris Fransa'ya pharma ilaç yükümüz için komple araç fiyat rica ederiz.
Toplam 8 palet, yaklaşık 2500 kg.
Yük 02.07.2026 tarihinde hazır olacaktır.

Teşekkürler.
""",
        "expected": {
            "result_type": "clarification",
            "service_type": "FTL",
            "commodity": "İlaç / Pharma",
            "risk_level": "yellow",
            "missing_fields": [
                "pharma temperature requirement",
                "pharma compliance document",
                "pharma special transport requirements"
            ],
            "action_type": "clarification",
            "action_checklist_contains": [
                "Sıcaklık gereksinimini müşteriyle doğrula.",
                "Uygunluk / ruhsat belgelerini kontrol et.",
                "Özel taşıma şartlarını netleştir."
            ],
            "commodity_profile": "İlaç / Pharma",
            "commodity_profile_keys": [
                "risk_reason",
                "missing_info_fields",
                "critical_missing_info_fields",
                "action_checklist"
            ],
            "commodity_profile_missing_fields": [
                "pharma temperature requirement",
                "pharma compliance document",
                "pharma special transport requirements"
            ],
            "commodity_profile_action_checklist_contains": [
                "Sıcaklık gereksinimini müşteriyle doğrula.",
                "Uygunluk / ruhsat belgelerini kontrol et.",
                "Özel taşıma şartlarını netleştir."
            ],
        },
    },

    {
        "name": "ADR class missing",
        "email": """
Merhaba,

Bursa'dan Lyon Fransa'ya ADR kapsamındaki endüstriyel malzememiz için komple araç fiyatı rica ederiz.
Toplam 10 palet, yaklaşık 6500 kg.
Yük 28.06.2026 tarihinde hazır olacaktır.

Teşekkürler.
""",
        "expected": {
            "result_type": "clarification",
            "equipment": "ADR Equipment Review",
            "service_type": "FTL",
            "risk_level": "yellow",
            "is_adr": True,
            "adr_class": None,
            "missing_fields": ["adr class"],
            "action_type": "clarification",
            "operational_error_contains": "ADR sınıfı eksik",
        },
    },
    {
        "name": "Non-ADR negation",
        "email": """
Merhaba,

İzmir'den Köln Almanya'ya 5 palet tekstil ürünü için komple araç fiyatı rica ederiz.
Toplam ağırlık yaklaşık 1800 kg.
Yük ADR kapsamında değildir.
Yük 29.06.2026 tarihinde hazır olacaktır.

Teşekkürler.
""",
        "expected": {
            "result_type": "quote",
            "equipment": "Tenteli / Curtainsider",
            "service_type": "FTL",
            "risk_level": "yellow",
            "is_adr": False,
            "adr_class": None,
            "action_type": "quote_with_review",
        },
    },

    {
        "name": "ADR Class 3 standard",
        "email": """
Merhaba,

Gebze'den Paris Fransa'ya ADR Class 3 kapsamındaki boya ürünümüz için komple araç fiyatı rica ederiz.
Toplam 12 palet, yaklaşık 9000 kg.
Yük 30.06.2026 tarihinde hazır olacaktır.

Teşekkürler.
""",
        "expected": {
            "result_type": "clarification",
            "equipment": "ADR-Capable Equipment",
            "service_type": "FTL",
            "risk_level": "yellow",
            "is_adr": True,
            "adr_class": "3",
            "expected_selected_supplier_name": "ADR Secure Logistics",
            "missing_fields": [
                "msds/sds document",
                "adr status",
                "chemical packaging type",
            ],
            "action_type": "clarification",
        },
    },

]