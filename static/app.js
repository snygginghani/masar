const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

let appState = {
  profile: null,
  jobs: [],
  applications: [],
  integrations: {},
};
let activeRoute = "discover";
let activeFilter = "all";
let pendingSendIds = [];
let onboardingStep = 1;
let capabilities = null;

const icons = {
  search: '<svg aria-hidden="true" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg>',
  arrow: '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M5 12h14M14 7l5 5-5 5"/></svg>',
  check: '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="m5 12 4 4L19 6"/></svg>',
  info: '<svg aria-hidden="true" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></svg>',
  alert: '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M12 3 2.5 20h19L12 3Z"/><path d="M12 9v5M12 17h.01"/></svg>',
  empty: '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M4 19.5V8l8-4 8 4v11.5"/><path d="M8 19.5v-5h8v5M9 9h.01M15 9h.01"/></svg>',
  map: '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M20 10c0 5-8 11-8 11S4 15 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/></svg>',
  external: '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M14 5h5v5M19 5l-9 9"/><path d="M18 13v6H5V6h6"/></svg>',
};

function escapeHTML(value = "") {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: options.body instanceof FormData
      ? { ...(options.headers || {}) }
      : { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  let body = {};
  try { body = await response.json(); } catch { body = {}; }
  if (!response.ok) {
    const message = typeof body.detail === "string" ? body.detail : "Something went wrong. Please try again.";
    throw new Error(message);
  }
  return body;
}

function toast(title, message = "", type = "success") {
  const region = $("#toast-region");
  const toastKey = `${title}|${message}|${type}`;
  const duplicate = $$('[data-toast-key]', region).find((item) => item.dataset.toastKey === toastKey);
  if (duplicate) duplicate.remove();
  while (region.children.length >= 3) region.firstElementChild?.remove();
  const item = document.createElement("div");
  item.className = `toast ${type === "error" ? "error" : ""}`;
  item.dataset.toastKey = toastKey;
  item.innerHTML = `${type === "error" ? icons.alert : icons.check}<div><strong>${escapeHTML(title)}</strong><span>${escapeHTML(message)}</span></div><button type="button" aria-label="Dismiss notification">×</button>`;
  region.append(item);
  const remove = () => item.remove();
  $("button", item).addEventListener("click", remove);
  window.setTimeout(remove, 5200);
}

function setButtonBusy(button, busy, label = "Working") {
  if (!button) return;
  if (busy) {
    button.dataset.oldHtml = button.innerHTML;
    button.disabled = true;
    button.innerHTML = `<span class="spinner" aria-hidden="true"></span><span>${escapeHTML(label)}</span>`;
  } else {
    button.disabled = false;
    if (button.dataset.oldHtml) button.innerHTML = button.dataset.oldHtml;
  }
}

async function refreshState() {
  const requests = [api("/api/state")];
  if (!capabilities) requests.push(api("/api/system/capabilities"));
  const [state, systemInfo] = await Promise.all(requests);
  appState = state;
  if (systemInfo) capabilities = systemInfo;
  renderAll();
}

function navigate(route) {
  activeRoute = route;
  $$("[data-view]").forEach((view) => view.classList.toggle("is-visible", view.dataset.view === route));
  $$("[data-route]").forEach((button) => {
    const isActive = button.dataset.route === route;
    button.classList.toggle("is-active", isActive);
    if (isActive) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  $("#selection-bar").hidden = route !== "discover" || selectedJobs().length === 0;
  window.scrollTo({ top: 0, behavior: "smooth" });
  if (route === "profile") fillProfileForm();
  if (route === "applications") renderApplications();
}

function selectedJobs() {
  return appState.jobs.filter((job) => job.selected && !job.demo);
}

function renderAll() {
  renderMetrics();
  renderJobs();
  renderApplications();
  renderConnections();
  fillProfileForm();
  fillSearchContext();
  const drafts = appState.applications.filter((item) => item.status !== "sent").length;
  const count = $("#draft-count");
  count.textContent = drafts;
  count.hidden = drafts === 0;
}

function renderMetrics() {
  const realJobs = appState.jobs.filter((job) => !job.demo);
  const openings = realJobs.filter((job) => (job.opportunity_kind || "opening") === "opening");
  const outreach = realJobs.filter((job) => job.opportunity_kind === "outreach");
  $("#metric-found").textContent = realJobs.length;
  $("#metric-openings").textContent = openings.length;
  $("#metric-outreach").textContent = outreach.length;
  $("#metric-selected").textContent = selectedJobs().length;
  $("#metric-applied").textContent = appState.jobs.filter((job) => job.status === "applied").length;
  $("#jobs-total").textContent = appState.jobs.length;
  $("#jobs-subtitle").textContent = appState.jobs.length
    ? `${openings.length} posted role${openings.length === 1 ? "" : "s"} · ${outreach.length} proactive compan${outreach.length === 1 ? "y" : "ies"}${appState.jobs.some((job) => job.demo) ? " · plus labelled demo data" : ""}.`
    : "Complete your profile, then run your first opportunity scan.";
  const selected = selectedJobs().length;
  $("#selection-count").textContent = selected;
  $("#selection-bar").hidden = activeRoute !== "discover" || selected === 0;
}

function companyInitials(name) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join("") || "?";
}

function filteredJobs() {
  if (activeFilter === "openings") return appState.jobs.filter((job) => (job.opportunity_kind || "opening") === "opening");
  if (activeFilter === "outreach") return appState.jobs.filter((job) => job.opportunity_kind === "outreach");
  if (activeFilter === "strong") return appState.jobs.filter((job) => job.match_score >= 80);
  if (activeFilter === "email") return appState.jobs.filter((job) => job.contact_email && !job.demo);
  if (activeFilter === "selected") return appState.jobs.filter((job) => job.selected);
  return appState.jobs;
}

function jobCard(job) {
  const sourceClass = job.demo ? "demo" : job.verified ? "verified" : "unverified";
  const sourceText = job.demo ? "Demo only" : job.verified ? "Page reached" : "Open to verify";
  const isOutreach = job.opportunity_kind === "outreach";
  const kindLabel = isOutreach ? "Company outreach" : "Posted role";
  return `
    <article class="job-card ${isOutreach ? "is-outreach" : "is-opening"} ${job.selected ? "is-selected" : ""}" data-job-id="${escapeHTML(job.id)}">
      <div class="company-mark" aria-hidden="true">${escapeHTML(companyInitials(job.company))}</div>
      <div class="job-main">
        <button type="button" data-open-job="${escapeHTML(job.id)}">${escapeHTML(job.title)}</button>
        <p>${escapeHTML(job.company)}</p>
        <div class="job-tags">
          <span class="tag opportunity-kind ${isOutreach ? "outreach" : "opening"}">${escapeHTML(kindLabel)}</span>
          <span class="tag">${icons.map}${escapeHTML(job.location)}</span>
          <span class="tag">${escapeHTML(job.workplace || "Not stated")}</span>
          <span class="tag ${sourceClass}">${escapeHTML(sourceText)}</span>
        </div>
      </div>
      <div class="job-detail-col">
        <strong>${escapeHTML(isOutreach ? "Proactive inquiry" : (job.employment_type || "Internship"))}</strong>
        <span>${escapeHTML(isOutreach ? "No advertised role" : (job.posted_date || "Date not stated"))}</span>
        <span>${job.contact_email ? "Published email verified" : (isOutreach ? "Official contact page" : "Application page")}</span>
      </div>
      <div class="match" aria-label="${job.match_score} percent profile fit">
        <strong>${job.match_score}%</strong><small>profile fit</small>
        <div class="match-bar"><i style="width:${job.match_score}%"></i></div>
      </div>
      <label class="switch" title="${job.demo ? "Demo jobs cannot be selected" : "Select this job"}">
        <span class="sr-only">Select ${escapeHTML(isOutreach ? "proactive outreach" : job.title)} at ${escapeHTML(job.company)}</span>
        <input type="checkbox" data-select-job="${escapeHTML(job.id)}" ${job.selected ? "checked" : ""} ${job.demo ? "disabled" : ""}>
        <span aria-hidden="true"></span>
      </label>
    </article>`;
}

function renderJobs() {
  const list = $("#jobs-list");
  const jobs = filteredJobs();
  if (!appState.jobs.length) {
    list.innerHTML = `
      <div class="empty-state"><div>
        <span class="empty-icon">${icons.empty}</span>
        <h3>Your shortlist is still quiet</h3>
        <p>Connect an AI provider to research posted roles and relevant organizations in your field—or load sample data to see the review flow.</p>
        <div class="empty-actions">
          <button class="button button-dark" type="button" data-empty-action="settings">Connect OpenRouter</button>
          <button class="button button-light" type="button" data-empty-action="demo">Load safe demo</button>
        </div>
      </div></div>`;
    return;
  }
  if (!jobs.length) {
    list.innerHTML = `<div class="empty-state"><div><span class="empty-icon">${icons.search}</span><h3>No opportunities in this filter</h3><p>Try another view or run a fresh scan.</p></div></div>`;
    return;
  }
  list.innerHTML = jobs.map(jobCard).join("");
}

function openJobDialog(id) {
  const job = appState.jobs.find((item) => item.id === id);
  if (!job) return;
  const dialog = $("#job-dialog");
  const isOutreach = job.opportunity_kind === "outreach";
  $("#dialog-source").textContent = job.demo ? "Masar demo — not a real job" : `${isOutreach ? "Proactive company" : "Posted role"} · ${job.source || "Source"} · ${job.verified ? "page reached" : "not verified"}`;
  const requirements = (job.requirements || []).map((item) => `<li>${escapeHTML(item)}</li>`).join("");
  const reasons = (job.match_reasons || []).map((item) => `<li>${escapeHTML(item)}</li>`).join("");
  const gaps = (job.gaps || []).map((item) => `<li>${escapeHTML(item)}</li>`).join("");
  $("#job-dialog-content").innerHTML = `
    <div class="dialog-title-row">
      <div class="company-mark" aria-hidden="true">${escapeHTML(companyInitials(job.company))}</div>
      <div><h2 id="dialog-job-title">${escapeHTML(job.title)}</h2><p>${escapeHTML(job.company)}</p></div>
      <div class="dialog-match" aria-label="${job.match_score} percent profile fit">${job.match_score}%</div>
    </div>
    <div class="dialog-meta">
      <span class="tag">${icons.map}${escapeHTML(job.location)}</span>
      <span class="tag">${escapeHTML(job.workplace || "Not stated")}</span>
      <span class="tag">${escapeHTML(job.employment_type || "Internship")}</span>
      <span class="tag opportunity-kind ${isOutreach ? "outreach" : "opening"}">${isOutreach ? "Proactive outreach" : "Posted opening"}</span>
      <span class="tag">Source confidence: ${escapeHTML(job.confidence_score || 50)}%</span>
      ${!isOutreach ? `<span class="tag">Posted: ${escapeHTML(job.posted_date || "Not stated")}</span>` : ""}
    </div>
    <section class="dialog-section"><h3>${isOutreach ? "Why this company is on the radar" : "The role"}</h3><p>${escapeHTML(job.summary || "No summary was provided by the source.")}</p></section>
    ${requirements ? `<section class="dialog-section"><h3>${isOutreach ? "Relevant team signals" : "What they mention"}</h3><ul class="bullet-list">${requirements}</ul></section>` : ""}
    ${(job.contact_email || job.contact_name || job.contact_role) ? `<section class="dialog-section contact-proof"><h3>Published contact</h3><p>${job.contact_name ? `<strong>${escapeHTML(job.contact_name)}</strong>${job.contact_role ? ` · ${escapeHTML(job.contact_role)}` : ""}<br>` : ""}${job.contact_email ? escapeHTML(job.contact_email) : "Use the official source page"}</p></section>` : ""}
    ${reasons ? `<section class="dialog-section"><h3>Why it may fit you</h3><ul class="bullet-list">${reasons}</ul></section>` : ""}
    ${gaps ? `<section class="dialog-section"><h3>Check before applying</h3><ul class="bullet-list gaps">${gaps}</ul></section>` : ""}
    <div class="dialog-actions">
      ${job.url ? `<a class="source-link" href="${escapeHTML(job.url)}" target="_blank" rel="noreferrer">Open evidence source ↗</a>` : `<span class="source-link">Demo listing</span>`}
      <button class="button ${job.selected ? "button-light" : "button-coral"}" type="button" data-dialog-select="${escapeHTML(job.id)}" ${job.demo ? "disabled" : ""}>${job.selected ? "Remove from shortlist" : (isOutreach ? "Select outreach" : "Select this role")}</button>
    </div>`;
  dialog.showModal();
}

async function toggleJobSelection(id, selected) {
  const job = appState.jobs.find((item) => item.id === id);
  if (!job || job.demo) return;
  const previous = job.selected;
  job.selected = selected;
  renderMetrics();
  renderJobs();
  try {
    await api(`/api/jobs/${encodeURIComponent(id)}/selection`, { method: "PATCH", body: JSON.stringify({ selected }) });
  } catch (error) {
    job.selected = previous;
    renderAll();
    toast("Could not update selection", error.message, "error");
  }
}

function renderApplications() {
  const list = $("#application-list");
  const applications = appState.applications;
  if (!applications.length) {
    list.innerHTML = `
      <div class="empty-state"><div>
        <span class="empty-icon">${icons.info}</span>
        <h3>No drafts yet</h3>
        <p>Select real roles from your shortlist, then choose “Prepare applications.”</p>
        <button class="button button-dark" type="button" data-empty-action="discover">Go to discovery</button>
      </div></div>`;
    return;
  }
  list.innerHTML = applications.map((application) => {
    const isSent = application.status === "sent";
    const external = application.method === "external";
    const proactive = application.opportunity_kind === "outreach";
    return `
      <article class="application-card" data-application-id="${escapeHTML(application.id)}">
        <header class="application-card-head">
          <div><div class="company-mark" aria-hidden="true">${escapeHTML(companyInitials(application.company))}</div><div><h3>${escapeHTML(application.job_title)}</h3><p>${escapeHTML(application.company)}</p></div></div>
          <div class="application-controls">
            <span class="method-badge ${isSent ? "sent" : external ? "external" : ""}">${isSent ? "Sent" : proactive ? (external ? "Contact page" : "Outreach email") : external ? "Apply page" : "Email draft"}</span>
            ${application.job_url ? `<a class="source-link" href="${escapeHTML(application.job_url)}" target="_blank" rel="noreferrer">Check source ↗</a>` : ""}
          </div>
        </header>
        <div class="application-body">
          <div class="draft-editor">
            ${external ? `<div class="approval-banner">${icons.info}<div><strong>${proactive ? "No verified public email was found." : "This company uses an application page."}</strong><span>${proactive ? "Use the official contact or careers page and adapt this honest inquiry. Masar will not submit it for you." : "Use this draft in the form or as a cover note. Masar will not fill or submit an external site."}</span></div></div>` : ""}
            <label class="field"><span>${external ? "Application title" : "Email subject"}</span><input data-app-field="subject" value="${escapeHTML(application.subject)}" ${isSent ? "disabled" : ""}></label>
            ${!external ? `<label class="field"><span>Recipient</span><input data-app-field="recipient" type="email" value="${escapeHTML(application.recipient || "")}" placeholder="careers@company.com" ${isSent ? "disabled" : ""}><small>Only use an address published by the employer.</small></label>` : ""}
            <label class="field"><span>${external ? "Cover note" : "Email body"}</span><textarea data-app-field="body" ${isSent ? "disabled" : ""}>${escapeHTML(application.body)}</textarea></label>
          </div>
          <aside class="application-aside">
            <p>${external ? (proactive ? "Check the company and contact route, then paste or adapt the inquiry yourself." : "Open the source, confirm the role is still active, then paste or adapt this draft.") : (proactive ? "Confirm the published contact and make sure the message never implies a vacancy exists." : "Read the full email and confirm the recipient from the employer’s source.")}</p>
            ${external
              ? `<a class="button button-coral" href="${escapeHTML(application.job_url || "#")}" target="_blank" rel="noreferrer">Open application page ${icons.external}</a>`
              : isSent
                ? `<div class="approval-banner">${icons.check}<div><strong>Email sent</strong><span>${application.sent_at ? new Date(application.sent_at).toLocaleString() : ""}</span></div></div>`
                : `<label class="approval-check"><input type="checkbox" data-approve-application ${application.approved ? "checked" : ""}><span><strong>Approve this email</strong><br>I checked the job, recipient, subject, and message.</span></label>`}
          </aside>
        </div>
      </article>`;
  }).join("");

  const approved = applications.filter((item) => item.method === "email" && item.approved && item.status !== "sent");
  if (applications.some((item) => item.method === "email" && item.status !== "sent")) {
    list.insertAdjacentHTML("beforeend", `
      <div class="send-dock">
        <p><strong>${approved.length} email${approved.length === 1 ? "" : "s"} approved</strong><small>${appState.integrations.smtp_connected ? "Your email connection is ready." : "Connect an email sender before the final send."}</small></p>
        <button class="button button-coral" type="button" id="send-approved" ${approved.length === 0 ? "disabled" : ""}>Send approved emails ${icons.arrow}</button>
      </div>`);
  }
}

function renderConnections() {
  const provider = appState.integrations.ai_provider || "openrouter";
  const providerState = appState.integrations.providers?.[provider] || {};
  const aiConnected = !!appState.integrations.ai_connected;
  const searchReady = aiConnected && (provider !== "ollama" || providerState.search_ready);
  const smtpConnected = !!appState.integrations.smtp_connected;
  const providerName = { openrouter: "OpenRouter", openai: "OpenAI", ollama: "Ollama" }[provider];
  $("#connection-dot").classList.toggle("is-connected", aiConnected);
  $("#connection-dot").setAttribute("aria-label", aiConnected ? `${providerName} connected` : "AI provider not connected");
  const ready = $("#search-readiness");
  const readinessText = !aiConnected
    ? "Connect an AI provider to run a live scan"
    : !searchReady
      ? "Ollama connected · add a search source for live discovery"
      : `Ready with ${appState.integrations.ai_model || "your model"}`;
  ready.innerHTML = `<i class="status-pip ${searchReady ? "ready" : ""}"></i>${escapeHTML(readinessText)}`;
  $("#ai-status").textContent = aiConnected ? `Connected · ${providerName}` : "Not connected";
  $("#ai-status").classList.toggle("connected", aiConnected);
  $("#smtp-status").textContent = smtpConnected ? `Connected · ${appState.integrations.smtp_from}` : "Not connected";
  $("#smtp-status").classList.toggle("connected", smtpConnected);
  $("#ai-provider").value = provider;
  applyAIProvider(provider, true);
  const preset = $("#smtp-preset");
  if (preset?.value) applySMTPPreset(preset.value);
}

function renderHardwareCard() {
  const card = $("#hardware-card");
  if (!card || !capabilities) return;
  const recommendation = capabilities.recommendation;
  const gpu = capabilities.gpus?.length
    ? capabilities.gpus.map((item) => `${item.name} · ${(item.vram_mb / 1024).toFixed(1)} GB VRAM`).join("; ")
    : "No supported NVIDIA GPU detected · CPU/system-memory mode";
  card.innerHTML = `<strong>Recommended: ${escapeHTML(recommendation.model)} · ${escapeHTML(recommendation.tier)}</strong><span>${escapeHTML(capabilities.memory_gb)} GB RAM · ${escapeHTML(gpu)}. ${escapeHTML(recommendation.reason)}</span><span>${capabilities.ollama_installed ? "Ollama is installed." : "Install Ollama first from ollama.com."} Model download: about ${escapeHTML(recommendation.download_size)}.</span><code>ollama pull ${escapeHTML(recommendation.model)}</code>`;
}

function applyAIProvider(provider, preferSaved = false) {
  const form = $("#ai-form");
  if (!form) return;
  const configs = {
    openrouter: { icon: "OR", key: "OpenRouter API key", placeholder: "sk-or-v1-...", model: "openai/gpt-5-mini", help: "Use an OpenRouter model with web-search tool support." },
    openai: { icon: "OA", key: "OpenAI API key", placeholder: "sk-...", model: "gpt-5.4", help: "Masar uses the Responses API and OpenAI's web-search tool." },
    ollama: { icon: "OL", key: "", placeholder: "", model: capabilities?.recommendation?.model || "qwen3:8b", help: "Choose an installed model, or pull the recommended model shown below." },
  };
  const config = configs[provider] || configs.openrouter;
  const saved = appState.integrations.providers?.[provider] || {};
  $("#ai-provider-icon").textContent = config.icon;
  $("#ai-key-field").hidden = provider === "ollama";
  $("#ollama-fields").hidden = provider !== "ollama";
  $("#ai-key-label").textContent = config.key;
  form.elements.api_key.placeholder = config.placeholder;
  $("#ai-model-help").textContent = config.help;
  if (preferSaved && saved.model) form.elements.model.value = saved.model;
  else form.elements.model.value = config.model;
  if (provider === "ollama") {
    form.elements.base_url.value = saved.base_url || "http://127.0.0.1:11434";
    $("#ollama-model-list").innerHTML = (saved.models || []).map((name) => `<option value="${escapeHTML(name)}"></option>`).join("");
    renderHardwareCard();
  }
}

function applyOllamaSearchMode(mode) {
  $("#ollama-search-key-field").hidden = mode !== "ollama";
  $("#searxng-url-field").hidden = mode !== "searxng";
}

function applySMTPPreset(preset) {
  const form = $("#smtp-form");
  if (!form) return;
  const host = form.elements.host;
  const port = form.elements.port;
  const username = form.elements.username;
  const fromEmail = form.elements.from_email;
  const helper = $("#smtp-preset-help");
  const usernameLabel = $("#smtp-username-label");
  const profileEmail = appState.profile?.data?.email || "";

  host.readOnly = preset === "gmail" || preset === "outlook";
  if (preset === "gmail") {
    host.value = "smtp.gmail.com";
    port.value = 587;
    usernameLabel.textContent = "Gmail address";
    if (!username.value.includes("@")) username.value = profileEmail;
    if (!fromEmail.value) fromEmail.value = username.value || profileEmail;
    helper.hidden = false;
    helper.innerHTML = "Use your full Gmail address and a <strong>16-character Google App Password</strong>. Your normal Gmail password will not work.";
  } else if (preset === "outlook") {
    host.value = "smtp.office365.com";
    port.value = 587;
    usernameLabel.textContent = "Microsoft email address";
    if (!username.value.includes("@")) username.value = profileEmail;
    if (!fromEmail.value) fromEmail.value = username.value || profileEmail;
    helper.hidden = false;
    helper.textContent = "Use your full Microsoft email address. Some organizations require an administrator to allow SMTP authentication.";
  } else {
    usernameLabel.textContent = "Username";
    helper.hidden = true;
    helper.textContent = "";
  }
}

function splitList(value) {
  return String(value || "").split(",").map((item) => item.trim()).filter(Boolean);
}

function fillSearchContext() {
  const profile = appState.profile?.data;
  if (!profile) return;
  const location = profile.search_locations?.[0] || profile.city || "";
  const country = profile.country || "";
  const field = profile.disciplines?.join(", ") || profile.degree || "";
  if (!$("#job-keywords").value) $("#job-keywords").value = (profile.preferred_roles || []).join(", ");
  if (!$("#job-discipline").value) $("#job-discipline").value = field;
  if (!$("#job-location").value) $("#job-location").value = location;
  if (!$("#job-country").value) $("#job-country").value = country;
  const area = [location, country].filter(Boolean).join(", ");
  $("#search-location-summary").textContent = area ? `Searching ${area}` : "Set your search area";
}

function formProfile(form) {
  const data = new FormData(form);
  return {
    full_name: String(data.get("full_name") || "").trim(),
    email: String(data.get("email") || "").trim(),
    phone: String(data.get("phone") || "").trim(),
    city: String(data.get("city") || "").trim(),
    country: String(data.get("country") || "").trim(),
    university: String(data.get("university") || "").trim(),
    degree: String(data.get("degree") || "").trim(),
    graduation: String(data.get("graduation") || "").trim(),
    linkedin: String(data.get("linkedin") || "").trim(),
    portfolio: String(data.get("portfolio") || "").trim(),
    preferred_roles: splitList(data.get("preferred_roles")),
    disciplines: splitList(data.get("disciplines")),
    search_locations: splitList(data.get("search_locations")),
    skills: splitList(data.get("skills")),
    internship_type: String(data.get("internship_type") || "Any"),
    workplace: data.getAll("workplace"),
    availability: String(data.get("availability") || "").trim(),
    weekly_hours: String(data.get("weekly_hours") || "").trim(),
    work_authorization: String(data.get("work_authorization") || "Not specified"),
    salary_preference: String(data.get("salary_preference") || "Open to discuss"),
    notes: String(data.get("notes") || "").trim(),
    ai_consent: data.has("ai_consent"),
  };
}

function fillProfileForm() {
  const profile = appState.profile?.data;
  const form = $("#profile-form");
  if (!profile || !form) return;
  Object.entries(profile).forEach(([key, value]) => {
    if (key === "workplace") {
      $$('[name="workplace"]', form).forEach((input) => { input.checked = value.includes(input.value); });
    } else if (key === "ai_consent") {
      const input = $('[name="ai_consent"]', form);
      if (input) input.checked = value;
    } else {
      const input = $(`[name="${key}"]`, form);
      if (input) input.value = Array.isArray(value) ? value.join(", ") : value;
    }
  });
  const state = $("#cv-state");
  if (appState.profile.cv_ready) {
    state.hidden = false;
    state.textContent = `Ready · ${appState.profile.cv_filename}`;
    $("#cv-label").textContent = "Replace your CV";
  } else {
    state.hidden = true;
    $("#cv-label").textContent = "Choose your CV";
  }
}

async function saveProfile(form) {
  const payload = formProfile(form);
  if (!payload.full_name || !payload.email) throw new Error("Full name and email are required.");
  return api("/api/profile", { method: "PUT", body: JSON.stringify(payload) });
}

async function uploadCV(file) {
  if (!file) throw new Error("Choose your CV first.");
  const data = new FormData();
  data.append("file", file);
  return api("/api/cv", { method: "POST", body: data });
}

function setOnboardingStep(step) {
  onboardingStep = step;
  $$(".onboarding-step").forEach((section) => section.classList.toggle("is-active", Number(section.dataset.step) === step));
  $$(".onboarding-progress i").forEach((bar, index) => bar.classList.toggle("is-active", index < step));
  $("#onboarding-step-label").textContent = `Step ${step} of 3`;
  $("#onboarding-back").hidden = step === 1;
  $("#onboarding-next").innerHTML = step === 3 ? `Build my profile ${icons.arrow}` : `Continue ${icons.arrow}`;
  const focusTarget = $(`.onboarding-step[data-step="${step}"] input:not([type="checkbox"]), .onboarding-step[data-step="${step}"] select`);
  window.setTimeout(() => focusTarget?.focus(), 80);
}

function validateOnboardingStep(step) {
  const section = $(`.onboarding-step[data-step="${step}"]`);
  const required = $$('[required]', section);
  return required.every((input) => input.reportValidity());
}

async function finishOnboarding() {
  const form = $("#onboarding-form");
  const button = $("#onboarding-next");
  const file = $('[name="cv"]', form).files[0];
  if (!file) {
    toast("Add your CV", "Masar needs a readable CV to match jobs.", "error");
    return;
  }
  setButtonBusy(button, true, "Building profile");
  try {
    const profile = formProfile(form);
    await api("/api/profile", { method: "PUT", body: JSON.stringify(profile) });
    await uploadCV(file);
    await refreshState();
    $("#onboarding").hidden = true;
    navigate("settings");
    toast("Profile ready", "Choose an AI provider next, then run your first live scan.");
  } catch (error) {
    toast("Could not finish setup", error.message, "error");
  } finally {
    setButtonBusy(button, false);
  }
}

async function discoverLiveJobs() {
  if (!appState.profile?.cv_ready) {
    navigate("profile");
    toast("Upload your CV first", "Live matching needs your CV text.", "error");
    return;
  }
  if (!appState.integrations.ai_connected) {
    navigate("settings");
    toast("Connect an AI provider", "Choose OpenRouter, OpenAI, or Ollama before running a live search.", "error");
    return;
  }
  const provider = appState.integrations.ai_provider;
  if (provider === "ollama" && !appState.integrations.providers?.ollama?.search_ready) {
    navigate("settings");
    toast("Add a search source", "Ollama needs an Ollama Web Search key or a local SearXNG URL for live discovery.", "error");
    return;
  }
  const button = $("#discover-button");
  setButtonBusy(button, true, "Researching opportunities");
  $("#jobs-list").innerHTML = `<div class="loading-lines"><div class="loading-card"></div><div class="loading-card"></div></div>`;
  try {
    const result = await api("/api/jobs/discover", {
      method: "POST",
      body: JSON.stringify({
        keywords: $("#job-keywords").value,
        discipline: $("#job-discipline").value,
        location: $("#job-location").value,
        country: $("#job-country").value,
        max_results: 20,
        include_outreach: $("#include-outreach").checked,
      }),
    });
    await refreshState();
    const coverage = `${result.openings} posted · ${result.outreach} proactive · ${result.sources_scanned} research sources`;
    toast("Opportunity scan complete", `${result.count} verified lead${result.count === 1 ? "" : "s"} · ${coverage}.`);
    if (result.track_warnings?.length) toast("One research lane needs attention", result.track_warnings.join(" · "), "error");
  } catch (error) {
    renderJobs();
    toast("Live search failed", error.message, "error");
  } finally {
    setButtonBusy(button, false);
  }
}

async function loadDemo() {
  try {
    const result = await api("/api/jobs/demo", { method: "POST", body: "{}" });
    await refreshState();
    toast("Demo loaded", `${result.count} fictional roles show how the shortlist works. They cannot be applied to.`);
  } catch (error) {
    toast("Could not load demo", error.message, "error");
  }
}

async function prepareApplications() {
  const jobs = selectedJobs();
  if (!jobs.length) return;
  const button = $("#prepare-button");
  setButtonBusy(button, true, "Preparing drafts");
  try {
    const result = await api("/api/applications/prepare", {
      method: "POST",
      body: JSON.stringify({ job_ids: jobs.map((job) => job.id) }),
    });
    await refreshState();
    navigate("applications");
    toast("Drafts ready", `${result.count} application${result.count === 1 ? "" : "s"} prepared for your review.`);
  } catch (error) {
    toast("Could not prepare drafts", error.message, "error");
  } finally {
    setButtonBusy(button, false);
  }
}

async function updateApplication(card, values) {
  try {
    await api(`/api/applications/${encodeURIComponent(card.dataset.applicationId)}`, {
      method: "PATCH",
      body: JSON.stringify(values),
    });
    const item = appState.applications.find((application) => application.id === card.dataset.applicationId);
    if (item) Object.assign(item, values);
    renderApplications();
  } catch (error) {
    toast("Could not save draft", error.message, "error");
    await refreshState();
  }
}

function openSendConfirm() {
  pendingSendIds = appState.applications
    .filter((item) => item.method === "email" && item.approved && item.status !== "sent")
    .map((item) => item.id);
  if (!pendingSendIds.length) return;
  if (!appState.integrations.smtp_connected) {
    navigate("settings");
    toast("Connect your email sender", "SMTP must be connected before sending.", "error");
    return;
  }
  $("#confirm-title").textContent = `Send ${pendingSendIds.length} approved email${pendingSendIds.length === 1 ? "" : "s"}?`;
  $("#confirm-dialog").showModal();
}

async function confirmSend() {
  const button = $("#confirm-send");
  setButtonBusy(button, true, "Sending");
  try {
    const result = await api("/api/applications/send", {
      method: "POST",
      body: JSON.stringify({ application_ids: pendingSendIds, confirm_send: true }),
    });
    $("#confirm-dialog").close();
    await refreshState();
    if (result.sent.length) toast("Applications sent", `${result.sent.length} email${result.sent.length === 1 ? "" : "s"} sent successfully.`);
    if (result.failed.length) toast("Some emails were not sent", result.failed.map((item) => item.error).join(" · "), "error");
  } catch (error) {
    toast("Send failed", error.message, "error");
  } finally {
    setButtonBusy(button, false);
  }
}

function bindEvents() {
  document.addEventListener("click", async (event) => {
    const routeButton = event.target.closest("[data-route]");
    if (routeButton) {
      event.preventDefault();
      navigate(routeButton.dataset.route);
      return;
    }
    const empty = event.target.closest("[data-empty-action]");
    if (empty) {
      if (empty.dataset.emptyAction === "demo") await loadDemo();
      else navigate(empty.dataset.emptyAction);
      return;
    }
    const open = event.target.closest("[data-open-job]");
    if (open) { openJobDialog(open.dataset.openJob); return; }
    const dialogSelect = event.target.closest("[data-dialog-select]");
    if (dialogSelect) {
      const job = appState.jobs.find((item) => item.id === dialogSelect.dataset.dialogSelect);
      await toggleJobSelection(job.id, !job.selected);
      $("#job-dialog").close();
      return;
    }
    if (event.target.closest("[data-close-dialog]")) $("#job-dialog").close();
    if (event.target.closest("[data-close-confirm]")) $("#confirm-dialog").close();
    if (event.target.closest("#send-approved")) openSendConfirm();
  });

  $("#mobile-settings").addEventListener("click", () => navigate("settings"));
  $("#discover-button").addEventListener("click", discoverLiveJobs);
  $("#prepare-button").addEventListener("click", prepareApplications);
  $("#confirm-send").addEventListener("click", confirmSend);

  $$(".filter-chip").forEach((chip) => chip.addEventListener("click", () => {
    activeFilter = chip.dataset.filter;
    $$(".filter-chip").forEach((item) => {
      const active = item === chip;
      item.classList.toggle("is-active", active);
      item.setAttribute("aria-pressed", String(active));
    });
    renderJobs();
  }));

  $("#jobs-list").addEventListener("change", async (event) => {
    const input = event.target.closest("[data-select-job]");
    if (input) await toggleJobSelection(input.dataset.selectJob, input.checked);
  });

  $("#application-list").addEventListener("change", async (event) => {
    const card = event.target.closest("[data-application-id]");
    if (!card) return;
    if (event.target.matches("[data-approve-application]")) {
      await updateApplication(card, { approved: event.target.checked });
    } else if (event.target.matches("[data-app-field]")) {
      await updateApplication(card, { [event.target.dataset.appField]: event.target.value });
    }
  });

  $("#profile-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = $('button[type="submit"]', event.currentTarget);
    setButtonBusy(button, true, "Saving");
    try {
      await saveProfile(event.currentTarget);
      await refreshState();
      $("#profile-save-status").textContent = "Saved just now";
      toast("Profile saved", "Future matches will use these details.");
    } catch (error) {
      toast("Could not save profile", error.message, "error");
    } finally { setButtonBusy(button, false); }
  });

  const cvInput = $("#cv-input");
  cvInput.addEventListener("change", async () => {
    if (!cvInput.files[0]) return;
    $("#cv-label").textContent = cvInput.files[0].name;
    try {
      const result = await uploadCV(cvInput.files[0]);
      await refreshState();
      toast("CV ready", `${result.characters.toLocaleString()} characters extracted locally.`);
    } catch (error) { toast("Could not read CV", error.message, "error"); }
  });

  const dropzone = $("#cv-dropzone");
  ["dragenter", "dragover"].forEach((name) => dropzone.addEventListener(name, (event) => { event.preventDefault(); dropzone.classList.add("is-dragging"); }));
  ["dragleave", "drop"].forEach((name) => dropzone.addEventListener(name, (event) => { event.preventDefault(); dropzone.classList.remove("is-dragging"); }));
  dropzone.addEventListener("drop", async (event) => {
    const file = event.dataTransfer?.files?.[0];
    if (!file) return;
    $("#cv-label").textContent = file.name;
    try {
      const result = await uploadCV(file);
      await refreshState();
      toast("CV ready", `${result.characters.toLocaleString()} characters extracted locally.`);
    } catch (error) { toast("Could not read CV", error.message, "error"); }
  });

  $("#ai-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = $('button[type="submit"]', form);
    const data = new FormData(form);
    const provider = String(data.get("provider") || "openrouter");
    const searchMode = $("#ollama-search-mode").value;
    const payload = {
      provider,
      api_key: data.get("api_key") || "",
      model: data.get("model") || "",
      base_url: data.get("base_url") || "http://127.0.0.1:11434",
      ollama_search_api_key: searchMode === "ollama" ? (data.get("ollama_search_api_key") || "") : "",
      searxng_url: searchMode === "searxng" ? (data.get("searxng_url") || "") : "",
    };
    setButtonBusy(button, true, "Connecting");
    try {
      const result = await api("/api/integrations/ai", { method: "POST", body: JSON.stringify(payload) });
      form.elements.api_key.value = "";
      form.elements.ollama_search_api_key.value = "";
      await refreshState();
      const localNote = provider === "ollama" && !result.model_ready
        ? `Ollama connected, but ${result.model} is not installed yet. Run the pull command shown in Settings.`
        : "Masar can now match your CV and prepare tailored drafts.";
      toast(`${provider === "ollama" ? "Ollama" : provider === "openai" ? "OpenAI" : "OpenRouter"} connected`, localNote);
    } catch (error) { toast("Could not connect", error.message, "error"); }
    finally { setButtonBusy(button, false); }
  });

  $("#ai-provider").addEventListener("change", (event) => applyAIProvider(event.target.value, false));
  $("#ollama-search-mode").addEventListener("change", (event) => applyOllamaSearchMode(event.target.value));

  $("#smtp-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = $('button[type="submit"]', form);
    const data = new FormData(form);
    const payload = {
      host: data.get("host"), port: Number(data.get("port")), username: data.get("username"),
      password: data.get("password"), from_email: data.get("from_email"), use_tls: data.has("use_tls"),
    };
    setButtonBusy(button, true, "Saving");
    try {
      await api("/api/integrations/smtp", { method: "POST", body: JSON.stringify(payload) });
      form.elements.password.value = "";
      await refreshState();
      toast("Email sender connected", "Approved emails can now be sent from your account.");
    } catch (error) { toast("Could not save email settings", error.message, "error"); }
    finally { setButtonBusy(button, false); }
  });

  $("#smtp-preset").addEventListener("change", (event) => applySMTPPreset(event.target.value));
  $('#smtp-form [name="username"]').addEventListener("input", (event) => {
    if ($("#smtp-preset").value === "gmail") {
      $('#smtp-form [name="from_email"]').value = event.target.value;
    }
  });

  $$(".reveal-button").forEach((button) => button.addEventListener("click", () => {
    const input = button.previousElementSibling;
    input.type = input.type === "password" ? "text" : "password";
    button.textContent = input.type === "password" ? "Show" : "Hide";
    button.setAttribute("aria-label", `${button.textContent} secret`);
  }));

  $("#clear-data").addEventListener("click", async () => {
    if (!window.confirm("Clear your profile, CV, job leads, drafts, and current connections from this computer?")) return;
    try {
      await api("/api/data", { method: "DELETE" });
      await refreshState();
      $("#onboarding").hidden = false;
      setOnboardingStep(1);
      toast("Local data cleared", "The uploaded CV and saved application data were removed.");
    } catch (error) { toast("Could not clear data", error.message, "error"); }
  });

  $("#onboarding-next").addEventListener("click", async () => {
    if (!validateOnboardingStep(onboardingStep)) return;
    if (onboardingStep < 3) setOnboardingStep(onboardingStep + 1);
    else await finishOnboarding();
  });
  $("#onboarding-back").addEventListener("click", () => setOnboardingStep(Math.max(1, onboardingStep - 1)));
  $('[name="cv"]', $("#onboarding-form")).addEventListener("change", (event) => {
    $("#onboarding-cv-label").textContent = event.target.files[0]?.name || "Choose your CV";
  });

  $("#job-dialog").addEventListener("click", (event) => {
    if (event.target === $("#job-dialog")) $("#job-dialog").close();
  });
  $("#confirm-dialog").addEventListener("click", (event) => {
    if (event.target === $("#confirm-dialog")) $("#confirm-dialog").close();
  });
}

async function init() {
  bindEvents();
  try {
    await refreshState();
    if (!appState.profile) {
      $("#onboarding").hidden = false;
      setOnboardingStep(1);
    } else {
      $("#onboarding").hidden = true;
    }
    const smtpPreset = $("#smtp-preset");
    smtpPreset.value = "gmail";
    applySMTPPreset("gmail");
  } catch (error) {
    toast("Masar could not start", error.message, "error");
  }
}

document.addEventListener("DOMContentLoaded", init);
