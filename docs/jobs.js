// Job Sheet dashboard. Reads/writes jobs.json + search.toml in the user's private repo through
// the GitHub Contents API. Schema mirrors src/jobapply/models.py — keep the two in sync.
// All job data is rendered with textContent (never innerHTML): it comes from scraped listings.
"use strict";

const API = "https://api.github.com";
const LS = { repo: "jobapply.repo", token: "jobapply.token", view: "jobapply.view" };
const STATUSES = ["potential", "queued", "applying", "applied", "assessment", "interview",
                  "offer", "rejected", "withdrawn", "closed"];
const DEAD = new Set(["rejected", "withdrawn", "closed"]);
const DAY = 86400000;

const state = {
  repo: null, token: null,
  data: null, sha: null,          // jobs.json + its blob sha (for optimistic writes)
  searchSha: null,
  view: { status: "active", q: "", source: "", sort: "match_score", dir: -1 },
  editing: null,                  // job id open in the dialog, or "" for a new job
};

const $ = (sel) => document.querySelector(sel);

function h(tag, props = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null) el.append(kid instanceof Node ? kid : String(kid));
  return el;
}

function toast(msg, bad = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (bad ? " bad" : "");
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), bad ? 6000 : 2500);
}

// ——— storage (localStorage can throw in private windows) ———
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch {} },
  del(k) { try { localStorage.removeItem(k); } catch {} },
};

// ——— GitHub API ———
class GhError extends Error { constructor(msg, status) { super(msg); this.status = status; } }

async function gh(path, opts = {}) {
  const res = await fetch(API + path, {
    ...opts,
    cache: "no-store",
    headers: {
      Authorization: `Bearer ${state.token}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      ...(opts.body ? { "Content-Type": "application/json" } : {}),
    },
  });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).message || msg; } catch {}
    throw new GhError(msg, res.status);
  }
  return res.json();
}

function b64decode(b64) {
  const bin = atob(b64.replace(/\s/g, ""));
  return new TextDecoder().decode(Uint8Array.from(bin, (c) => c.charCodeAt(0)));
}

function b64encode(text) {
  const bytes = new TextEncoder().encode(text);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

const contentsPath = (name) => `/repos/${state.repo}/contents/${encodeURIComponent(name)}`;

async function readFile(name) {
  const f = await gh(contentsPath(name));
  // Files over 1 MB come back without inline content; fetch the blob instead.
  const content = f.content ? f.content : (await gh(`/repos/${state.repo}/git/blobs/${f.sha}`)).content;
  return { text: b64decode(content), sha: f.sha };
}

async function writeFile(name, text, sha, message) {
  const r = await gh(contentsPath(name), {
    method: "PUT",
    body: JSON.stringify({ message, content: b64encode(text), ...(sha ? { sha } : {}) }),
  });
  return r.content.sha;
}

async function loadJobs() {
  const f = await readFile("jobs.json");
  state.data = JSON.parse(f.text);
  state.data.jobs ||= [];
  state.sha = f.sha;
}

// Apply fn to a copy of the data and push it. If someone else (the CLI) pushed first,
// reload and re-apply — fn must be safe to run against fresh data.
async function mutate(fn, message) {
  for (let attempt = 0; attempt < 3; attempt++) {
    const draft = structuredClone(state.data);
    const result = fn(draft);
    if (result === false) return false;
    try {
      state.sha = await writeFile("jobs.json", JSON.stringify(draft, null, 2) + "\n", state.sha, message);
      state.data = draft;
      render();
      return true;
    } catch (e) {
      if (e.status === 409 || e.status === 422) { await loadJobs(); continue; }
      toast(`Save failed: ${e.message}`, true);
      throw e;
    }
  }
  toast("Save failed: the file kept changing. Reload and try again.", true);
  return false;
}

// ——— job helpers (mirror models.py) ———
const nowIso = () => new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
const TRACKING = new Set(["ref", "refid", "src", "source", "trk", "trackingid", "lipi", "gh_src",
                          "lever-source", "lever-origin", "jobsource"]);

function normalizeUrl(raw) {
  const u = new URL(raw.trim());
  const host = u.host.toLowerCase().replace(/^www\./, "");
  let path = u.pathname.replace(/\/+$/, "") || "/";
  if (host.includes("linkedin.com") && path.includes("/jobs/view/")) {
    return `https://${host}/jobs/view/${path.split("/").pop().split("-").pop()}`;
  }
  const params = [...u.searchParams].filter(([k]) => !k.toLowerCase().startsWith("utm_") && !TRACKING.has(k.toLowerCase()));
  params.sort((a, b) => (a[0] + "\0" + a[1] < b[0] + "\0" + b[1] ? -1 : 1));
  const q = new URLSearchParams(params).toString();
  return `https://${host}${path}${q ? "?" + q : ""}`;
}

async function jobId(url) {
  const digest = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(normalizeUrl(url)));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 10);
}

function setStatus(job, status, summary = "") {
  if (job.status === status) return;
  job.status = status;
  const t = nowIso();
  if (status === "queued" && !job.queued_at) job.queued_at = t;
  if (status === "applied" && !job.applied_at) job.applied_at = t;
  (job.events ||= []).push({ date: t, type: status, summary: summary || "changed on dashboard" });
  job.updated_at = t;
}

const safeHref = (url) => (/^https?:\/\//i.test(url || "") ? url : null);

function parseDate(s) {
  if (!s) return null;
  const [y, m, d] = s.slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d);
}

function fmtDate(s) {
  const d = parseDate(s);
  return d ? d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: d.getFullYear() === new Date().getFullYear() ? undefined : "2-digit" }) : "";
}

function daysFromToday(s) {
  const d = parseDate(s);
  if (!d) return null;
  const t = new Date(); t.setHours(0, 0, 0, 0);
  return Math.round((d - t) / DAY);
}

function fmtMoney(n, period) {
  if (n == null) return "";
  if (period === "hour") return `$${n}`;
  return n >= 1000 ? `$${Math.round(n / 1000)}k` : `$${n}`;
}

function fmtSalary(s) {
  if (!s || (s.min == null && s.max == null)) return "";
  const per = { year: "", month: "/mo", hour: "/hr" }[s.period || "year"] ?? "";
  const lo = fmtMoney(s.min, s.period), hi = fmtMoney(s.max, s.period);
  return (lo && hi && lo !== hi ? `${lo}–${hi.replace("$", "")}` : lo || hi) + per;
}

const annual = (s) => {
  if (!s) return -1;
  const v = s.max ?? s.min ?? -1;
  return v * ({ hour: 2080, month: 12 }[s.period] || 1);
};

// ——— rendering ———
function visibleJobs() {
  const { status, q, source, sort, dir } = state.view;
  const needle = q.trim().toLowerCase();
  const jobs = state.data.jobs.filter((j) => {
    if (status === "active" && DEAD.has(j.status)) return false;
    if (status !== "active" && status !== "all" && j.status !== status) return false;
    if (source && j.source !== source) return false;
    if (needle && ![j.company, j.role, ...(j.location || [])].join(" ").toLowerCase().includes(needle)) return false;
    return true;
  });
  const key = {
    match_score: (j) => j.match_score ?? -1,
    company: (j) => (j.company || "").toLowerCase(),
    role: (j) => (j.role || "").toLowerCase(),
    location: (j) => (j.location || []).join(", ").toLowerCase(),
    date_posted: (j) => j.date_posted || "",
    closes_at: (j) => j.closes_at || (dir > 0 ? "9999" : ""),
    salary: (j) => annual(j.salary),
    status: (j) => STATUSES.indexOf(j.status),
  }[sort];
  return jobs.sort((a, b) => {
    const x = key(a), y = key(b);
    return (x < y ? -1 : x > y ? 1 : 0) * dir;
  });
}

function renderCounts() {
  const jobs = state.data.jobs;
  const n = (s) => jobs.filter((j) => j.status === s).length;
  const items = [
    ["active", "Active", jobs.filter((j) => !DEAD.has(j.status)).length],
    ...STATUSES.map((s) => [s, s, n(s)]),
    ["all", "All", jobs.length],
  ];
  $("#counts").replaceChildren(...items.map(([key, label, count]) =>
    h("button", {
      class: `count${state.view.status === key ? " on" : ""}${count ? "" : " zero"}`,
      "aria-pressed": String(state.view.status === key),
      onclick: () => { state.view.status = key; saveView(); render(); },
    }, h("span", { class: "n", text: count }), h("span", { class: "l", text: label }))));
}

function statusSelect(job) {
  return h("select", {
    class: `status st-${job.status}`,
    "aria-label": `Status for ${job.company} ${job.role}`,
    onclick: (e) => e.stopPropagation(),
    onchange: (e) => {
      const to = e.target.value;
      mutate((d) => setStatus(d.jobs.find((x) => x.id === job.id), to), `${job.company}: ${to}`)
        .then((ok) => ok && toast(`${job.company} → ${to}`));
    },
  }, STATUSES.map((s) => h("option", { value: s, selected: s === job.status, text: s })));
}

function queueButton(job) {
  const queued = job.status === "queued";
  if (!queued && job.status !== "potential") return null;
  return h("button", {
    class: `btn sm${queued ? "" : " red"}`,
    title: queued ? "Remove from the apply queue" : "Queue for /apply",
    text: queued ? "Unqueue" : "Queue",
    onclick: (e) => {
      e.stopPropagation();
      const to = queued ? "potential" : "queued";
      mutate((d) => setStatus(d.jobs.find((x) => x.id === job.id), to), `${job.company}: ${to}`)
        .then((ok) => ok && toast(queued ? "Removed from queue" : `Queued — run /apply in Claude Code`));
    },
  });
}

function dateCell(s, isClose) {
  if (!s) return h("td", { class: "date dim", text: "—" });
  const days = daysFromToday(s);
  let rel = "", cls = "";
  if (isClose) {
    if (days < 0) { cls = "past"; rel = "closed"; }
    else { rel = days === 0 ? "today" : `in ${days}d`; if (days <= 7) cls = "soon"; }
  } else {
    rel = days === 0 ? "today" : `${-days}d ago`;
  }
  return h("td", { class: `date ${cls}`, title: s }, fmtDate(s), h("span", { class: "rel", text: rel }));
}

function renderRows() {
  const jobs = visibleJobs();
  $("#empty").hidden = jobs.length > 0;
  $("#rows").replaceChildren(...jobs.map((j) => {
    const href = safeHref(j.url);
    return h("tr", { class: DEAD.has(j.status) ? "dead" : "", onclick: () => openDetail(j.id) },
      h("td", { class: "num", text: j.match_score != null ? Math.round(j.match_score) : "—" }),
      h("td", { class: "company", title: j.company, text: j.company }),
      h("td", { class: "role", text: j.role }),
      h("td", { class: "loc", text: (j.location || []).join(" · ") || (j.remote ? "Remote" : "") }),
      dateCell(j.date_posted, false),
      dateCell(j.closes_at, true),
      h("td", { class: "num" }, fmtSalary(j.salary), j.salary?.basis === "estimated" ? h("span", { class: "est", text: "est." }) : null),
      h("td", {}, statusSelect(j)),
      h("td", { class: "actions" }, queueButton(j),
        href ? h("a", { href, target: "_blank", rel: "noopener noreferrer", title: "Open listing", onclick: (e) => e.stopPropagation(), text: "↗" }) : null),
    );
  }));
  document.querySelectorAll("th[data-sort]").forEach((th) => {
    th.classList.toggle("sorted", th.dataset.sort === state.view.sort);
    th.classList.toggle("asc", state.view.dir > 0);
  });
}

function renderSources() {
  const sel = $("#source");
  const sources = [...new Set(state.data.jobs.map((j) => j.source).filter(Boolean))].sort();
  sel.replaceChildren(h("option", { value: "", text: "All sources" }),
    ...sources.map((s) => h("option", { value: s, selected: s === state.view.source, text: s })));
}

function render() {
  if (!state.data) return;
  $("#sheetno").textContent = `${state.repo} · ${state.data.jobs.length} jobs`;
  renderCounts();
  renderSources();
  renderRows();
}

function saveView() { store.set(LS.view, JSON.stringify(state.view)); }

// ——— detail / add dialog ———
function openDetail(id) {
  const job = id ? state.data.jobs.find((j) => j.id === id) : { status: "potential", source: "manual", location: [] };
  state.editing = id || "";
  const f = $("#jobform");
  f.reset();
  $("#dtitle").textContent = id ? `${job.company} — ${job.role}` : "Add a job";
  f.status.replaceChildren(...STATUSES.map((s) => h("option", { value: s, text: s })));
  const val = {
    company: job.company, role: job.role, url: job.url, location: (job.location || []).join(", "),
    status: job.status, level: job.level, date_posted: job.date_posted, closes_at: job.closes_at,
    salary_min: job.salary?.min, salary_max: job.salary?.max, salary_basis: job.salary?.basis || "listed",
    match_score: job.match_score != null ? Math.round(job.match_score) : "", match_notes: job.match_notes, notes: job.notes,
  };
  for (const [k, v] of Object.entries(val)) f.elements[k].value = v ?? "";

  const meta = [];
  if (job.source) meta.push(`source: ${job.source}`);
  if (job.ats) meta.push(`portal: ${job.ats}`);
  if (job.portal_account) meta.push(`account: ${job.portal_account.email} @ ${job.portal_account.domain}`);
  if (job.sponsorship) meta.push(job.sponsorship);
  if (job.applied_at) meta.push(`applied ${fmtDate(job.applied_at)}`);
  if (id) meta.push(`id ${job.id}`);
  $("#dmeta").textContent = meta.join(" · ");

  const events = [...(job.events || [])].reverse();
  $("#evhead").hidden = $("#events").hidden = !events.length;
  $("#events").replaceChildren(...events.map((e) => h("li", {},
    h("span", { class: "when", text: fmtDate(e.date) }), h("span", { class: "type", text: e.type }), e.summary || "")));
  $("#ddelete").hidden = !id;
  $("#detail").showModal();
}

async function saveDetail(e) {
  e.preventDefault();
  const f = $("#jobform");
  const v = Object.fromEntries(new FormData(f));
  if (!safeHref(v.url)) { toast("URL must start with http(s)://", true); return; }
  const num = (x) => (x === "" || x == null ? null : Number(x));
  const fields = {
    company: v.company.trim(), role: v.role.trim(), url: v.url.trim(),
    location: v.location.split(",").map((s) => s.trim()).filter(Boolean),
    level: v.level.trim() || null, date_posted: v.date_posted || null, closes_at: v.closes_at || null,
    match_score: num(v.match_score), match_notes: v.match_notes.trim() || null, notes: v.notes,
    salary: num(v.salary_min) != null || num(v.salary_max) != null
      ? { min: num(v.salary_min) ?? num(v.salary_max), max: num(v.salary_max) ?? num(v.salary_min), currency: "USD", period: "year", basis: v.salary_basis }
      : null,
  };
  const btn = $("#dsave");
  btn.disabled = true;
  try {
    if (state.editing) {
      const id = state.editing;
      await mutate((d) => {
        const job = d.jobs.find((j) => j.id === id);
        if (!job) return false;
        // Keep any salary sub-fields (e.g. period) the form doesn't show.
        if (fields.salary && job.salary) fields.salary = { ...job.salary, ...fields.salary, period: job.salary.period || "year" };
        for (const [k, val] of Object.entries(fields)) { if (val == null || val === "") delete job[k]; else job[k] = val; }
        setStatus(job, v.status);
        job.updated_at = nowIso();
      }, `edit ${fields.company}: ${fields.role}`);
    } else {
      const id = await jobId(fields.url);
      if (state.data.jobs.some((j) => j.id === id)) { toast("That job is already on the sheet", true); return; }
      const t = nowIso();
      const job = { id, ...fields, source: "manual", status: "potential", events: [], created_at: t, updated_at: t };
      for (const k of Object.keys(job)) if (job[k] == null) delete job[k];
      setStatus(job, v.status, "added on dashboard");
      await mutate((d) => { if (d.jobs.some((j) => j.id === id)) return false; d.jobs.push(job); }, `add ${fields.company}: ${fields.role}`);
    }
    $("#detail").close();
    toast("Saved");
  } finally {
    btn.disabled = false;
  }
}

async function deleteJob() {
  const id = state.editing;
  const job = state.data.jobs.find((j) => j.id === id);
  if (!job || !confirm(`Delete ${job.company} — ${job.role}? This can't be undone from here.`)) return;
  if (await mutate((d) => { d.jobs = d.jobs.filter((j) => j.id !== id); }, `delete ${job.company}: ${job.role}`)) {
    $("#detail").close();
    toast("Deleted");
  }
}

// ——— settings tab ———
async function loadSearch() {
  try {
    const f = await readFile("search.toml");
    $("#searchtoml").value = f.text;
    state.searchSha = f.sha;
    $("#searchmsg").textContent = "";
  } catch (e) {
    $("#searchmsg").textContent = e.status === 404 ? "No search.toml yet — saving creates it." : `Couldn't load: ${e.message}`;
  }
}

async function saveSearch() {
  const btn = $("#savesearch");
  btn.disabled = true;
  try {
    state.searchSha = await writeFile("search.toml", $("#searchtoml").value, state.searchSha, "update search settings");
    $("#searchmsg").textContent = "Saved. Next fetch uses it.";
  } catch (e) {
    $("#searchmsg").textContent = e.status === 409 ? "Changed elsewhere — reload the tab first." : `Save failed: ${e.message}`;
  } finally {
    btn.disabled = false;
  }
}

function showTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t.dataset.tab === name));
  $("#tab-jobs").hidden = name !== "jobs";
  $("#tab-settings").hidden = name !== "settings";
  if (name === "settings") loadSearch();
}

// ——— lock / unlock ———
function showLock(message = "") {
  $("#app").hidden = true;
  $("#lock").hidden = false;
  $("#sheetno").textContent = "Locked";
  $("#lockerr").textContent = message;
  const f = $("#unlock");
  f.repo.value = state.repo || store.get(LS.repo) || "";
  f.token.value = "";
  (f.repo.value ? f.token : f.repo).focus();
}

function lock(message = "Locked. The token was removed from this browser.") {
  store.del(LS.token);
  state.token = null;
  state.data = null;
  $("#rows").replaceChildren();
  $("#searchtoml").value = "";
  showLock(message);
}

// Only fine-grained tokens can be limited to one repo. Classic (ghp_) and gh-CLI/OAuth (gho_)
// tokens reach every repo the user owns — including this dashboard's code.
const FINE_GRAINED = /^github_pat_\w+$/;
const TOKEN_HELP = "Use a fine-grained token (starts with github_pat_) limited to only your job-data repo. "
  + "Classic and gh-CLI tokens can reach all your repos.";

class NotPrivate extends Error {}

async function checkRepo() {
  const repo = await gh(`/repos/${state.repo}`);
  if (repo.private !== true) {
    throw new NotPrivate(`${state.repo} is public — make it private on GitHub before using the dashboard.`);
  }
}

async function unlockWith(repo, token) {
  if (!FINE_GRAINED.test(token)) {
    store.del(LS.token);
    state.token = null;
    showLock(TOKEN_HELP);
    return;
  }
  state.repo = repo;
  state.token = token;
  try {
    await checkRepo();
    await loadJobs();
  } catch (e) {
    state.data = null;
    state.token = null;
    const why = e instanceof NotPrivate ? e.message
      : e.status === 401 ? "That token was rejected (expired or mistyped)."
      : e.status === 404 ? `Can't see ${repo}/jobs.json with this token. Check the repo name and that the token is limited to that repo with Contents access.`
      : e.status === 403 ? "GitHub refused the request (permissions or rate limit)."
      : `Couldn't load: ${e.message}`;
    store.del(LS.token);
    showLock(why);
    return;
  }
  store.set(LS.repo, repo);
  store.set(LS.token, token);
  $("#lock").hidden = true;
  $("#app").hidden = false;
  render();
}

async function reload() {
  const btn = $("#reload");
  btn.disabled = true;
  try { await checkRepo(); await loadJobs(); render(); toast("Up to date"); }
  catch (e) {
    if (e instanceof NotPrivate) lock(e.message);
    else toast(`Reload failed: ${e.message}`, true);
  }
  finally { btn.disabled = false; }
}

// ——— wiring ———
function init() {
  try { Object.assign(state.view, JSON.parse(store.get(LS.view) || "{}")); } catch {}

  $("#unlock").addEventListener("submit", (e) => {
    e.preventDefault();
    const f = e.target;
    unlockWith(f.repo.value.trim(), f.token.value.trim());
  });
  $("#lockbtn").addEventListener("click", lock);
  $("#reload").addEventListener("click", reload);
  $("#addbtn").addEventListener("click", () => openDetail(null));
  $("#q").value = state.view.q;
  $("#q").addEventListener("input", (e) => { state.view.q = e.target.value; saveView(); renderRows(); });
  $("#source").addEventListener("change", (e) => { state.view.source = e.target.value; saveView(); renderRows(); });
  document.querySelectorAll("th[data-sort]").forEach((th) => th.addEventListener("click", () => {
    const key = th.dataset.sort;
    state.view.dir = state.view.sort === key ? -state.view.dir : (["company", "role", "location", "closes_at", "status"].includes(key) ? 1 : -1);
    state.view.sort = key;
    saveView();
    renderRows();
  }));
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));
  $("#jobform").addEventListener("submit", saveDetail);
  $("#dclose").addEventListener("click", () => $("#detail").close());
  $("#ddelete").addEventListener("click", deleteJob);
  $("#savesearch").addEventListener("click", saveSearch);

  const repo = store.get(LS.repo), token = store.get(LS.token);
  if (repo && token) unlockWith(repo, token);
  else showLock();
}

init();
