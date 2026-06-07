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
        },
    },
]