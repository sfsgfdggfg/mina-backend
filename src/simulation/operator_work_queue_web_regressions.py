from __future__ import annotations

from pathlib import Path


def evaluate_operator_work_queue_web_regressions() -> dict:
    failures: list[str] = []
    passes: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    root = Path(__file__).resolve().parents[2]
    shell = (root / "src" / "web_shell.py").read_text(encoding="utf-8")
    js = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    css = (root / "ui" / "web_shell" / "app.css").read_text(encoding="utf-8")
    assignment_service = (root / "src" / "core" / "operational_work_assignment_service.py").read_text(encoding="utf-8")

    check(
        'href="/app/work">İş Kuyruğu</a>' in shell
        and '@router.get("/app/work")' in shell
        and 'page="work"' in shell,
        "pilot shell exposes operator work queue as a first-class authenticated workspace",
    )

    work_block = js.split("const WORK_TYPE_LABELS", 1)[1].split("function renderJobs", 1)[0]
    check(
        'api("/operational-work-queue")' in work_block
        and 'api("/operational-work-my")' in work_block
        and 'innerHTML' not in work_block,
        "work queue UI consumes backend authority and renders controlled text without dynamic HTML",
    )

    for suffix in ("assign-to-me", "acknowledge", "renew", "takeover", "release"):
        check(
            f'"{suffix}"' in work_block,
            f"work queue UI wires controlled {suffix} assignment mutation",
        )

    check(
        'APPROVAL_WORK_ACTIONS' in work_block
        and 'Bana Atananlar' in work_block
        and 'Onay Bekleyenler' in work_block
        and 'Sahipsiz Kritikler' in work_block,
        "operator queue offers bounded coordination views without changing backend priority order",
    )

    check(
        'first_look_seconds' in assignment_service
        and 'İlk bakış:' in work_block
        and 'tamamlandı olarak işaretlemez' in work_block,
        "first-look timing is backend-derived while release remains explicitly non-completion authority",
    )

    check(
        '.work-list' in css and '.work-card.critical' in css and '.work-first-look' in css,
        "operator work queue has responsive visual hierarchy for priority assignment and timing evidence",
    )

    return {
        "name": "Pilot operator work queue web workspace",
        "passed": not failures,
        "passes": passes,
        "failures": failures,
    }


if __name__ == "__main__":
    result = evaluate_operator_work_queue_web_regressions()
    for label in result["passes"]:
        print("PASS", label)
    for label in result["failures"]:
        print("FAIL", label)
    print("\nP2-11 operator work queue web regressions:", "PASS" if result["passed"] else "FAIL")
    raise SystemExit(0 if result["passed"] else 1)
