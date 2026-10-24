/* CV studio uses the same state and request helpers as the opportunity workspace. */
let studioBusy = false;
let editorVersion = "";
let editorDirty = false;
let studioTab = "review";

function formFeedback(form, message, error = false) {
  const element = $(".form-feedback", form);
  if (!element) return;
  element.hidden = false;
  element.textContent = message;
  element.classList.toggle("is-error", error);
}

function studioFeedback(message, error = false) {
  const node = $("#studio-feedback");
  node.hidden = !message;
  node.textContent = message;
  node.classList.toggle("is-error", error);
}

function studioSelectTab(value) {
  studioTab = value;
  $$('[data-studio-tab]').forEach(button => {
    const active = button.dataset.studioTab === value;
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
  $("#review-panel").hidden = value !== "review";
  $("#editor-panel").hidden = value !== "editor";
}

function selectSettingsTab(value) {
  $$('[data-settings-tab]').forEach(button => {
    const active = button.dataset.settingsTab === value;
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
  $("#ai-form").hidden = value !== "ai";
  $("#smtp-form").hidden = value !== "email";
  $(".tutorial-card").hidden = value !== "email";
  $("#settings-data-panel").hidden = value !== "data";
  $("#settings-danger").hidden = value !== "data";
}

function renderStudio() {
  const profile = appState.profile;
  const review = appState.cv_review;
  const ready = !!profile?.cv_ready;
  const valid = !!review && !review.stale;
  $("#studio-filename").textContent = profile?.cv_filename || "Add a CV to get started";
  $("#studio-file-detail").textContent = ready ? "Stored on this computer · Original preserved until you choose a new version" : "Upload a CV in Your profile to start";
  $("#review-cv-button").disabled = !ready || studioBusy;
  $("#rewrite-cv-button").disabled = !ready || studioBusy;
  $("#review-empty").hidden = !!review;
  $("#review-results").hidden = !review;
  $("#save-cv-button").disabled = !valid || studioBusy;
  $("#adopt-cv-button").disabled = !valid || editorDirty || studioBusy || !$("#cv-facts-confirm").checked;
  $("#cv-download").hidden = !valid || editorDirty;
  $("#journey-profile").textContent = ready ? "Profile & CV ready" : "Add your background";
  $("#journey-review").textContent = valid ? `Reviewed · ${review.score}/100` : "Make a strong first impression";
  $("#journey-discover").textContent = `${appState.jobs.filter(job => !job.demo).length} saved opportunities`;
  $("#journey-applications").textContent = `${appState.applications.length} applications`;
  $("#user-avatar").textContent = companyInitials(profile?.data?.full_name || "Masar");
  $("#workspace-connection").textContent = appState.integrations.ai_connected ? "AI connected" : "Local workspace";
  if (!review) {
    editorVersion = "";
    $("#cv-pdf-preview").hidden = true;
    $("#pdf-placeholder").hidden = false;
    $("#cv-editor-fields").innerHTML = "<p>Run a CV review to start editing.</p>";
    return;
  }
  if (review.stale) studioFeedback("Your profile or CV changed. Run a new review to update your score and document.", true);
  const recommendations = review.recommendations || [];
  $("#review-results").innerHTML = `
    <div class="review-grid"><aside class="score-card"><span class="eyebrow">WRITING READINESS</span><div class="score-value">${review.score}<span>/100</span></div><h2>${review.score >= 80 ? "A strong starting point" : review.score >= 55 ? "Good foundations to build on" : "Let’s strengthen the essentials"}</h2><p>${escapeHTML(review.explanation)}</p><span class="review-date">${review.word_count} words · ${new Date(review.updated_at).toLocaleDateString()}</span></aside>
    <section class="card rubric-card"><div class="card-heading"><h2>What’s behind your score</h2><span>6 checks</span></div>${review.criteria.map(item => `<div class="rubric-row"><div><strong>${escapeHTML(item.label)}</strong><span>${item.score} / ${item.maximum}</span></div><meter min="0" max="${item.maximum}" value="${item.score}" aria-label="${escapeHTML(item.label)}">${item.score}</meter><p>${escapeHTML(item.evidence)}</p></div>`).join("")}</section></div>
    <section class="recommendations"><div class="section-bar"><div><h2>Your next improvements</h2><p>Focus on the changes that make your experience easier to understand.</p></div><button class="button button-light" type="button" data-studio-tab="editor">Open editor ${icons.arrow}</button></div><div class="recommendation-grid">${recommendations.length ? recommendations.map((item,index) => `<article class="card recommendation-card"><span class="recommendation-index">${String(index+1).padStart(2,"0")}</span><div><span class="priority">${escapeHTML(item.priority)} priority</span><h3>${escapeHTML(item.title)}</h3><p>${escapeHTML(item.detail)}</p></div></article>`).join("") : `<article class="card recommendation-card"><div><h3>Your text covers the core checks.</h3><p>Review dates, chronology and links, then tailor the strongest projects to each role. The score does not evaluate every aspect of a CV.</p></div></article>`}</div></section>`;
  $("#rewrite-description").textContent = review.rewrite_mode === "assisted"
    ? "A suggested rewrite based on your uploaded CV. Verify every claim, then save your edits."
    : review.rewrite_mode === "edited" ? "Your edited version. Verify the facts and preview the PDF before using it for applications."
    : "This is extracted source text, not a rewrite. Connect AI for an edited version, or organize the text yourself.";
  const version = review.source_hash + review.updated_at;
  if (!editorDirty && version !== editorVersion) {
    renderCVEditor(review.document);
    editorVersion = version;
    $("#cv-pdf-preview").hidden = true;
    $("#pdf-placeholder").hidden = false;
  }
}

function renderCVEditor(document) {
  $("#cv-editor-fields").innerHTML = `
    <div class="card-heading"><h3>Document details</h3><span>Editable</span></div>
    <label class="field"><span>Full name</span><input name="cv_name" maxlength="160" required value="${escapeHTML(document.name)}"></label>
    <label class="field"><span>Professional headline</span><input name="cv_headline" maxlength="200" value="${escapeHTML(document.headline)}"></label>
    <label class="field"><span>Contact & professional links</span><textarea name="cv_contact" rows="3" maxlength="1000">${escapeHTML(document.contact)}</textarea></label>
    <p class="editor-help">Use “## ” for job or project titles and “- ” for bullets. Plain text stays easy to edit and readable in the PDF.</p>
    <div id="cv-sections">${document.sections.map(section => editorSection(section)).join("")}</div>
    <button type="button" class="button button-light" id="add-cv-section">+ Add section</button>`;
}

function editorSection(section) {
  return `<fieldset class="cv-section"><legend>CV section</legend><label class="field"><span>Section heading</span><input data-section-heading required maxlength="100" value="${escapeHTML(section.heading)}"></label><label class="field"><span>Content</span><textarea data-section-body rows="9" required maxlength="12000">${escapeHTML(section.body)}</textarea></label><button type="button" class="text-button remove-section">Remove section</button></fieldset>`;
}

function readEditor() {
  const form = $("#cv-editor-form");
  return {name:form.elements.cv_name.value.trim(), headline:form.elements.cv_headline.value.trim(), contact:form.elements.cv_contact.value.trim(),
    sections:$$('.cv-section',form).map(section => ({heading:$("[data-section-heading]",section).value.trim(),body:$("[data-section-body]",section).value.trim()}))};
}

function markEditorDirty() {
  editorDirty = true;
  dirtyForms.add("cv-editor-form");
  $("#cv-save-status").textContent = "Unsaved changes";
  $("#cv-facts-confirm").checked = false;
  $("#cv-pdf-preview").hidden = true;
  $("#pdf-placeholder").hidden = false;
  $("#pdf-placeholder").textContent = "Save your changes to update the PDF preview.";
  renderStudio();
}

async function runCVReview(useAI) {
  if (studioBusy) return;
  if (editorDirty && !window.confirm("A new review will replace your unsaved CV edits. Continue?")) return;
  if (useAI && !editorDirty && appState.cv_review && !window.confirm("A new AI rewrite will replace your saved CV draft. Download a copy first if you want to keep it. Continue?")) return;
  if (useAI && !appState.integrations.ai_connected) {
    navigate("settings"); selectSettingsTab("ai");
    formFeedback($("#ai-form"), "Connect a provider, then return to CV studio to generate your rewrite.");
    return;
  }
  studioBusy = true;
  const button = $(useAI ? "#rewrite-cv-button" : "#review-cv-button");
  setButtonBusy(button, true, useAI ? "Preparing your rewrite" : "Reviewing your CV");
  studioFeedback(useAI ? "Reading your CV and organizing a suggested version. This can take a minute." : "Checking structure, clarity and relevant evidence…");
  renderStudio();
  try {
    await api("/api/cv/review", {method:"POST",body:JSON.stringify({use_ai:useAI})});
    editorDirty = false; dirtyForms.delete("cv-editor-form"); editorVersion = "";
    $("#cv-facts-confirm").checked = false;
    await refreshState();
    studioSelectTab(useAI ? "editor" : "review");
    studioFeedback(useAI ? "Your suggested version is ready. Review the wording and save to preview the PDF." : "Review complete. Explore the breakdown, then open the editor to improve your CV.");
  } catch(error) { studioFeedback(error.message, true); }
  finally { studioBusy = false; setButtonBusy(button,false); renderStudio(); }
}

async function saveCVEditor(event) {
  event.preventDefault();
  if (studioBusy || !appState.cv_review) return;
  const button = $("#save-cv-button");
  studioBusy = true; setButtonBusy(button,true,"Building PDF"); renderStudio();
  try {
    const result = await api("/api/cv/review/document", {method:"PUT",body:JSON.stringify({source_hash:appState.cv_review.source_hash,document:readEditor()})});
    appState.cv_review = result.review;
    editorDirty = false; dirtyForms.delete("cv-editor-form"); editorVersion = result.review.source_hash + result.review.updated_at;
    // Fetch first so PDF generation failures appear as useful inline errors.
    const response = await fetch("/api/cv/review/pdf");
    if (!response.ok) throw new Error("PDF could not be generated. Your edits were saved; try again.");
    const blob = await response.blob();
    const frame = $("#cv-pdf-preview");
    if (frame.dataset.blobUrl) URL.revokeObjectURL(frame.dataset.blobUrl);
    frame.dataset.blobUrl = URL.createObjectURL(blob);
    frame.src = frame.dataset.blobUrl;
    frame.hidden = false; $("#pdf-placeholder").hidden = true;
    $("#cv-save-status").textContent = "Saved · PDF ready";
    studioFeedback("Your PDF is ready. Download it or confirm the facts to use it for future applications.");
  } catch(error) { studioFeedback(error.message,true); }
  finally { studioBusy = false; setButtonBusy(button,false); renderStudio(); }
}

document.addEventListener("DOMContentLoaded", () => {
  $$(".brand-mark").forEach(element => { element.innerHTML = '<img src="/static/assets/masar-symbol.png" alt="" width="40" height="40">'; });
  const sidebar = $(".nav-list");
  sidebar.insertBefore($('.nav-item[data-route="profile"]',sidebar), $('.nav-item[data-route="review"]',sidebar));
  $$(".brand small").forEach(el => el.textContent = "Career workspace");
  selectSettingsTab("ai");
  $("#review-cv-button").addEventListener("click",()=>runCVReview(false));
  $("#rewrite-cv-button").addEventListener("click",()=>runCVReview(true));
  $("#cv-editor-form").addEventListener("submit",saveCVEditor);
  $("#cv-editor-form").addEventListener("input",markEditorDirty);
  $("#cv-facts-confirm").addEventListener("change",renderStudio);
  document.addEventListener("click", event => {
    const tab = event.target.closest("[data-studio-tab]");
    if (tab) studioSelectTab(tab.dataset.studioTab);
    const settings = event.target.closest("[data-settings-tab]");
    if (settings) selectSettingsTab(settings.dataset.settingsTab);
    if (event.target.closest("#add-cv-section")) {
      if ($$(".cv-section").length >= 15) return;
      $("#cv-sections").insertAdjacentHTML("beforeend",editorSection({heading:"New section",body:""})); markEditorDirty();
    }
    if (event.target.closest(".remove-section")) {
      if ($$(".cv-section").length <= 1) return studioFeedback("Keep at least one CV section.",true);
      event.target.closest(".cv-section").remove(); markEditorDirty();
    }
  });
  $$('[role="tablist"]').forEach(list => list.addEventListener("keydown", event => {
    if (!["ArrowLeft","ArrowRight","Home","End"].includes(event.key)) return;
    const tabs = $$('[role="tab"]',list); let index = tabs.indexOf(document.activeElement);
    if (index < 0) return;
    event.preventDefault();
    index = event.key === "Home" ? 0 : event.key === "End" ? tabs.length-1 : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    tabs[index].click(); tabs[index].focus();
  }));
  $("#adopt-cv-button").addEventListener("click", async () => {
    if (!$("#cv-facts-confirm").checked || editorDirty || studioBusy) return;
    studioBusy = true;
    const button = $("#adopt-cv-button"); setButtonBusy(button,true,"Updating CV"); renderStudio();
    try {
      await api("/api/cv/review/use",{method:"POST",body:JSON.stringify({source_hash:appState.cv_review.source_hash,confirmed:true})});
      await refreshState(); navigate("discover");
      toast("Your revised CV is ready to use","The original is preserved. Review and approve any unsent applications again before sending.");
    } catch(error) { studioFeedback(error.message,true); }
    finally { studioBusy = false; setButtonBusy(button,false); renderStudio(); }
  });
});
