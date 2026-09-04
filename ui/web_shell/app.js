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
  return ({ job: "Bu iş", job_legacy_disable: "Bu iş · devre dışı", customer: "Müşteri", agency: "Ajans", legacy_dispatch: "Sistem varsayılanı" })[value] || codeLabel(value);
}
function transportLabel(value) {
  return ({ road: "Karayolu", rail: "Demiryolu", sea: "Denizyolu", air: "Havayolu", multimodal: "Multimodal" })[value] || codeLabel(value);
}
function reminderStateLabel(value) {
  return ({
    waiting: "Bekliyor", manual_reminder_due: "Manuel hatırlatma zamanı",
    approval_required_supplier_reminder_due: "Hatırlatma onay bekliyor", automatic_reminder_due: "Otomatik hatırlatma zamanı",
    human_contact_required: "Telefon / WhatsApp takibi gerekli", outside_business_hours_waiting: "Çalışma saati bekleniyor",
    commercial_response_present: "Yanıt alındı", not_waiting_for_response: "Yanıt beklenmiyor",
    approval_rejected_no_send: "Hatırlatma reddedildi", automation_delivery_attention: "Gönderim hatası",
    automation_cancelled_manual_attention: "Manuel takip gerekli", missing_supplier_recipient_manual_attention: "Tedarikçi e-postası eksik",
    supplier_calendar_unavailable_manual_attention: "Çalışma takvimi doğrulanamadı", not_automation_eligible: "Otomasyon dışı"
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
};

const APPROVAL_WORK_ACTIONS = new Set([
  "confirm_extraction",
  "approve_supplier_follow_up",
  "review_and_approve_supplier_reminder",
  "review_and_approve_customer_update",
  "decide_quote_approval",
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

function workCard(item, myIds, refresh) {
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
  if (actions.childElementCount) card.append(actions);
  return card;
}

function renderOperationalWork(queue, mine) {
  title.textContent = "İş Kuyruğu";
  const root = node("div", "", "work-page");
  const items = queue.items || [];
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
      renderOperationalWork(queue, mine);
    }));
  }
  root.append(tabs);

  const activeFilter = filters.find(([key]) => key === operationalWorkView) || filters[0];
  const visible = items.filter(activeFilter[2]);
  const list = node("div", "", "work-list");
  const refresh = () => loadOperationalWork(operationalWorkView);
  visible.forEach(item => list.append(workCard(item, myIds, refresh)));
  if (!visible.length) list.append(node("div", "Bu görünümde bekleyen iş yok.", "work-empty"));
  root.append(list);
  content.replaceChildren(root);
}

async function loadOperationalWork(view = operationalWorkView) {
  operationalWorkView = view;
  const [queue, mine] = await Promise.all([
    api("/operational-work-queue"),
    api("/operational-work-my"),
  ]);
  renderOperationalWork(queue, mine);
  setStatus("Güncel");
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

  const reminder = supplier.reminder || {};
  if (reminder.state) {
    const reminderLine = node("div", "", "supplier-reminder-line");
    reminderLine.append(node("strong", reminderStateLabel(reminder.state)));
    if (reminder.due_at) reminderLine.append(node("span", ` · ${formatDate(reminder.due_at)}`, "small"));
    if (reminder.resume_at) reminderLine.append(node("span", ` · devam ${formatDate(reminder.resume_at)}`, "small"));
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

async function renderApprovedQuoteSend(container, quoteCase, approval, refresh) {
  const sent = [...(quoteCase.manual_sent_evidence || []), ...(quoteCase.automated_sent_evidence || [])]
    .sort((a, b) => new Date(b.sent_at) - new Date(a.sent_at));
  if (sent.length) {
    const latest = sent[0];
    container.append(node("div", `Gönderildi · ${latest.recipient_email || "-"} · ${formatDate(latest.sent_at)}`, "notice success-notice"));
    return;
  }
  let finalOutput;
  try { finalOutput = await api(`/quote-cases/${encodeURIComponent(quoteCase.case_id)}/final-output`); }
  catch (error) { container.append(node("div", `Gönderime hazır değil: ${error.message || error}`, "notice")); return; }
  const sendBox = node("div", "", "quote-send-box approval-focused");
  sendBox.append(node("h3", "Müşteriye Gönder"));
  const recipientLabel = node("label", "Alıcı e-posta"); const recipient = document.createElement("input"); recipient.type = "email"; recipient.autocomplete = "off"; recipientLabel.append(recipient);
  sendBox.append(recipientLabel, node("div", finalOutput.subject, "quote-subject"), node("div", finalOutput.body, "preview approval-message-body"));
  const price = node("div", `${moneyLabel(finalOutput.final_price, finalOutput.currency)}`, "quote-final-price"); sendBox.append(price);
  const feedback = node("div", "", "muted approval-feedback"); const actions = node("div", "", "actions");
  const send = actionButton("Gönder", "approve", async () => {
    const email = recipient.value.trim(); if (!email || !recipient.checkValidity()) { feedback.textContent = "Geçerli alıcı e-posta adresi gerekli."; return; }
    send.disabled = true; feedback.textContent = "Gönderim öncesi onay ve içerik yeniden doğrulanıyor…";
    try { await api(`/quote-cases/${encodeURIComponent(quoteCase.case_id)}/send`, { method: "POST", body: JSON.stringify({ expected_approval_id: approval.approval_id, recipient_email: email }) }); await refresh(); }
    catch (error) { feedback.textContent = error.message || String(error); send.disabled = false; }
  });
  const manual = actionButton("Harici Gönderildi Olarak Kaydet", "", async () => {
    const email = recipient.value.trim(); if (!email || !recipient.checkValidity()) { feedback.textContent = "Geçerli alıcı e-posta adresi gerekli."; return; }
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
    summaryItem("Gönderim", (quoteCase.automated_sent_evidence || []).length + (quoteCase.manual_sent_evidence || []).length)
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

  await renderQuoteSection(root, data, async () => loadJob(jobId));
  const suppliers = sectionBlock("Tedarikçiler", "RFQ durumu, fiyat ve takip aksiyonları.");
  for (const supplier of (data.suppliers || [])) await renderSupplier(
    suppliers, jobId, supplier, async () => loadJob(jobId), data.automation?.supplier_reminder_policy || null
  );
  if (!(data.suppliers || []).length) suppliers.append(emptyState("Henüz tedarikçi çalışması yok")); root.append(suppliers);
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
  wrap.append(node("h2", "Operatör İş Kuyruğu Performansı"));
  const performance = section?.work_assignment_performance || {};
  const summary = performance.summary || {};
  const summaryGrid = node("div", "", "grid report-performance-metrics");
  summaryGrid.append(
    metric("Atama generation", summary.assignment_generation_count ?? 0),
    metric("İlk bakış kaydı", summary.acknowledged_generation_count ?? 0),
    metric("İlk bakış kapsamı %", summary.first_look_coverage_percent ?? "-"),
    metric("Ort. ilk bakış", summary.average_first_look_seconds == null ? "-" : durationLabel(summary.average_first_look_seconds)),
    metric("Medyan ilk bakış", summary.median_first_look_seconds == null ? "-" : durationLabel(summary.median_first_look_seconds))
  );
  wrap.append(summaryGrid);

  const authority = node("div", "", "notice report-performance-note");
  const slaText = performance.first_look_sla_status === "threshold_not_configured"
    ? "İlk bakış SLA eşiği henüz tanımlı değil; SLA yüzdesi üretilmiyor."
    : `İlk bakış SLA durumu: ${codeLabel(performance.first_look_sla_status)}`;
  const completionText = performance.completion_metric_status === "work_type_completion_mapping_not_configured"
    ? "Release/handoff tamamlanma sayılmaz; work-type completion eşlemesi henüz tanımlı değil."
    : `Tamamlanma metriği: ${codeLabel(performance.completion_metric_status)}`;
  authority.append(
    node("div", `Dönem temeli: ${codeLabel(performance.period_basis)}`),
    node("div", slaText),
    node("div", completionText)
  );
  wrap.append(authority);

  const rows = performance.rows || [];
  if (!rows.length) {
    wrap.append(node("div", "Bu dönem için ölçülebilir assignment performans kaydı yok.", "muted report-performance-empty"));
    return wrap;
  }
  const tableWrap = node("div", "", "table-wrap report-performance-table");
  const table = document.createElement("table");
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  ["Operatör", "Atama", "İlk Bakış", "Kapsam %", "Ort. İlk Bakış", "Medyan", "Handoff", "Bırakma", "Reassignment"].forEach(label => {
    headRow.append(node("th", label));
  });
  thead.append(headRow);
  table.append(thead);
  const tbody = document.createElement("tbody");
  for (const row of rows) {
    const tr = document.createElement("tr");
    tr.append(
      node("td", row.name || "-"),
      node("td", row.assignment_generation_count ?? 0),
      node("td", row.acknowledged_generation_count ?? 0),
      node("td", row.first_look_coverage_percent ?? "-"),
      node("td", row.average_first_look_seconds == null ? "-" : durationLabel(row.average_first_look_seconds)),
      node("td", row.median_first_look_seconds == null ? "-" : durationLabel(row.median_first_look_seconds)),
      node("td", row.shift_handoff_count ?? 0),
      node("td", row.operator_release_count ?? 0),
      node("td", row.reassignment_generation_count ?? 0)
    );
    tbody.append(tr);
  }
  table.append(tbody);
  tableWrap.append(table);
  wrap.append(tableWrap);
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

function renderAutomationSettings(policyPayload) {
  const panel = node("section", "", "settings-panel");
  const heading = node("div", "", "settings-heading");
  heading.append(node("h2", "Otomasyon"), node("p", "Ajans genelinde MINAI aksiyonlarının otomatik, onaylı veya manuel çalışmasını belirler. İşe özel ayar daha yüksek önceliklidir.", "muted"));
  panel.append(heading);
  const current = policyPayload?.policy || {};
  const fallback = policyPayload?.legacy_fallback || {};
  const form = node("div", "", "automation-settings-form");
  const supplier = policySelect("Tedarikçi hatırlatmaları", current.supplier_reminder_mode, fallback.supplier_reminder_mode);
  const customer = policySelect("Müşteri deadline bilgilendirmeleri", current.customer_deadline_update_mode, fallback.customer_deadline_update_mode);
  const explainer = node("div", "", "automation-mode-explainer");
  explainer.append(
    node("div", "Manuel · MINAI hazırlar/izler, otomatik gönderim yapmaz.", "small"),
    node("div", "Operatör onayı · MINAI mesajı hazırlar, gönderimden önce insan kararı gerekir.", "small"),
    node("div", "Otomatik · mevcut güvenlik, takvim ve state kontrolleri izin verirse sistem gönderir.", "small")
  );
  const actions = node("div", "", "actions");
  const save = node("button", "Otomasyon Ayarlarını Kaydet", "primary"); save.type = "button"; actions.append(save);
  const feedback = node("div", "", "muted settings-feedback");
  if (current.updated_by) feedback.textContent = `Son değişiklik: ${current.updated_by} · ${formatDate(current.updated_at)}`;
  save.addEventListener("click", async () => {
    save.disabled = true; feedback.textContent = "Kaydediliyor…";
    const value = select => select.value === "inherit" ? null : select.value;
    try {
      const saved = await api("/automation-policy/agency", { method: "POST", body: JSON.stringify({
        supplier_reminder_mode: value(supplier.select), customer_deadline_update_mode: value(customer.select)
      }) });
      feedback.textContent = `Kaydedildi · ${saved.updated_by || "operatör"} · ${formatDate(saved.updated_at)}`; setStatus("Kaydedildi");
    } catch (error) { feedback.textContent = error.message || String(error); setStatus("Hata", false); }
    finally { save.disabled = false; }
  });
  form.append(supplier.label, customer.label, explainer, actions, feedback); panel.append(form); return panel;
}

function renderSettings(branding, automationPolicy) {
  setPageContext("Ayarlar", "Sistem Ayarları");
  const page = node("div", "", "settings-page");
  const tabs = node("div", "", "settings-tabs");
  const body = node("div", "", "settings-tab-body");
  const panels = { automation: () => renderAutomationSettings(automationPolicy), branding: () => renderBrandingPanel(branding) };
  let selected = "automation";
  function draw() {
    tabs.replaceChildren();
    [["automation", "Otomasyon"], ["branding", "Branding"]].forEach(([key, label]) => {
      const button = actionButton(label, key === selected ? "active" : "", () => { selected = key; draw(); });
      tabs.append(button);
    });
    body.replaceChildren(panels[selected]());
  }
  page.append(tabs, body); content.replaceChildren(page); draw();
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
    } else if (page === "work") {
      await loadOperationalWork(); return;
    } else if (page === "jobs") {
      renderJobs(await api("/mina-jobs"));
    } else if (page === "job") {
      await loadJob(document.body.dataset.jobId || ""); return;
    } else if (page === "reports") {
      renderReports(await api("/reports"));
    } else if (page === "settings") {
      const automationPolicy = await api("/automation-policy/agency");
      renderSettings(branding, automationPolicy);
    }
    setStatus("Güncel");
  } catch (error) { showError(error); }
}

document.addEventListener("DOMContentLoaded", boot);
