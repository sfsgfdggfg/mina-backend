from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP_PATH = ROOT / "ui" / "app.py"
MINA_UI_PATH = ROOT / "ui" / "mina_operations.py"


def evaluate_mina_operations_ui_regressions() -> dict:
    failures: list[str] = []
    passes: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    app_text = APP_PATH.read_text(encoding="utf-8")
    ui_text = MINA_UI_PATH.read_text(encoding="utf-8")
    try:
        ast.parse(app_text)
        ast.parse(ui_text)
        syntax_ok = True
    except SyntaxError:
        syntax_ok = False
    check(syntax_ok, "MINA operations UI sources parse as Python")

    check(
        'from ui.mina_operations import render_mina_operations' in app_text
        and '["MINA İşleri", "Yeni Talep", "Veri & Rehber"]' in app_text
        and "index=0" in app_text,
        "MINA jobs are the default development workspace",
    )
    check(
        "render_mina_job_list" in ui_text
        and "mina_job_status_filter" in ui_text
        and "mina_job_search" in ui_text
        and "İşi Aç" in ui_text,
        "main workspace lists filters searches and opens durable MINA jobs",
    )
    check(
        all(
            label in ui_text
            for label in (
                '"Genel"', '"Tedarikçiler"', '"Teklif"',
                '"Zaman Çizelgesi"', '"Kontroller"',
            )
        ),
        "job detail separates operational context into focused tabs",
    )

    check(
        "Tedarikçi Fiyatları" in ui_text
        and "Bu Fiyatı Kullan" in ui_text
        and "Manuel / Harici Fiyat Gir" in ui_text
        and "/supplier-prices/manual" in ui_text
        and "/supplier-prices/fixed-rate/" in ui_text,
        "supplier price sources fixed rates and manual price entry are wired to controlled APIs",
    )

    check(
        "Reminder Önizle" in ui_text
        and "Reminder'ı Şimdi Gönder" in ui_text
        and "/reminder-preview" in ui_text
        and "/reminder-now" in ui_text
        and "send_now_allowed" in ui_text,
        "supplier reminder preview and one-click early send are wired to controlled APIs",
    )
    check(
        "Bu işte otomatik supplier reminder'larını kapat" in ui_text
        and "Bu işte otomatik müşteri deadline bilgilendirmesini kapat" in ui_text
        and "/automation-overrides" in ui_text,
        "job-level automation disable overrides are visible and isolated",
    )
    check(
        "Müşteri kabul etti" in ui_text
        and "Operasyonu başlat" in ui_text
        and "Araç yola çıktı" in ui_text
        and "Teslim edildi" in ui_text
        and "Kapatma nedeni" in ui_text,
        "manual lifecycle controls cover acceptance operations transit delivery and closure",
    )

    check(
        "EVENT_LABELS" in ui_text
        and "event.get(\"actor\")" in ui_text
        and "st.json" not in ui_text,
        "timeline shows controlled event summaries without raw metadata dumps",
    )
    prohibited = (
        "MINAI_PILOT_TOKEN",
        "Authorization",
        "customer_target_price",
        "primary_price_negotiation_exhausted",
    )
    check(
        not any(value in ui_text for value in prohibited),
        "development UI does not embed pilot credentials or protected commercial evidence",
    )
    check(
        'ISTANBUL = ZoneInfo("Europe/Istanbul")' in ui_text
        and "astimezone(ISTANBUL)" in ui_text,
        "MINA timestamps render deterministically in Europe Istanbul",
    )
    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_mina_operations_ui_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print(
        "\nMINA operations UI regressions: "
        + ("PASS" if result["passed"] else "FAIL")
    )
    raise SystemExit(0 if result["passed"] else 1)
