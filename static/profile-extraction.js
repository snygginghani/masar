let extractionDraft = null;
let extractionBusy = false;

function extractionStatus(message, error = false) {
  const target = $("#extraction-status");
  target.textContent = message;
  target.classList.toggle("is-error", error);
}

document.addEventListener("DOMContentLoaded", () => {
  $("#extraction-prices").addEventListener("click", async () => {
    const button = $("#extraction-prices");
    setButtonBusy(button, true, "Checking prices");
    try {
      const result = await api("/api/profile/extraction-options");
      const choice = $("#extraction-model").value;
      $("#extraction-model").innerHTML = result.models.map(model => `<option value="${escapeHTML(model.id)}">${escapeHTML(model.label)} · $${model.input_per_million.toFixed(3)} / $${model.output_per_million.toFixed(2)} per M</option>`).join("");
      if (result.models.some(model => model.id === choice)) $("#extraction-model").value = choice;
      $("#extraction-price-note").textContent = result.models.length ? `Live prices checked ${new Date(result.checked_at).toLocaleString()}. Input / output rates per million tokens. Example: 3,000 input + 1,000 output tokens cost ${result.models.map(model => `${model.label.split(" · ")[0]} $${model.example_cost_usd.toFixed(6)}`).join("; ")}. Actual usage varies, including reasoning tokens. Prices may change.` : "Neither model is currently available within the price ceiling. You can still enter details manually.";
    } catch (error) { extractionStatus(error.message, true); }
    finally { setButtonBusy(button, false); }
  });

  $("#extract-profile").addEventListener("click", async () => {
    if (extractionBusy) return;
    if (!appState.profile?.cv_ready) return extractionStatus("Upload your CV in the Your CV panel first.", true);
    if (!$("#extraction-consent").checked) return extractionStatus("Check the consent box to send this CV to OpenRouter.", true);
    if (extractionDraft && !window.confirm("Replace these extraction suggestions with a new request? Your profile form will not change.")) return;
    const button = $("#extract-profile");
    const form = $("#profile-form");
    const before = Object.fromEntries(new FormData(form).entries());
    extractionBusy = true; setButtonBusy(button, true, "Extracting details");
    $("#apply-extraction").disabled = true;
    extractionStatus("Reading the uploaded CV. Your current profile and unsaved edits will stay intact.");
    try {
      const result = await api("/api/profile/extract", {method: "POST", body: JSON.stringify({consent: true, model: $("#extraction-model").value})});
      extractionDraft = {...result, before};
      $("#extraction-suggestions").innerHTML = result.suggestions.map((item, index) => `<article class="extraction-row"><label class="extraction-choice"><input type="checkbox" data-suggestion="${index}" ${before[item.field] ? "" : "checked"}><span><strong>${escapeHTML(item.label)}</strong><span>${escapeHTML(item.value)}</span></span></label><p>Current: ${escapeHTML(before[item.field] || "Not set")}</p><details><summary>View supporting CV text</summary><blockquote>${escapeHTML(item.evidence)}</blockquote></details></article>`).join("");
      $("#extraction-preview").hidden = !result.suggestions.length;
      extractionStatus(`${result.suggestions.length} supported suggestions from ${result.model.label.split(" · ")[0]}. ${result.rejected_fields.length ? "Unverifiable values were omitted: " + result.rejected_fields.join(", ") + ". " : ""}Check every suggestion; a matching quote does not guarantee the model interpreted it correctly.`);
      if (result.suggestions.length) $("#extraction-preview-heading").focus();
    } catch (error) { extractionStatus(error.message, true); }
    finally { extractionBusy = false; setButtonBusy(button, false); $("#apply-extraction").disabled = false; }
  });

  $("#apply-extraction").addEventListener("click", async () => {
    if (!extractionDraft || extractionBusy) return;
    const selected = $$("[data-suggestion]:checked", $("#extraction-suggestions"));
    if (!selected.length) return extractionStatus("Select at least one suggested field, or dismiss the suggestions.", true);
    const button = $("#apply-extraction");
    extractionBusy = true; setButtonBusy(button, true, "Checking source");
    try {
      const source = await api("/api/profile/extraction-source");
      if (source.source_hash !== extractionDraft.source_hash) throw new Error("Your CV or saved profile changed. Extract again before using these suggestions.");
      const form = $("#profile-form");
      let applied = 0, skipped = 0;
      for (const checkbox of selected) {
        const item = extractionDraft.suggestions[Number(checkbox.dataset.suggestion)];
        const input = form.elements.namedItem(item.field);
        if (!input || input.value !== (extractionDraft.before[item.field] || "")) { skipped++; continue; }
        input.value = item.value;
        applied++;
      }
      if (applied) dirtyForms.add("profile-form");
      extractionStatus(`${applied} fields copied into the form, not saved. ${skipped ? `${skipped} fields were skipped because you edited them after extraction started. ` : ""}Review the form and choose Save profile.`);
      $("#extraction-preview").hidden = true; extractionDraft = null;
      if (applied) $("#profile-save-status").textContent = "Extracted details · review and save";
    } catch (error) { extractionStatus(error.message, true); }
    finally { extractionBusy = false; setButtonBusy(button, false); }
  });
  $("#dismiss-extraction").addEventListener("click", () => {
    if (extractionBusy) return;
    extractionDraft = null; $("#extraction-preview").hidden = true;
    extractionStatus("Suggestions dismissed. Your profile has not changed.");
  });
});
