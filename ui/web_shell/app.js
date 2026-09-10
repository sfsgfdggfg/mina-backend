const content = document.getElementById("app-content");
const title = document.getElementById("page-title");
const statusPill = document.getElementById("status-pill");
const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";

function node(tag, text = "", className = "") {
  const el = document.createElement(tag);
  if (text !== "") el.textContent = String(text);
  if (className) el.className = className;
  return el;
}

function formatDate(value) {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return new Intl.DateTimeFormat("tr-TR", {
    dateStyle: "short", timeStyle: "short", timeZone: "Europe/Istanbul"
  }).format(parsed);
}

function formatDashboardDate(value, includeYear = false) {
  if (!value) return "-";
  const parsed = new Date(`${value}T12:00:00+03:00`);
  if (Number.isNaN(parsed.getTime())) return String(value);
  const options = { day: "numeric", month: "short", timeZone: "Europe/Istanbul" };
  if (includeYear) options.year = "numeric";
  return new Intl.DateTimeFormat("tr-TR", options).format(parsed);
}

function setStatus(text, ok = true) {
  statusPill.textContent = text;
  statusPill.style.color = ok ? "#127a55" : "#b42318";
}

const STAGE_LABELS = {
  intake: "Talep", inquiry_confirmed: "Talep Doğrulandı", pricing: "Fiyatlama",
  quote_ready: "Teklif Hazır", quote_sent: "Teklif Gönderildi", negotiation: "Müzakere",
  accepted: "Kabul Edildi", operations: "Operasyon", operation_opened: "Operasyon Açıldı",
  supplier_confirmation_pending: "Tedarikçi Teyidi", vehicle_details_pending: "Araç Bilgisi Bekleniyor",
  vehicle_assigned: "Araç Atandı", pre_loading_check: "Yükleme Öncesi Kontrol",
  ready_for_loading: "Yüklemeye Hazır", loaded: "Yüklendi", in_transit: "Yolda",
  delivery: "Teslimat", delivered: "Teslim Edildi", pod_cmr_pending: "POD/CMR Bekleniyor",
  closing_review: "Kapanış Kontrolü", completed: "Tamamlandı", lost: "Kaybedildi", cancelled: "İptal"
};

function stageLabel(value) { return STAGE_LABELS[value] || codeLabel(value); }
function modeLabel(value) {
  return ({ automatic: "Otomatik", approval_required: "Operatör Onayı", manual: "Manuel" })[value] || "Üst kural";
}
function policySourceLabel(value) {
  return ({ job: "Bu iş", job_legacy_disable: "Bu iş · devre dışı", supplier: "Tedarikçi", customer: "Müşteri", agency: "Ajans", legacy_dispatch: "Sistem varsayılanı" })[value] || codeLabel(value);
}
function transportLabel(value) {
  return ({ road: "Karayolu", rail: "Demiryolu", sea: "Denizyolu", air: "Havayolu", multimodal: "Multimodal" })[value] || codeLabel(value);
}
function reminderStateLabel(value) {
  return ({
    waiting: "Bekliyor", manual_reminder_due: "Manuel hatırlatma zamanı",
    approval_required_supplier_reminder_due: "Hatırlatma onay bekliyor", automatic_reminder_due: "Otomatik hatırlatma zamanı",
    human_contact_required: "Manuel tedarikçi takibi gerekli", waiting_supplier_contact_escalation: "Tedarikçi temas zamanı bekleniyor", outside_business_hours_waiting: "Çalışma saati bekleniyor",
    commercial_response_present: "Yanıt alındı", not_waiting_for_response: "Yanıt beklenmiyor",
    approval_rejected_no_send: "Hatırlatma reddedildi", automation_delivery_attention: "Gönderim hatası",
    automation_cancelled_manual_attention: "Manuel takip gerekli", missing_supplier_recipient_manual_attention: "Tedarikçi e-postası eksik",
    supplier_calendar_unavailable_manual_attention: "Çalışma takvimi doğrulanamadı", not_automation_eligible: "Otomasyon dışı",
    procurement_closed: "Fiyat toplama kapandı"
  })[value] || codeLabel(value);
}
function moneyLabel(value, currency = "") {
  if (value == null) return "-";
  const number = Number(value);
  return `${Number.isFinite(number) ? new Intl.NumberFormat("tr-TR", { maximumFractionDigits: 2 }).format(number) : value} ${currency || ""}`.trim();
}
function setPageContext(pageTitle, eyebrow = "Operasyon Merkezi") {
  title.textContent = pageTitle;
  const eyebrowNode = document.querySelector(".eyebrow");
  if (eyebrowNode) eyebrowNode.textContent = eyebrow;
}
function markActiveNavigation(page) {
  const target = page === "job" ? "/app/jobs" : `/app/${page === "dashboard" ? "dashboard" : page}`;
  document.querySelectorAll("nav a").forEach(link => {
    link.classList.toggle("active", link.getAttribute("href") === target);
  });
}
function emptyState(titleText, detailText = "") {
  const box = node("div", "", "empty-state");
  box.append(node("strong", titleText));
  if (detailText) box.append(node("span", detailText));
  return box;
}
function formatDateOnly(value) {
  if (!value) return "-";
  const raw = String(value).slice(0, 10);
  const parsed = new Date(`${raw}T12:00:00+03:00`);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "short", year: "numeric", timeZone: "Europe/Istanbul" }).format(parsed);
}

async function api(path, options = {}) {
  const config = { credentials: "same-origin", ...options };
  config.headers = { Accept: "application/json", ...(options.headers || {}) };
  const method = (config.method || "GET").toUpperCase();
  if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
    config.headers["X-CSRF-Token"] = csrfToken;
    if (config.body && !config.headers["Content-Type"]) {
      config.headers["Content-Type"] = "application/json";
    }
  }
  const response = await fetch(path, config);
  if (response.status === 401) {
    window.location.assign("/app/login");
    throw new Error("Oturum sona erdi.");
  }
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try { detail = (await response.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return response.json();
}

function showError(error) {
  content.replaceChildren(node("div", error.message || String(error), "error"));
  setStatus("Hata", false);
}

function dashboardJobTarget(jobId) {
  window.location.assign(`/app/jobs/${encodeURIComponent(jobId)}`);
}

function dashboardEntry(entry) {
  const card = node("button", "", `calendar-entry ${entry.has_attention ? "attention" : ""}`);
  card.type = "button";
  const top = node("div", "", "calendar-entry-top");
  top.append(node("strong", entry.mina_code || "MINA"), node("span", entry.label || entry.kind || "-", "badge"));
  card.append(top);
  card.append(node("div", entry.customer_name || "-", "calendar-customer"));
  card.append(node("div", entry.route || "-", "small"));
  const when = entry.all_day ? "Tüm gün" : formatDate(entry.at);
  card.append(node("div", when, "calendar-time"));
  card.addEventListener("click", () => dashboardJobTarget(entry.job_id));
  return card;
}

function attentionCard(item, unscheduled = false) {
  const severity = unscheduled ? "warning" : (item.severity || "");
  const card = node("button", "", `attention-card ${severity}`);
  card.type = "button";
  card.append(node("strong", `${item.mina_code || "MINA"} · ${item.customer_name || "-"}`));
  card.append(node("div", item.route || "-", "small"));
  const reasons = unscheduled
    ? ["Plan tarihi eksik", item.reason || "Kesin tarih bekleniyor"]
    : (item.reasons || []);
  card.append(node("div", reasons.join(" · "), "attention-reason"));
  card.addEventListener("click", () => dashboardJobTarget(item.job_id));
  return card;
}

function appendDashboardEntries(column, entries, selectedDays) {
  const visibleLimit = selectedDays === 5 ? 2 : 4;
  const cards = entries.map(dashboardEntry);
  cards.forEach((card, index) => {
    if (index >= visibleLimit) card.hidden = true;
    column.append(card);
  });
  if (cards.length <= visibleLimit) return;
  const hiddenCount = cards.length - visibleLimit;
  const more = actionButton(`+${hiddenCount} kayıt daha`, "calendar-more", () => {
    const collapsed = cards.slice(visibleLimit).some(card => card.hidden);
    cards.slice(visibleLimit).forEach(card => { card.hidden = !collapsed; });
    more.textContent = collapsed ? "Daralt" : `+${hiddenCount} kayıt daha`;
  });
  column.append(more);
}

function renderDashboard(data, selectedDays = 5) {
  title.textContent = "Ana Ekran";
  const root = node("div", "", "dashboard");
  const summary = data.summary || {};
  const metrics = node("div", "", "grid dashboard-metrics");
  metrics.append(
    metric("Aktif iş", summary.active_jobs ?? 0),
    metric("Takvim olayı", summary.calendar_entries ?? 0),
    metric("Dikkat gereken", summary.attention_jobs ?? 0),
    metric("Tarihi net değil", summary.unscheduled_jobs ?? 0)
  );
  root.append(metrics);

  const attention = data.attention || [];
  const unscheduled = data.unscheduled || [];
  const attentionSection = node("section", "", "dashboard-attention");
  if (attention.length || unscheduled.length) {
    attentionSection.append(node("h2", "Dikkat Gerekenler"));
    const attentionGrid = node("div", "", "attention-grid dashboard-attention-grid");
    const unscheduledByJob = new Map(unscheduled.map(item => [item.job_id, item]));
    attention.forEach(item => {
      const missing = unscheduledByJob.get(item.job_id);
      if (missing) {
        const merged = { ...item, reasons: [...(item.reasons || []), "Plan tarihi eksik", missing.reason || "Kesin tarih bekleniyor"] };
        attentionGrid.append(attentionCard(merged));
        unscheduledByJob.delete(item.job_id);
      } else {
        attentionGrid.append(attentionCard(item));
      }
    });
    unscheduledByJob.forEach(item => attentionGrid.append(attentionCard(item, true)));
    attentionSection.append(attentionGrid);
  } else {
    const clear = node("div", "", "dashboard-clear");
    clear.append(
      node("strong", "Dikkat Gerekenler"),
      node("span", "Kritik, riskli veya plan tarihi eksik aktif kayıt yok.")
    );
    attentionSection.append(clear);
  }
  root.append(attentionSection);

  const toolbar = node("div", "", "dashboard-toolbar");
  const period = node("div", "", "dashboard-period");
  period.append(node("h2", "Operasyon Takvimi"));
  period.append(node(
    "div",
    `${formatDashboardDate(data.anchor_date, true)} → ${formatDashboardDate(data.window_end_date, true)}`,
    "small"
  ));
  const controls = node("div", "", "segment-control");
  [3, 5].forEach(days => {
    const button = actionButton(`${days} Gün`, days === selectedDays ? "active" : "", () => loadDashboard(days));
    controls.append(button);
  });
  toolbar.append(period, controls); root.append(toolbar);

  const calendar = node("div", "", `calendar-grid days-${selectedDays}`);
  (data.days || []).forEach(day => {
    const column = node("section", "", `calendar-day ${day.is_today ? "today" : ""}`);
    const heading = node("div", "", "calendar-day-heading");
    heading.append(node("strong", day.weekday || ""), node("span", formatDashboardDate(day.date), "small"));
    column.append(heading);
    const entries = day.entries || [];
    appendDashboardEntries(column, entries, selectedDays);
    if (!entries.length) column.append(node("div", "Planlı kayıt yok", "calendar-empty"));
    calendar.append(column);
  });
  root.append(calendar);
  content.replaceChildren(root);
}

async function loadDashboard(days = 5) {
  try {
    const data = await api(`/operations-dashboard?days=${days}`);
    renderDashboard(data, days); setStatus("Güncel");
  } catch (error) { showError(error); }
}


const WORK_TYPE_LABELS = {
  attachment_review: "Ek inceleme",
  customer_extraction_confirmation: "Talep doğrulama",
  supplier_follow_up: "Tedarikçi takip",
  supplier_clarification_gap: "Tedarikçi açıklama",
  supplier_contact_escalation: "Tedarikçi eskalasyon",
  customer_deadline_update: "Müşteri bilgilendirme",
  quote_approval: "Teklif onayı",
  operation_start_message: "Operasyon başlangıcı",
};

const WORK_ACTION_LABELS = {
  inspect_attachment_review: "Eki incele",
  confirm_extraction: "Talebi doğrula",
  approve_supplier_follow_up: "Tedarikçi takibini onayla",
  send_supplier_follow_up: "Tedarikçi takibini gönder",
  inspect_supplier_follow_up: "Tedarikçi takip durumunu incele",
  inspect_supplier_clarification: "Tedarikçi açıklamasını incele",
  send_supplier_reminder_manually: "Tedarikçiye manuel hatırlatma gönder",
  review_and_approve_supplier_reminder: "Tedarikçi hatırlatmasını onayla",
  contact_supplier_phone_or_whatsapp: "Tedarikçiyi ara / WhatsApp ile takip et",
  contact_supplier_using_profile: "Tedarikçiyi profilindeki kanalla takip et",
  inspect_supplier_automation_delivery: "Tedarikçi gönderim hatasını incele",
  inspect_supplier_automation_state: "Tedarikçi otomasyon durumunu incele",
  inspect_supplier_contact_data: "Tedarikçi iletişim bilgisini kontrol et",
  inspect_supplier_calendar: "Tedarikçi çalışma takvimini kontrol et",
  contact_customer_manually: "Müşteriyi bilgilendir",
  review_and_approve_customer_update: "Müşteri bilgilendirmesini onayla",
  inspect_customer_update_delivery: "Müşteri gönderim hatasını incele",
  inspect_customer_update_state: "Müşteri otomasyon durumunu incele",
  inspect_customer_contact_data: "Müşteri iletişim bilgisini kontrol et",
  decide_quote_approval: "Teklif onayını kararlaştır",
  inspect_quote_approval_state: "Teklif onayı durumunu incele",
  retry_operation_start_message: "Operasyon e-postasını yeniden gönder",
  inspect_operation_start_send_reservation: "Operasyon maili gönderim sonucunu kontrol et",
  approve_selected_supplier_operation_email: "Tedarikçi onay / toplama mailini onayla",
  approve_supplier_closure_email: "Tedarikçi teşekkür kapanışını onayla",
  send_selected_supplier_operation_email_manually: "Onay / toplama mailini manuel gönder",
  send_supplier_closure_email_manually: "Tedarikçi kapanışını manuel gönder",
};

const APPROVAL_WORK_ACTIONS = new Set([
  "confirm_extraction",
  "approve_supplier_follow_up",
  "review_and_approve_supplier_reminder",
  "review_and_approve_customer_update",
  "decide_quote_approval",
  "approve_selected_supplier_operation_email",
  "approve_supplier_closure_email",
]);

const WORK_PRIORITY_LABELS = {
  critical: "Kritik",
  high: "Yüksek",
  normal: "Normal",
  low: "Düşük",
};

let operationalWorkView = "all";

function codeLabel(value) {
  return String(value || "-").replaceAll("_", " ");
}

function workTypeLabel(item) {
  return WORK_TYPE_LABELS[item.work_type] || codeLabel(item.work_type);
}

function workActionLabel(item) {
  return WORK_ACTION_LABELS[item.next_action] || codeLabel(item.next_action);
}

function durationLabel(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  if (value < 60) return `${Math.floor(value)} sn`;
  if (value < 3600) return `${Math.floor(value / 60)} dk`;
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  return minutes ? `${hours} sa ${minutes} dk` : `${hours} sa`;
}

function ageLabel(item) {
  const hours = item.age_hours;
  if (hours == null) return "Bekleme süresi bilinmiyor";
  if (hours < 1) return "1 saatten azdır bekliyor";
  if (hours < 24) return `${hours} saattir bekliyor`;
  return `${Math.floor(hours / 24)} gün ${hours % 24} saattir bekliyor`;
}

function isApprovalWork(item) {
  return APPROVAL_WORK_ACTIONS.has(item.next_action);
}

async function mutateOperationalWork(item, suffix, refresh, confirmText = "") {
  if (confirmText && !window.confirm(confirmText)) return;
  try {
    await api(`/operational-work-items/${encodeURIComponent(item.work_id)}/${suffix}`, { method: "POST" });
    await refresh();
  } catch (error) {
    showError(error);
  }
}

function workAssignmentSummary(item, isMine) {
  const status = item.assignment_status || "unassigned";
  if (status === "unassigned") return "Sahipsiz";
  if (status === "expired") return `${item.assigned_to || "Atanan kişi"} · atama süresi doldu`;
  const remaining = item.lease_seconds_remaining == null
    ? ""
    : ` · ${durationLabel(item.lease_seconds_remaining)} kaldı`;
  const owner = isMine ? "Bende" : (item.assigned_to || "Atandı");
  return `${owner}${remaining}`;
}

function workCard(item, myIds, refresh, operators = []) {
  const isMine = myIds.has(item.work_id);
  const card = node("article", "", `work-card ${item.priority_band || "normal"}`);
  const heading = node("div", "", "work-card-heading");
  const headingText = node("div");
  headingText.append(
    node("div", workTypeLabel(item), "work-type"),
    node("strong", workActionLabel(item), "work-action")
  );
  const priority = node("span", WORK_PRIORITY_LABELS[item.priority_band] || "Normal", `badge priority-${item.priority_band || "normal"}`);
  heading.append(headingText, priority);
  card.append(heading);

  const meta = node("div", "", "work-meta");
  meta.append(
    node("span", ageLabel(item)),
    node("span", `Skor ${item.priority_score ?? "-"}`),
    node("span", `Alan: ${codeLabel(item.route)}`)
  );
  if ((item.blocker_count || 0) > 0) meta.append(node("span", `${item.blocker_count} blocker`, "work-blocker"));
  if ((item.warning_count || 0) > 0) meta.append(node("span", `${item.warning_count} uyarı`, "work-warning"));
  card.append(meta);

  const assignment = node("div", "", "work-assignment");
  assignment.append(node("strong", "Atama"), node("span", workAssignmentSummary(item, isMine)));
  if (item.first_look_seconds != null) {
    assignment.append(node("span", `İlk bakış: ${durationLabel(item.first_look_seconds)}`, "work-first-look"));
  } else if (isMine && item.assignment_status === "assigned") {
    assignment.append(node("span", "İlk bakış henüz kaydedilmedi", "work-first-look pending"));
  }
  card.append(assignment);

  const actions = node("div", "", "actions work-actions");
  if (item.assignment_status === "unassigned") {
    actions.append(actionButton("Üstlen", "approve", () => mutateOperationalWork(item, "assign-to-me", refresh)));
  } else if (item.assignment_status === "expired") {
    actions.append(actionButton("Devral", "approve", () => mutateOperationalWork(item, "takeover", refresh)));
  } else if (isMine && item.assignment_status === "assigned") {
    actions.append(actionButton("Gördüm / Üzerindeyim", "approve", () => mutateOperationalWork(item, "acknowledge", refresh)));
  } else if (isMine && item.assignment_status === "acknowledged") {
    actions.append(actionButton("Süreyi Yenile", "", () => mutateOperationalWork(item, "renew", refresh)));
  }
  if (isMine && ["assigned", "acknowledged"].includes(item.assignment_status)) {
    actions.append(actionButton(
      "Bırak", "",
      () => mutateOperationalWork(item, "release", refresh, "Bu işi sahipsiz bırakmak istiyor musun? Bu işlem işi tamamlandı olarak işaretlemez.")
    ));
  }
  if (operators.length > 1) {
    const assignWrap = node("div", "", "direct-assign");
    const select = document.createElement("select");
    const placeholder = document.createElement("option"); placeholder.value = ""; placeholder.textContent = "Başka operatöre ata…"; select.append(placeholder);
    operators.forEach(operator => {
      const option = document.createElement("option"); option.value = operator.email; option.textContent = operator.operator_name; select.append(option);
    });
    const assign = actionButton("Ata", "", async () => {
      if (!select.value) return;
      assign.disabled = true;
      try {
        await api(`/operational-work-items/${encodeURIComponent(item.work_id)}/assign`, {
          method: "POST", body: JSON.stringify({ target_email: select.value })
        });
        await refresh();
      } catch (error) { showError(error); }
      finally { assign.disabled = false; }
    });
    assignWrap.append(select, assign); card.append(assignWrap);
  }
  if (actions.childElementCount) card.append(actions);
  return card;
}

function renderOperationalWork(queue, mine, operatorsPayload = {}) {
  title.textContent = "İş Kuyruğu";
  const root = node("div", "", "work-page");
  const items = queue.items || [];
  const operators = operatorsPayload.operators || [];
  const myIds = new Set((mine.items || []).map(item => item.work_id));
  const approvalCount = items.filter(isApprovalWork).length;
  const unassignedCriticalCount = items.filter(item =>
    item.priority_band === "critical" && item.assignment_status === "unassigned"
  ).length;

  const metrics = node("div", "", "grid work-metrics");
  metrics.append(
    metric("Açık iş", queue.pending_count ?? items.length),
    metric("Bana atanan", mine.active_count ?? myIds.size),
    metric("Onay bekleyen", approvalCount),
    metric("Sahipsiz kritik", unassignedCriticalCount)
  );
  root.append(metrics);

  root.append(node(
    "div",
    "Atama koordinasyon içindir. Bir işi bırakmak veya devretmek, o işi tamamlandı olarak işaretlemez.",
    "notice work-authority-note"
  ));

  const filters = [
    ["all", "Tümü", item => true],
    ["mine", "Bana Atananlar", item => myIds.has(item.work_id)],
    ["approval", "Onay Bekleyenler", item => isApprovalWork(item)],
    ["critical", "Sahipsiz Kritikler", item => item.priority_band === "critical" && item.assignment_status === "unassigned"],
  ];
  const tabs = node("div", "", "work-tabs");
  for (const [key, label, predicate] of filters) {
    const count = items.filter(predicate).length;
    tabs.append(actionButton(`${label} · ${count}`, key === operationalWorkView ? "active" : "", () => {
      operationalWorkView = key;
      renderOperationalWork(queue, mine, operatorsPayload);
    }));
  }
  root.append(tabs);

  const activeFilter = filters.find(([key]) => key === operationalWorkView) || filters[0];
  const visible = items.filter(activeFilter[2]);
  const list = node("div", "", "work-list");
  const refresh = () => loadOperationalWork(operationalWorkView);
  visible.forEach(item => list.append(workCard(item, myIds, refresh, operators)));
  if (!visible.length) list.append(node("div", "Bu görünümde bekleyen iş yok.", "work-empty"));
  root.append(list);
  content.replaceChildren(root);
}

async function loadOperationalWork(view = operationalWorkView) {
  operationalWorkView = view;
  const [queue, mine, operatorsPayload] = await Promise.all([
    api("/operational-work-queue"),
    api("/operational-work-my"),
    api("/operators"),
  ]);
  renderOperationalWork(queue, mine, operatorsPayload);
  setStatus("Güncel");
}


function inboxField(labelText, type = "text") {
  const label = node("label", labelText, "inbox-field");
  const input = document.createElement("input");
  input.type = type;
  label.append(input);
  return { label, input };
}

const DEMO_INBOUND_TEMPLATES = [
  {
    key: "ftl", label: "Tam FTL talebi", sender: "atlas@atlas-tekstil.customer.invalid",
    name: "Atlas Tekstil", subject: "Adana Hamburg komple araç fiyat talebi",
    body: "DEMO:FTL\nMerhaba, 11 Eylül yüklemeli Adana-Hamburg 20 ton tekstil için tenteli komple araç fiyatı rica ederiz. Teslim 16 Eylül. Fiyatı bugün içinde bekliyoruz."
  },
  {
    key: "machine", label: "Eksik bilgili makina", sender: "lojistik@mavi-makina.customer.invalid",
    name: "Mavi Makina", subject: "Bursa Stuttgart makina taşıması",
    body: "DEMO:MACHINE\nMerhaba, Bursa'dan Stuttgart'a yaklaşık 3 ton makina taşıması için fiyat rica ederiz. Makina ölçülerini henüz paylaşamıyoruz."
  },
  {
    key: "reefer", label: "Acil reefer", sender: "export@nova-gida.customer.invalid",
    name: "Nova Gıda", subject: "Mersin Münih +4 derece acil fiyat",
    body: "DEMO:REEFER\nMerhaba, Mersin-Münih 18 ton gıda, +4°C reefer. 11 Eylül yükleme, 15 Eylül teslim. İki saat içinde fiyat rica ederiz."
  },
];

function shipmentSummary(shipment = {}) {
  const wrap = node("div", "", "inbox-shipment-summary");
  const route = `${shipment.pickup_city || shipment.pickup_country || "?"} → ${shipment.delivery_city || shipment.delivery_country || "?"}`;
  wrap.append(
    summaryItem("Müşteri", shipment.customer_name || "-"),
    summaryItem("Rota", route),
    summaryItem("Yük", shipment.commodity || "-"),
    summaryItem("Ağırlık", shipment.gross_weight_kg == null ? "-" : `${shipment.gross_weight_kg} kg`),
    summaryItem("Taşıma", transportLabel(shipment.transport_mode)),
    summaryItem("Ekipman", shipment.equipment_type || "-")
  );
  return wrap;
}

function inboxProposalCard(proposal, refresh) {
  const card = node("article", "", "inbox-proposal-card");
  const mail = proposal.inbound_mail || {};
  const shipment = proposal.confirmed_shipment || proposal.proposed_shipment || {};
  const head = node("div", "", "inbox-proposal-head");
  const htext = node("div");
  htext.append(node("strong", mail.subject || "Konusuz talep"), node("div", `${mail.sender_name || shipment.customer_name || "-"} · ${mail.sender_address || "-"}`, "small muted"));
  const status = proposal.extraction_status === "confirmed" ? (proposal.resume_status === "completed" ? "Akış başladı" : "Doğrulandı") : "Doğrulama bekliyor";
  head.append(htext, node("span", status, `badge ${proposal.extraction_status === "confirmed" ? "open" : ""}`));
  card.append(head, shipmentSummary(shipment));

  const unknown = proposal.unknown_fields || [];
  if (unknown.length) card.append(node("div", `Eksik/Belirsiz alanlar: ${unknown.join(", ")}`, "notice inbox-unknown"));
  if (proposal.changed_fields?.length) card.append(node("div", `Operatör düzeltmeleri: ${proposal.changed_fields.join(", ")}`, "small muted"));
  if (proposal.mina_code) card.append(node("div", `MINA işi: ${proposal.mina_code}`, "inbox-mina-code"));

  const feedback = node("div", "", "muted settings-feedback");
  const actions = node("div", "", "actions inbox-actions");
  if (proposal.extraction_status === "proposed") {
    actions.append(actionButton("Doğrula ve MINA işi oluştur", "primary", async () => {
      actions.querySelectorAll("button").forEach(btn => btn.disabled = true);
      feedback.textContent = "Doğrulanıyor…";
      try {
        const confirmed = await api(`/extraction-proposals/${encodeURIComponent(proposal.proposal_id)}/confirm`, {method:"POST", body:JSON.stringify({corrections:{}})});
        feedback.textContent = `${confirmed.mina_code || "MINA işi"} oluşturuldu.`;
        await refresh();
      } catch (e) { feedback.textContent = e.message || String(e); setStatus("Hata", false); }
    }));
  } else if (proposal.resume_status !== "completed") {
    actions.append(actionButton("Operasyon akışını devam ettir", "primary", async () => {
      actions.querySelectorAll("button").forEach(btn => btn.disabled = true);
      feedback.textContent = "MINAI pipeline çalışıyor…";
      try {
        const result = await api(`/extraction-proposals/${encodeURIComponent(proposal.proposal_id)}/resume`, {method:"POST"});
        const type = result.result_type || result.downstream_result_type || "işlendi";
        feedback.textContent = `Pipeline sonucu: ${codeLabel(type)}`;
        await refresh();
      } catch (e) { feedback.textContent = e.message || String(e); setStatus("Hata", false); }
    }));
  } else if (proposal.mina_job_id) {
    actions.append(actionButton("MINA işini aç", "", () => window.location.assign(`/app/jobs/${encodeURIComponent(proposal.mina_job_id)}`)));
  }
  card.append(actions, feedback);
  return card;
}

function renderInbox(proposals = []) {
  setPageContext("Gelen Talepler", "Müşteri Talep Girişi");
  const root = node("div", "", "inbox-page");
  const intro = node("div", "", "notice");
  intro.textContent = "Demo ortamında aşağıdaki sentetik müşteri mailleri gerçek extraction → operatör doğrulaması → MINA işi → operasyon pipeline zincirini çalıştırır. Extraction tek başına operasyonel gerçek sayılmaz.";
  root.append(intro);

  const composer = node("section", "", "section inbox-composer");
  composer.append(node("h2", "Yeni müşteri talebi simüle et"));
  const templateBar = node("div", "", "actions inbox-template-actions");
  const senderName = inboxField("Gönderen adı");
  const senderEmail = inboxField("Gönderen e-posta", "email");
  const subject = inboxField("Konu");
  const bodyLabel = node("label", "E-posta içeriği", "inbox-field inbox-body-field");
  const body = document.createElement("textarea"); body.rows = 7; bodyLabel.append(body);
  function loadTemplate(template) {
    senderName.input.value = template.name; senderEmail.input.value = template.sender;
    subject.input.value = template.subject; body.value = template.body;
  }
  DEMO_INBOUND_TEMPLATES.forEach(template => templateBar.append(actionButton(template.label, "", () => loadTemplate(template))));
  loadTemplate(DEMO_INBOUND_TEMPLATES[0]);
  const fields = node("div", "", "settings-two-col");
  fields.append(senderName.label, senderEmail.label, subject.label); composer.append(templateBar, fields, bodyLabel);
  const composeFeedback = node("div", "", "muted settings-feedback");
  const submit = actionButton("Talebi MINAI'ye al", "primary", async () => {
    if (!body.value.trim() || !senderEmail.input.value.trim()) { composeFeedback.textContent = "Gönderen e-posta ve mail içeriği gerekli."; return; }
    submit.disabled = true; composeFeedback.textContent = "Talep işleniyor…";
    try {
      const externalId = `demo-inbound-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      const result = await api("/process-email", {method:"POST", body:JSON.stringify({
        email_text:body.value, sender_address:senderEmail.input.value.trim(), sender_name:senderName.input.value.trim() || null,
        subject:subject.input.value.trim() || null, external_message_id:externalId
      })});
      composeFeedback.textContent = result.ingestion_status === "created" ? "Extraction önerisi oluşturuldu; aşağıdan doğrulayabilirsin." : `Talep durumu: ${codeLabel(result.ingestion_status)}`;
      await loadInbox();
    } catch (e) { composeFeedback.textContent = e.message || String(e); setStatus("Hata", false); }
    finally { submit.disabled = false; }
  });
  composer.append(submit, composeFeedback); root.append(composer);

  const queue = node("section", "", "section inbox-queue");
  const proposedCount = proposals.filter(item => item.extraction_status === "proposed").length;
  queue.append(node("h2", `Extraction Kuyruğu · ${proposals.length}`), node("div", `${proposedCount} talep operatör doğrulaması bekliyor.`, "small muted"));
  const list = node("div", "", "inbox-proposal-list");
  proposals.forEach(item => list.append(inboxProposalCard(item, loadInbox)));
  if (!proposals.length) list.append(emptyState("Henüz gelen talep yok", "Yukarıdaki sentetik senaryolardan biriyle başlayabilirsin."));
  queue.append(list); root.append(queue); content.replaceChildren(root); setStatus("Güncel");
}

async function loadInbox() {
  const payload = await api("/extraction-proposals");
  renderInbox(payload.proposals || []);
}

function renderJobs(data) {
  setPageContext("MINA İşleri");
  const jobs = data.jobs || [];
  const openJobs = jobs.filter(job => !job.is_closed);
  const metrics = node("div", "", "grid jobs-metrics");
  metrics.append(
    metric("Aktif iş", openJobs.length),
    metric("Kapalı iş", jobs.length - openJobs.length),
    metric("Toplam", jobs.length)
  );

  const toolbar = node("div", "", "toolbar jobs-toolbar");
  const search = document.createElement("input");
  search.type = "search";
  search.placeholder = "MINA kodu, müşteri, rota veya sorumlu ara";
  search.setAttribute("aria-label", "MINA işleri ara");
  const scope = document.createElement("select");
  scope.setAttribute("aria-label", "İş durumu filtresi");
  [["open", "Aktif"], ["all", "Tümü"], ["closed", "Kapalı"]].forEach(([value, label]) => {
    const option = document.createElement("option"); option.value = value; option.textContent = label; scope.append(option);
  });
  toolbar.append(search, scope);

  const resultNote = node("div", "", "muted jobs-result-note");
  const desktopWrap = node("div", "", "table-wrap jobs-table");
  const table = document.createElement("table");
  table.innerHTML = "<thead><tr><th>İş</th><th>Müşteri</th><th>Rota</th><th>Aşama</th><th>Operasyon</th><th>Güncelleme</th></tr></thead>";
  const body = document.createElement("tbody"); table.append(body); desktopWrap.append(table);
  const cards = node("div", "", "jobs-card-list");
  const results = node("div"); results.append(resultNote, desktopWrap, cards);
  content.replaceChildren(metrics, toolbar, results);

  function openJob(job) { window.location.assign(`/app/jobs/${encodeURIComponent(job.job_id)}`); }
  function draw() {
    body.replaceChildren(); cards.replaceChildren();
    const q = search.value.trim().toLocaleLowerCase("tr-TR");
    const filtered = jobs.filter(job => {
      const scopeMatch = scope.value === "all" || (scope.value === "open" && !job.is_closed) || (scope.value === "closed" && job.is_closed);
      const textMatch = !q || [job.mina_code, job.customer_name, job.route, job.stage, job.operations_owner, job.sales_owner]
        .some(v => String(v || "").toLocaleLowerCase("tr-TR").includes(q));
      return scopeMatch && textMatch;
    });
    resultNote.textContent = `${filtered.length} iş gösteriliyor`;
    for (const job of filtered) {
      const tr = node("tr", "", "clickable");
      tr.append(node("td", job.mina_code), node("td", job.customer_name || "-"), node("td", job.route || "-"));
      const stage = node("span", stageLabel(job.stage), `badge ${job.is_closed ? "" : "open"}`);
      const stageTd = node("td"); stageTd.append(stage); tr.append(stageTd);
      tr.append(node("td", job.operations_owner || "-"), node("td", formatDate(job.updated_at)));
      tr.addEventListener("click", () => openJob(job)); body.append(tr);

      const card = node("button", "", "job-list-card"); card.type = "button";
      const head = node("div", "", "job-list-card-head");
      head.append(node("strong", job.mina_code), node("span", stageLabel(job.stage), `badge ${job.is_closed ? "" : "open"}`));
      card.append(head, node("div", job.customer_name || "-", "job-list-customer"), node("div", job.route || "-", "small"));
      const foot = node("div", "", "job-list-card-foot");
      foot.append(node("span", job.operations_owner || "Sorumlu yok"), node("span", formatDate(job.updated_at)));
      card.append(foot); card.addEventListener("click", () => openJob(job)); cards.append(card);
    }
    if (!filtered.length) {
      const tr = document.createElement("tr");
      const td = node("td", "Eşleşen MINA işi yok · arama veya durum filtresini değiştir.", "muted jobs-empty-cell");
      td.colSpan = 6; tr.append(td); body.append(tr);
      cards.append(emptyState("Eşleşen MINA işi yok", "Arama veya durum filtresini değiştir."));
    }
  }
  search.addEventListener("input", draw); scope.addEventListener("change", draw); draw();
}

function summaryItem(label, value) {
  const item = node("div", "", "summary-item");
  item.append(node("span", label), node("strong", value ?? "-"));
  return item;
}

function actionButton(label, className, handler) {
  const button = node("button", label, className);
  button.type = "button";
  button.addEventListener("click", handler);
  return button;
}

async function postDecision(path, decision, reason = null) {
  const body = { decision };
  if (reason) body.reason = reason;
  return api(path, { method: "POST", body: JSON.stringify(body) });
}

function approvalPreviewCard(preview, approvePath, onDone) {
  const card = node("div", "", "approval-card approval-focused");
  card.append(node("h3", preview.subject || "Onay bekleyen mesaj"));
  card.append(node("div", preview.body_text || "", "preview approval-message-body"));
  const feedback = node("div", "", "muted approval-feedback");
  const actions = node("div", "", "actions approval-primary-actions");
  const approve = actionButton("Onayla ve Gönder", "approve", async () => {
    approve.disabled = true; reject.disabled = true; feedback.textContent = "Gönderim yeniden doğrulanıyor…";
    try { await postDecision(approvePath, "approve"); feedback.textContent = "Onaylandı."; await onDone(); }
    catch (error) { feedback.textContent = error.message || String(error); approve.disabled = false; reject.disabled = false; }
  });
  const reject = actionButton("Reddet", "reject", () => {
    rejectPanel.hidden = false; reason.focus();
  });
  actions.append(approve, reject);

  const rejectPanel = node("div", "", "approval-reject-panel"); rejectPanel.hidden = true;
  const reasonLabel = node("label", "Reddetme nedeni");
  const reason = document.createElement("textarea"); reason.maxLength = 800; reason.rows = 3;
  reason.placeholder = "Kısa ve operasyonel bir neden yaz"; reasonLabel.append(reason);
  const rejectActions = node("div", "", "actions");
  const cancelReject = actionButton("Vazgeç", "", () => { rejectPanel.hidden = true; reason.value = ""; });
  const confirmReject = actionButton("Reddi Kaydet", "reject", async () => {
    const value = reason.value.trim();
    if (!value) { feedback.textContent = "Reddetme nedeni gerekli."; return; }
    confirmReject.disabled = true; approve.disabled = true; feedback.textContent = "Red kararı kaydediliyor…";
    try { await postDecision(approvePath, "reject", value); feedback.textContent = "Reddedildi."; await onDone(); }
    catch (error) { feedback.textContent = error.message || String(error); confirmReject.disabled = false; approve.disabled = false; }
  });
  rejectActions.append(cancelReject, confirmReject); rejectPanel.append(reasonLabel, rejectActions);
  card.append(actions, rejectPanel, feedback); return card;
}

function reminderPreviewCard(preview, sendPath, onDone) {
  const card = node("div", "", "approval-card approval-focused reminder-preview-card");
  card.append(node("h3", preview.subject || "Tedarikçi hatırlatması"));
  card.append(node("div", preview.body_text || "", "preview approval-message-body"));
  const evidence = node("div", "", "approval-evidence-row");
  evidence.append(node("span", `Planlanan zaman: ${formatDate(preview.planned_due_at)}`, "small"));
  if (!preview.send_now_allowed && preview.next_supplier_open_at) {
    evidence.append(node("span", `Sonraki çalışma başlangıcı: ${formatDate(preview.next_supplier_open_at)}`, "small work-warning"));
  }
  card.append(evidence);
  const feedback = node("div", "", "muted approval-feedback");
  if (preview.send_now_allowed) {
    const actions = node("div", "", "actions");
    const send = actionButton("Şimdi Hatırlat", "approve", async () => {
      send.disabled = true; feedback.textContent = "Gönderim öncesi kurallar yeniden doğrulanıyor…";
      try { await api(sendPath, { method: "POST" }); feedback.textContent = "Hatırlatma gönderildi."; await onDone(); }
      catch (error) { feedback.textContent = error.message || String(error); send.disabled = false; }
    });
    actions.append(send); card.append(actions);
  } else {
    card.append(node("div", "Tedarikçi iletişim saatleri dışında gönderim yapılamaz.", "notice"));
  }
  card.append(feedback); return card;
}

async function renderSupplier(container, jobId, supplier, refresh, effectivePolicy = null) {
  const card = node("div", "", "supplier-card");
  const head = node("div", "", "supplier-card-head");
  head.append(node("h3", supplier.supplier_name || "Tedarikçi"), node("span", supplier.dispatch_tier || "-", "badge"));
  card.append(head);
  const facts = node("div", "", "supplier-facts");
  facts.append(
    summaryItem("Durum", codeLabel(supplier.status)),
    summaryItem("Gönderildi", formatDate(supplier.sent_at)),
    summaryItem("Görüldü/Teyit", formatDate(supplier.latest_acknowledgement_at)),
    summaryItem("Yanıt", formatDate(supplier.responded_at))
  );
  card.append(facts);
  if (supplier.commercial_response) {
    const response = supplier.commercial_response;
    const commercial = node("div", "", "supplier-commercial");
    commercial.append(
      node("strong", moneyLabel(response.cost, response.currency)),
      node("span", response.transit_time ? `Transit: ${response.transit_time}` : "Transit: -", "small"),
      node("span", `Yanıt: ${codeLabel(response.status)}`, "small")
    );
    card.append(commercial);
  }

  if (supplier.status === "send_outcome_unknown") {
    card.append(sendOutcomeReconciliationBox({
      title: "Tedarikçi fiyat talebi gönderimini doğrula",
      endpoint: `/supplier-rfqs/${encodeURIComponent(supplier.rfq_id)}/send-reconciliation`,
      refresh,
    }));
  }
  if (supplier.status === "clarification_required") {
    try {
      const rfqDetail = await api(`/supplier-rfqs/${encodeURIComponent(supplier.rfq_id)}`);
      const unknownFollowUp = (rfqDetail.follow_ups || []).find(item => item.status === "send_outcome_unknown");
      if (unknownFollowUp) card.append(sendOutcomeReconciliationBox({
        title: "Tedarikçi takip maili gönderimini doğrula",
        endpoint: `/supplier-rfq-follow-ups/${encodeURIComponent(unknownFollowUp.follow_up_id)}/send-reconciliation`,
        refresh,
      }));
    } catch (_) { /* normal supplier rendering remains available */ }
  }

  const reminder = supplier.reminder || {};
  if (reminder.state) {
    const reminderLine = node("div", "", "supplier-reminder-line");
    reminderLine.append(node("strong", reminderStateLabel(reminder.state)));
    if (reminder.due_at) reminderLine.append(node("span", ` · ${formatDate(reminder.due_at)}`, "small"));
    if (reminder.resume_at) reminderLine.append(node("span", ` · devam ${formatDate(reminder.resume_at)}`, "small"));
    if (reminder.escalation_due_at) reminderLine.append(node("span", ` · temas ${formatDate(reminder.escalation_due_at)}`, "small"));
    if ((reminder.preferred_contact_channels || []).length) reminderLine.append(node("span", ` · kanal: ${reminder.preferred_contact_channels.join(" / ")}`, "small"));
    card.append(reminderLine);
  }

  const previewArea = node("div", "", "supplier-preview-area");
  const actions = node("div", "", "actions supplier-actions");
  if (reminder.state === "approval_required_supplier_reminder_due") {
    actions.append(actionButton("Mesajı Önizle ve Karar Ver", "", async () => {
      try {
        const preview = await api(`/mina-jobs/${encodeURIComponent(jobId)}/supplier-rfqs/${encodeURIComponent(supplier.rfq_id)}/reminder-approval-preview`);
        previewArea.replaceChildren(approvalPreviewCard(
          preview,
          `/mina-jobs/${encodeURIComponent(jobId)}/supplier-rfqs/${encodeURIComponent(supplier.rfq_id)}/reminder-approval`,
          refresh,
        ));
      } catch (error) { previewArea.replaceChildren(node("div", error.message || String(error), "error")); }
    }));
  } else if (["manual_reminder_due", "automatic_reminder_due"].includes(reminder.state)
      || (reminder.state === "waiting" && effectivePolicy?.effective_mode !== "approval_required")) {
    actions.append(actionButton("Hatırlatmayı Önizle", "", async () => {
      try {
        const preview = await api(`/mina-jobs/${encodeURIComponent(jobId)}/supplier-rfqs/${encodeURIComponent(supplier.rfq_id)}/reminder-preview`);
        previewArea.replaceChildren(reminderPreviewCard(
          preview,
          `/mina-jobs/${encodeURIComponent(jobId)}/supplier-rfqs/${encodeURIComponent(supplier.rfq_id)}/reminder-now`,
          refresh,
        ));
      } catch (error) { previewArea.replaceChildren(node("div", error.message || String(error), "error")); }
    }));
  }
  if (actions.childNodes.length) card.append(actions);
  card.append(previewArea); container.append(card);
}

async function renderCustomerApproval(container, jobId, plan, refresh) {
  if (plan?.state !== "approval_required_customer_update_due") return;
  const card = node("div", "", "approval-card");
  card.append(node("h3", "Müşteri deadline bilgilendirmesi"));
  card.append(node("div", "MINAI mesajı hazırladı; gönderim için operatör onayı gerekiyor.", "notice"));
  const actions = node("div", "", "actions");
  actions.append(actionButton("Mesajı Önizle", "", async () => {
    try {
      const preview = await api(`/mina-jobs/${encodeURIComponent(jobId)}/customer-deadline-update/approval-preview`);
      const old = card.querySelector(".preview-wrap"); if (old) old.remove();
      const wrap = node("div", "", "preview-wrap");
      wrap.append(approvalPreviewCard(
        preview,
        `/mina-jobs/${encodeURIComponent(jobId)}/customer-deadline-update/approval`,
        refresh,
      ));
      card.append(wrap);
    } catch (error) { showError(error); }
  }));
  card.append(actions); container.append(card);
}

function sectionBlock(titleText, description = "") {
  const section = node("section", "", "section job-detail-section");
  const heading = node("div", "", "section-heading");
  heading.append(node("h2", titleText));
  if (description) heading.append(node("p", description, "muted"));
  section.append(heading); return section;
}

function renderShipmentSection(container, data) {
  const shipment = data.job?.shipment || {};
  const section = sectionBlock("Yük Bilgileri", "İlk talep ve teyit edilmiş shipment alanları.");
  const grid = node("div", "", "detail-grid");
  grid.append(
    summaryItem("Taşıma", transportLabel(shipment.transport_mode)),
    summaryItem("Servis", shipment.service_type || "-"),
    summaryItem("Ekipman", shipment.equipment_type || "-"),
    summaryItem("Emtia", shipment.commodity || "-"),
    summaryItem("Yükleme adresi", shipment.pickup_address || "-"),
    summaryItem("Yükleme irtibatı", [shipment.pickup_contact_name, shipment.pickup_contact_phone].filter(Boolean).join(" · ") || "-"),
    summaryItem("Teslim adresi", shipment.delivery_address || "-"),
    summaryItem("Teslim irtibatı", [shipment.delivery_contact_name, shipment.delivery_contact_phone].filter(Boolean).join(" · ") || "-"),
    summaryItem("Brüt ağırlık", shipment.gross_weight_kg == null ? "-" : `${moneyLabel(shipment.gross_weight_kg)} kg${shipment.weight_is_approximate ? " ~" : ""}`),
    summaryItem("Hazır tarihi", formatDateOnly(shipment.cargo_ready_date)),
    summaryItem("Teslim beklentisi", formatDateOnly(shipment.required_delivery_date)),
    summaryItem("Teklif deadline", formatDate(shipment.customer_quote_deadline_at))
  );
  section.append(grid);
  if (shipment.is_adr || shipment.is_temperature_controlled || shipment.special_notes) {
    const flags = node("div", "", "job-flags");
    if (shipment.is_adr) flags.append(node("span", `ADR${shipment.adr_class ? ` · ${shipment.adr_class}` : ""}`, "badge warning-badge"));
    if (shipment.is_temperature_controlled) flags.append(node("span", `Isı kontrollü${shipment.temperature_requirement ? ` · ${shipment.temperature_requirement}` : ""}`, "badge warning-badge"));
    if (shipment.special_notes) flags.append(node("span", shipment.special_notes, "small"));
    section.append(flags);
  }
  if ((shipment.packages || []).length) {
    const packageList = node("div", "", "package-list");
    (shipment.packages || []).forEach((pkg, index) => {
      const dims = [pkg.length_cm, pkg.width_cm, pkg.height_cm].every(v => v != null)
        ? `${pkg.length_cm}×${pkg.width_cm}×${pkg.height_cm} cm` : "ölçü eksik";
      const text = `${pkg.quantity || 0} × ${pkg.package_type || "paket"} · ${dims}${pkg.weight_kg != null ? ` · ${pkg.weight_kg} kg/adet` : ""}`;
      packageList.append(node("div", `#${index + 1} · ${text}`, "package-row"));
    });
    section.append(packageList);
  }
  container.append(section);
}

function overrideChoice(mode, disabled) { return disabled && !mode ? "disabled" : (mode || "inherit"); }
function jobAutomationSelect(labelText, policy, overrideMode, disabled) {
  const wrap = node("div", "", "job-automation-control");
  const label = node("label", labelText);
  const select = document.createElement("select");
  [["inherit", "Üst kuralı kullan"], ["manual", "Manuel"], ["approval_required", "Operatör onayı"], ["automatic", "Otomatik"], ["disabled", "Bu işte devre dışı"]]
    .forEach(([value, text]) => { const option = document.createElement("option"); option.value = value; option.textContent = text; select.append(option); });
  select.value = overrideChoice(overrideMode, disabled); label.append(select); wrap.append(label);
  if (policy) wrap.append(node("div", `Şu an: ${modeLabel(policy.effective_mode)} · kaynak: ${policySourceLabel(policy.resolved_from)}`, "small policy-evidence"));
  return { wrap, select };
}

function renderJobAutomationSection(container, data, jobId, refresh) {
  const automation = data.automation || {};
  const overrides = automation.overrides || {};
  const section = sectionBlock("Otomasyon", "Bu ayarlar yalnız bu MINA işini etkiler; ajans ve müşteri kurallarını değiştirmez.");
  const controls = node("div", "", "job-automation-grid");
  const supplier = jobAutomationSelect("Tedarikçi hatırlatmaları", automation.supplier_reminder_policy,
    overrides.supplier_reminder_mode, overrides.disable_supplier_reminders);
  const customer = jobAutomationSelect("Müşteri deadline bilgilendirmesi", automation.customer_deadline_update_policy,
    overrides.customer_deadline_update_mode, overrides.disable_customer_deadline_updates);
  controls.append(supplier.wrap, customer.wrap); section.append(controls);
  if (data.controls?.automation_overrides_editable) {
    const feedback = node("div", "", "muted settings-feedback");
    const actions = node("div", "", "actions");
    const save = actionButton("İş Otomasyonunu Kaydet", "primary", async () => {
      const decode = value => ({
        mode: ["manual", "approval_required", "automatic"].includes(value) ? value : null,
        disabled: value === "disabled"
      });
      const s = decode(supplier.select.value); const c = decode(customer.select.value);
      save.disabled = true; feedback.textContent = "Kaydediliyor…";
      try {
        await api(`/mina-jobs/${encodeURIComponent(jobId)}/automation-overrides`, { method: "POST", body: JSON.stringify({
          disable_supplier_reminders: s.disabled, disable_customer_deadline_updates: c.disabled,
          supplier_reminder_mode: s.mode, customer_deadline_update_mode: c.mode
        }) });
        feedback.textContent = "İşe özel otomasyon ayarı kaydedildi."; await refresh();
      } catch (error) { feedback.textContent = error.message || String(error); save.disabled = false; }
    });
    actions.append(save); section.append(actions, feedback);
  }
  container.append(section);
}

function supplierPriceSourceLabel(value) {
  return ({
    rfq_email: "RFQ e-posta", email: "E-posta", phone: "Telefon",
    whatsapp: "WhatsApp", portal: "Portal", api: "API",
    manual: "Manuel", fixed_rate: "Sabit fiyat"
  })[value] || codeLabel(value);
}

function freshPriceEntryId(prefix) {
  const id = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}:${id}`;
}

function renderSupplierPricesSection(container, data, jobId, refresh) {
  const view = data.supplier_prices || {};
  const offers = view.price_offers || [];
  const rates = view.applicable_fixed_rates || [];
  const section = sectionBlock(
    "Tedarikçi Fiyatları",
    "RFQ, telefon, WhatsApp ve sabit fiyatlar aynı seçim motorunda karşılaştırılır."
  );

  if (offers.length) {
    const list = node("div", "", "supplier-price-list");
    offers.slice().sort((a,b) => new Date(b.recorded_at || 0) - new Date(a.recorded_at || 0)).forEach(offer => {
      const card = node("div", "", "supplier-commercial supplier-price-card");
      card.append(
        node("strong", `${offer.supplier_name || "Tedarikçi"} · ${moneyLabel(offer.cost, offer.currency)}`),
        node("span", supplierPriceSourceLabel(offer.source_type), "badge"),
        node("span", offer.transit_time ? `Transit: ${offer.transit_time}` : "Transit: -", "small")
      );
      if (offer.equipment_type) card.append(node("span", `Ekipman: ${offer.equipment_type}`, "small"));
      list.append(card);
    });
    section.append(list);
  } else {
    section.append(emptyState("Henüz kullanılabilir tedarikçi fiyatı yok", "RFQ yanıtı bekleyebilir veya telefon/WhatsApp fiyatı kaydedebilirsin."));
  }

  if (rates.length) {
    const rateWrap = node("div", "", "fixed-rate-list");
    rateWrap.append(node("h3", "Bu işe uyan sabit fiyatlar"));
    rates.forEach(item => {
      const rate = item.rate || {};
      const row = node("div", "", "supplier-commercial fixed-rate-row");
      row.append(
        node("strong", `${rate.supplier_name || "Tedarikçi"} · ${moneyLabel(rate.cost, rate.currency)}`),
        node("span", rate.transit_time ? `Transit: ${rate.transit_time}` : "", "small")
      );
      if (data.controls?.supplier_price_entry_available) {
        const use = actionButton("Bu İşte Kullan", "", async () => {
          use.disabled = true;
          try {
            await api(`/mina-jobs/${encodeURIComponent(jobId)}/supplier-prices/fixed-rate/${encodeURIComponent(rate.rate_id)}`, {
              method: "POST", body: JSON.stringify({ entry_id: freshPriceEntryId("web-fixed-rate") })
            });
            await refresh();
          } catch (error) { showError(error); use.disabled = false; }
        });
        row.append(use);
      }
      rateWrap.append(row);
    });
    section.append(rateWrap);
  }

  if (data.controls?.supplier_price_entry_available) {
    const supplierNames = [...new Set([
      ...(data.suppliers || []).map(item => item.supplier_name),
      ...offers.map(item => item.supplier_name),
      ...rates.map(item => item.rate?.supplier_name),
    ].filter(Boolean))].sort();
    const form = node("div", "", "approval-focused supplier-price-entry");
    form.append(node("h3", "Telefon / WhatsApp / Harici Fiyat Kaydet"));
    if (!supplierNames.length) {
      form.append(node("div", "Önce bu iş için uygun tedarikçi çalışması oluşmalı.", "notice"));
    } else {
      const supplierLabel=node("label","Tedarikçi"); const supplier=document.createElement("select");
      supplierNames.forEach(name=>{const o=document.createElement("option");o.value=name;o.textContent=name;supplier.append(o);}); supplierLabel.append(supplier);
      const sourceLabel=node("label","Kaynak"); const source=document.createElement("select");
      [["phone","Telefon"],["whatsapp","WhatsApp"],["email","E-posta"],["portal","Portal"],["manual","Manuel"]].forEach(([v,t])=>{const o=document.createElement("option");o.value=v;o.textContent=t;source.append(o);}); sourceLabel.append(source);
      const costLabel=node("label","Tedarikçi maliyeti"); const cost=document.createElement("input");cost.type="number";cost.min="0.01";cost.step="0.01";costLabel.append(cost);
      const currencyLabel=node("label","Para birimi"); const currency=document.createElement("input");currency.value="EUR";currency.maxLength=3;currencyLabel.append(currency);
      const transitLabel=node("label","Transit süre"); const transit=document.createElement("input");transit.placeholder="örn. 5-7 gün";transit.maxLength=120;transitLabel.append(transit);
      const equipmentLabel=node("label","Ekipman"); const equipment=document.createElement("input");equipment.value=data.job?.shipment?.equipment_type||"";equipment.maxLength=120;equipmentLabel.append(equipment);
      const basisLabel=node("label","Fiyat kapsamı"); const basis=document.createElement("select");
      [["all_in","All-in"],["base_freight_plus_extras","Navlun + ekstralar"]].forEach(([v,t])=>{const o=document.createElement("option");o.value=v;o.textContent=t;basis.append(o);});basisLabel.append(basis);
      const feedback=node("div","","muted settings-feedback");
      const save=actionButton("Fiyatı Kaydet","primary",async()=>{
        const amount=Number(cost.value); if(!Number.isFinite(amount)||amount<=0){feedback.textContent="Geçerli tedarikçi maliyeti gerekli.";return;}
        save.disabled=true; feedback.textContent="Fiyat kaydediliyor…";
        try {
          await api(`/mina-jobs/${encodeURIComponent(jobId)}/supplier-prices/manual`,{method:"POST",body:JSON.stringify({
            entry_id:freshPriceEntryId("web-direct-price"), supplier_name:supplier.value, source_type:source.value,
            cost:amount, currency:(currency.value||"EUR").trim().toUpperCase(), transit_time:transit.value.trim()||null,
            equipment_type:equipment.value.trim()||null, pricing_basis:basis.value, included_costs:basis.value==="all_in"?[]:null,
            excluded_costs:[]
          })}); await refresh();
        } catch(error){feedback.textContent=error.message||String(error);save.disabled=false;}
      });
      const grid=node("div","","settings-two-col");grid.append(supplierLabel,sourceLabel,costLabel,currencyLabel,transitLabel,equipmentLabel,basisLabel);
      form.append(grid,save,feedback);
    }
    section.append(form);
  }

  if (data.controls?.supplier_price_progress_available) {
    const progress = node("div", "", "approval-focused supplier-price-progress");
    progress.append(node("h3", "Müşteri Teklifini Hazırla"));
    const marginLabel=node("label","Bu işe özel maliyet üzerine % (opsiyonel)"); const margin=document.createElement("input");
    margin.type="number";margin.min="0";margin.step="0.1";margin.placeholder="Müşteri/ajans kuralı yoksa gir";marginLabel.append(margin);
    const feedback=node("div","","muted settings-feedback");
    const prepare=actionButton("Teklifi Hazırla","approve",async()=>{
      const raw=margin.value.trim(); const body={};
      if(raw){const value=Number(raw);if(!Number.isFinite(value)||value<0){feedback.textContent="Geçerli bir yüzde gir.";return;}body.quote_pricing_override={method:"cost_markup_percentage",value};}
      prepare.disabled=true;feedback.textContent="Tüm fiyat kaynakları karşılaştırılıyor…";
      try {
        const result=await api(`/mina-jobs/${encodeURIComponent(jobId)}/supplier-prices/progress`,{method:"POST",body:JSON.stringify(body)});
        if(result.result_type==="pricing_policy_required") feedback.textContent="Müşteri veya ajans fiyatlama kuralı yok. İşe özel oran girerek tekrar deneyebilirsin.";
        else await refresh();
      } catch(error){feedback.textContent=error.message||String(error);} finally{prepare.disabled=false;}
    });
    progress.append(marginLabel,prepare,feedback); section.append(progress);
  }
  container.append(section);
}

function quoteStatusLabel(value) {
  return ({ pending: "Onay bekliyor", approved: "Onaylandı", rejected: "Reddedildi", invalidated: "Geçersizleşti" })[value] || codeLabel(value);
}

function renderQuoteRevisionEditor(container, quoteCase, approvalId, refresh) {
  const editor = node("div", "", "quote-revision-editor"); editor.hidden = true;
  const subjectLabel = node("label", "Konu"); const subject = document.createElement("input");
  subject.value = quoteCase.quote_draft?.subject || ""; subject.maxLength = 500; subjectLabel.append(subject);
  const bodyLabel = node("label", "Mesaj"); const body = document.createElement("textarea");
  body.rows = 8; body.value = quoteCase.quote_draft?.body || ""; bodyLabel.append(body);
  const priceLabel = node("label", "Müşteri fiyatı"); const price = document.createElement("input");
  price.type = "number"; price.min = "0"; price.step = "0.01"; price.value = quoteCase.customer_quote?.final_price ?? ""; priceLabel.append(price);
  const noteLabel = node("label", "Revizyon notu"); const note = document.createElement("input"); note.maxLength = 800; noteLabel.append(note);
  const feedback = node("div", "", "muted approval-feedback");
  const actions = node("div", "", "actions");
  const cancel = actionButton("Vazgeç", "", () => { editor.hidden = true; });
  const save = actionButton("Revizyonu Kaydet", "primary", async () => {
    if (!subject.value.trim() || !body.value.trim()) { feedback.textContent = "Konu ve mesaj gerekli."; return; }
    save.disabled = true; feedback.textContent = "Revizyon kaydediliyor ve yeni onay oluşturuluyor…";
    try {
      await api(`/quote-cases/${encodeURIComponent(quoteCase.case_id)}/revise`, { method: "POST", body: JSON.stringify({
        expected_approval_id: approvalId, subject: subject.value.trim(), body: body.value,
        final_price: price.value ? Number(price.value) : null, operator_note: note.value.trim() || null
      }) });
      await refresh();
    } catch (error) { feedback.textContent = error.message || String(error); save.disabled = false; }
  });
  actions.append(cancel, save); editor.append(subjectLabel, bodyLabel, priceLabel, noteLabel, actions, feedback);
  container.append(editor); return editor;
}

function renderQuoteApprovalActions(container, quoteCase, approval, refresh) {
  const actions = node("div", "", "actions quote-decision-actions");
  const feedback = node("div", "", "muted approval-feedback");
  const approve = actionButton("Teklifi Onayla", "approve", async () => {
    approve.disabled = true; feedback.textContent = "Onay kaydediliyor…";
    try { await api(`/quote-approvals/${encodeURIComponent(approval.approval_id)}/approve`, { method: "POST", body: "{}" }); await refresh(); }
    catch (error) { feedback.textContent = error.message || String(error); approve.disabled = false; }
  });
  const reject = actionButton("Reddet", "reject", () => { rejectPanel.hidden = false; reason.focus(); });
  const revise = actionButton("Teklifi Düzenle", "", () => { revisionEditor.hidden = false; });
  actions.append(approve, revise, reject); container.append(actions);
  const revisionEditor = renderQuoteRevisionEditor(container, quoteCase, approval.approval_id, refresh);
  const rejectPanel = node("div", "", "approval-reject-panel"); rejectPanel.hidden = true;
  const reasonLabel = node("label", "Reddetme nedeni"); const reason = document.createElement("textarea"); reason.rows = 3; reason.maxLength = 800; reasonLabel.append(reason);
  const rejectActions = node("div", "", "actions");
  rejectActions.append(actionButton("Vazgeç", "", () => { rejectPanel.hidden = true; reason.value = ""; }), actionButton("Reddi Kaydet", "reject", async () => {
    if (!reason.value.trim()) { feedback.textContent = "Reddetme nedeni gerekli."; return; }
    try { await api(`/quote-approvals/${encodeURIComponent(approval.approval_id)}/reject`, { method: "POST", body: JSON.stringify({ rejection_reason: reason.value.trim() }) }); await refresh(); }
    catch (error) { feedback.textContent = error.message || String(error); }
  }));
  rejectPanel.append(reasonLabel, rejectActions); container.append(rejectPanel, feedback);
}

function sendOutcomeReconciliationBox({ title, endpoint, refresh, expectedApprovalId = null }) {
  const box = node("div", "", "approval-focused send-reconciliation-box");
  box.append(node("h4", title), node("div", "Outlook > Gönderilmiş Öğeler'i kontrol et. MINAI sonucu tahmin etmez.", "notice"));
  const sentTimeLabel = node("label", "Outlook'ta görünen gönderim zamanı");
  const sentTime = document.createElement("input"); sentTime.type = "datetime-local"; sentTimeLabel.append(sentTime);
  const noteLabel = node("label", "Kontrol notu (opsiyonel)");
  const note = document.createElement("textarea"); note.rows = 2; note.maxLength = 1000; noteLabel.append(note);
  const feedback = node("div", "", "muted approval-feedback");
  const actions = node("div", "", "actions");
  async function reconcile(outcome) {
    let observedSentAt = null;
    if (outcome === "confirmed_sent") {
      if (!sentTime.value) { feedback.textContent = "Outlook'ta görünen gönderim zamanını gir."; return; }
      const parsed = new Date(sentTime.value);
      if (Number.isNaN(parsed.getTime())) { feedback.textContent = "Gönderim zamanı geçerli değil."; return; }
      observedSentAt = parsed.toISOString();
    }
    const body = { outcome, observed_sent_at: observedSentAt, note: note.value.trim() || null };
    if (expectedApprovalId) body.expected_approval_id = expectedApprovalId;
    try {
      feedback.textContent = "Kontrol sonucu kaydediliyor…";
      await api(endpoint, { method: "POST", body: JSON.stringify(body) });
      await refresh();
    } catch (error) { feedback.textContent = error.message || String(error); }
  }
  actions.append(
    actionButton("Gönderildiğini Doğrula", "approve", () => reconcile("confirmed_sent")),
    actionButton("Gönderilmediğini Doğrula", "", () => reconcile("confirmed_not_sent"))
  );
  box.append(sentTimeLabel, noteLabel, actions, feedback); return box;
}


async function renderApprovedQuoteSend(container, quoteCase, approval, refresh) {
  const reconciledSent = (quoteCase.send_reconciliation_evidence || [])
    .filter(item => item.outcome === "confirmed_sent")
    .map(item => ({ recipient_email: item.recipient_email, sent_at: item.observed_sent_at, reconciled_by: item.reconciled_by }));
  const sent = [...(quoteCase.manual_sent_evidence || []), ...(quoteCase.automated_sent_evidence || []), ...reconciledSent]
    .sort((a, b) => new Date(b.sent_at) - new Date(a.sent_at));
  if (sent.length) {
    const latest = sent[0];
    container.append(node("div", `Gönderildi · ${latest.recipient_email || "-"} · ${formatDate(latest.sent_at)}`, "notice success-notice"));
    return;
  }
  const sendState = quoteCase.automated_send_state || null;
  if (sendState?.status === "sending") {
    container.append(node("div", "Gönderim provider sonucu bekliyor. Aynı teklif yeniden gönderilemez.", "notice"));
    return;
  }
  if (sendState?.status === "delivery_outcome_unknown") {
    container.append(node("div", "Gönderim sonucu belirsiz. Tekrar gönderim kilitli; önce Outlook gönderilmiş öğeleriyle kontrol gerekli.", "notice"));
    container.append(sendOutcomeReconciliationBox({
      title: "Teklif gönderimini doğrula",
      endpoint: `/quote-cases/${encodeURIComponent(quoteCase.case_id)}/send-reconciliation`,
      expectedApprovalId: approval.approval_id,
      refresh,
    }));
    return;
  }
  let finalOutput; let authority;
  try {
    [finalOutput, authority] = await Promise.all([
      api(`/quote-cases/${encodeURIComponent(quoteCase.case_id)}/final-output`),
      api(`/quote-cases/${encodeURIComponent(quoteCase.case_id)}/recipient-authority`),
    ]);
  }
  catch (error) { container.append(node("div", `Gönderime hazır değil: ${error.message || error}`, "notice")); return; }
  const sendBox = node("div", "", "quote-send-box approval-focused");
  sendBox.append(node("h3", "Müşteriye Gönder"));
  authority = authority || {};
  const allowedRecipients = authority.allowed_recipient_emails || [];
  if (!allowedRecipients.length) {
    sendBox.append(node("div", "Doğrulanmış müşteri alıcısı yok. Önce müşteri master/contact veya güvenilir gönderici kaydı tamamlanmalı.", "notice"));
    container.append(sendBox); return;
  }
  const recipientLabel = node("label", "Doğrulanmış alıcı"); const recipient = document.createElement("select");
  allowedRecipients.forEach(email => { const option = document.createElement("option"); option.value = email; option.textContent = email; recipient.append(option); });
  if (authority.default_recipient_email) recipient.value = authority.default_recipient_email;
  recipientLabel.append(recipient);
  sendBox.append(recipientLabel, node("div", finalOutput.subject, "quote-subject"), node("div", finalOutput.body, "preview approval-message-body"));
  const price = node("div", `${moneyLabel(finalOutput.final_price, finalOutput.currency)}`, "quote-final-price"); sendBox.append(price);
  const feedback = node("div", "", "muted approval-feedback"); const actions = node("div", "", "actions");
  const send = actionButton("Gönder", "approve", async () => {
    const email = recipient.value.trim(); if (!email) { feedback.textContent = "Doğrulanmış alıcı gerekli."; return; }
    send.disabled = true; feedback.textContent = "Gönderim öncesi onay ve içerik yeniden doğrulanıyor…";
    try { await api(`/quote-cases/${encodeURIComponent(quoteCase.case_id)}/send`, { method: "POST", body: JSON.stringify({ expected_approval_id: approval.approval_id, recipient_email: email }) }); await refresh(); }
    catch (error) { feedback.textContent = error.message || String(error); send.disabled = false; }
  });
  const manual = actionButton("Harici Gönderildi Olarak Kaydet", "", async () => {
    const email = recipient.value.trim(); if (!email) { feedback.textContent = "Doğrulanmış alıcı gerekli."; return; }
    manual.disabled = true; feedback.textContent = "Harici gönderim kanıtı kaydediliyor…";
    try { await api(`/quote-cases/${encodeURIComponent(quoteCase.case_id)}/record-manually-sent`, { method: "POST", body: JSON.stringify({ expected_approval_id: approval.approval_id, recipient_email: email }) }); await refresh(); }
    catch (error) { feedback.textContent = error.message || String(error); manual.disabled = false; }
  });
  actions.append(send, manual); sendBox.append(actions, feedback); container.append(sendBox);
}

async function renderQuoteSection(container, data, refresh) {
  const section = sectionBlock("Teklif", "Müşteri teklifinin fiyat, onay ve gönderim otoritesi.");
  const caseId = data.quote?.case_id;
  if (!caseId) { section.append(emptyState("Henüz teklif oluşturulmadı", "Fiyatlama tamamlandığında teklif burada görünecek.")); container.append(section); return; }
  let quoteCase;
  try { quoteCase = await api(`/quote-cases/${encodeURIComponent(caseId)}`); }
  catch (error) { section.append(node("div", error.message || String(error), "error")); container.append(section); return; }
  const approval = quoteCase.quote_approval;
  const q = quoteCase.customer_quote || {}; const supplier = quoteCase.supplier_quote || {};
  const grid = node("div", "", "detail-grid quote-metrics");
  grid.append(
    summaryItem("Tedarikçi", supplier.supplier_name || "-"),
    summaryItem("Maliyet", moneyLabel(supplier.cost, supplier.currency)),
    summaryItem("Müşteri fiyatı", moneyLabel(q.final_price, q.currency)),
    summaryItem("Onay", approval ? quoteStatusLabel(approval.approval_status) : "Onay kaydı yok"),
    summaryItem("Revizyon", data.quote?.current_revision_number ?? 0),
    summaryItem("Gönderim", (quoteCase.automated_sent_evidence || []).length + (quoteCase.manual_sent_evidence || []).length + (quoteCase.send_reconciliation_evidence || []).filter(item => item.outcome === "confirmed_sent").length)
  );
  section.append(grid);
  if (!approval) { section.append(node("div", "Teklif onay kaydı henüz oluşmadı.", "notice")); container.append(section); return; }
  const snapshot = approval.quote_snapshot || {};
  const decision = node("div", "", "quote-decision-card approval-focused");
  decision.append(node("h3", snapshot.quote_subject || quoteCase.quote_draft?.subject || "Müşteri Teklifi"));
  decision.append(node("div", snapshot.quote_body || quoteCase.quote_draft?.body || "", "preview approval-message-body"));
  if (approval.approval_status === "pending") renderQuoteApprovalActions(decision, quoteCase, approval, refresh);
  else if (approval.approval_status === "approved") {
    decision.append(node("div", `Onaylayan: ${approval.approved_by || "-"} · ${formatDate(approval.approved_at)}`, "small policy-evidence"));
    await renderApprovedQuoteSend(decision, quoteCase, approval, refresh);
  } else {
    if (approval.rejection_reason) decision.append(node("div", `Neden: ${approval.rejection_reason}`, "notice"));
    const editor = renderQuoteRevisionEditor(decision, quoteCase, approval.approval_id, refresh);
    const edit = actionButton("Teklifi Düzenle", "", () => { editor.hidden = false; }); decision.append(edit);
  }
  section.append(decision); container.append(section);
}

function operationStartStatusLabel(value) {
  return ({
    approval_required: "Operatör onayı bekliyor", manual_required: "Manuel gönderim bekliyor",
    sending: "Gönderim sonucu bekleniyor", delivery_outcome_unknown: "Gönderim sonucu belirsiz",
    sent: "Gönderildi", rejected: "Reddedildi", failed: "Gönderim başarısız"
  })[value] || codeLabel(value);
}

function operationStartMessageCard(message, refresh) {
  const card = node("div", "", "operation-start-message approval-focused");
  const head = node("div", "", "operation-start-head");
  const kind = message.kind === "selected_supplier_confirmation" ? "Seçilen tedarikçi" : "Teklif kapanışı";
  head.append(node("strong", `${kind} · ${message.supplier_name}`), node("span", operationStartStatusLabel(message.status), "badge"));
  card.append(head, node("div", message.subject || "-", "quote-subject"), node("div", message.body_text || "", "preview approval-message-body"));
  card.append(node("div", `Mod: ${modeLabel(message.outbound_mode)} · Alıcı: ${message.recipient_email || "-"}`, "small policy-evidence"));
  if (message.attention_reason) card.append(node("div", message.attention_reason, "notice"));
  if (message.status === "sent") {
    card.append(node("div", `Gönderildi · ${formatDate(message.sent_at)} · ${message.sent_by || "-"}`, "notice success-notice"));
    return card;
  }
  if (message.status === "rejected") {
    card.append(node("div", `Reddedildi${message.decision_reason ? ` · ${message.decision_reason}` : ""}`, "notice"));
    return card;
  }
  if (message.status === "sending") {
    card.append(node("div", "Gönderim rezervasyonu var. Provider sonucu kesinleşmeden aynı mesaj tekrar gönderilmez. Uzun süre bu durumda kalırsa gönderilmiş öğeleri kontrol et.", "notice"));
  }
  if (message.status === "delivery_outcome_unknown") {
    card.append(node("div", "Gönderim sonucu belirsiz. Tekrar göndermeden önce Outlook Gönderilmiş Öğeler'i kontrol et.", "notice"));
    card.append(sendOutcomeReconciliationBox({
      title: "Operasyon maili gönderimini doğrula",
      endpoint: `/operation-start-messages/${encodeURIComponent(message.message_id)}/send-reconciliation`,
      refresh,
    }));
    return card;
  }
  const feedback = node("div", "", "muted approval-feedback");
  const actions = node("div", "", "actions");
  if (["approval_required", "failed"].includes(message.status)) {
    const approveLabel = message.status === "failed" ? "Yeniden Gönder" : "Onayla ve Gönder";
    const approve = actionButton(approveLabel, "approve", async () => {
      approve.disabled = true; feedback.textContent = "Kurallar yeniden doğrulanıyor…";
      try {
        await api(`/operation-start-messages/${encodeURIComponent(message.message_id)}/decision`, {
          method: "POST", body: JSON.stringify({ decision: "approve" })
        });
        await refresh();
      } catch (error) { feedback.textContent = error.message || String(error); approve.disabled = false; }
    });
    const reject = actionButton("Reddet", "reject", () => { rejectPanel.hidden = false; reason.focus(); });
    actions.append(approve, reject);
  }
  if (["manual_required", "failed"].includes(message.status)) {
    actions.append(actionButton("Harici Gönderildi Olarak Kaydet", "", async event => {
      const button = event.currentTarget; button.disabled = true; feedback.textContent = "Gönderim kanıtı kaydediliyor…";
      try {
        await api(`/operation-start-messages/${encodeURIComponent(message.message_id)}/record-manually-sent`, { method: "POST" });
        await refresh();
      } catch (error) { feedback.textContent = error.message || String(error); button.disabled = false; }
    }));
  }
  const rejectPanel = node("div", "", "approval-reject-panel"); rejectPanel.hidden = true;
  const reasonLabel = node("label", "Reddetme nedeni"); const reason = document.createElement("textarea");
  reason.rows = 3; reason.maxLength = 1000; reasonLabel.append(reason);
  const rejectActions = node("div", "", "actions");
  rejectActions.append(
    actionButton("Vazgeç", "", () => { rejectPanel.hidden = true; reason.value = ""; }),
    actionButton("Reddi Kaydet", "reject", async () => {
      const value = reason.value.trim(); if (!value) { feedback.textContent = "Reddetme nedeni gerekli."; return; }
      try {
        await api(`/operation-start-messages/${encodeURIComponent(message.message_id)}/decision`, {
          method: "POST", body: JSON.stringify({ decision: "reject", reason: value })
        });
        await refresh();
      } catch (error) { feedback.textContent = error.message || String(error); }
    })
  );
  rejectPanel.append(reasonLabel, rejectActions);
  if (actions.childElementCount) card.append(actions);
  card.append(rejectPanel, feedback); return card;
}

function renderOperationStartSection(container, data, jobId, refresh) {
  const section = sectionBlock("Operasyonu Başlat", "Müşteri kabulünden sonra seçilen tedarikçiye onay + toplama talimatı, fiyat vermiş diğer tedarikçilere nazik kapanış.");
  const view = data.operation_start || {};
  const messages = view.messages || [];
  if (data.controls?.operation_start_available && !messages.length) {
    const box = node("div", "", "operation-start-launch approval-focused");
    box.append(node("div", "Bu aksiyon fiyat toplamayı kapatır ve seçilmiş tedarikçiyi operasyon akışına devreder.", "notice"));
    const reasonLabel = node("label", "Diğer tedarikçilere kapanış nedeni (opsiyonel)");
    const reason = document.createElement("textarea"); reason.rows = 2; reason.maxLength = 1000;
    reason.placeholder = "Boş bırakılırsa MINAI nötr bir açıklama kullanır; sebep uydurmaz."; reasonLabel.append(reason);
    const feedback = node("div", "", "muted approval-feedback");
    const start = actionButton("Operasyonu Başlat", "approve", async () => {
      if (!window.confirm("Operasyonu başlatmak ve fiyat toplama sürecini kapatmak istiyor musun?")) return;
      start.disabled = true; feedback.textContent = "Seçili tedarikçi ve fiyat kanıtı doğrulanıyor…";
      try {
        await api(`/mina-jobs/${encodeURIComponent(jobId)}/operation-start`, {
          method: "POST", body: JSON.stringify({ closure_reason: reason.value.trim() || null })
        });
        await refresh();
      } catch (error) { feedback.textContent = error.message || String(error); start.disabled = false; }
    });
    box.append(reasonLabel, start, feedback); section.append(box);
  }
  messages.forEach(message => section.append(operationStartMessageCard(message, refresh)));
  if (!messages.length && !data.controls?.operation_start_available) {
    section.append(emptyState("Operasyon başlangıcı henüz hazır değil", "Müşteri teklifi kabul edildiğinde bu kontrol açılır."));
  }
  container.append(section);
}

function renderOperationSection(container, data) {
  const operation = data.operation || {};
  const section = sectionBlock("Operasyon", "Araç, sürücü, ETA, teslim ve istisna kanıtları.");
  const execution = operation.execution || operation.snapshot || null;
  if (execution) {
    const grid = node("div", "", "detail-grid operation-grid");
    grid.append(
      summaryItem("Tedarikçi teyidi", formatDate(execution.supplier_confirmed_at)),
      summaryItem("Araç", execution.vehicle_plate || "-"),
      summaryItem("Sürücü", execution.driver_name || "-"),
      summaryItem("Telefon", execution.driver_phone || "-"),
      summaryItem("Yükleme randevusu", formatDate(execution.loading_appointment_at)),
      summaryItem("Yüklendi", formatDate(execution.loaded_at)),
      summaryItem("Konum", execution.current_location || "-"),
      summaryItem("ETA", formatDate(execution.current_eta)),
      summaryItem("Teslim randevusu", formatDate(execution.delivery_appointment_at)),
      summaryItem("Teslim edildi", formatDate(execution.delivered_at)),
      summaryItem("POD", formatDate(execution.pod_received_at)),
      summaryItem("CMR", formatDate(execution.cmr_received_at))
    );
    section.append(grid);
  } else section.append(emptyState("Henüz operasyon yürütme kaydı yok", "Operasyon açıldığında araç, sürücü ve ETA kanıtları burada toplanır."));
  const exceptions = operation.exceptions || [];
  if (exceptions.length) {
    const list = node("div", "", "exception-list");
    exceptions.slice().sort((a,b) => (a.status === "open" ? -1 : 1) - (b.status === "open" ? -1 : 1)).forEach(item => {
      const card = node("div", "", `exception-card ${item.status === "open" ? item.impact_level || "" : "resolved"}`);
      const head = node("div", "", "exception-head"); head.append(node("strong", codeLabel(item.exception_type)), node("span", item.status === "open" ? "Açık" : "Çözüldü", "badge"));
      card.append(head, node("div", item.cause || "-"));
      const meta = node("div", "", "small exception-meta");
      if (item.location) meta.append(node("span", item.location)); if (item.new_eta) meta.append(node("span", `Yeni ETA ${formatDate(item.new_eta)}`));
      if (item.next_action) meta.append(node("span", `Sonraki: ${item.next_action}`)); card.append(meta); list.append(card);
    }); section.append(list);
  }
  container.append(section);
}

function timeline(container, events) {
  const section = sectionBlock("Zaman Çizelgesi", "Son 25 kalıcı iş olayı, en yeni üstte.");
  const rows = (events || []).slice().reverse().slice(0, 25);
  if (!rows.length) { section.append(emptyState("Henüz timeline olayı yok")); container.append(section); return; }
  rows.forEach(event => {
    const item = node("div", "", "timeline-item");
    item.append(node("strong", codeLabel(event.event_type)));
    item.append(node("div", `${formatDate(event.occurred_at)} · ${event.actor || "sistem"}`, "small"));
    section.append(item);
  });
  container.append(section);
}

async function renderJob(data, jobId) {
  const summary = data.summary || {}; setPageContext(summary.mina_code || "MINA İşi", "MINA İş Detayı");
  const root = node("div", "", "job-detail-page");
  const topbar = node("div", "", "job-detail-topbar");
  const back = node("a", "← MINA İşleri", "job-back-link"); back.href = "/app/jobs";
  const stage = node("span", stageLabel(summary.stage), `badge ${summary.is_closed ? "" : "open"}`); topbar.append(back, stage); root.append(topbar);
  const overview = node("div", "", "summary-grid job-overview-grid");
  overview.append(
    summaryItem("Müşteri", summary.customer_name || "-"), summaryItem("Rota", summary.route || "-"),
    summaryItem("Taşıma", transportLabel(summary.transport_mode)), summaryItem("Operasyon sorumlusu", summary.operations_owner || "-"),
    summaryItem("Satış sorumlusu", summary.sales_owner || "-"), summaryItem("Teklif deadline", formatDate(summary.customer_quote_deadline_at))
  ); root.append(overview);
  const next = data.controls?.allowed_next_stages || [];
  if (next.length) root.append(node("div", `İzin verilen sonraki aşamalar: ${next.map(stageLabel).join(" · ")}`, "small job-next-stages"));

  renderShipmentSection(root, data);
  renderJobAutomationSection(root, data, jobId, async () => loadJob(jobId));

  const approvals = sectionBlock("MINAI Onayları", "Sadece şu anda karar gerektiren otomasyon mesajları.");
  await renderCustomerApproval(approvals, jobId, data.automation?.customer_deadline_plan || {}, async () => loadJob(jobId));
  if (!approvals.querySelector(".approval-card")) approvals.append(emptyState("Bekleyen otomasyon onayı yok"));
  root.append(approvals);

  renderSupplierPricesSection(root, data, jobId, async () => loadJob(jobId));
  await renderQuoteSection(root, data, async () => loadJob(jobId));
  const suppliers = sectionBlock("Tedarikçiler", "RFQ durumu, fiyat ve takip aksiyonları.");
  for (const supplier of (data.suppliers || [])) await renderSupplier(
    suppliers, jobId, supplier, async () => loadJob(jobId), data.automation?.supplier_reminder_policy || null
  );
  if (!(data.suppliers || []).length) suppliers.append(emptyState("Henüz tedarikçi çalışması yok")); root.append(suppliers);
  renderOperationStartSection(root, data, jobId, async () => loadJob(jobId));
  renderOperationSection(root, data); timeline(root, data.timeline || []); content.replaceChildren(root);
}

async function loadJob(jobId) {
  try { const data = await api(`/mina-jobs/${encodeURIComponent(jobId)}`); await renderJob(data, jobId); setStatus("Güncel"); }
  catch (error) { showError(error); }
}

function metric(label, value) {
  const card = node("div", "", "metric");
  card.append(node("span", label), node("strong", value ?? "-"));
  return card;
}

function renderOperatorPerformance(section) {
  const wrap = node("section", "", "section report-operator-performance");
  wrap.append(node("h2", "Operasyon Gerçek Metrikleri"));
  const performance = section?.work_assignment_performance || {};
  const summary = performance.summary || {};
  const summaryGrid = node("div", "", "grid report-performance-metrics");
  summaryGrid.append(
    metric("Atama", summary.assignment_generation_count ?? 0),
    metric("İlk bakış kaydı", summary.acknowledged_generation_count ?? 0),
    metric("İlk bakış kapsamı %", summary.first_look_coverage_percent ?? "-"),
    metric("Ort. ilk bakış", summary.average_first_look_seconds == null ? "-" : durationLabel(summary.average_first_look_seconds)),
    metric("Medyan ilk bakış", summary.median_first_look_seconds == null ? "-" : durationLabel(summary.median_first_look_seconds)),
    metric("P90 ilk bakış", summary.p90_first_look_seconds == null ? "-" : durationLabel(summary.p90_first_look_seconds)),
    metric("Hedef içinde %", summary.first_look_sla_percent ?? "-")
  );
  wrap.append(summaryGrid);
  wrap.append(node("div", `İlk bakış hedefi: ${summary.first_look_target_minutes == null ? "kapalı" : `${summary.first_look_target_minutes} dk`} · Hız metrikleri personel puanı değildir.`, "notice report-performance-note"));

  const decision = section?.decision_performance || {}; const ds=decision.summary||{};
  const decisionGrid=node("div","","grid report-performance-metrics report-secondary-metrics");
  decisionGrid.append(metric("Karar adedi",ds.decision_count??0),metric("Ort. karar",ds.average_decision_seconds==null?"-":durationLabel(ds.average_decision_seconds)),metric("Medyan karar",ds.median_decision_seconds==null?"-":durationLabel(ds.median_decision_seconds)),metric("P90 karar",ds.p90_decision_seconds==null?"-":durationLabel(ds.p90_decision_seconds)),metric("Karar hedefi içinde %",ds.decision_sla_percent??"-"));
  const excludedDecisionEvidence=(decision.excluded_unlinked_quote_decision_count??0)+(decision.excluded_unlinked_operation_start_decision_count??0);
  const decisionNote=`Karar hedefi: ${decision.decision_target_minutes==null?"kapalı":`${decision.decision_target_minutes} dk`}${excludedDecisionEvidence?` · ${excludedDecisionEvidence} bağlantısız legacy karar kanıtı metrik dışında.`:""}`;
  wrap.append(node("h3","Onay / Karar Süreleri"),decisionGrid,node("div",decisionNote,"small muted"));

  const milestones=section?.milestone_performance||{}; const m=milestones.metrics||{};
  const milestoneGrid=node("div","","grid milestone-metrics");
  const names={operation_start_to_supplier_confirmation_seconds:"Operasyon açılışı → tedarikçi teyidi",supplier_confirmation_to_vehicle_assignment_seconds:"Tedarikçi teyidi → araç ataması",vehicle_assignment_to_loaded_seconds:"Araç ataması → yükleme",loaded_to_delivered_seconds:"Yükleme → teslim"};
  Object.entries(names).forEach(([key,label])=>{const v=m[key]||{};const card=node("div","","metric milestone-metric");card.append(node("span",label),node("strong",v.median==null?"-":durationLabel(v.median)),node("small",`Ort ${v.average==null?"-":durationLabel(v.average)} · P90 ${v.p90==null?"-":durationLabel(v.p90)} · n=${v.count??0}`,"muted"));milestoneGrid.append(card);});
  wrap.append(node("h3","Operasyon Aşama Süreleri"),milestoneGrid);

  const rows = performance.rows || [];
  if (rows.length) {
    const tableWrap=node("div","","table-wrap report-performance-table");const table=document.createElement("table");const thead=document.createElement("thead");const hr=document.createElement("tr");["Operatör","Atama","İlk bakış","Kapsam %","Ort.","Medyan","P90","Hedef %","Handoff","Yeniden atama"].forEach(l=>hr.append(node("th",l)));thead.append(hr);table.append(thead);const tbody=document.createElement("tbody");rows.forEach(row=>{const tr=document.createElement("tr");tr.append(node("td",row.name||"-"),node("td",row.assignment_generation_count??0),node("td",row.acknowledged_generation_count??0),node("td",row.first_look_coverage_percent??"-"),node("td",row.average_first_look_seconds==null?"-":durationLabel(row.average_first_look_seconds)),node("td",row.median_first_look_seconds==null?"-":durationLabel(row.median_first_look_seconds)),node("td",row.p90_first_look_seconds==null?"-":durationLabel(row.p90_first_look_seconds)),node("td",row.first_look_sla_percent??"-"),node("td",row.shift_handoff_count??0),node("td",row.reassignment_generation_count??0));tbody.append(tr);});table.append(tbody);tableWrap.append(table);wrap.append(tableWrap);
  }
  return wrap;
}

function renderReports(data) {
  title.textContent = "Raporlar";
  const overview = data.overview || {};
  const grid = node("div", "", "grid");
  grid.append(
    metric("Toplam iş", overview.job_count ?? 0),
    metric("Açık iş", overview.open_job_count ?? 0),
    metric("Gönderilen teklif", overview.quotes_sent_count ?? 0),
    metric("Kazanılan iş", overview.awarded_job_count ?? 0),
    metric("Açık istisna", overview.open_exception_count ?? 0),
    metric("Zamanında teslimat %", overview.on_time_delivery_percent ?? "-")
  );
  const operatorPerformance = renderOperatorPerformance(data.operations || {});
  const note = node("div", "Finansal değerler para birimleri arasında toplanmaz; eksik kanıt sıfır kabul edilmez.", "notice section");
  content.replaceChildren(grid, operatorPerformance, note);
}

let currentBranding = null;

function applyBranding(branding) {
  currentBranding = branding || null;
  if (!branding) return;
  const root = document.documentElement.style;
  root.setProperty("--accent", branding.primary_color);
  root.setProperty("--accent-contrast", branding.primary_contrast_color);
  root.setProperty("--accent-soft", branding.primary_soft_color);
  root.setProperty("--accent-hover", branding.primary_hover_color);
  root.setProperty("--secondary-accent", branding.secondary_accent_color);
  root.setProperty("--secondary-accent-contrast", branding.secondary_contrast_color);
  root.setProperty("--secondary-accent-soft", branding.secondary_soft_color);

  const name = document.getElementById("shell-brand-name");
  const mark = document.getElementById("shell-brand-mark");
  if (name) name.textContent = branding.company_name || "MINAI";
  if (mark) {
    mark.replaceChildren();
    mark.classList.remove("has-logo");
    if (branding.logo_data_uri) {
      const image = document.createElement("img");
      image.className = "shell-brand-logo";
      image.alt = "";
      image.src = branding.logo_data_uri;
      mark.append(image);
      mark.classList.add("has-logo");
    } else {
      mark.textContent = (branding.company_name || "M").trim().slice(0, 1).toUpperCase() || "M";
    }
  }
  document.title = `${branding.company_name || "MINAI"} · MINAI`;
}

function brandingLogoPreview(container, dataUri, companyName) {
  container.replaceChildren();
  if (dataUri) {
    const image = document.createElement("img");
    image.className = "branding-preview-logo";
    image.alt = "Logo önizlemesi";
    image.src = dataUri;
    container.append(image);
  } else {
    container.append(node("span", (companyName || "M").trim().slice(0, 1).toUpperCase() || "M"));
  }
}

function renderBrandingPanel(branding) {
  let pendingLogo = branding.logo_data_uri || null;
  const panel = node("section", "", "settings-panel");
  const heading = node("div", "", "settings-heading");
  heading.append(node("h2", "Branding"), node("p", "Firma adı, logo ve marka renkleri. Kritik durum renkleri sistem tarafından sabit tutulur.", "muted"));
  panel.append(heading);

  const form = node("div", "", "branding-form");
  const companyLabel = node("label", "Firma adı");
  const companyInput = document.createElement("input");
  companyInput.type = "text"; companyInput.maxLength = 120; companyInput.value = branding.company_name || "MINAI";
  companyLabel.append(companyInput);

  const colors = node("div", "", "branding-color-grid");
  const primaryLabel = node("label", "Ana marka rengi");
  const primaryInput = document.createElement("input"); primaryInput.type = "color";
  primaryInput.value = (branding.primary_color || "#3157D5").toLowerCase(); primaryLabel.append(primaryInput);
  const secondaryLabel = node("label", "İkincil vurgu rengi");
  const secondaryInput = document.createElement("input"); secondaryInput.type = "color";
  secondaryInput.value = (branding.secondary_accent_color || "#172033").toLowerCase(); secondaryLabel.append(secondaryInput);
  colors.append(primaryLabel, secondaryLabel);

  const logoLabel = node("label", "Logo");
  const logoInput = document.createElement("input"); logoInput.type = "file";
  logoInput.accept = "image/png,image/jpeg,image/webp";
  logoLabel.append(logoInput, node("span", "PNG, JPEG veya WebP · en fazla 256 KB", "muted branding-help"));

  const preview = node("div", "", "branding-preview");
  const previewMark = node("div", "", "branding-preview-mark");
  brandingLogoPreview(previewMark, pendingLogo, companyInput.value);
  const previewText = node("strong", companyInput.value || "MINAI", "branding-preview-name");
  const previewPrimary = node("button", "Birincil Aksiyon", "primary"); previewPrimary.type = "button"; previewPrimary.disabled = true;
  const previewSecondary = node("span", "Vurgu", "branding-secondary-chip");
  preview.append(previewMark, previewText, previewPrimary, previewSecondary);

  const actions = node("div", "", "actions branding-actions");
  const clearLogo = node("button", "Logoyu Kaldır"); clearLogo.type = "button";
  const save = node("button", "Kaydet", "primary"); save.type = "button";
  actions.append(clearLogo, save);
  const feedback = node("div", "", "muted branding-feedback");

  function refreshLocalPreview() {
    previewText.textContent = companyInput.value.trim() || "MINAI";
    brandingLogoPreview(previewMark, pendingLogo, companyInput.value);
    previewPrimary.style.background = primaryInput.value;
    previewSecondary.style.background = secondaryInput.value;
  }
  companyInput.addEventListener("input", refreshLocalPreview);
  primaryInput.addEventListener("input", refreshLocalPreview);
  secondaryInput.addEventListener("input", refreshLocalPreview);
  logoInput.addEventListener("change", () => {
    const file = logoInput.files?.[0]; if (!file) return;
    if (!["image/png", "image/jpeg", "image/webp"].includes(file.type) || file.size > 256 * 1024) {
      feedback.textContent = "Logo PNG/JPEG/WebP olmalı ve 256 KB'ı geçmemeli."; logoInput.value = ""; return;
    }
    const reader = new FileReader();
    reader.addEventListener("load", () => { pendingLogo = String(reader.result || ""); feedback.textContent = "Logo önizlemeye yüklendi; kaydetmeden kalıcı olmaz."; refreshLocalPreview(); });
    reader.readAsDataURL(file);
  });
  clearLogo.addEventListener("click", () => { pendingLogo = null; logoInput.value = ""; feedback.textContent = "Logo kaldırılacak; değişikliği kaydet."; refreshLocalPreview(); });
  save.addEventListener("click", async () => {
    save.disabled = true; feedback.textContent = "Kaydediliyor…";
    try {
      const saved = await api("/settings/branding", { method: "POST", body: JSON.stringify({
        company_name: companyInput.value, logo_data_uri: pendingLogo,
        primary_color: primaryInput.value, secondary_accent_color: secondaryInput.value
      }) });
      applyBranding(saved); feedback.textContent = "Branding ayarları kaydedildi."; setStatus("Kaydedildi");
    } catch (error) { feedback.textContent = error.message || String(error); setStatus("Hata", false); }
    finally { save.disabled = false; }
  });
  form.append(companyLabel, colors, logoLabel, preview, actions, feedback); panel.append(form); refreshLocalPreview();
  return panel;
}

function policySelect(labelText, currentValue, fallbackValue) {
  const label = node("label", labelText);
  const select = document.createElement("select");
  [["inherit", `Sistem varsayılanı (${modeLabel(fallbackValue)})`], ["manual", "Manuel"], ["approval_required", "Operatör onayı"], ["automatic", "Otomatik"]]
    .forEach(([value, text]) => { const option = document.createElement("option"); option.value = value; option.textContent = text; select.append(option); });
  select.value = currentValue || "inherit"; label.append(select); return { label, select };
}

function textareaLines(labelText, values = [], rows = 3) {
  const label = node("label", labelText);
  const input = document.createElement("textarea"); input.rows = rows;
  input.value = (values || []).join("\n"); label.append(input);
  return { label, input, value: () => input.value.split("\n").map(v => v.trim()).filter(Boolean) };
}

function numberField(labelText, value, min, max) {
  const label = node("label", labelText); const input = document.createElement("input");
  input.type = "number"; input.min = String(min); input.max = String(max); input.value = value ?? ""; label.append(input);
  return { label, input, value: () => input.value === "" ? null : Number(input.value) };
}

function automationModeSelect(labelText, value, inheritText = "Üst kuralı kullan") {
  const label = node("label", labelText); const select = document.createElement("select");
  [["inherit", inheritText], ["manual", "Manuel"], ["approval_required", "Operatör onayı"], ["automatic", "Otomatik"]].forEach(([v,t]) => {
    const option = document.createElement("option"); option.value=v; option.textContent=t; select.append(option);
  });
  select.value = value || "inherit"; label.append(select); return { label, select, value: () => select.value === "inherit" ? null : select.value };
}

function renderCustomerAutomationExceptions(customers = []) {
  const box = node("div", "", "settings-subsection customer-exceptions");
  box.append(node("h3", "Müşteri İstisnaları"), node("p", "Yalnız ajans genel kuralından farklı davranacak müşteriler için kullan. Boş müşteriler listeyi kalabalıklaştırmaz.", "muted"));
  const active = customers.filter(c => c.active !== false);
  const selectorLabel = node("label", "Müşteri"); const selector = document.createElement("select");
  const ph = document.createElement("option"); ph.value=""; ph.textContent="Müşteri seç…"; selector.append(ph);
  active.forEach(c => { const o=document.createElement("option"); o.value=c.customer_id; o.textContent=c.customer_name; selector.append(o); });
  selectorLabel.append(selector); box.append(selectorLabel);
  const editor = node("div", "", "settings-inline-editor"); box.append(editor);
  function draw() {
    editor.replaceChildren(); const customer=active.find(c=>c.customer_id===selector.value); if (!customer) return;
    const supplier=automationModeSelect("Tedarikçi hatırlatmaları", customer.supplier_reminder_mode, "Ajans ayarını kullan");
    const deadline=automationModeSelect("Müşteri deadline bilgilendirmesi", customer.customer_deadline_update_mode, "Ajans ayarını kullan");
    const controls=node("div","","settings-two-col"); controls.append(supplier.label, deadline.label); editor.append(controls);
    const fb=node("div","","muted settings-feedback"); const save=actionButton("Müşteri İstisnasını Kaydet","primary",async()=>{
      save.disabled=true; fb.textContent="Kaydediliyor…";
      try { const r=await api(`/master-data/customers/${encodeURIComponent(customer.customer_id)}/automation-policy`,{method:"POST",body:JSON.stringify({supplier_reminder_mode:supplier.value(),customer_deadline_update_mode:deadline.value()})});
        Object.assign(customer,r); fb.textContent="Müşteri otomasyon istisnası kaydedildi."; setStatus("Kaydedildi");
      } catch(e){fb.textContent=e.message||String(e); setStatus("Hata",false);} finally{save.disabled=false;}
    }); editor.append(save,fb);
  }
  selector.addEventListener("change",draw); return box;
}

function renderAutomationSettings(policyPayload, customers = []) {
  const panel = node("section", "", "settings-panel");
  const heading = node("div", "", "settings-heading");
  heading.append(node("h2", "Otomasyon"), node("p", "Ajans genel kuralı basit kalır; müşteri ve iş istisnaları gerektiğinde üstüne yazılır.", "muted")); panel.append(heading);
  const current = policyPayload?.policy || {}; const fallback = policyPayload?.legacy_fallback || {};
  const form = node("div", "", "automation-settings-form");
  const supplier = policySelect("Tedarikçi hatırlatmaları", current.supplier_reminder_mode, fallback.supplier_reminder_mode);
  const customer = policySelect("Müşteri deadline bilgilendirmeleri", current.customer_deadline_update_mode, fallback.customer_deadline_update_mode);
  const explainer = node("div", "", "automation-mode-explainer");
  explainer.append(node("div", "Manuel · MINAI izler ve hazırlar; göndermez.", "small"), node("div", "Operatör onayı · MINAI hazırlar, insan kararı gerekir.", "small"), node("div", "Otomatik · güvenlik/state/takvim izin verirse gönderir.", "small"));
  const save=actionButton("Ajans Otomasyonunu Kaydet","primary",async()=>{ save.disabled=true; feedback.textContent="Kaydediliyor…"; const value=s=>s.value==="inherit"?null:s.value;
    try{const r=await api("/automation-policy/agency",{method:"POST",body:JSON.stringify({supplier_reminder_mode:value(supplier.select),customer_deadline_update_mode:value(customer.select)})}); feedback.textContent=`Kaydedildi · ${r.updated_by||"operatör"} · ${formatDate(r.updated_at)}`; setStatus("Kaydedildi");}
    catch(e){feedback.textContent=e.message||String(e);setStatus("Hata",false);}finally{save.disabled=false;}});
  const feedback=node("div","","muted settings-feedback"); if(current.updated_by) feedback.textContent=`Son değişiklik: ${current.updated_by} · ${formatDate(current.updated_at)}`;
  form.append(supplier.label,customer.label,explainer,save,feedback); panel.append(form,renderCustomerAutomationExceptions(customers)); return panel;
}

function renderSupplierLearning(container, supplier) {
  const area=node("div","","supplier-learning"); container.append(area);
  async function load(){
    area.replaceChildren(node("div","Öğrenilen tedarikçi davranışları yükleniyor…","muted"));
    try { const data=await api(`/master-data/suppliers/${encodeURIComponent(supplier.supplier_id)}/learning-facts`); area.replaceChildren();
      const head=node("div","","settings-subheading"); head.append(node("h3","MINAI Geçmiş Gözlemleri"),node("p","Geçmiş mail/operasyon kanıtından türetilen gözlemler öneridir; operatör doğrulamadan kalıcı kural olmaz.","muted"));
      const derive=actionButton("Geçmişten Gözlem Üret","",async()=>{derive.disabled=true;try{await api(`/master-data/suppliers/${encodeURIComponent(supplier.supplier_id)}/derive-learning`,{method:"POST"});await load();}catch(e){area.append(node("div",e.message||String(e),"error"));}finally{derive.disabled=false;}}); head.append(derive); area.append(head);
      const facts=data.facts||[]; if(!facts.length){area.append(emptyState("Henüz öğrenilmiş gözlem yok","Geçmiş RFQ/yanıt kanıtı oluştukça MINAI öneriler üretebilir."));return;}
      const list=node("div","","learning-fact-list"); facts.slice().reverse().forEach(f=>{const card=node("div","","learning-fact-card");
        card.append(node("strong",f.fact_key),node("div",Array.isArray(f.value)?f.value.join(" · "):String(f.value),"small"),node("div",`${codeLabel(f.status)} · güven ${Math.round((f.confidence||0)*100)}% · ${codeLabel(f.source_type)}`,"muted small"));
        if(f.source_type==="minai_inference" && (f.evidence||[])[0]?.summary) card.append(node("div",(f.evidence||[])[0].summary,"muted small"));
        if(f.status==="proposed"){const a=node("div","","actions"); a.append(actionButton("Doğrula","approve",async()=>{await api(`/learning-facts/${encodeURIComponent(f.fact_id)}/confirm`,{method:"POST",body:JSON.stringify({review_note:"Tedarikçi profili ekranında operatör tarafından doğrulandı."})});await load();}),actionButton("Reddet","reject",async()=>{await api(`/learning-facts/${encodeURIComponent(f.fact_id)}/reject`,{method:"POST",body:JSON.stringify({review_note:"Tedarikçi profili ekranında operatör tarafından reddedildi."})});await load();}));card.append(a);} list.append(card);}); area.append(list);
    } catch(e){area.replaceChildren(node("div",e.message||String(e),"error"));}
  } load();
}

function renderSupplierSettings(suppliersPayload = {}) {
  const panel=node("section","","settings-panel"); const suppliers=(suppliersPayload.suppliers||[]).filter(s=>s.active!==false);
  const heading=node("div","","settings-heading"); heading.append(node("h2","Tedarikçiler"),node("p","Karayolu tedarikçi ilişkileri kişiye/firmaya özgü olabilir. Ayrıntılar opsiyoneldir; boş alanlarda genel MINAI davranışı kullanılır.","muted")); panel.append(heading);
  const label=node("label","Tedarikçi"); const select=document.createElement("select"); const ph=document.createElement("option");ph.value="";ph.textContent="Tedarikçi seç…";select.append(ph);suppliers.forEach(s=>{const o=document.createElement("option");o.value=s.supplier_id;o.textContent=s.supplier_name;select.append(o);});label.append(select);panel.append(label);
  const editor=node("div","","supplier-settings-editor"); panel.append(editor);
  function draw(){editor.replaceChildren();const supplier=suppliers.find(s=>s.supplier_id===select.value);if(!supplier)return;const r=supplier.relationship||{};
    const meta=node("div","","detail-grid supplier-profile-summary");meta.append(summaryItem("Rol",codeLabel(supplier.role)),summaryItem("Güvenilirlik",supplier.reliability_score),summaryItem("Fiyat",supplier.price_score),summaryItem("Hız",supplier.speed_score));editor.append(meta);
    const contacts=node("div","", "small supplier-profile-readonly"); contacts.textContent=`Kontaklar: ${(supplier.contacts||[]).map(c=>[c.contact_name,c.email,c.phone].filter(Boolean).join(" / ")).join(" · ")||"-"} | Güçlü rotalar: ${(supplier.priority_routes||[]).join(" · ")||"-"}`;editor.append(contacts);
    const form=node("div","","supplier-relationship-form");
    const channels=node("fieldset","","channel-fieldset");channels.append(node("legend","Tercih edilen iletişim kanalları"));const channelChecks={};["email","phone","whatsapp"].forEach(ch=>{const l=node("label", "", "check-label");const i=document.createElement("input");i.type="checkbox";i.checked=(r.preferred_contact_channels||["email","phone","whatsapp"]).includes(ch);channelChecks[ch]=i;l.append(i,node("span",ch==="email"?"E-posta":ch==="phone"?"Telefon":"WhatsApp"));channels.append(l);});
    const languageLabel=node("label","Tercih edilen dil");const language=document.createElement("input");language.value=r.preferred_language||"";language.maxLength=80;languageLabel.append(language);
    const reminder=automationModeSelect("Hatırlatma modu",r.supplier_reminder_mode,"İş/Müşteri/Ajans kuralını kullan"); const opMode=automationModeSelect("Yük onayı + toplama maili",r.operation_email_mode||"approval_required","Operatör onayı"); const closeMode=automationModeSelect("Teklif kapanış / teşekkür maili",r.closure_email_mode||"approval_required","Operatör onayı");
    const first=numberField("İlk reminder (dk)",r.first_reminder_minutes,5,480), ack=numberField("‘Çalışıyoruz’ sonrası bekleme (dk)",r.acknowledged_wait_minutes,15,720), max=numberField("E-posta reminder (0=atma, 1=bir kez)",r.max_email_reminders,0,1), phone=numberField("Reminder sonrası telefon eskalasyonu (dk)",r.phone_escalation_after_minutes,5,720), wa=numberField("Reminder sonrası WhatsApp eskalasyonu (dk)",r.whatsapp_escalation_after_minutes,5,720);
    const managementLabel=node("label","Yönetici/patron eskalasyonu");const management=document.createElement("select");[["inherit","Belirtilmedi"],["yes","Uygun"],["no","Kullanma"]].forEach(([v,t])=>{const o=document.createElement("option");o.value=v;o.textContent=t;management.append(o);});management.value=r.management_escalation_allowed==null?"inherit":(r.management_escalation_allowed?"yes":"no");managementLabel.append(management);
    const blockedLabel=node("label","", "check-label");const blocked=document.createElement("input");blocked.type="checkbox";blocked.checked=!!r.automatic_contact_blocked;blockedLabel.append(blocked,node("span","Bu tedarikçiye otomatik temas gönderme"));
    const tone=textareaLines("Hitap / ton notları",r.communication_tone_notes), time=textareaLines("İletişim zamanı notları",r.communication_time_notes), nego=textareaLines("Pazarlık davranışı",r.negotiation_notes), commercial=textareaLines("Ticari notlar",r.commercial_notes), behavior=textareaLines("Operasyon davranışı",r.operational_behavior_notes), relation=textareaLines("İlişki notları",r.relationship_notes);
    const paymentLabel=node("label","Ödeme/vade notu");const payment=document.createElement("textarea");payment.rows=2;payment.value=r.payment_terms_note||"";paymentLabel.append(payment); const detentionLabel=node("label","Detention notu");const detention=document.createElement("textarea");detention.rows=2;detention.value=r.detention_notes||"";detentionLabel.append(detention); const vehicleLabel=node("label","Araç bilgisi davranış notu");const vehicle=document.createElement("textarea");vehicle.rows=2;vehicle.value=r.vehicle_information_notes||"";vehicleLabel.append(vehicle);
    const grid=node("div","","settings-two-col");grid.append(languageLabel,reminder.label,opMode.label,closeMode.label,first.label,ack.label,max.label,phone.label,wa.label,managementLabel);form.append(channels,grid,blockedLabel,tone.label,time.label,nego.label,commercial.label,behavior.label,relation.label,paymentLabel,detentionLabel,vehicleLabel);
    const fb=node("div","","muted settings-feedback");const save=actionButton("Tedarikçi Profilini Kaydet","primary",async()=>{const chosen=Object.entries(channelChecks).filter(([,i])=>i.checked).map(([k])=>k);if(!chosen.length){fb.textContent="En az bir iletişim kanalı seç.";return;}save.disabled=true;fb.textContent="Kaydediliyor…";
      const relationship={...r,preferred_contact_channels:chosen,preferred_language:language.value.trim()||null,supplier_reminder_mode:reminder.value(),first_reminder_minutes:first.value(),acknowledged_wait_minutes:ack.value(),max_email_reminders:max.value(),phone_escalation_after_minutes:phone.value(),whatsapp_escalation_after_minutes:wa.value(),management_escalation_allowed:management.value==="inherit"?null:management.value==="yes",operation_email_mode:opMode.value()||"approval_required",closure_email_mode:closeMode.value()||"approval_required",automatic_contact_blocked:blocked.checked,communication_tone_notes:tone.value(),communication_time_notes:time.value(),negotiation_notes:nego.value(),commercial_notes:commercial.value(),operational_behavior_notes:behavior.value(),relationship_notes:relation.value(),payment_terms_note:payment.value.trim()||null,detention_notes:detention.value.trim()||null,vehicle_information_notes:vehicle.value.trim()||null};
      const payload={supplier_name:supplier.supplier_name,active:supplier.active,role:supplier.role,contacts:supplier.contacts||[],geographies:supplier.geographies||[],service_types:supplier.service_types||[],equipment_types:supplier.equipment_types||[],special_capabilities:supplier.special_capabilities||[],priority_routes:supplier.priority_routes||[],legacy_region_tags:supplier.legacy_region_tags||[],reliability_score:supplier.reliability_score,price_score:supplier.price_score,speed_score:supplier.speed_score,relationship,notes:supplier.notes};
      try{const saved=await api(`/master-data/suppliers/${encodeURIComponent(supplier.supplier_id)}`,{method:"POST",body:JSON.stringify(payload)});Object.assign(supplier,saved);fb.textContent="Tedarikçi ilişki profili kaydedildi.";setStatus("Kaydedildi");}catch(e){fb.textContent=e.message||String(e);setStatus("Hata",false);}finally{save.disabled=false;}});
    form.append(save,fb);editor.append(form);renderSupplierLearning(editor,supplier);
  }
  select.addEventListener("change",draw); if(suppliers.length===1){select.value=suppliers[0].supplier_id;draw();} return panel;
}


function localDateTimeValue(date) {
  const adjusted = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return adjusted.toISOString().slice(0, 16);
}

async function renderRelationshipFactReview(container, subject) {
  container.replaceChildren(node("div", "Gözlemler yükleniyor…", "muted"));
  try {
    const base = subject.subject_type === "supplier" ? "/master-data/suppliers" : "/master-data/customers";
    const data = await api(`${base}/${encodeURIComponent(subject.subject_id)}/learning-facts`);
    container.replaceChildren();
    const facts = (data.facts || []).slice().reverse();
    if (!facts.length) { container.append(emptyState("Bu taraf için gözlem yok")); return; }
    facts.forEach(f => {
      const card=node("div","","learning-fact-card");
      card.append(
        node("strong",f.fact_key),
        node("div",Array.isArray(f.value)?f.value.join(" · "):String(f.value),"small"),
        node("div",`${codeLabel(f.status)} · güven ${Math.round((f.confidence||0)*100)}% · ${codeLabel(f.source_type)}`,"muted small")
      );
      if(f.source_type==="minai_inference" && (f.evidence||[])[0]?.summary){
        card.append(node("div",(f.evidence||[])[0].summary,"muted small"));
      }
      if(f.status==="proposed"){
        const actions=node("div","","actions");
        actions.append(
          actionButton("Doğrula","approve",async()=>{await api(`/learning-facts/${encodeURIComponent(f.fact_id)}/confirm`,{method:"POST",body:JSON.stringify({review_note:"İlişki Hafızası ekranında operatör tarafından doğrulandı."})});await renderRelationshipFactReview(container,subject);}),
          actionButton("Reddet","reject",async()=>{await api(`/learning-facts/${encodeURIComponent(f.fact_id)}/reject`,{method:"POST",body:JSON.stringify({review_note:"İlişki Hafızası ekranında operatör tarafından reddedildi."})});await renderRelationshipFactReview(container,subject);})
        ); card.append(actions);
      }
      container.append(card);
    });
  } catch (e) { container.replaceChildren(node("div",e.message||String(e),"error")); }
}

function renderRelationshipOnboardingResult(container, result) {
  container.replaceChildren();
  const summary=node("div","","summary-grid relationship-history-summary");
  summary.append(
    summaryItem("Okunan benzersiz mail",result.unique_message_count??0),
    summaryItem("Eşleşen mail",result.matched_message_count??0),
    summaryItem("Eşleşmeyen",result.unmatched_message_count??0),
    summaryItem("Belirsiz eşleşme",result.ambiguous_message_count??0),
    summaryItem("Yeni öneri",result.proposed_fact_count??0),
    summaryItem("AI gözlemi",result.ai_observation_count??0),
    summaryItem("Sınırlı örnek",result.ai_observation_sample_only_count??0),
    summaryItem("Tekrarlayan patern",result.ai_observation_recurring_count??0),
    summaryItem("AI hard guard eledi",result.ai_observation_hard_rejected_count??result.ai_observation_skipped_count??0)
  ); container.append(summary);
  if (result.raw_messages_persisted === false || result.raw_body_persisted === false) {
    container.append(node("div","Ham geçmiş mail gövdeleri onboarding state’inde saklanmadı.","notice"));
  }
  const unmatched=result.unmatched_addresses||[];
  if(unmatched.length) container.append(node("div",`Eşleşmeyen karşı taraf adayları: ${unmatched.slice(0,20).join(" · ")}${unmatched.length>20?` · +${unmatched.length-20}`:""}`,"small relationship-unmatched"));
  const ambiguous=result.ambiguous_addresses||[];
  if(ambiguous.length) container.append(node("div",`Çakışan master-data adresleri: ${ambiguous.join(" · ")}`,"warning small"));
  const subjects=result.subjects||[];
  const list=node("div","","relationship-subject-list");
  subjects.forEach(subject=>{
    const card=node("section","","relationship-subject-card");
    card.append(
      node("h3",subject.subject_label||"-"),
      node("div",`${subject.subject_type==="supplier"?"Tedarikçi":"Müşteri"} · ${subject.message_count} mail · ${subject.thread_count} konu · karşı taraf cevap örneği ${subject.counterparty_response_sample_count} · ajans cevap örneği ${subject.agency_response_sample_count}`,"muted small")
    );
    const facts=node("div","","relationship-subject-facts");
    const toggle=actionButton("Gözlemleri Aç","",async()=>{toggle.disabled=true;await renderRelationshipFactReview(facts,subject);toggle.disabled=false;});
    card.append(toggle,facts); list.append(card);
  });
  if(!subjects.length) list.append(emptyState("Master-data ile eşleşen ilişki bulunamadı","Eşleşmeyen adresleri kontrol edip müşteri/tedarikçi master kaydı oluşturduktan sonra analiz tekrar çalıştırılabilir."));
  container.append(list);
}

function renderRelationshipOnboardingSettings(status = {}) {
  const panel=node("section","","settings-panel");
  const h=node("div","","settings-heading");
  h.append(node("h2","İlişki Hafızası"),node("p","Müşteri ve tedarikçi geçmiş e-postalarından ölçülebilir ilişki davranışları ve doğrulama bekleyen MINAI gözlemleri üretir. Normal günlük inbox pull’undan ayrıdır.","muted"));panel.append(h);
  const health=node("div","","summary-grid relationship-onboarding-health");
  health.append(
    summaryItem("Outlook",status.synthetic_mailbox?"Demo mailbox":(status.outlook_configured?"Hazır":"Yapılandırma eksik")),
    summaryItem("Müşteri master",status.customer_master_count??0),
    summaryItem("Tedarikçi master",status.supplier_master_count??0),
    summaryItem("Bekleyen müşteri gözlemi",status.proposed_customer_fact_count??0),
    summaryItem("Bekleyen tedarikçi gözlemi",status.proposed_supplier_fact_count??0)
  ); panel.append(health);
  panel.append(node("div",status.synthetic_mailbox?"Demo modunda bu ekran gerçek Outlook yerine sentetik mailbox geçmişini kullanır. Ham mail gövdeleri kalıcı onboarding state’ine yazılmaz.":"Ham mail gövdeleri kalıcı onboarding state’ine yazılmaz. Eşleşmeyen taraflar otomatik müşteri/tedarikçi yapılmaz.","notice"));

  const form=node("div","","relationship-onboarding-form");
  const now=new Date(); const startDefault=new Date(now.getTime()-180*24*60*60*1000);
  const startLabel=node("label","Başlangıç");const start=document.createElement("input");start.type="datetime-local";start.value=localDateTimeValue(startDefault);startLabel.append(start);
  const endLabel=node("label","Bitiş");const end=document.createElement("input");end.type="datetime-local";end.value=localDateTimeValue(now);endLabel.append(end);
  const limit=numberField("Maksimum mesaj",5000,1,status.max_history_messages||10000);
  const aliases=textareaLines("Ajansın ek e-posta adresleri / alias’ları",[],2);
  const authorizedLabel=node("label","","check-label");const authorized=document.createElement("input");authorized.type="checkbox";authorizedLabel.append(authorized,node("span","Bu mailbox geçmişini seçilen tarih aralığında analiz etmeye yetkim var."));
  const aiLabel=node("label","","check-label");const ai=document.createElement("input");ai.type="checkbox";aiLabel.append(ai,node("span",status.synthetic_mailbox?"Sentetik AI davranış gözlemlerini de üret (dış servis çağrısı yapılmaz).":"AI davranış gözlemlerini de üret (privacy transform sonrası OpenAI çağrısı yapılır)."));
  const grid=node("div","","settings-two-col");grid.append(startLabel,endLabel,limit.label,aliases.label);form.append(grid,authorizedLabel,aiLabel);
  const feedback=node("div","","muted settings-feedback");const result=node("div","","relationship-onboarding-result");
  const run=actionButton(status.synthetic_mailbox?"Sentetik Outlook Analizini Başlat":"Geçmiş Outlook Analizini Başlat","primary",async()=>{
    if(!authorized.checked){feedback.textContent="Analiz için yetki onay kutusunu işaretlemelisin.";return;}
    if(!start.value||!end.value){feedback.textContent="Başlangıç ve bitiş tarihi gerekli.";return;}
    run.disabled=true;feedback.textContent="Geçmiş e-postalar okunuyor ve ilişki kanıtı çıkarılıyor…";result.replaceChildren();
    try{
      const response=await api("/relationship-onboarding/outlook/analyze",{method:"POST",body:JSON.stringify({
        start_at:new Date(start.value).toISOString(),end_at:new Date(end.value).toISOString(),max_messages:limit.value(),authorization_confirmed:true,include_ai_observations:ai.checked,agency_alias_addresses:aliases.value()
      })});
      feedback.textContent=`Analiz tamamlandı · ${response.unique_message_count??0} benzersiz mail · ${response.proposed_fact_count??0} yeni öneri.`;renderRelationshipOnboardingResult(result,response);setStatus("Analiz tamamlandı");
    }catch(e){feedback.textContent=e.message||String(e);setStatus("Hata",false);}finally{run.disabled=false;}
  });
  form.append(run,feedback,result);panel.append(form);return panel;
}

function renderPerformanceSettings(settings = {}) {
  const panel=node("section","","settings-panel");const h=node("div","","settings-heading");h.append(node("h2","Performans"),node("p","Tek personel puanı yok. MINAI gerçek süreleri ölçer; hedefler yalnız süreç darboğazını görmek içindir.","muted"));panel.append(h);
  const firstEnabled=document.createElement("input");firstEnabled.type="checkbox";firstEnabled.checked=settings.first_look_target_minutes!=null;const first=numberField("İlk bakış hedefi (dk)",settings.first_look_target_minutes??15,1,240);const firstRow=node("div","","performance-setting-row");const firstToggle=node("label","","check-label");firstToggle.append(firstEnabled,node("span","İlk bakış hedefini kullan"));firstRow.append(firstToggle,first.label);
  const decisionEnabled=document.createElement("input");decisionEnabled.type="checkbox";decisionEnabled.checked=settings.decision_target_minutes!=null;const decision=numberField("Onay/karar hedefi (dk)",settings.decision_target_minutes??15,1,480);const decisionRow=node("div","","performance-setting-row");const decisionToggle=node("label","","check-label");decisionToggle.append(decisionEnabled,node("span","Karar hedefini kullan"));decisionRow.append(decisionToggle,decision.label);
  const note=node("div","Gerçek raporlar ortalama, medyan ve P90 sürelerini ayrı gösterir. Görev bırakma/devretme tamamlanma değildir.","notice");const fb=node("div","","muted settings-feedback");if(settings.updated_by)fb.textContent=`Son değişiklik: ${settings.updated_by} · ${formatDate(settings.updated_at)}`;
  const save=actionButton("Performans Hedeflerini Kaydet","primary",async()=>{save.disabled=true;fb.textContent="Kaydediliyor…";try{const r=await api("/settings/performance",{method:"POST",body:JSON.stringify({first_look_target_minutes:firstEnabled.checked?first.value():null,decision_target_minutes:decisionEnabled.checked?decision.value():null})});fb.textContent=`Kaydedildi · ${r.updated_by} · ${formatDate(r.updated_at)}`;setStatus("Kaydedildi");}catch(e){fb.textContent=e.message||String(e);setStatus("Hata",false);}finally{save.disabled=false;}});
  panel.append(firstRow,decisionRow,note,save,fb);return panel;
}

let settingsSelectedTab="automation";
function renderSettings(branding, automationPolicy, customersPayload = {}, suppliersPayload = {}, performanceSettings = {}, relationshipStatus = {}) {
  setPageContext("Ayarlar", "Sistem Ayarları"); const page=node("div","","settings-page");const tabs=node("div","","settings-tabs");const body=node("div","","settings-tab-body");
  const panels={automation:()=>renderAutomationSettings(automationPolicy,customersPayload.customers||[]),suppliers:()=>renderSupplierSettings(suppliersPayload),relationship:()=>renderRelationshipOnboardingSettings(relationshipStatus),performance:()=>renderPerformanceSettings(performanceSettings),branding:()=>renderBrandingPanel(branding)};
  function draw(){tabs.replaceChildren();[["automation","Otomasyon"],["suppliers","Tedarikçiler"],["relationship","İlişki Hafızası"],["performance","Performans"],["branding","Branding"]].forEach(([k,l])=>tabs.append(actionButton(l,k===settingsSelectedTab?"active":"",()=>{settingsSelectedTab=k;draw();})));body.replaceChildren(panels[settingsSelectedTab]());}
  page.append(tabs,body);content.replaceChildren(page);draw();
}

async function boot() {
  const page = document.body.dataset.page;
  markActiveNavigation(page);
  content.replaceChildren(node("div", "Yükleniyor…", "muted loading-state"));
  try {
    const branding = await api("/settings/branding");
    applyBranding(branding);
    if (page === "dashboard") {
      await loadDashboard(5); return;
    } else if (page === "inbox") {
      await loadInbox(); return;
    } else if (page === "work") {
      await loadOperationalWork(); return;
    } else if (page === "jobs") {
      renderJobs(await api("/mina-jobs"));
    } else if (page === "job") {
      await loadJob(document.body.dataset.jobId || ""); return;
    } else if (page === "reports") {
      renderReports(await api("/reports"));
    } else if (page === "settings") {
      const [automationPolicy, customersPayload, suppliersPayload, performanceSettings, relationshipStatus] = await Promise.all([
        api("/automation-policy/agency"), api("/master-data/customers"),
        api("/master-data/suppliers"), api("/settings/performance"), api("/relationship-onboarding/status")
      ]);
      renderSettings(branding, automationPolicy, customersPayload, suppliersPayload, performanceSettings, relationshipStatus);
    }
    setStatus("Güncel");
  } catch (error) { showError(error); }
}

document.addEventListener("DOMContentLoaded", boot);
