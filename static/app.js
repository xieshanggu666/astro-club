/* 星野日志 前端逻辑 */
"use strict";

// ---------- 工具 ----------
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function req(method, path, body) {
  const opt = { method };
  if (body !== undefined) {
    opt.headers = { "Content-Type": "application/json" };
    opt.body = JSON.stringify(body);
  }
  const r = await fetch(path, opt);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `请求失败 (${r.status})`);
  return data;
}
const api = {
  get: p => req("GET", p),
  post: (p, b) => req("POST", p, b ?? {}),
  put: (p, b) => req("PUT", p, b),
  del: p => req("DELETE", p),
};

let toastTimer = null;
function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2200);
}
function showErr(e) { toast("⚠ " + e.message); }

const TYPE_LABEL = { planet: "行星", dso: "深空", lunar: "月球", double: "双星", comet: "彗星", star: "恒星", other: "其他" };
const MOON_LABEL = { none: "无影响", low: "轻微", medium: "中等", high: "敏感" };
const STATUS_LABEL = { planning: "计划中", active: "进行中", completed: "已完成" };
const LEVEL_ICON = { ok: "🟢", warning: "🟡", error: "🔴" };

function fmtExposure(ex) {
  if (!ex || typeof ex !== "object") return "";
  const parts = [];
  if (ex.iso) parts.push("ISO " + ex.iso);
  if (ex.shutter) parts.push("单张 " + ex.shutter);
  if (ex.frames) parts.push("× " + ex.frames + " 帧");
  if (ex.gain) parts.push("增益 " + ex.gain);
  return parts.join(" · ");
}
function condText(r) {
  const parts = [];
  if (r.limiting_magnitude) parts.push(`极限星等 ${r.limiting_magnitude}`);
  if (r.transparency) parts.push(`透明度 ${r.transparency}/5`);
  if (r.seeing) parts.push(`视宁度 ${r.seeing}/5`);
  return parts.join(" · ");
}

// ---------- 全局状态 ----------
const state = { tab: "planner", sessionId: null, recordSessionId: null, logTargetId: null, recordFormItem: null, editTargetId: null };
let TARGETS = [], EQUIP = [], SESSIONS = [];

async function refreshCaches() {
  [TARGETS, EQUIP, SESSIONS] = await Promise.all([
    api.get("/api/targets"), api.get("/api/equipment"), api.get("/api/sessions"),
  ]);
}
const eqName = id => (EQUIP.find(e => e.id === id) || {}).name || `#${id}`;

// ---------- 页签 ----------
function switchTab(tab) {
  state.tab = tab;
  $$("#tabs button").forEach(b => b.classList.toggle("active", b.dataset.tab === tab));
  $$(".tab").forEach(s => s.classList.toggle("active", s.id === "tab-" + tab));
  ({ planner: renderPlanner, record: renderRecordTab, logbook: renderLogbook,
     targets: renderTargets, equipment: renderEquipment })[tab]();
}

// ---------- 目标库 ----------
function targetFormHtml(t) {
  t = t || {};
  const eqChecks = EQUIP.map(e => `
    <label><input type="checkbox" class="tf-eq" value="${e.id}"
      ${(t.equipment_needed || []).includes(e.id) ? "checked" : ""}> ${esc(e.name)}</label>`).join("");
  const typeOpts = Object.entries(TYPE_LABEL).map(([k, v]) =>
    `<option value="${k}" ${t.type === k ? "selected" : ""}>${v}</option>`).join("");
  const moonOpts = Object.entries(MOON_LABEL).map(([k, v]) =>
    `<option value="${k}" ${t.moon_sensitivity === k ? "selected" : ""}>${v}</option>`).join("");
  return `
  <div class="card">
    <h2>${t.id ? "编辑目标" : "添加目标"}</h2>
    <div class="row">
      <div class="grow"><label>名称 *</label><input id="tf_name" value="${esc(t.name || "")}"></div>
      <div><label>类型</label><select id="tf_type">${typeOpts}</select></div>
      <div><label>星座</label><input id="tf_cons" value="${esc(t.constellation || "")}" style="width:90px"></div>
      <div><label>目标高度(°)</label><input id="tf_alt" type="number" value="${t.best_altitude ?? ""}" style="width:80px"></div>
      <div><label>最低高度(°)</label><input id="tf_malt" type="number" value="${t.min_altitude ?? 15}" style="width:80px"></div>
    </div>
    <div class="row" style="margin-top:8px">
      <div><label>预计出现（起）</label><input id="tf_vs" type="time" value="${esc(t.visible_start || "")}"></div>
      <div><label>预计出现（止）</label><input id="tf_ve" type="time" value="${esc(t.visible_end || "")}"></div>
      <div><label>月光影响</label><select id="tf_moon">${moonOpts}</select></div>
      <div class="grow"><label>备注</label><input id="tf_desc" value="${esc(t.description || "")}"></div>
    </div>
    <h3>所需设备</h3>
    <div class="eq-checks">${eqChecks || '<span class="muted">请先在「设备」页添加设备</span>'}</div>
    <div style="margin-top:10px">
      <button class="btn" onclick="saveTarget()">${t.id ? "保存修改" : "添加目标"}</button>
      ${t.id ? '<button class="btn ghost" onclick="cancelEditTarget()">取消</button>' : ""}
    </div>
  </div>`;
}

async function renderTargets() {
  await refreshCaches();
  const editing = state.editTargetId ? TARGETS.find(t => t.id === state.editTargetId) : null;
  const rowsHtml = TARGETS.map(t => `
    <tr>
      <td><b>${esc(t.name)}</b> <span class="badge type">${TYPE_LABEL[t.type] || t.type}</span></td>
      <td>${esc(t.constellation || "—")}</td>
      <td>${t.best_altitude ?? "—"}°</td>
      <td>${t.visible_start && t.visible_end ? `${t.visible_start}–${t.visible_end}` : "—"}</td>
      <td>${MOON_LABEL[t.moon_sensitivity] || "—"}</td>
      <td class="small">${(t.equipment_needed || []).map(eqName).map(esc).join("、") || "—"}</td>
      <td style="white-space:nowrap">
        <button class="btn small ghost" onclick="editTarget(${t.id})">编辑</button>
        <button class="btn small danger" onclick="delTarget(${t.id})">删除</button>
      </td>
    </tr>`).join("");
  $("#tab-targets").innerHTML = targetFormHtml(editing) + `
    <div class="card"><h2>目标库（${TARGETS.length}）</h2>
      ${TARGETS.length ? `<table><thead><tr>
        <th>名称</th><th>星座</th><th>高度</th><th>预计出现</th><th>月光影响</th><th>所需设备</th><th></th>
      </tr></thead><tbody>${rowsHtml}</tbody></table>` : '<div class="empty">还没有目标，先添加一个吧</div>'}
    </div>`;
}

function editTarget(id) { state.editTargetId = id; renderTargets(); }
function cancelEditTarget() { state.editTargetId = null; renderTargets(); }

async function saveTarget() {
  const body = {
    name: $("#tf_name").value.trim(),
    type: $("#tf_type").value,
    constellation: $("#tf_cons").value.trim(),
    best_altitude: $("#tf_alt").value,
    min_altitude: $("#tf_malt").value,
    visible_start: $("#tf_vs").value,
    visible_end: $("#tf_ve").value,
    moon_sensitivity: $("#tf_moon").value,
    description: $("#tf_desc").value.trim(),
    equipment_needed: $$(".tf-eq:checked").map(c => +c.value),
  };
  try {
    if (state.editTargetId) {
      await api.put(`/api/targets/${state.editTargetId}`, body);
      toast("目标已更新");
    } else {
      await api.post("/api/targets", body);
      toast("目标已添加");
    }
    state.editTargetId = null;
    renderTargets();
  } catch (e) { showErr(e); }
}

async function delTarget(id) {
  if (!confirm("确定删除该目标？相关计划条目也会移除。")) return;
  try { await api.del(`/api/targets/${id}`); toast("已删除"); renderTargets(); }
  catch (e) { showErr(e); }
}

// ---------- 设备 ----------
async function renderEquipment() {
  await refreshCaches();
  const rowsHtml = EQUIP.map(e => `
    <tr><td><b>${esc(e.name)}</b></td><td>${esc(e.kind || "—")}</td>
        <td class="muted">${esc(e.notes || "")}</td>
        <td><button class="btn small danger" onclick="delEquip(${e.id})">删除</button></td></tr>`).join("");
  $("#tab-equipment").innerHTML = `
    <div class="card"><h2>添加设备</h2>
      <div class="row">
        <div class="grow"><label>名称 *</label><input id="ef_name"></div>
        <div><label>类型</label><input id="ef_kind" placeholder="望远镜/相机/双筒…"></div>
        <div class="grow"><label>备注</label><input id="ef_notes"></div>
        <div><button class="btn" onclick="addEquip()">添加</button></div>
      </div>
    </div>
    <div class="card"><h2>设备列表（${EQUIP.length}）</h2>
      ${EQUIP.length ? `<table><thead><tr><th>名称</th><th>类型</th><th>备注</th><th></th></tr></thead>
      <tbody>${rowsHtml}</tbody></table>` : '<div class="empty">还没有设备</div>'}
    </div>`;
}

async function addEquip() {
  try {
    await api.post("/api/equipment", {
      name: $("#ef_name").value.trim(), kind: $("#ef_kind").value.trim(), notes: $("#ef_notes").value.trim(),
    });
    toast("设备已添加"); renderEquipment();
  } catch (e) { showErr(e); }
}
async function delEquip(id) {
  if (!confirm("确定删除该设备？")) return;
  try { await api.del(`/api/equipment/${id}`); toast("已删除"); renderEquipment(); }
  catch (e) { showErr(e); }
}

// ---------- 观测计划 ----------
async function renderPlanner() {
  await refreshCaches();
  if (!state.sessionId && SESSIONS.length) state.sessionId = SESSIONS[0].id;
  const list = SESSIONS.map(s => `
    <div class="list-item ${s.id === state.sessionId ? "selected" : ""}" onclick="selectSession(${s.id})">
      <div><b>${esc(s.title || "未命名活动")}</b> <span class="badge status-${s.status}">${STATUS_LABEL[s.status]}</span></div>
      <div class="meta">${s.date} · ${esc(s.location || "未定地点")} · 目标 ${s.item_count} · 记录 ${s.record_count}</div>
    </div>`).join("");
  $("#tab-planner").innerHTML = `
    <div class="layout">
      <div>
        <button class="btn" style="width:100%;margin-bottom:10px" onclick="newSession()">＋ 新建观测活动</button>
        ${list || '<div class="empty">还没有观测活动</div>'}
      </div>
      <div id="session-detail"></div>
    </div>`;
  if (state.sessionId) await renderSessionDetail();
  else $("#session-detail").innerHTML = '<div class="card empty">点击左侧「新建观测活动」开始规划</div>';
}

function selectSession(id) { state.sessionId = id; renderPlanner(); }

async function newSession() {
  try {
    const today = new Date().toISOString().slice(0, 10);
    const s = await api.post("/api/sessions", { title: "观测活动", date: today, status: "planning" });
    state.sessionId = s.id;
    renderPlanner();
    toast("已创建，请完善活动信息");
  } catch (e) { showErr(e); }
}

async function renderSessionDetail() {
  const full = await api.get(`/api/sessions/${state.sessionId}/full`);
  const { session: s, items, analysis } = full;
  EQUIP = full.equipment;

  const statusOpts = Object.entries(STATUS_LABEL).map(([k, v]) =>
    `<option value="${k}" ${s.status === k ? "selected" : ""}>${v}</option>`).join("");

  const itemRows = items.map(it => {
    const rep = analysis.items[String(it.id)] || { level: "ok" };
    const eqOpts = EQUIP.map(e =>
      `<option value="${e.id}" ${it.equipment_ids.includes(e.id) ? "selected" : ""}>${esc(e.name)}</option>`).join("");
    return `<tr>
      <td class="muted">${it.position || "—"}</td>
      <td><b>${esc(it.target_name)}</b> <span class="badge type">${TYPE_LABEL[it.type] || ""}</span>
          <div class="small muted">出现 ${it.visible_start && it.visible_end ? `${it.visible_start}–${it.visible_end}` : "—"} · 高度 ${it.best_altitude ?? "—"}° · 月光${MOON_LABEL[it.moon_sensitivity] || ""}</div></td>
      <td><input type="time" id="ps_${it.id}" value="${esc(it.planned_start || "")}" onchange="saveItem(${it.id})"></td>
      <td><input type="time" id="pe_${it.id}" value="${esc(it.planned_end || "")}" onchange="saveItem(${it.id})"></td>
      <td><select multiple size="2" id="peq_${it.id}" onchange="saveItem(${it.id})">${eqOpts}</select></td>
      <td><span class="dot ${rep.level}"></span></td>
      <td><button class="btn small danger" onclick="delItem(${it.id})">删</button></td>
    </tr>`;
  }).join("");

  const targetOpts = TARGETS.map(t => `<option value="${t.id}">${esc(t.name)}</option>`).join("");

  // 检查报告
  const conflicts = analysis.conflicts.map(c => `<div class="msg ${c.type}">⚠ ${esc(c.message)}</div>`).join("");
  const itemMsgs = items.map(it => {
    const rep = analysis.items[String(it.id)];
    if (!rep || rep.level === "ok") return "";
    return rep.messages.filter(m => m.level !== "ok").map(m =>
      `<div class="msg ${m.level}">${LEVEL_ICON[m.level]} <b>${esc(it.target_name)}</b>：${esc(m.text)}</div>`).join("");
  }).join("");
  const sum = analysis.summary;
  const report = items.length ? `
    <div class="card">
      <h2>检查报告
        <span class="small muted">合适 ${sum.ok} · 注意 ${sum.warning} · 待处理 ${sum.error} · 冲突 ${sum.conflicts}</span>
      </h2>
      ${conflicts}${itemMsgs || (!conflicts ? '<div class="msg ok">🟢 计划没有发现问题</div>' : "")}
    </div>` : "";

  $("#session-detail").innerHTML = `
    <div class="card">
      <h2>活动信息
        <span style="float:right">
          <button class="btn small" onclick="saveSession(${s.id})">保存</button>
          <button class="btn small danger" onclick="delSession(${s.id})">删除活动</button>
        </span>
      </h2>
      <div class="row">
        <div class="grow"><label>标题</label><input id="sf_title" value="${esc(s.title)}"></div>
        <div><label>日期</label><input id="sf_date" type="date" value="${esc(s.date)}"></div>
        <div class="grow"><label>地点</label><input id="sf_loc" value="${esc(s.location)}"></div>
        <div><label>状态</label><select id="sf_status">${statusOpts}</select></div>
      </div>
      <div class="row" style="margin-top:8px">
        <div><label>可用时段起</label><input id="sf_ss" type="time" value="${esc(s.slot_start)}"></div>
        <div><label>可用时段止</label><input id="sf_se" type="time" value="${esc(s.slot_end)}"></div>
        <div><label>月相照明 %</label><input id="sf_moon" type="number" min="0" max="100" value="${s.moon_illumination ?? ""}" style="width:80px"></div>
        <div><label>月亮在天上（起）</label><input id="sf_ms" type="time" value="${esc(s.moon_up_start)}"></div>
        <div><label>（止）</label><input id="sf_me" type="time" value="${esc(s.moon_up_end)}"></div>
      </div>
      <h3>天气记录（用于适宜性提示）</h3>
      <div class="row">
        <div><label>透明度 1-5</label><input id="sf_tr" type="number" min="1" max="5" value="${s.transparency ?? ""}" style="width:70px"></div>
        <div><label>视宁度 1-5</label><input id="sf_see" type="number" min="1" max="5" value="${s.seeing ?? ""}" style="width:70px"></div>
        <div><label>云量 %</label><input id="sf_cloud" type="number" min="0" max="100" value="${s.cloud_cover ?? ""}" style="width:70px"></div>
        <div class="grow"><label>天气备注</label><input id="sf_wn" value="${esc(s.weather_notes)}"></div>
      </div>
    </div>

    <div class="card">
      <h2>观测顺序
        <span style="float:right"><button class="btn small" onclick="autoSchedule()">🪄 按可用时段自动排序</button></span>
      </h2>
      ${items.length ? `<table><thead><tr>
        <th>#</th><th>目标</th><th>开始</th><th>结束</th><th>使用设备（可多选）</th><th>状态</th><th></th>
      </tr></thead><tbody>${itemRows}</tbody></table>` : '<div class="empty">还没有计划目标</div>'}
      <div class="row" style="margin-top:10px">
        <div class="grow"><select id="new_item_target">${targetOpts}</select></div>
        <div><button class="btn" onclick="addItem()">＋ 添加目标</button></div>
      </div>
    </div>
    ${report}`;
}

function sessionFormBody() {
  return {
    title: $("#sf_title").value.trim(), date: $("#sf_date").value, location: $("#sf_loc").value.trim(),
    slot_start: $("#sf_ss").value, slot_end: $("#sf_se").value,
    moon_illumination: $("#sf_moon").value,
    moon_up_start: $("#sf_ms").value, moon_up_end: $("#sf_me").value,
    transparency: $("#sf_tr").value, seeing: $("#sf_see").value, cloud_cover: $("#sf_cloud").value,
    weather_notes: $("#sf_wn").value.trim(), status: $("#sf_status").value,
  };
}

async function saveSession(id) {
  try { await api.put(`/api/sessions/${id}`, sessionFormBody()); toast("活动信息已保存"); renderPlanner(); }
  catch (e) { showErr(e); }
}

async function delSession(id) {
  if (!confirm("删除该活动及其全部计划与记录？")) return;
  try {
    await api.del(`/api/sessions/${id}`);
    state.sessionId = null; renderPlanner(); toast("已删除");
  } catch (e) { showErr(e); }
}

async function addItem() {
  const tid = +$("#new_item_target").value;
  if (!tid) return;
  try {
    const t = TARGETS.find(x => x.id === tid);
    await api.post(`/api/sessions/${state.sessionId}/items`, {
      target_id: tid, equipment_ids: t ? t.equipment_needed : [],
    });
    renderSessionDetail();
  } catch (e) { showErr(e); }
}

async function saveItem(id) {
  const body = {
    planned_start: $(`#ps_${id}`).value,
    planned_end: $(`#pe_${id}`).value,
    equipment_ids: [...$(`#peq_${id}`).selectedOptions].map(o => +o.value),
  };
  try { await api.put(`/api/items/${id}`, body); renderSessionDetail(); }
  catch (e) { showErr(e); }
}

async function delItem(id) {
  try { await api.del(`/api/items/${id}`); renderSessionDetail(); }
  catch (e) { showErr(e); }
}

async function autoSchedule() {
  try {
    await api.post(`/api/sessions/${state.sessionId}/auto-schedule`);
    toast("已按出现时间自动排序");
    renderSessionDetail();
  } catch (e) { showErr(e); }
}

// ---------- 观测记录 ----------
async function renderRecordTab() {
  await refreshCaches();
  if (!state.recordSessionId && SESSIONS.length) {
    const open = SESSIONS.find(s => s.status !== "completed");
    state.recordSessionId = (open || SESSIONS[0]).id;
  }
  const opts = SESSIONS.map(s =>
    `<option value="${s.id}" ${s.id === state.recordSessionId ? "selected" : ""}>
      ${s.date} ${esc(s.title || "")}（${STATUS_LABEL[s.status]}）</option>`).join("");
  $("#tab-record").innerHTML = `
    <div class="card"><div class="row">
      <div class="grow"><label>选择观测活动</label><select id="rec_session" onchange="state.recordSessionId=+this.value;state.recordFormItem=null;renderRecordTab()">${opts}</select></div>
    </div></div>
    <div id="record-area"></div>`;
  if (state.recordSessionId) await renderRecordArea();
  else $("#record-area").innerHTML = '<div class="card empty">请先在「观测计划」中创建活动</div>';
}

async function renderRecordArea() {
  const full = await api.get(`/api/sessions/${state.recordSessionId}/full`);
  const { session: s, items, records } = full;

  const itemCards = items.map(it => {
    const n = records.filter(r => r.plan_item_id === it.id).length;
    const open = state.recordFormItem === it.id;
    return `<div class="card">
      <div class="row" style="align-items:center">
        <div class="grow"><b>${esc(it.target_name)}</b>
          <span class="badge type">${TYPE_LABEL[it.type] || ""}</span>
          <span class="small muted">计划 ${it.planned_start || "??"}–${it.planned_end || "??"}</span>
          ${n ? `<span class="badge">已有 ${n} 条记录</span>` : ""}
        </div>
        <div><button class="btn small" onclick="toggleRecordForm(${it.id})">${open ? "收起" : "✏️ 写记录"}</button></div>
      </div>
      ${open ? recordFormHtml(it) : ""}
    </div>`;
  }).join("");

  const recCards = records.map(r => recordCardHtml(r)).join("");

  $("#record-area").innerHTML = `
    <h3>计划条目 —— ${s.date} ${esc(s.title || "")}</h3>
    ${itemCards || '<div class="card empty">该活动还没有计划目标，请先在「观测计划」中添加</div>'}
    <h3>本场记录（${records.length}）</h3>
    ${recCards || '<div class="card empty">还没有观测记录</div>'}`;
}

function recordFormHtml(it) {
  const now = new Date();
  const hhmm = String(now.getHours()).padStart(2, "0") + ":" + String(now.getMinutes()).padStart(2, "0");
  return `<div style="border-top:1px solid var(--border);margin-top:10px;padding-top:10px">
    <div class="row">
      <div><label>实际开始</label><input type="time" id="rf_s" value="${esc(it.planned_start || hhmm)}">
        <button class="btn small ghost" onclick="document.querySelector('#rf_s').value='${hhmm}'">现在</button></div>
      <div><label>实际结束</label><input type="time" id="rf_e" value="${esc(it.planned_end || "")}">
        <button class="btn small ghost" onclick="document.querySelector('#rf_e').value='${hhmm}'">现在</button></div>
      <div><label>极限星等</label><input type="number" step="0.1" id="rf_mag" style="width:80px"></div>
      <div><label>透明度 1-5</label><input type="number" min="1" max="5" id="rf_tr" style="width:70px"></div>
      <div><label>视宁度 1-5</label><input type="number" min="1" max="5" id="rf_see" style="width:70px"></div>
    </div>
    <div class="row" style="margin-top:8px">
      <div><label>滤镜</label><input id="rf_filter" placeholder="如 UHC / OIII / 无" style="width:150px"></div>
      <div><label>ISO</label><input id="rf_iso" type="number" style="width:80px"></div>
      <div><label>单张曝光</label><input id="rf_sh" placeholder="如 30s" style="width:80px"></div>
      <div><label>帧数</label><input id="rf_fr" type="number" style="width:70px"></div>
      <div><label>增益</label><input id="rf_gain" type="number" style="width:70px"></div>
    </div>
    <div style="margin-top:8px"><label>文字感受</label>
      <textarea id="rf_imp" placeholder="看到了什么？细节、颜色、对比度、突发情况……"></textarea></div>
    <div style="margin-top:8px">
      <button class="btn" onclick="saveRecord(${it.id}, ${it.target_id})">保存记录</button>
      <span class="small muted"> 照片可在保存后作为附件添加到记录卡片上</span>
    </div>
  </div>`;
}

function toggleRecordForm(itemId) {
  state.recordFormItem = state.recordFormItem === itemId ? null : itemId;
  renderRecordArea();
}

async function saveRecord(itemId, targetId) {
  const body = {
    session_id: state.recordSessionId, target_id: targetId, plan_item_id: itemId,
    actual_start: $("#rf_s").value, actual_end: $("#rf_e").value,
    limiting_magnitude: $("#rf_mag").value,
    transparency: $("#rf_tr").value, seeing: $("#rf_see").value,
    filters: $("#rf_filter").value.trim(),
    exposure: {
      iso: $("#rf_iso").value, shutter: $("#rf_sh").value.trim(),
      frames: $("#rf_fr").value, gain: $("#rf_gain").value,
    },
    impressions: $("#rf_imp").value.trim(),
  };
  try {
    await api.post("/api/records", body);
    state.recordFormItem = null;
    toast("记录已保存");
    renderRecordArea();
  } catch (e) { showErr(e); }
}

function recordCardHtml(r) {
  const photos = (r.photos || []).map(p => `
    <span class="ph">
      <a href="/uploads/${esc(p.filename)}" target="_blank"><img src="/uploads/${esc(p.filename)}" alt=""></a>
      <button class="del" title="删除照片" onclick="delPhoto(${p.id})">×</button>
    </span>`).join("");
  const expo = fmtExposure(r.exposure);
  return `<div class="card">
    <div class="row" style="align-items:center">
      <div class="grow"><b>${esc(r.target_name)}</b>
        <span class="small muted">${r.actual_start || "??"}–${r.actual_end || "??"}</span></div>
      <div>
        <label class="small" style="display:inline-block;margin-right:6px">📷 添加照片（可选）
          <input type="file" accept="image/*" style="display:inline;width:auto" onchange="uploadPhoto(${r.id}, this)"></label>
        <button class="btn small danger" onclick="delRecord(${r.id})">删除</button>
      </div>
    </div>
    <div class="small" style="margin-top:4px">
      ${condText(r) ? `<div>👁 ${esc(condText(r))}</div>` : ""}
      ${r.filters ? `<div>🔻 滤镜：${esc(r.filters)}</div>` : ""}
      ${expo ? `<div>📸 曝光：${esc(expo)}</div>` : ""}
      ${r.impressions ? `<div style="margin-top:4px">💬 ${esc(r.impressions)}</div>` : ""}
    </div>
    ${photos ? `<div class="photos">${photos}</div>` : ""}
  </div>`;
}

async function uploadPhoto(recordId, input) {
  const file = input.files[0];
  if (!file) return;
  try {
    const r = await fetch(`/api/records/${recordId}/photos?name=${encodeURIComponent(file.name)}`, {
      method: "POST", headers: { "Content-Type": file.type || "application/octet-stream" }, body: file,
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || "上传失败");
    toast("照片已添加");
    state.tab === "record" ? renderRecordArea() : openLogTarget(state.logTargetId);
  } catch (e) { showErr(e); }
}

async function delPhoto(pid) {
  try {
    await api.del(`/api/photos/${pid}`);
    toast("照片已删除");
    state.tab === "record" ? renderRecordArea() : openLogTarget(state.logTargetId);
  } catch (e) { showErr(e); }
}

async function delRecord(id) {
  if (!confirm("删除这条观测记录？")) return;
  try { await api.del(`/api/records/${id}`); toast("已删除"); renderRecordArea(); }
  catch (e) { showErr(e); }
}

// ---------- 观测日志 ----------
async function renderLogbook() {
  const book = await api.get("/api/logbook");
  const cards = book.map(b => `
    <div class="list-item ${b.target_id === state.logTargetId ? "selected" : ""}" onclick="openLogTarget(${b.target_id})">
      <b>${esc(b.name)}</b> <span class="badge type">${TYPE_LABEL[b.type] || ""}</span>
      <div class="meta">${b.record_count} 条记录 · 最近 ${b.last_date}</div>
    </div>`).join("");
  $("#tab-logbook").innerHTML = `
    <div class="layout">
      <div><h2>按目标整理</h2>${cards || '<div class="empty">还没有任何观测记录</div>'}</div>
      <div id="log-detail"><div class="card empty">选择左侧目标，查看并比较不同日期的记录</div></div>
    </div>`;
  if (state.logTargetId) openLogTarget(state.logTargetId);
}

async function openLogTarget(tid) {
  state.logTargetId = tid;
  $$("#tab-logbook .list-item").forEach(el => el.classList.remove("selected"));
  const data = await api.get(`/api/targets/${tid}/log`);
  const { target, records } = data;

  // 对比表：字段为行，每次观测为列
  const cols = records.map(r => `<th>${r.session_date}<div class="small muted">${esc(r.session_title || "")}</div></th>`).join("");
  const row = (label, fn) => `<tr><td>${label}</td>${records.map(r => `<td>${fn(r) || "—"}</td>`).join("")}</tr>`;
  const compare = records.length ? `
    <div class="compare-wrap"><table class="compare">
      <thead><tr><th>对比项</th>${cols}</tr></thead>
      <tbody>
        ${row("实际时段", r => `${r.actual_start || "??"}–${r.actual_end || "??"}`)}
        ${row("目视条件", r => esc(condText(r)))}
        ${row("滤镜", r => esc(r.filters))}
        ${row("曝光参数", r => esc(fmtExposure(r.exposure)))}
        ${row("文字感受", r => esc(r.impressions))}
        ${row("照片", r => (r.photos || []).map(p =>
          `<a href="/uploads/${esc(p.filename)}" target="_blank"><img src="/uploads/${esc(p.filename)}" style="width:60px;height:60px;object-fit:cover;border-radius:4px;margin:2px"></a>`).join(""))}
      </tbody>
    </table></div>` : '<div class="empty">该目标还没有记录</div>';

  const cards = [...records].reverse().map(r => `
    <div class="card">
      <b>${r.session_date}</b> <span class="muted small">${esc(r.session_title || "")} · ${esc(r.location || "")}</span>
      <div class="small" style="margin-top:4px">
        <div>🕐 ${r.actual_start || "??"}–${r.actual_end || "??"}　${esc(condText(r))}</div>
        ${r.filters ? `<div>🔻 滤镜：${esc(r.filters)}</div>` : ""}
        ${fmtExposure(r.exposure) ? `<div>📸 ${esc(fmtExposure(r.exposure))}</div>` : ""}
        ${r.impressions ? `<div style="margin-top:4px">💬 ${esc(r.impressions)}</div>` : ""}
      </div>
      ${(r.photos || []).length ? `<div class="photos">${r.photos.map(p => `
        <span class="ph"><a href="/uploads/${esc(p.filename)}" target="_blank"><img src="/uploads/${esc(p.filename)}"></a>
        <button class="del" onclick="delPhoto(${p.id})">×</button></span>`).join("")}</div>` : ""}
    </div>`).join("");

  $("#log-detail").innerHTML = `
    <div class="card">
      <h2>${esc(target.name)} <span class="badge type">${TYPE_LABEL[target.type] || ""}</span></h2>
      <div class="small muted">${esc(target.description || "")}</div>
    </div>
    <div class="card"><h2>不同日期对比（${records.length} 次记录）</h2>${compare}</div>
    ${cards}`;
}

// ---------- 启动 ----------
$$("#tabs button").forEach(b => b.addEventListener("click", () => switchTab(b.dataset.tab)));
renderPlanner();
