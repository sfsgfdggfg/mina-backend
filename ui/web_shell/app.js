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
  const note = node("div", "Finansal değerler para birimleri arasında toplanmaz; eksik kanıt sıfır kabul edilmez.", "notice section");
  content.replaceChildren(grid, note);
}

async function boot() {
  const page = document.body.dataset.page;
  try {
    if (page === "jobs") {
      renderJobs(await api("/mina-jobs"));
    } else if (page === "job") {
      await loadJob(document.body.dataset.jobId || ""); return;
    } else if (page === "reports") {
      renderReports(await api("/reports"));
    }
    setStatus("Güncel");
  } catch (error) { showError(error); }
}

document.addEventListener("DOMContentLoaded", boot);
