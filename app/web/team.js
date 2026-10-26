/* 运营部团队版:登录门禁、顶栏用户信息、运营看板、用户管理。纯原生 JS + SVG,无新依赖。 */
(function () {
  "use strict";
  const ROLE_LABEL = { admin: "管理员", manager: "部门主管", operator: "运营", viewer: "只读观察者" };
  const PF = { douyin: "抖音", xhs: "小红书", kuaishou: "快手", shipinhao: "视频号" };
  const ST = { active: "正常", invalid: "失效", unknown: "未知" };
  const TABS = {
    admin: null,
    manager: ["team-dashboard", "overview", "accounts", "hub", "queue", "risk-control"],
    operator: ["team-dashboard", "accounts", "hub"],
    viewer: ["team-dashboard"],
  };
  const esc = v => String(v == null ? "" : v).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = v => Number(v || 0).toLocaleString("zh-CN");
  const fmtTime = iso => {
    if (!iso) return "从未同步";
    const d = new Date(iso);
    return d.toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false, month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) + "（北京时间）";
  };
  async function j(path, opts) {
    const r = await fetch(path, { credentials: "same-origin", ...(opts || {}), headers: { "content-type": "application/json", ...((opts || {}).headers || {}) } });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) { const e = new Error(typeof body.detail === "string" ? body.detail : "请求失败（" + r.status + "）"); e.status = r.status; throw e; }
    return body;
  }

  let USER = null;
  const state = { days: 7, data: null, f: { owner: "", tag: "", platform: "", status: "" } };

  // ───── 登录门禁 ─────
  function loginView(msg) {
    document.body.classList.add("team-locked");
    let box = document.getElementById("team-login");
    if (!box) { box = document.createElement("div"); box.id = "team-login"; document.body.appendChild(box); }
    box.innerHTML = `
      <form class="team-login-card" autocomplete="on">
        <div class="team-login-brand">CreatorHub <span>运营部</span></div>
        <h2>登录团队工作台</h2>
        <p class="team-mut">请使用管理员分配的账号登录。本系统仅限内网使用。</p>
        <label>用户名<input name="username" autocomplete="username" required maxlength="32"></label>
        <label>密码<input name="password" type="password" autocomplete="current-password" required></label>
        <div class="team-err" role="alert">${esc(msg || "")}</div>
        <button type="submit" class="team-btn primary">登录</button>
        <p class="team-mut small">忘记密码请联系管理员重置。</p>
      </form>`;
    box.querySelector("form").addEventListener("submit", async ev => {
      ev.preventDefault();
      const fd = new FormData(ev.target), btn = ev.target.querySelector("button");
      btn.disabled = true; btn.textContent = "登录中…";
      try {
        await j("/api/auth/login", { method: "POST", body: JSON.stringify({ username: fd.get("username"), password: fd.get("password") }) });
        location.hash = "#team-dashboard";
        location.reload();
      } catch (e) {
        box.querySelector(".team-err").textContent = e.message;
        btn.disabled = false; btn.textContent = "登录";
      }
    });
    box.querySelector("input[name=username]").focus();
  }

  function loadApp() {
    document.querySelectorAll('script[type="text/x-team-deferred"]').forEach(old => {
      const s = document.createElement("script");
      s.src = old.dataset.src; s.async = false;
      document.body.appendChild(s);
    });
  }

  function applyRole() {
    const allowed = TABS[USER.role];
    document.body.dataset.teamRole = USER.role;
    document.querySelectorAll(".navitem[data-tab]").forEach(b => {
      const tab = b.dataset.tab;
      const ok = tab === "team-users" ? USER.role === "admin" : (!allowed || allowed.includes(tab));
      b.hidden = !ok;
    });
    document.querySelectorAll(".nav .nav-sep").forEach(sep => {
      let n = sep.nextElementSibling, any = false;
      while (n && !n.classList.contains("nav-sep")) { if (!n.hidden) any = true; n = n.nextElementSibling; }
      sep.hidden = !any;
    });
    const box = document.getElementById("team-user");
    box.hidden = false;
    box.innerHTML = `<span class="team-avatar">${esc((USER.display_name || USER.username).slice(0, 1))}</span>
      <span class="team-who"><b>${esc(USER.display_name || USER.username)}</b><small>${esc(ROLE_LABEL[USER.role] || USER.role)}${USER.role === "operator" ? " · 归属人 " + esc(USER.owner_name || "未设置") : ""}</small></span>
      <button type="button" class="team-btn ghost" id="team-logout">退出</button>`;
    document.getElementById("team-logout").onclick = async () => {
      try { await j("/api/auth/logout", { method: "POST" }); } catch (e) {}
      location.hash = ""; location.reload();
    };
  }

  // ───── 运营看板 ─────
  function card(label, value, sub, tone) {
    return `<div class="team-kpi ${tone || ""}"><span>${esc(label)}</span><b>${value}</b>${sub ? `<small>${sub}</small>` : ""}</div>`;
  }
  function trendSvg(days, values) {
    const W = 640, H = 200, P = 28, max = Math.max(1, ...values);
    const step = (W - P * 2) / Math.max(1, values.length - 1);
    const pts = values.map((v, i) => [P + i * step, H - P - (v / max) * (H - P * 2)]);
    const line = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
    const area = line + ` L${pts[pts.length - 1][0].toFixed(1)} ${H - P} L${P} ${H - P} Z`;
    const every = values.length > 10 ? 5 : 1;
    const labels = days.map((d, i) => (i % every === 0 || i === days.length - 1) ? `<text x="${pts[i][0]}" y="${H - 8}" text-anchor="middle">${d.slice(5)}</text>` : "").join("");
    const dots = pts.map((p, i) => `<circle cx="${p[0]}" cy="${p[1]}" r="3"><title>${days[i]}：${values[i]} 条</title></circle>`).join("");
    return `<svg viewBox="0 0 ${W} ${H}" class="team-trend" role="img" aria-label="新增作品趋势">
      <line x1="${P}" x2="${W - P}" y1="${H - P}" y2="${H - P}" class="axis"/>
      <text x="${P}" y="14" class="ymax">最高 ${max} 条/天</text>
      <path d="${area}" class="area"/><path d="${line}" class="line"/>${dots}${labels}</svg>`;
  }
  function bars(items, key, labelFn) {
    const max = Math.max(1, ...items.map(i => i[key]));
    return items.map(i => `<div class="team-bar"><span class="lbl">${esc(labelFn(i))}</span><span class="track"><i style="width:${(i[key] / max * 100).toFixed(1)}%"></i></span><b>${num(i[key])}</b></div>`).join("");
  }
  function empty(text) { return `<div class="team-empty">${esc(text)}</div>`; }

  function renderDashboard() {
    const root = document.getElementById("team-dashboard-root");
    const d = state.data;
    if (!d) { root.innerHTML = empty("正在加载看板数据…"); return; }
    const c = d.cards, viewer = USER.role === "viewer";
    const f = state.f;
    const owners = [...new Set(d.accounts.map(a => a.owner))].sort();
    const tags = [...new Set(d.accounts.flatMap(a => a.tags))].sort();
    const pfs = [...new Set(d.accounts.map(a => a.platform))];
    const sts = [...new Set(d.accounts.map(a => a.status || "unknown"))];
    const rows = d.accounts.filter(a => (!f.owner || a.owner === f.owner) && (!f.tag || a.tags.includes(f.tag)) && (!f.platform || a.platform === f.platform) && (!f.status || (a.status || "unknown") === f.status));
    const sel = (name, label, opts, fmt) => `<label class="team-filter">${label}<select data-f="${name}"><option value="">全部</option>${opts.map(o => `<option value="${esc(o)}" ${f[name] === o ? "selected" : ""}>${esc(fmt ? fmt(o) : o)}</option>`).join("")}</select></label>`;
    const scopeNote = d.scope === "own" ? `只显示归属人为「${esc(USER.owner_name || "未设置")}」的账号` : "显示团队全部账号";
    root.innerHTML = `
      <div class="team-head">
        <div><span class="team-scope">${scopeNote}</span>
          <span class="team-sync ${d.stale ? "stale" : ""}">最近同步：${fmtTime(d.last_synced)}${d.stale ? " · 已超过 24 小时，数据可能过期" : ""}</span></div>
        <button type="button" class="team-btn ghost" id="team-refresh">刷新</button>
      </div>
      <div class="team-kpis">
        ${card("账号总数", num(c.accounts))}
        ${card("正常账号", num(c.active_accounts), c.accounts ? `占 ${Math.round(c.active_accounts / c.accounts * 100)}%` : "")}
        ${card("作品总数", num(c.works), "来自「同步作品」")}
        ${card("粉丝合计", num(c.followers))}
        ${card("未读私信", num(c.unread_dm), "", c.unread_dm ? "warn" : "")}
        ${card("待处理 / 失败任务", `${num(c.tasks)} <em>/ ${num(c.failed_tasks)}</em>`, "", c.failed_tasks ? "bad" : "")}
      </div>
      ${!d.accounts.length ? empty(d.scope === "own" ? "你名下还没有账号。请让管理员在「平台账号」里把账号的归属人设为你。" : "还没有任何账号。管理员可在「平台账号」里扫码授权添加。") : `
      <div class="team-grid">
        <div class="team-card wide">
          <div class="team-card-h"><h3>按归属人对比</h3><small>按作品数排序</small></div>
          <div class="team-table-wrap"><table class="team-table"><thead><tr><th>归属人</th><th>账号数</th><th>正常</th><th>作品数</th><th>粉丝</th><th>未读私信</th><th>任务（失败）</th><th>作品占比</th></tr></thead><tbody>
          ${d.owners.map(g => `<tr><td><b>${esc(g.owner)}</b></td><td>${num(g.accounts)}</td><td>${num(g.active_accounts)}</td><td>${num(g.works)}</td><td>${num(g.followers)}</td><td>${num(g.unread_dm)}</td><td>${num(g.tasks)}${g.failed_tasks ? ` <span class="bad">(${g.failed_tasks})</span>` : ""}</td><td class="pct"><span class="track"><i style="width:${c.works ? (g.works / c.works * 100).toFixed(1) : 0}%"></i></span></td></tr>`).join("")}
          </tbody></table></div>
        </div>
        <div class="team-card">
          <div class="team-card-h"><h3>新增作品趋势</h3>
            <div class="team-seg">${[7, 30].map(n => `<button type="button" data-days="${n}" class="${state.days === n ? "on" : ""}">近 ${n} 天</button>`).join("")}</div></div>
          ${d.trend.works.some(Boolean) ? trendSvg(d.trend.days, d.trend.works) : empty(`近 ${state.days} 天没有新发布的作品（或还没同步作品）`)}
          <small class="team-mut">口径：已同步作品的发布时间，只统计你可见的账号。</small>
        </div>
        <div class="team-card">
          <div class="team-card-h"><h3>平台分布</h3></div>
          ${bars(d.platforms, "accounts", i => PF[i.platform] || i.platform)}
          <div class="team-card-h" style="margin-top:14px"><h3>账号状态</h3></div>
          ${bars(Object.entries(d.statuses).map(([k, v]) => ({ k, v })), "v", i => ST[i.k] || i.k)}
        </div>
        <div class="team-card wide">
          <div class="team-card-h"><h3>账号状态列表</h3><small>${rows.length} / ${d.accounts.length} 个</small></div>
          <div class="team-filters">
            ${sel("owner", "归属人", owners)}${sel("tag", "标签", tags)}${sel("platform", "平台", pfs, p => PF[p] || p)}${sel("status", "状态", sts, s => ST[s] || s)}
          </div>
          ${rows.length ? `<div class="team-table-wrap"><table class="team-table"><thead><tr><th>账号</th><th>平台</th><th>归属人</th><th>标签</th><th>状态</th><th>粉丝</th><th>作品</th>${viewer ? "" : "<th>未读私信</th>"}<th>任务</th><th>最近同步</th></tr></thead><tbody>
          ${rows.map(a => `<tr><td><b>${esc(a.nickname || "（未命名）")}</b><small class="team-mut"> #${a.id}</small></td><td>${esc(PF[a.platform] || a.platform)}</td><td>${esc(a.owner)}</td><td>${a.tags.map(t => `<span class="team-tag">${esc(t)}</span>`).join("") || '<span class="team-mut">—</span>'}</td><td><span class="team-st ${a.status === "active" ? "ok" : "bad"}">${esc(ST[a.status] || a.status || "未知")}</span></td><td>${num(a.follower_count)}</td><td>${num(a.works)}</td>${viewer ? "" : `<td>${num(a.unread_dm)}</td>`}<td>${num(a.tasks.total)}${a.tasks.failed ? ` <span class="bad">(${a.tasks.failed} 失败)</span>` : ""}</td><td class="${a.stale ? "stale" : ""}">${fmtTime(a.last_synced)}</td></tr>`).join("")}
          </tbody></table></div>` : empty("没有符合筛选条件的账号")}
        </div>
      </div>`}`;
    root.querySelector("#team-refresh").onclick = () => loadDashboard();
    root.querySelectorAll("[data-days]").forEach(b => b.onclick = () => { state.days = Number(b.dataset.days); loadDashboard(); });
    root.querySelectorAll("select[data-f]").forEach(s => s.onchange = () => { state.f[s.dataset.f] = s.value; renderDashboard(); });
  }
  async function loadDashboard() {
    try { state.data = await j("/api/dashboard?days=" + state.days); renderDashboard(); }
    catch (e) { document.getElementById("team-dashboard-root").innerHTML = empty("看板加载失败：" + e.message); }
  }

  // ───── 用户管理 ─────
  async function loadUsers() {
    const root = document.getElementById("team-users-root");
    if (USER.role !== "admin") { root.innerHTML = empty("只有管理员可以管理用户"); return; }
    let d;
    try { d = await j("/api/auth/users"); } catch (e) { root.innerHTML = empty("加载失败：" + e.message); return; }
    const roleSel = (cur, id) => `<select data-role="${id}">${Object.entries(d.roles).map(([k, v]) => `<option value="${k}" ${k === cur ? "selected" : ""}>${esc(v)}</option>`).join("")}</select>`;
    root.innerHTML = `
      <div class="team-grid">
        <div class="team-card wide">
          <div class="team-card-h"><h3>团队成员</h3><small>${d.users.length} 人</small></div>
          <div class="team-table-wrap"><table class="team-table"><thead><tr><th>用户名</th><th>显示名</th><th>角色</th><th>归属人（运营看哪些号）</th><th>状态</th><th>最近登录</th><th>操作</th></tr></thead><tbody>
          ${d.users.map(u => `<tr data-id="${u.id}"><td><b>${esc(u.username)}</b>${u.id === USER.id ? ' <span class="team-tag">我</span>' : ""}</td><td>${esc(u.display_name)}</td><td>${roleSel(u.role, u.id)}</td>
            <td><input data-owner="${u.id}" value="${esc(u.owner_name)}" list="team-owner-list" placeholder="未设置" maxlength="40"></td>
            <td><span class="team-st ${u.is_active ? "ok" : "bad"}">${u.is_active ? "启用" : "已停用"}</span></td><td>${u.last_login_at ? fmtTime(u.last_login_at) : '<span class="team-mut">从未登录</span>'}</td>
            <td class="ops"><button type="button" class="team-btn ghost" data-act="save">保存</button><button type="button" class="team-btn ghost" data-act="pw">重置密码</button><button type="button" class="team-btn ghost" data-act="toggle">${u.is_active ? "停用" : "启用"}</button><button type="button" class="team-btn ghost danger" data-act="del">删除</button></td></tr>`).join("")}
          </tbody></table></div>
          <datalist id="team-owner-list">${d.owners.map(o => `<option value="${esc(o)}">`).join("")}</datalist>
          <p class="team-mut small">运营只能看到「账号归属人」等于他这里填的归属人的账号；主管和管理员看全部；只读观察者只看汇总数据。</p>
        </div>
        <div class="team-card">
          <div class="team-card-h"><h3>新增成员</h3></div>
          <form id="team-new-user" class="team-form" autocomplete="off">
            <label>用户名<input name="username" required maxlength="32" placeholder="字母/数字，如 lifl"></label>
            <label>显示名<input name="display_name" maxlength="40" placeholder="如 李枫林"></label>
            <label>角色${roleSel("operator", "new")}</label>
            <label>归属人<input name="owner_name" list="team-owner-list" maxlength="40" placeholder="默认同显示名"></label>
            <label>初始密码<input name="password" type="password" autocomplete="new-password" minlength="8" required placeholder="至少 8 位"></label>
            <div class="team-err" role="alert"></div>
            <button class="team-btn primary" type="submit">创建</button>
          </form>
        </div>
      </div>`;
    const toast = (m, ok) => { const t = window.toast; if (typeof t === "function") t(m, ok ? "ok" : "err"); else alert(m); };
    root.querySelector("#team-new-user").onsubmit = async ev => {
      ev.preventDefault();
      const fd = new FormData(ev.target);
      const body = { username: fd.get("username"), display_name: fd.get("display_name"), password: fd.get("password"), role: ev.target.querySelector("select").value };
      if (fd.get("owner_name")) body.owner_name = fd.get("owner_name");
      try { await j("/api/auth/users", { method: "POST", body: JSON.stringify(body) }); toast("已创建成员", true); loadUsers(); }
      catch (e) { ev.target.querySelector(".team-err").textContent = e.message; }
    };
    root.querySelectorAll("tr[data-id]").forEach(tr => {
      const id = Number(tr.dataset.id), u = d.users.find(x => x.id === id);
      const patch = async body => { try { await j("/api/auth/users/" + id, { method: "PATCH", body: JSON.stringify(body) }); toast("已保存", true); loadUsers(); } catch (e) { toast(e.message); } };
      tr.querySelector('[data-act="save"]').onclick = () => patch({ role: tr.querySelector("select").value, owner_name: tr.querySelector("input").value });
      tr.querySelector('[data-act="toggle"]').onclick = () => patch({ is_active: !u.is_active });
      tr.querySelector('[data-act="pw"]').onclick = () => { const p = prompt(`为 ${u.username} 设置新密码（至少 8 位）：`); if (p) patch({ password: p }); };
      tr.querySelector('[data-act="del"]').onclick = async () => {
        if (!confirm(`确定删除成员 ${u.username}？此操作不可撤销。`)) return;
        try { await j("/api/auth/users/" + id, { method: "DELETE" }); toast("已删除", true); loadUsers(); } catch (e) { toast(e.message); }
      };
    });
  }

  window.TeamUI = {
    allowTab(name) {
      if (!USER) return true;
      if (name === "team-users") return USER.role === "admin";
      const a = TABS[USER.role]; return !a || a.includes(name);
    },
    render(name) { if (name === "team-dashboard") loadDashboard(); else if (name === "team-users") loadUsers(); },
    sessionExpired() { if (!document.getElementById("team-login")) loginView("登录已过期，请重新登录"); },
  };

  // 启动:先确认登录,再加载主工作台脚本
  fetch("/api/auth/me", { credentials: "same-origin" }).then(async r => {
    if (!r.ok) { loginView(""); return; }
    USER = (await r.json()).user;
    window.TEAM_USER = USER;
    applyRole();
    loadApp();
  }).catch(() => loginView("无法连接服务，请确认 CreatorHub 已启动"));
})();
