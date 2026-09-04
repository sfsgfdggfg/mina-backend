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
  title.textContent = "MINA İşleri";
  const toolbar = node("div", "", "toolbar");
  const search = document.createElement("input");
  search.type = "search";
  search.placeholder = "MINA kodu, müşteri, rota veya sorumlu ara";
  toolbar.append(search);
  const wrap = node("div", "", "table-wrap");
  const table = document.createElement("table");
  table.innerHTML = "<thead><tr><th>İş</th><th>Müşteri</th><th>Rota</th><th>Aşama</th><th>Operasyon</th><th>Güncelleme</th></tr></thead>";
  const body = document.createElement("tbody");
  table.append(body); wrap.append(table); content.replaceChildren(toolbar, wrap);
  const jobs = data.jobs || [];

  function draw(query = "") {
    body.replaceChildren();
    const q = query.trim().toLocaleLowerCase("tr-TR");
    jobs.filter(job => !q || [job.mina_code, job.customer_name, job.route, job.stage,
      job.operations_owner, job.sales_owner].some(v => String(v || "").toLocaleLowerCase("tr-TR").includes(q)))
      .forEach(job => {
        const tr = node("tr", "", "clickable");
        tr.append(node("td", job.mina_code), node("td", job.customer_name || "-"), node("td", job.route || "-"));
        const stage = node("span", job.stage || "-", `badge ${job.is_closed ? "" : "open"}`);
        const stageTd = node("td"); stageTd.append(stage); tr.append(stageTd);
        tr.append(node("td", job.operations_owner || "-"), node("td", formatDate(job.updated_at)));
        tr.addEventListener("click", () => window.location.assign(`/app/jobs/${encodeURIComponent(job.job_id)}`));
        body.append(tr);
      });
  }
  search.addEventListener("input", () => draw(search.value)); draw();
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
  const card = node("div", "", "approval-card");
  card.append(node("h3", preview.subject || "Onay bekleyen mesaj"));
  card.append(node("div", preview.body_text || "", "preview"));
  const actions = node("div", "", "actions");
  actions.append(actionButton("Onayla ve Gönder", "approve", async () => {
    try { await postDecision(approvePath, "approve"); await onDone(); }
    catch (error) { showError(error); }
  }));
  actions.append(actionButton("Reddet", "reject", async () => {
    const reason = window.prompt("Reddetme nedeni:");
    if (!reason || !reason.trim()) return;
    try { await postDecision(approvePath, "reject", reason.trim()); await onDone(); }
    catch (error) { showError(error); }
  }));
  card.append(actions); return card;
}

async function renderSupplier(container, jobId, supplier, refresh) {
  const card = node("div", "", "supplier-card");
  card.append(node("h3", supplier.supplier_name || "Tedarikçi"));
  const line = node("div", "", "row");
  line.append(node("span", `Durum: ${supplier.status || "-"}`, "small"));
  line.append(node("span", `Katman: ${supplier.dispatch_tier || "-"}`, "small"));
  if (supplier.commercial_response?.cost != null) {
    line.append(node("span", `Fiyat: ${supplier.commercial_response.cost} ${supplier.commercial_response.currency || ""}`, "small"));
  }
  card.append(line);
  const reminder = supplier.reminder || {};
  if (reminder.state) card.append(node("div", `Reminder: ${reminder.state}`, "small"));
  if (reminder.state === "approval_required_supplier_reminder_due") {
    const actions = node("div", "", "actions");
    actions.append(actionButton("Mesajı Önizle", "", async () => {
      try {
        const preview = await api(`/mina-jobs/${encodeURIComponent(jobId)}/supplier-rfqs/${encodeURIComponent(supplier.rfq_id)}/reminder-approval-preview`);
        const old = card.querySelector(".approval-card"); if (old) old.remove();
        card.append(approvalPreviewCard(
          preview,
          `/mina-jobs/${encodeURIComponent(jobId)}/supplier-rfqs/${encodeURIComponent(supplier.rfq_id)}/reminder-approval`,
          refresh,
        ));
      } catch (error) { showError(error); }
    }));
    card.append(actions);
  }
  container.append(card);
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

function timeline(container, events) {
  const section = node("div", "", "section");
  section.append(node("h2", "Zaman Çizelgesi"));
  (events || []).slice().reverse().slice(0, 25).forEach(event => {
    const item = node("div", "", "timeline-item");
    item.append(node("strong", String(event.event_type || "event").replaceAll("_", " ")));
    item.append(node("div", `${formatDate(event.occurred_at)} · ${event.actor || "-"}`, "small"));
    section.append(item);
  });
  container.append(section);
}

async function renderJob(data, jobId) {
  const summary = data.summary || {};
  title.textContent = summary.mina_code || "MINA İşi";
  const root = node("div");
  const grid = node("div", "", "summary-grid");
  grid.append(
    summaryItem("Müşteri", summary.customer_name || "-"),
    summaryItem("Rota", summary.route || "-"),
    summaryItem("Aşama", summary.stage || "-"),
    summaryItem("Operasyon", summary.operations_owner || "-")
  );
  root.append(grid);

  const automation = node("div", "", "section");
  automation.append(node("h2", "MINAI Onayları"));
  const refresh = async () => loadJob(jobId);
  await renderCustomerApproval(
    automation, jobId, data.automation?.customer_deadline_plan || {}, refresh
  );
  root.append(automation);

  const suppliers = node("div", "", "section");
  suppliers.append(node("h2", "Tedarikçiler"));
  for (const supplier of (data.suppliers || [])) {
    await renderSupplier(suppliers, jobId, supplier, refresh);
  }
  if (!(data.suppliers || []).length) suppliers.append(node("div", "Henüz tedarikçi çalışması yok.", "muted"));
  root.append(suppliers);

  const operation = data.operation || {};
  const operationSection = node("div", "", "section");
  operationSection.append(node("h2", "Operasyon"));
  const execution = operation.execution || operation.snapshot || null;
  if (execution) {
    const opGrid = node("div", "", "summary-grid");
    opGrid.append(
      summaryItem("Araç", execution.vehicle_plate || "-"),
      summaryItem("Sürücü", execution.driver_name || "-"),
      summaryItem("Konum", execution.current_location || "-"),
      summaryItem("ETA", formatDate(execution.current_eta_at || execution.eta_at))
    );
    operationSection.append(opGrid);
  } else {
    operationSection.append(node("div", "Henüz operasyon yürütme kaydı yok.", "muted"));
  }
  const exceptions = operation.exceptions || [];
  if (exceptions.length) {
    operationSection.append(node("div", `${exceptions.filter(x => x.status === "open").length} açık istisna`, "notice"));
  }
  root.append(operationSection);
  timeline(root, data.timeline || []);
  content.replaceChildren(root);
}

async function loadJob(jobId) {
  try {
    const data = await api(`/mina-jobs/${encodeURIComponent(jobId)}`);
    await renderJob(data, jobId); setStatus("Güncel");
  } catch (error) { showError(error); }
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

function renderBrandingSettings(branding) {
  title.textContent = "Ayarlar";
  let pendingLogo = branding.logo_data_uri || null;
  const page = node("div", "", "settings-page");
  const heading = node("div", "", "settings-heading");
  heading.append(node("h2", "Branding"), node("p", "Firma adı, logo ve marka renkleri. Kritik durum renkleri sistem tarafından sabit tutulur.", "muted"));
  page.append(heading);

  const form = node("div", "", "branding-form");
  const companyLabel = node("label", "Firma adı");
  const companyInput = document.createElement("input");
  companyInput.type = "text";
  companyInput.maxLength = 120;
  companyInput.value = branding.company_name || "MINAI";
  companyLabel.append(companyInput);

  const colors = node("div", "", "branding-color-grid");
  const primaryLabel = node("label", "Ana marka rengi");
  const primaryInput = document.createElement("input");
  primaryInput.type = "color";
  primaryInput.value = (branding.primary_color || "#3157D5").toLowerCase();
  primaryLabel.append(primaryInput);
  const secondaryLabel = node("label", "İkincil vurgu rengi");
  const secondaryInput = document.createElement("input");
  secondaryInput.type = "color";
  secondaryInput.value = (branding.secondary_accent_color || "#172033").toLowerCase();
  secondaryLabel.append(secondaryInput);
  colors.append(primaryLabel, secondaryLabel);

  const logoLabel = node("label", "Logo");
  const logoInput = document.createElement("input");
  logoInput.type = "file";
  logoInput.accept = "image/png,image/jpeg,image/webp";
  logoLabel.append(logoInput, node("span", "PNG, JPEG veya WebP · en fazla 256 KB", "muted branding-help"));

  const preview = node("div", "", "branding-preview");
  const previewMark = node("div", "", "branding-preview-mark");
  brandingLogoPreview(previewMark, pendingLogo, companyInput.value);
  const previewText = node("strong", companyInput.value || "MINAI", "branding-preview-name");
  const previewPrimary = node("button", "Birincil Aksiyon", "primary");
  previewPrimary.type = "button";
  previewPrimary.disabled = true;
  const previewSecondary = node("span", "Vurgu", "branding-secondary-chip");
  preview.append(previewMark, previewText, previewPrimary, previewSecondary);

  const actions = node("div", "", "actions branding-actions");
  const clearLogo = node("button", "Logoyu Kaldır");
  clearLogo.type = "button";
  const save = node("button", "Kaydet", "primary");
  save.type = "button";
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
    const file = logoInput.files?.[0];
    if (!file) return;
    if (!["image/png", "image/jpeg", "image/webp"].includes(file.type) || file.size > 256 * 1024) {
      feedback.textContent = "Logo PNG/JPEG/WebP olmalı ve 256 KB'ı geçmemeli.";
      logoInput.value = "";
      return;
    }
    const reader = new FileReader();
    reader.addEventListener("load", () => {
      pendingLogo = String(reader.result || "");
      feedback.textContent = "Logo önizlemeye yüklendi; kaydetmeden kalıcı olmaz.";
      refreshLocalPreview();
    });
    reader.readAsDataURL(file);
  });
  clearLogo.addEventListener("click", () => {
    pendingLogo = null;
    logoInput.value = "";
    feedback.textContent = "Logo kaldırılacak; değişikliği kaydet.";
    refreshLocalPreview();
  });
  save.addEventListener("click", async () => {
    try {
      const saved = await api("/settings/branding", {
        method: "POST",
        body: JSON.stringify({
          company_name: companyInput.value,
          logo_data_uri: pendingLogo,
          primary_color: primaryInput.value,
          secondary_accent_color: secondaryInput.value
        })
      });
      applyBranding(saved);
      feedback.textContent = "Branding ayarları kaydedildi.";
      setStatus("Kaydedildi");
    } catch (error) {
      feedback.textContent = error.message || String(error);
      setStatus("Hata", false);
    }
  });

  form.append(companyLabel, colors, logoLabel, preview, actions, feedback);
  page.append(form);
  content.replaceChildren(page);
  refreshLocalPreview();
}

async function boot() {
  const page = document.body.dataset.page;
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
      renderBrandingSettings(branding);
    }
    setStatus("Güncel");
  } catch (error) { showError(error); }
}

document.addEventListener("DOMContentLoaded", boot);
