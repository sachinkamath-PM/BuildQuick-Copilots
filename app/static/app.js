const state = {
  product: "tyche",
  conversations: {},
  sending: false,
  accessToken: null,
  tycheWorkspace: null,
  selectedBulletId: "bullet-1",
  plutusWorkspace: null,
  nousWorkspace: null,
  nousProposals: {},
  nousSelectedSourceIds: null,
  browserAuthMode: "development",
};

const productCopy = {
  tyche: {
    title: "Product résumé",
    subtitle: "Senior Product Manager · Updated today",
    eyebrow: "TYCHE · RÉSUMÉ",
    welcome: "Edit with evidence",
    description: "Ask about this résumé or the selected text. Suggestions stay reviewable until you apply them.",
    placeholder: "Ask Tyche about this selection",
  },
  plutus: {
    title: "Family overview",
    subtitle: "All accounts · Apr–Jun 2026",
    eyebrow: "PLUTUS · DASHBOARD",
    welcome: "Understand your finances",
    description: "Ask about changes, comparisons, or scenarios. Facts and assumptions remain distinct.",
    placeholder: "Ask Plutus about this dashboard",
  },
  nous: {
    title: "Agent workspace",
    subtitle: "Customer research · Ready to plan",
    eyebrow: "NOUS · WORKFLOW",
    welcome: "Turn outcomes into plans",
    description: "Describe an outcome. Plans, agents, approvals, and outputs will remain visible.",
    placeholder: "Ask Nous to plan an outcome",
  },
};

const panel = document.querySelector("#assistant-panel");
const conversation = document.querySelector("#conversation");
const input = document.querySelector("#message-input");
const sendButton = document.querySelector("#send-button");

function currentContext() {
  const common = {
    product: state.product,
    page: { type: "workspace", id: `${state.product}-home`, label: productCopy[state.product].title },
    filters: {},
    authorised_resources: [],
    snapshot_version: "resume-v1",
  };
  if (state.product === "tyche") {
    const workspace = state.tycheWorkspace;
    const selected = workspace?.resume.bullets.find((item) => item.id === state.selectedBulletId) || workspace?.resume.bullets[0];
    return {
      ...common,
      page: { type: "resume", id: workspace?.resume.id || "resume-1", label: workspace?.resume.title || "Product résumé" },
      selection: {
        type: "resume_bullet",
        ids: [selected?.id || "bullet-1"],
        label: "Selected résumé bullet",
        excerpt: selected?.text || "Managed the product roadmap.",
      },
      filters: { grounded_workspace: Boolean(workspace) },
      snapshot_version: workspace?.resume ? `${workspace.resume.id}:v${workspace.resume.version}` : "resume-v1",
      authorised_resources: [
        { id: workspace?.resume.id || "resume-1", type: "resume", label: workspace?.resume.title || "Product résumé" },
        ...(workspace?.job_description ? [{
          id: workspace.job_description.id,
          type: "job_description",
          label: `${workspace.job_description.title} at ${workspace.job_description.company}`,
        }] : []),
      ],
    };
  }
  if (state.product === "plutus") {
    const workspace = state.plutusWorkspace;
    const analysis = workspace?.analysis;
    return {
      ...common,
      page: { type: "financial_dashboard", id: "family-dashboard", label: "Family overview" },
      date_range: analysis ? { start: analysis.period_start, end: analysis.period_end } : { start: "2026-04-01", end: "2026-06-30" },
      filters: { grounded_workspace: Boolean(workspace) },
      snapshot_version: workspace ? `plutus:v${workspace.version}` : "dashboard-v1",
      authorised_resources: [{ id: "family-dashboard", type: "financial_dashboard", label: "Family overview" }],
    };
  }
  return {
    ...common,
    filters: { grounded_workspace: Boolean(state.nousWorkspace) },
    snapshot_version: state.nousWorkspace ? `nous:v${state.nousWorkspace.version}` : "workflow-v1",
    authorised_resources: (state.nousWorkspace?.sources || [])
      .filter((source) => state.nousSelectedSourceIds?.has(source.id))
      .map((source) => ({ id: source.id, type: source.source_type, label: source.label })),
  };
}

function renderContext() {
  const context = currentContext();
  const chips = [context.page.label];
  if (context.selection) chips.push(context.selection.label);
  if (context.date_range) chips.push("Apr–Jun 2026");
  document.querySelector("#context-strip").innerHTML = chips
    .map((chip) => `<span class="context-chip">Using: ${escapeHtml(chip)}</span>`)
    .join("");
}

function renderTycheWorkspace(workspace) {
  state.tycheWorkspace = workspace;
  if (!workspace.resume.bullets.some((item) => item.id === state.selectedBulletId)) {
    state.selectedBulletId = workspace.resume.bullets[0]?.id;
  }
  document.querySelector("#workspace-title").textContent = workspace.resume.title;
  document.querySelector("#workspace-subtitle").textContent = `${workspace.resume.target_role} · Version ${workspace.resume.version}`;
  document.querySelector("#resume-company").textContent = workspace.resume.company;
  document.querySelector("#resume-role").textContent = `${workspace.resume.role} · ${workspace.resume.period}`;
  document.querySelector("#resume-source").textContent = workspace.resume.source_filename || "Demo résumé";
  const hasImportedBlocks = Boolean(workspace.resume.blocks?.length);
  document.querySelector("#resume-section-label").classList.toggle("hidden", hasImportedBlocks);
  document.querySelector("#resume-company").classList.toggle("hidden", hasImportedBlocks);
  document.querySelector("#resume-role").classList.toggle("hidden", hasImportedBlocks);
  const bulletById = Object.fromEntries(workspace.resume.bullets.map((item) => [item.id, item]));
  const visibleBlocks = hasImportedBlocks ? workspace.resume.blocks : workspace.resume.bullets;
  document.querySelector("#resume-bullets").innerHTML = visibleBlocks.map((block) => {
    if (block.kind === "heading") return `<h3 class="resume-block-heading">${escapeHtml(block.text)}</h3>`;
    if (block.kind === "paragraph") return `<p class="resume-block-paragraph">${escapeHtml(block.text)}</p>`;
    const bullet = bulletById[block.id] || block;
    return `
    <button id="selection-${escapeHtml(bullet.id)}" class="resume-bullet ${bullet.id === state.selectedBulletId ? "selected" : ""}" data-bullet-id="${escapeHtml(bullet.id)}" aria-pressed="${bullet.id === state.selectedBulletId}">
      <span>${escapeHtml(bullet.text)}</span><small>${bullet.id === state.selectedBulletId ? "Selected" : "Select"}</small>
    </button>`;
  }).join("");
  document.querySelectorAll("[data-bullet-id]").forEach((button) => button.addEventListener("click", () => {
    state.selectedBulletId = button.dataset.bulletId;
    renderTycheWorkspace(state.tycheWorkspace);
    renderContext();
  }));

  const ats = workspace.ats;
  document.querySelector("#ats-score").textContent = ats ? ats.score : "—";
  document.querySelector("#ats-label").textContent = ats ? `${workspace.job_description.title} at ${workspace.job_description.company}` : "Add a target role";
  document.querySelector("#job-toggle").textContent = ats ? "Update role" : "Add job description";
  document.querySelector("#ats-diagnostics").innerHTML = ats ? ats.diagnostics.map((item) =>
    `<span class="ats-pill">${escapeHtml(capitalise(item.category))} ${item.score}</span>`
  ).join("") : "";

  document.querySelector("#evidence-list").innerHTML = workspace.evidence.map((item) => `
    <div id="evidence-${escapeHtml(item.id.replaceAll(":", "-"))}" class="evidence-item">
      <div class="evidence-kind">${item.kind === "user_claim" ? "USER-SUPPLIED" : "ROLE REQUIREMENT"}</div>
      <strong>${escapeHtml(item.label)}</strong><small>${escapeHtml(item.excerpt)}</small>
    </div>`).join("");
  renderContext();
}

async function loadTycheWorkspace() {
  await ensureAccessToken();
  const response = await fetch("/api/tyche/workspace", { headers: authHeaders() });
  if (!response.ok) throw new Error("Could not load Tyche workspace");
  const result = await response.json();
  renderTycheWorkspace(result.workspace);
}

const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });

function signedMoney(value) {
  return `${value >= 0 ? "+" : "−"}${inr.format(Math.abs(value))}`;
}

function renderPlutusWorkspace(workspace) {
  state.plutusWorkspace = workspace;
  const analysis = workspace.analysis;
  document.querySelector("#workspace-subtitle").textContent = `${formatQuarter(analysis.period_start)} · Version ${workspace.version}`;
  document.querySelector("#plutus-period").textContent = `${formatQuarter(analysis.period_start)} compared with ${formatQuarter(analysis.previous_period_start)}`;
  const source = workspace.last_import;
  document.querySelector("#plutus-data-source").textContent = source
    ? `CSV · ${source.account_rows} accounts and ${source.transaction_rows} transactions in latest import`
    : "Demo records";
  document.querySelector("#net-worth").textContent = inr.format(analysis.net_worth);
  document.querySelector("#net-worth-change").textContent = `${signedMoney(analysis.net_worth_change)} from recorded previous balances`;
  document.querySelector("#period-spending").textContent = inr.format(analysis.current_spending);
  document.querySelector("#spending-change").textContent = `${signedMoney(analysis.spending_change)} versus the preceding period`;
  document.querySelector("#category-changes").innerHTML = [...analysis.category_changes]
    .sort((a, b) => Math.abs(b.change) - Math.abs(a.change))
    .map((item) => `<div class="insight-row"><strong>${escapeHtml(item.category)}</strong><small>${inr.format(item.current_spend)} · ${signedMoney(item.change)}</small></div>`).join("");
  document.querySelector("#subscriptions").innerHTML = analysis.subscriptions.length ? analysis.subscriptions.map((item) =>
    `<div class="insight-row"><strong>${escapeHtml(item.merchant)}</strong><small>${inr.format(item.typical_amount)} · ${item.occurrences} similar charges</small></div>`
  ).join("") : `<div class="insight-row"><small>No recurring pattern detected.</small></div>`;
  document.querySelector("#anomalies").innerHTML = analysis.anomalies.length ? analysis.anomalies.map((item) =>
    `<div id="transaction-${escapeHtml(item.transaction_id)}" class="insight-row"><strong>${escapeHtml(item.merchant)} · ${inr.format(item.amount)}</strong><small>${escapeHtml(item.reason)}</small></div>`
  ).join("") : `<div class="insight-row"><small>No transaction crossed the current rule.</small></div>`;
  document.querySelector("#coverage-gaps").innerHTML = analysis.coverage_gaps.length ? analysis.coverage_gaps.map((item) =>
    `<div id="policy-${escapeHtml(item.source_id)}" class="insight-row"><strong>${item.status === "confirmed_missing" ? "Confirmed gap" : "Incomplete data"}</strong><small>${escapeHtml(item.label)}</small></div>`
  ).join("") : `<div class="insight-row"><small>No recorded gaps.</small></div>`;
  document.querySelector("#account-list").innerHTML = workspace.accounts.map((account) => `
    <div id="account-${escapeHtml(account.id)}" class="account-row"><div><strong>${escapeHtml(account.name)}</strong><small>${escapeHtml(account.owner)} · ${escapeHtml(capitalise(account.account_type))}</small></div><div class="account-value"><strong>${inr.format(account.balance)}</strong><small>Previously ${inr.format(account.previous_balance)}</small></div></div>`).join("");
  renderContext();
}

function formatQuarter(isoDate) {
  const date = new Date(`${isoDate}T00:00:00Z`);
  return `Q${Math.floor(date.getUTCMonth() / 3) + 1} ${date.getUTCFullYear()}`;
}

async function loadPlutusWorkspace() {
  await ensureAccessToken();
  const response = await fetch("/api/plutus/workspace", { headers: authHeaders() });
  if (!response.ok) throw new Error("Could not load Plutus workspace");
  const result = await response.json();
  renderPlutusWorkspace(result.workspace);
}

function renderNousWorkspace(workspace) {
  state.nousWorkspace = workspace;
  const availableSourceIds = new Set(workspace.sources.filter((source) => source.authorised).map((source) => source.id));
  if (state.nousSelectedSourceIds === null) state.nousSelectedSourceIds = new Set(availableSourceIds);
  else state.nousSelectedSourceIds = new Set([...state.nousSelectedSourceIds].filter((id) => availableSourceIds.has(id)));
  const agentsById = Object.fromEntries(workspace.agents.map((agent) => [agent.id, agent]));
  document.querySelector("#nous-agents").innerHTML = workspace.agents.map((agent) => `
    <div class="agent-row"><strong>${escapeHtml(agent.name)}</strong><small>${escapeHtml(agent.role)}</small></div>`).join("");
  document.querySelector("#nous-sources").innerHTML = workspace.sources.map((source) => `
    <label class="agent-row source-choice"><input type="checkbox" data-nous-source-id="${escapeHtml(source.id)}" ${state.nousSelectedSourceIds.has(source.id) ? "checked" : ""} ${source.authorised ? "" : "disabled"} /><span><strong>${escapeHtml(source.label)}</strong><small>${escapeHtml(source.source_type.replaceAll("_", " "))} · ${source.record_count} record${source.record_count === 1 ? "" : "s"}</small></span></label>`).join("");
  document.querySelector("#nous-plans").innerHTML = workspace.plans.length ? [...workspace.plans].reverse().map((plan) => {
    const outputs = workspace.outputs.filter((output) => output.plan_id === plan.id);
    const actions = workspace.external_actions.filter((action) => action.plan_id === plan.id);
    const planSources = plan.source_ids.map((id) => workspace.sources.find((source) => source.id === id)?.label || id);
    return `<article class="nous-plan" data-plan-id="${plan.id}">
      <div class="nous-plan-header"><div><span class="document-meta">OUTCOME PLAN</span><h2>${escapeHtml(plan.objective)}</h2></div><span class="plan-status">${escapeHtml(plan.status)}</span></div>
      <small class="plan-provenance">Locked sources: ${planSources.length ? planSources.map(escapeHtml).join(", ") : "No source selected"}</small>
      ${plan.required_inputs.length ? `<div class="proposal-status">Required input: ${plan.required_inputs.map(escapeHtml).join(", ")}. Select sources and create a new plan.</div>` : ""}
      <div>${plan.steps.map((step, index) => `<div class="plan-step"><span class="step-dot ${step.status}">${step.status === "completed" ? "✓" : index + 1}</span><div><strong>${escapeHtml(step.title)}</strong><small>${escapeHtml(agentsById[step.agent_id]?.name || step.agent_id)}</small></div><small>${escapeHtml(step.status)}</small></div>`).join("")}</div>
      ${outputs.map((output) => `<div class="nous-output"><strong>${escapeHtml(output.title)}</strong><small>Produced by ${escapeHtml(agentsById[output.agent_id]?.name || output.agent_id)} · Sources: ${output.source_ids.map((id) => escapeHtml(workspace.sources.find((source) => source.id === id)?.label || id)).join(", ")}</small><p>${escapeHtml(output.content)}</p></div>`).join("")}
      ${actions.map((action) => `<div class="nous-output"><strong>${escapeHtml(capitalise(action.kind))} ${escapeHtml(action.status)}</strong><small>Destination: ${escapeHtml(action.destination)}</small><p>${escapeHtml(action.content_preview)}</p></div>`).join("")}
      <div class="plan-actions">
        ${plan.status === "draft" && !plan.required_inputs.length ? `<button data-start-plan="${plan.id}">Start plan</button>` : ""}
        ${plan.status === "running" ? `<span class="role-line">Agents are working…</span>` : ""}
        ${plan.status === "reviewable" && !actions.some((action) => action.status === "proposed" || action.status === "approved") ? `<input data-destination="${plan.id}" aria-label="External action destination" value="Strategy review workspace" /><button data-propose-action="${plan.id}">Preview publish</button>` : ""}
        ${plan.status === "completed" ? `<span class="role-line">Approval recorded. No connector action was executed.</span>` : ""}
      </div>
      <div id="nous-action-${plan.id}"></div>
    </article>`;
  }).join("") : `<article class="nous-plan"><p class="role-line">No plans yet. Describe an outcome in Ask Nous.</p></article>`;

  document.querySelectorAll("[data-start-plan]").forEach((button) => button.addEventListener("click", () => startNousPlan(button.dataset.startPlan)));
  document.querySelectorAll("[data-nous-source-id]").forEach((checkbox) => checkbox.addEventListener("change", () => {
    if (checkbox.checked) state.nousSelectedSourceIds.add(checkbox.dataset.nousSourceId);
    else state.nousSelectedSourceIds.delete(checkbox.dataset.nousSourceId);
    renderContext();
  }));
  document.querySelectorAll("[data-propose-action]").forEach((button) => button.addEventListener("click", () => {
    const destination = document.querySelector(`[data-destination="${button.dataset.proposeAction}"]`).value;
    proposeNousAction(button.dataset.proposeAction, destination);
  }));
  Object.entries(state.nousProposals).forEach(([planId, proposal]) => {
    const target = document.querySelector(`#nous-action-${planId}`);
    if (target) renderProposal(target, proposal, []);
  });
  renderContext();
}

async function loadNousWorkspace() {
  await ensureAccessToken();
  const response = await fetch("/api/nous/workspace", { headers: authHeaders() });
  if (!response.ok) throw new Error("Could not load Nous workspace");
  const result = await response.json();
  renderNousWorkspace(result.workspace);
}

async function startNousPlan(planId) {
  const response = await fetch(`/api/nous/plans/${planId}/start`, { method: "POST", headers: authHeaders() });
  const result = await response.json();
  if (!response.ok) return;
  renderNousWorkspace(result.workspace);
  window.setTimeout(() => advanceNousPlan(planId), 650);
}

async function advanceNousPlan(planId) {
  const response = await fetch(`/api/nous/plans/${planId}/advance`, { method: "POST", headers: authHeaders() });
  const result = await response.json();
  if (!response.ok) return;
  renderNousWorkspace(result.workspace);
  const plan = result.workspace.plans.find((item) => item.id === planId);
  if (plan?.status === "running") window.setTimeout(() => advanceNousPlan(planId), 850);
}

async function proposeNousAction(planId, destination) {
  const plan = state.nousWorkspace.plans.find((item) => item.id === planId);
  const response = await fetch(`/api/nous/plans/${planId}/external-actions`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ conversation_id: plan.conversation_id, kind: "publish", destination }),
  });
  const result = await response.json();
  if (!response.ok) return;
  state.nousProposals[planId] = result.proposal;
  renderNousWorkspace(result.workspace);
}

function renderWelcome() {
  const copy = productCopy[state.product];
  conversation.innerHTML = `
    <div class="welcome">
      <div class="welcome-mark">✦</div>
      <h3>${copy.welcome}</h3>
      <p>${copy.description}</p>
    </div>`;
}

async function ensureConversation() {
  if (state.conversations[state.product]) return state.conversations[state.product];
  const response = await fetch("/api/conversations", {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ product: state.product }),
  });
  if (!response.ok) throw new Error("Could not create conversation");
  const created = await response.json();
  state.conversations[state.product] = created.id;
  return created.id;
}

async function ensureAccessToken() {
  if (state.accessToken) return state.accessToken;
  const storageKey = "parallel-copilots-access-token";
  if (state.browserAuthMode === "guest") {
    const stored = window.sessionStorage.getItem(storageKey);
    if (stored) {
      state.accessToken = stored;
      return stored;
    }
  }
  if (state.browserAuthMode === "external") throw new Error("Sign-in integration is required");
  const endpoint = state.browserAuthMode === "guest" ? "/api/auth/guest-token" : "/api/auth/dev-token";
  const response = await fetch(endpoint, { method: "POST" });
  if (!response.ok) throw new Error("Sign-in is required");
  const result = await response.json();
  state.accessToken = result.access_token;
  if (state.browserAuthMode === "guest") window.sessionStorage.setItem(storageKey, state.accessToken);
  return state.accessToken;
}

function authHeaders(extra = {}) {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${state.accessToken}`,
    ...extra,
  };
}

function addMessage(role, text, pending = false) {
  const item = document.createElement("div");
  item.className = `message ${role}`;
  item.setAttribute("role", role === "assistant" ? "status" : "group");
  item.innerHTML = `<div class="bubble"></div>`;
  item.querySelector(".bubble").textContent = text;
  if (pending) item.dataset.pending = "true";
  conversation.appendChild(item);
  conversation.scrollTop = conversation.scrollHeight;
  return item;
}

function renderEvidence(container, evidence) {
  if (!evidence?.length) return;
  const list = document.createElement("div");
  list.className = "source-list";
  evidence.forEach((source) => {
    const button = document.createElement("button");
    button.className = "source";
    button.textContent = `↗ ${source.label}`;
    button.addEventListener("click", () => {
      const target = document.querySelector(source.href);
      target?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
    list.appendChild(button);
  });
  container.appendChild(list);
}

function renderProposal(container, proposal, evidence = []) {
  const supporting = evidence.filter((item) => proposal.payload?.evidence_ids?.includes(item.id));
  const card = document.createElement("div");
  card.className = "proposal";
  card.setAttribute("role", "group");
  card.setAttribute("aria-label", proposal.title);
  card.dataset.proposalId = proposal.id;
  card.innerHTML = `
    <div class="proposal-head"><strong>${escapeHtml(proposal.title)}</strong><span>${escapeHtml(proposal.summary)}</span></div>
    ${proposal.diff ? `<div class="diff">
      <div class="diff-part"><span class="diff-label">ORIGINAL</span><div>${escapeHtml(proposal.diff.original)}</div></div>
      <div class="diff-part"><span class="diff-label">SUGGESTED</span><textarea aria-label="Suggested text">${escapeHtml(proposal.diff.suggested)}</textarea></div>
    </div>` : ""}
    ${proposal.payload?.content_preview ? `<div class="diff-part"><span class="diff-label">EXACT CONTENT PREVIEW</span><div>${escapeHtml(proposal.payload.content_preview)}</div><span class="diff-label">DESTINATION</span><div>${escapeHtml(proposal.payload.destination)}</div></div>` : ""}
    ${supporting.length ? `<div class="proposal-evidence"><span class="diff-label">SUPPORTED BY</span>${supporting.map((item) => `<button class="source" data-evidence-href="${escapeHtml(item.href || "")}">${escapeHtml(item.label)}</button>`).join("")}</div>` : ""}
    <div class="proposal-actions">
      <button data-action="cancel">Cancel</button>
      <button data-action="edit">Save edit</button>
      <button class="apply" data-action="apply">Apply</button>
    </div>`;
  card.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", () => handleProposal(card, proposal, button.dataset.action));
  });
  card.querySelectorAll("[data-evidence-href]").forEach((button) => button.addEventListener("click", () => {
    document.querySelector(button.dataset.evidenceHref)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }));
  container.appendChild(card);
}

async function handleProposal(card, proposal, action) {
  const suggestedText = card.querySelector("textarea")?.value;
  card.querySelectorAll("button").forEach((button) => (button.disabled = true));
  const response = await fetch(`/api/proposals/${proposal.id}`, {
    method: "POST",
    headers: authHeaders(action === "apply" ? { "Idempotency-Key": crypto.randomUUID() } : {}),
    body: JSON.stringify({ action, suggested_text: suggestedText, source_version: proposal.source_version }),
  });
  const result = await response.json();
  if (!response.ok) {
    card.insertAdjacentHTML("beforeend", `<div class="proposal-status">${escapeHtml(result.detail || "Action failed")}</div>`);
    card.querySelectorAll("button").forEach((button) => (button.disabled = false));
    return;
  }
  if (action === "apply") {
    if (result.workspace?.resume) renderTycheWorkspace(result.workspace);
    else if (result.workspace?.accounts) renderPlutusWorkspace(result.workspace);
    else if (result.workspace?.agents) {
      delete state.nousProposals[proposal.payload.plan_id];
      renderNousWorkspace(result.workspace);
      return;
    }
    else if (result.proposal.diff) document.querySelector(`[data-bullet-id="${state.selectedBulletId}"] span`).textContent = result.proposal.diff.suggested;
  }
  if (action === "cancel" && result.workspace?.agents) {
    delete state.nousProposals[proposal.payload.plan_id];
    renderNousWorkspace(result.workspace);
    return;
  }
  card.querySelector(".proposal-actions").remove();
  card.insertAdjacentHTML("beforeend", `<div class="proposal-status">${action === "apply" ? "Applied to the workspace" : action === "edit" ? "Edit saved — review and apply when ready" : "Suggestion cancelled"}${result.undo_change_id ? ` · <button class="undo-link" data-undo-id="${result.undo_change_id}">Undo</button>` : ""}</div>`);
  card.querySelector("[data-undo-id]")?.addEventListener("click", async (event) => {
    const undoResponse = await fetch(`/api/tyche/changes/${event.target.dataset.undoId}/undo`, { method: "POST", headers: authHeaders() });
    const undoResult = await undoResponse.json();
    if (!undoResponse.ok) {
      event.target.closest(".proposal-status").textContent = undoResult.detail || "Undo failed";
      return;
    }
    renderTycheWorkspace(undoResult.workspace);
    event.target.closest(".proposal-status").textContent = "Change undone";
  });
}

async function submitJobDescription(event) {
  event.preventDefault();
  const status = document.querySelector("#job-status");
  status.textContent = "Analysing…";
  try {
    await ensureAccessToken();
    const response = await fetch("/api/tyche/job-description", {
      method: "PUT",
      headers: authHeaders(),
      body: JSON.stringify({
        title: document.querySelector("#job-title").value,
        company: document.querySelector("#job-company").value,
        text: document.querySelector("#job-description").value,
      }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Could not analyse this role");
    renderTycheWorkspace(result.workspace);
    document.querySelector("#job-form").classList.add("hidden");
    status.textContent = "";
  } catch (error) {
    status.textContent = error.message;
  }
}

function formAuthHeaders() {
  return { Authorization: `Bearer ${state.accessToken}` };
}

async function importResume(file) {
  const status = document.querySelector("#resume-file-status");
  status.textContent = "Importing and checking document…";
  try {
    await ensureAccessToken();
    const body = new FormData();
    body.append("file", file);
    const response = await fetch("/api/tyche/resume/import", { method: "POST", headers: formAuthHeaders(), body });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Could not import this résumé");
    renderTycheWorkspace(result.workspace);
    status.textContent = `${file.name} imported. Select a claim to edit with Tyche.`;
  } catch (error) {
    status.textContent = error.message;
  }
}

async function importJobDescription(file) {
  const status = document.querySelector("#job-status");
  status.textContent = "Importing and analysing…";
  try {
    await ensureAccessToken();
    const body = new FormData();
    body.append("title", document.querySelector("#job-title").value);
    body.append("company", document.querySelector("#job-company").value);
    body.append("file", file);
    const response = await fetch("/api/tyche/job-description/import", { method: "POST", headers: formAuthHeaders(), body });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Could not import this job description");
    document.querySelector("#job-description").value = result.workspace.job_description.text;
    renderTycheWorkspace(result.workspace);
    status.textContent = `${result.source_filename} imported.`;
  } catch (error) {
    status.textContent = error.message;
  }
}

async function exportResume() {
  const status = document.querySelector("#resume-file-status");
  status.textContent = "Preparing DOCX…";
  try {
    await ensureAccessToken();
    const response = await fetch("/api/tyche/resume/export.docx", { headers: formAuthHeaders() });
    if (!response.ok) {
      const result = await response.json();
      throw new Error(result.detail || "Could not export this résumé");
    }
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const filename = disposition.match(/filename="([^"]+)"/)?.[1] || "resume.docx";
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
    status.textContent = `${filename} exported.`;
  } catch (error) {
    status.textContent = error.message;
  }
}

async function importFinancialRecords(event) {
  event.preventDefault();
  const status = document.querySelector("#financial-import-status");
  const accounts = document.querySelector("#accounts-file").files[0];
  const transactions = document.querySelector("#transactions-file").files[0];
  if (!accounts && !transactions) {
    status.textContent = "Choose at least one CSV file.";
    return;
  }
  status.textContent = "Validating both files…";
  try {
    await ensureAccessToken();
    const body = new FormData();
    if (accounts) body.append("accounts_file", accounts);
    if (transactions) body.append("transactions_file", transactions);
    const response = await fetch("/api/plutus/import", { method: "POST", headers: formAuthHeaders(), body });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Could not import these records");
    renderPlutusWorkspace(result.workspace);
    const summary = result.workspace.last_import;
    status.textContent = summary.warnings.length
      ? `Imported with notes: ${summary.warnings.join(" ")}`
      : "Records imported and analysis refreshed.";
    document.querySelector("#accounts-file").value = "";
    document.querySelector("#transactions-file").value = "";
  } catch (error) {
    status.textContent = error.message;
  }
}

async function downloadFinancialTemplate(kind) {
  await ensureAccessToken();
  const response = await fetch(`/api/plutus/import/templates/${kind}.csv`, { headers: formAuthHeaders() });
  if (!response.ok) return;
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `plutus-${kind}-template.csv`;
  anchor.click();
  URL.revokeObjectURL(url);
}

async function importNousSources(event) {
  event.preventDefault();
  const inputElement = document.querySelector("#nous-source-files");
  const status = document.querySelector("#nous-source-status");
  const files = [...inputElement.files];
  if (!files.length) return;
  status.textContent = "Validating sources…";
  try {
    await ensureAccessToken();
    const body = new FormData();
    files.forEach((file) => body.append("files", file));
    const response = await fetch("/api/nous/sources/import", { method: "POST", headers: formAuthHeaders(), body });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Could not import these sources");
    result.sources.forEach((source) => state.nousSelectedSourceIds.add(source.id));
    renderNousWorkspace(result.workspace);
    inputElement.value = "";
    status.textContent = `${result.sources.length} source${result.sources.length === 1 ? "" : "s"} imported and selected.`;
  } catch (error) {
    status.textContent = error.message;
  }
}

async function submitGoalScenario(event) {
  event.preventDefault();
  const status = document.querySelector("#scenario-status");
  const resultContainer = document.querySelector("#scenario-result");
  status.textContent = "Calculating…";
  resultContainer.innerHTML = "";
  try {
    await ensureAccessToken();
    const previousProduct = state.product;
    state.product = "plutus";
    const conversationId = await ensureConversation();
    state.product = previousProduct;
    const response = await fetch("/api/plutus/scenarios", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({
        conversation_id: conversationId,
        name: document.querySelector("#goal-name").value,
        target_amount: Number(document.querySelector("#goal-target").value),
        current_amount: Number(document.querySelector("#goal-current").value),
        target_date: document.querySelector("#goal-date").value,
        annual_return_rate: Number(document.querySelector("#goal-return").value),
        annual_inflation_rate: Number(document.querySelector("#goal-inflation").value),
      }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Could not calculate this scenario");
    const scenario = result.scenario;
    resultContainer.innerHTML = `<div class="scenario-summary"><strong>${inr.format(scenario.required_monthly_contribution)} / month</strong><span>Inflation-adjusted target ${inr.format(scenario.inflation_adjusted_target)} over ${scenario.months} months</span><span>Assumptions: ${(scenario.annual_return_rate * 100).toFixed(1)}% return · ${(scenario.annual_inflation_rate * 100).toFixed(1)}% inflation</span><span>${escapeHtml(scenario.formula)}</span></div>`;
    renderProposal(resultContainer, result.proposal, []);
    status.textContent = "Review the assumptions before creating the goal.";
  } catch (error) {
    status.textContent = error.message;
  }
}

async function submitMessage(event) {
  event.preventDefault();
  const content = input.value.trim();
  if (!content || state.sending) return;
  if (state.product === "nous") {
    await submitNousCommand(content);
    return;
  }
  state.sending = true;
  conversation.setAttribute("aria-busy", "true");
  sendButton.disabled = true;
  document.querySelector(".welcome")?.remove();
  addMessage("user", content);
  input.value = "";
  const assistantItem = addMessage("assistant", "", true);
  const bubble = assistantItem.querySelector(".bubble");

  try {
    await ensureAccessToken();
    const conversationId = await ensureConversation();
    const response = await fetch(`/api/conversations/${conversationId}/messages`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ content, context: currentContext() }),
    });
    if (!response.ok || !response.body) throw new Error("Assistant unavailable");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (!line) continue;
        const event = JSON.parse(line);
        if (event.type === "delta") bubble.textContent += event.text;
        if (event.type === "complete") {
          bubble.textContent = event.message.content;
          renderEvidence(assistantItem, event.message.evidence);
          event.message.proposals.forEach((proposal) => renderProposal(assistantItem, proposal, event.message.evidence));
        }
        if (event.type === "error") bubble.textContent = event.message;
      }
      conversation.scrollTop = conversation.scrollHeight;
    }
  } catch (error) {
    bubble.textContent = "The assistant is unavailable. Your workspace was not changed.";
  } finally {
    state.sending = false;
    conversation.setAttribute("aria-busy", "false");
    sendButton.disabled = false;
    assistantItem.removeAttribute("data-pending");
    input.focus();
  }
}

async function submitNousCommand(content) {
  state.sending = true;
  conversation.setAttribute("aria-busy", "true");
  sendButton.disabled = true;
  document.querySelector(".welcome")?.remove();
  addMessage("user", content);
  input.value = "";
  const assistantItem = addMessage("assistant", "Preparing a reviewable plan…", true);
  try {
    await ensureAccessToken();
    const conversationId = await ensureConversation();
    const response = await fetch("/api/nous/plans", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({
        conversation_id: conversationId,
        objective: content,
        source_ids: [...(state.nousSelectedSourceIds || [])],
      }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Could not prepare the plan");
    assistantItem.querySelector(".bubble").textContent = result.assistant_message.content;
    renderNousWorkspace(result.workspace);
    const summary = document.createElement("div");
    summary.className = "proposal";
    summary.innerHTML = `<div class="proposal-head"><strong>Proposed plan</strong><span>${result.plan.steps.length} steps · ${result.plan.steps.map((step) => escapeHtml(step.agent_id.replace("agent-", ""))).join(" → ")}</span></div><div class="proposal-status">Review and start the plan in the workspace.</div>`;
    assistantItem.appendChild(summary);
  } catch (error) {
    assistantItem.querySelector(".bubble").textContent = error.message;
  } finally {
    state.sending = false;
    conversation.setAttribute("aria-busy", "false");
    sendButton.disabled = false;
    assistantItem.removeAttribute("data-pending");
    input.focus();
  }
}

function switchProduct(product) {
  state.product = product;
  const copy = productCopy[product];
  document.querySelectorAll(".product-tab").forEach((button) => button.classList.toggle("active", button.dataset.product === product));
  document.querySelectorAll(".product-workspace").forEach((workspace) => workspace.classList.toggle("active", workspace.id === `${product}-workspace`));
  document.querySelector("#workspace-title").textContent = copy.title;
  document.querySelector("#workspace-subtitle").textContent = copy.subtitle;
  document.querySelector("#workspace-eyebrow").textContent = copy.eyebrow;
  document.querySelector("#assistant-name").textContent = `Ask ${capitalise(product)}`;
  document.querySelector("#assistant-toggle").textContent = `Ask ${capitalise(product)}`;
  input.placeholder = copy.placeholder;
  renderContext();
  renderWelcome();
  if (product === "tyche" && !state.tycheWorkspace) loadTycheWorkspace().catch(() => {});
  if (product === "plutus" && !state.plutusWorkspace) loadPlutusWorkspace().catch(() => {
    document.querySelector("#net-worth-change").textContent = "Plutus data unavailable";
  });
  if (product === "nous" && !state.nousWorkspace) loadNousWorkspace().catch(() => {});
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#039;", '"': "&quot;" })[character]);
}
function capitalise(value) { return value[0].toUpperCase() + value.slice(1); }

document.querySelectorAll(".product-tab").forEach((button) => button.addEventListener("click", () => switchProduct(button.dataset.product)));
document.querySelector("#composer").addEventListener("submit", submitMessage);
document.querySelector("#job-form").addEventListener("submit", submitJobDescription);
document.querySelector("#resume-file").addEventListener("change", (event) => {
  const file = event.target.files[0];
  if (file) importResume(file);
  event.target.value = "";
});
document.querySelector("#job-file").addEventListener("change", (event) => {
  const file = event.target.files[0];
  if (file) importJobDescription(file);
  event.target.value = "";
});
document.querySelector("#resume-export").addEventListener("click", exportResume);
document.querySelector("#job-toggle").addEventListener("click", () => document.querySelector("#job-form").classList.remove("hidden"));
document.querySelector("#job-close").addEventListener("click", () => document.querySelector("#job-form").classList.add("hidden"));
document.querySelector("#scenario-form").addEventListener("submit", submitGoalScenario);
document.querySelector("#financial-import-form").addEventListener("submit", importFinancialRecords);
document.querySelector("#nous-source-form").addEventListener("submit", importNousSources);
document.querySelector("#nous-source-toggle").addEventListener("click", () => document.querySelector("#nous-source-form").classList.toggle("hidden"));
document.querySelector("#financial-import-toggle").addEventListener("click", () => document.querySelector("#financial-import-form").classList.remove("hidden"));
document.querySelector("#financial-import-close").addEventListener("click", () => document.querySelector("#financial-import-form").classList.add("hidden"));
document.querySelectorAll("[data-template]").forEach((button) => button.addEventListener("click", () => downloadFinancialTemplate(button.dataset.template)));
document.querySelector("#scenario-toggle").addEventListener("click", () => document.querySelector("#scenario-form").classList.remove("hidden"));
document.querySelector("#scenario-close").addEventListener("click", () => document.querySelector("#scenario-form").classList.add("hidden"));
document.querySelector("#close-panel").addEventListener("click", () => {
  panel.classList.add("closed");
  document.querySelector("#assistant-toggle").setAttribute("aria-expanded", "false");
});
document.querySelector("#reset-conversation").addEventListener("click", async () => {
  const conversationId = state.conversations[state.product];
  if (conversationId) {
    const response = await fetch(`/api/conversations/${conversationId}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    if (!response.ok && response.status !== 404) return;
    delete state.conversations[state.product];
  }
  renderWelcome();
  input.focus();
});
document.querySelector("#assistant-toggle").addEventListener("click", () => {
  panel.classList.remove("closed");
  document.querySelector("#assistant-toggle").setAttribute("aria-expanded", "true");
  input.focus();
});
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    document.querySelector("#composer").requestSubmit();
  }
});

async function initialiseApp() {
  try {
    const response = await fetch("/api/config");
    const config = await response.json();
    state.browserAuthMode = config.browser_auth_mode || "external";
    document.querySelectorAll(".product-tab").forEach((button) => {
      button.hidden = config.features?.[button.dataset.product] === false;
    });
    const enabled = Object.entries(config.features || {}).filter(([, value]) => value).map(([key]) => key);
    if (!enabled.includes(state.product) && enabled.length) switchProduct(enabled[0]);
  } catch (_) {
    // Local defaults keep all products available when public configuration is unavailable.
  }
  if (state.product === "tyche") {
    loadTycheWorkspace().catch(() => {
      document.querySelector("#ats-label").textContent = "Tyche data unavailable";
    });
  }
}

renderContext();
renderWelcome();
initialiseApp();
