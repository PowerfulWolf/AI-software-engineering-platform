"use strict";
let snapshot = null;
let page = "team";
let selected = null;
let refreshing = false;
const labels = {
  NEW: "待启动",
  PREPARING: "准备项目",
  READY_FOR_DISCUSSION: "等待讨论需求",
  PRODUCT_DISCOVERY: "产品梳理",
  WAITING_PRODUCT_REPLY: "等待补充需求",
  WAITING_PRODUCT_APPROVAL: "等待产品批准",
  DESIGNING: "技术设计",
  PLANNING: "计划编排",
  DISPATCHING: "分配成员",
  DELIVERING: "分仓交付",
  INTEGRATING: "联合验收",
  IMPLEMENTING: "实现中",
  CONTINUE_REQUIRED: "等待继续实现",
  QUEUED: "已重新排队",
  QA: "测试中",
  REVIEW: "评审中",
  DONE: "已完成",
  BLOCKED: "已阻塞",
  FAILED: "失败",
  WAITING_HUMAN: "等待人工",
  coder: "实现",
  qa: "测试",
  reviewer: "评审",
  orchestrator: "任务编排",
  SUCCEEDED: "执行成功",
  INVALID: "输出无效",
  TIMED_OUT: "执行超时",
  UNKNOWN: "未确认",
};
const label = (value) => labels[value] || value;
const roleOrder = { coder: 0, qa: 1, reviewer: 2 };
const el = (tag, text, className) => {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (className) n.className = className;
  return n;
};
const button = (text, action, className = "link") => {
  const n = el("button", text, className);
  n.addEventListener("click", action);
  return n;
};
const time = (value) =>
  value ? new Date(value).toLocaleString() : "暂无活动记录";
const badge = (status) =>
  el(
    "span",
    label(status),
    "badge " +
      (status === "DONE"
        ? "done"
        : status.includes("WAITING") || ["BLOCKED", "FAILED"].includes(status)
          ? "blocked"
          : "current"),
  );
function assignmentBadge(task, assignment) {
  if (task.terminal) return badge(task.status);
  if (assignment.current_stage) return badge(task.status);
  const current = task.assignments.find((candidate) => candidate.current_stage);
  if (!current)
    return el("span", "已分配 · 等待调度", "badge");
  const assignedOrder = roleOrder[assignment.role];
  const currentOrder = roleOrder[current.role];
  if (assignedOrder !== undefined && currentOrder !== undefined) {
    if (assignedOrder < currentOrder)
      return el("span", "本轮已完成", "badge done");
    if (assignedOrder > currentOrder)
      return el("span", `等待${label(assignment.role)}阶段`, "badge");
  }
  return el("span", "已分配 · 非当前阶段", "badge");
}
const taskById = (id) => snapshot.tasks.find((t) => t.id === id);
const requestById = (id) => snapshot.requests.find((r) => r.id === id);
function paths(scope) {
  return scope.selected_paths
    .map((p) => (p === "." ? scope.root : scope.root + "/" + p))
    .join("\n");
}
function documentList(parent, documents) {
  if (!documents.length) {
    parent.append(el("p", "暂无已提交产物。", "muted"));
    return;
  }
  for (const doc of documents) {
    const d = el("details");
    d.dataset.key = doc.source_uri;
    d.append(
      el("summary", doc.name),
      el("p", doc.source_uri, "paths"),
      el("p", "SHA-256 · " + doc.sha256, "paths"),
    );
    d.append(
      el(
        "pre",
        doc.content || "当前提供已提交文档的身份引用；正文尚未接入此视图。",
      ),
    );
    parent.append(d);
  }
}
function taskRow(task, agentId) {
  const n = el("div", undefined, "work-row");
  const row = el("div", undefined, "row");
  const request = requestById(task.request_id);
  row.append(
    button(request ? request.title : task.title, () =>
      showDetail("task", task.id),
    ),
  );
  const a = task.assignments.find((a) => a.agent_id === agentId);
  row.append(a ? assignmentBadge(task, a) : badge(task.status));
  n.append(row);
  n.append(el("p", paths(task.scope), "paths"));
  if (a)
    n.append(
      el(
        "div",
        `${label(a.role)} · ${a.current_stage ? "当前交付阶段" : "已分配"} · 分配模型 ${a.planned_provider} / ${a.planned_model}`,
        "muted",
      ),
    );
  n.append(el("div", "最近活动 " + time(task.last_activity), "muted"));
  if (task.blocker) n.append(el("div", task.blocker, "blocker"));
  return n;
}
function renderTeam(content) {
  const summary = el("div", undefined, "summary");
  for (const [count, title] of [
    [snapshot.agents.length, "位组织成员"],
    [snapshot.tasks.filter((t) => !t.terminal).length, "项未结束任务"],
    [snapshot.requests.filter((r) => r.blocker).length, "项需求待处理"],
  ]) {
    const n = el("span");
    n.append(el("strong", String(count)), document.createTextNode(title));
    summary.append(n);
  }
  content.append(summary);
  if (!snapshot.agents.length)
    content.append(
      el(
        "div",
        "尚无已登记成员。生产交付分配后会显示真实成员，不创建演示 Agent。",
        "empty",
      ),
    );
  for (const agent of snapshot.agents) {
    const card = el("article", undefined, "agent"),
      head = el("div", undefined, "row"),
      identity = el("div", undefined, "identity"),
      name = el("div");
    name.append(
      el("h2", agent.name),
      el("div", agent.roles.map(label).join(" / "), "muted"),
    );
    identity.append(el("div", agent.name.slice(0, 1), "avatar"), name);
    head.append(
      identity,
      el("span", agent.enabled ? "已启用 · 运行状态未确认" : "已停用", "badge"),
    );
    card.append(head);
    card.append(
      el(
        "div",
        `${agent.current_stage_delivery_ids.length} 项处于当前岗位阶段 · ${agent.assigned_delivery_ids.length} 项未结束分配 · 并发上限 ${agent.max_parallel_assignments}（组织配置，非实时占用）`,
        "muted",
      ),
    );
    const work = el("div", undefined, "work");
    for (const id of agent.assigned_delivery_ids) {
      const t = taskById(id);
      if (t) work.append(taskRow(t, agent.id));
    }
    if (!agent.assigned_delivery_ids.length)
      work.append(el("p", "当前公司没有未结束的任务分配。", "muted"));
    card.append(work);
    const history = el("details");
    history.dataset.key = agent.id;
    history.append(
      el("summary", `历史任务 · ${agent.history_delivery_ids.length}`),
    );
    for (const id of agent.history_delivery_ids) {
      const t = taskById(id);
      if (t) history.append(taskRow(t, agent.id));
    }
    card.append(history);
    content.append(card);
  }
  content.append(
    el(
      "p",
      "成员属于组织；这里的工作记录只统计当前公司。产品、设计、规划阶段可在需求中查看，尚未登记为独立 AgentProfile 的岗位不会虚构成员或在线状态。",
      "muted",
    ),
  );
}
function renderRequests(content) {
  if (!snapshot.requests.length) {
    const n = el("div", undefined, "empty");
    n.append(
      el("p", "还没有需求。先准备涉及的代码目录，再讨论需求。"),
      el(
        "code",
        'ase request create /absolute/backend /absolute/frontend --name "需求名称"',
      ),
    );
    content.append(n);
  }
  for (const request of snapshot.requests) {
    const card = el("article", undefined, "request"),
      head = el("div", undefined, "row");
    head.append(
      button(request.title, () => showDetail("request", request.id)),
      badge(request.stage),
    );
    card.append(head);
    const write = request.scopes.filter((s) => !s.reference_only),
      done = write.filter(
        (s) => taskById(s.delivery_id)?.status === "DONE",
      ).length;
    card.append(
      el(
        "p",
        `${request.scopes.length} 个代码目录范围 · ${done}/${write.length} 个改造仓库任务完成 · 联合需求以整体验收为准`,
        "muted",
      ),
    );
    for (const scope of request.scopes) {
      card.append(el("p", paths(scope), "paths"));
      const task = taskById(scope.delivery_id);
      card.append(
        el(
          "span",
          scope.reference_only
            ? "只读参考"
            : task
              ? label(task.status)
              : "尚未生成交付任务",
          "badge",
        ),
      );
    }
    if (request.blocker) card.append(el("div", request.blocker, "blocker"));
    content.append(card);
  }
}
function showDetail(kind, id) {
  selected = { kind, id };
  renderDetail();
  document
    .getElementById("detail")
    .scrollIntoView({ behavior: "smooth", block: "start" });
}
function renderDetail() {
  const panel = document.getElementById("detail");
  panel.replaceChildren();
  panel.hidden = !selected;
  if (!selected) return;
  const item =
    selected.kind === "task" ? taskById(selected.id) : requestById(selected.id);
  if (!item) {
    panel.append(el("p", "当前快照中找不到这条记录。"));
    return;
  }
  const top = el("div", undefined, "row");
  top.append(
    el("h2", selected.kind === "task" ? "任务详情" : "需求详情"),
    button(
      "关闭",
      () => {
        selected = null;
        renderDetail();
      },
      "",
    ),
  );
  panel.append(
    top,
    el("h3", item.title),
    el("p", item.id, "paths"),
    badge(item.status || item.stage),
  );
  if (item.blocker) panel.append(el("div", item.blocker, "blocker"));
  panel.append(el("p", "下一步 · " + item.next_action, "muted"));
  if (selected.kind === "request") {
    for (const scope of item.scopes) {
      panel.append(el("p", paths(scope), "paths"));
      const task = taskById(scope.delivery_id);
      if (task)
        panel.append(
          button("查看仓库任务 · " + label(task.status), () =>
            showDetail("task", task.id),
          ),
        );
    }
    panel.append(el("h2", "阶段产物"));
    documentList(panel, item.documents);
    return;
  }
  panel.append(
    el("p", paths(item.scope), "paths"),
    el("p", "最近活动 · " + time(item.last_activity), "muted"),
  );
  if (item.candidate_revision)
    panel.append(el("p", "候选版本 · " + item.candidate_revision, "paths"));
  panel.append(el("h2", "成员与分配模型"));
  for (const a of item.assignments)
    panel.append(
      el(
        "p",
        `${snapshot.agents.find((x) => x.id === a.agent_id)?.name || a.agent_id} · ${label(a.role)} · ${a.planned_provider} / ${a.planned_model}${a.current_stage ? " · 当前阶段" : ""}`,
      ),
    );
  panel.append(el("h2", "执行与阶段时间线"));
  const list = el("ol");
  for (const entry of item.timeline) {
    const li = el("li");
    li.append(
      el("div", entry.summary),
      el("div", time(entry.occurred_at), "muted"),
      el("div", entry.source_uri, "paths"),
    );
    list.append(li);
  }
  panel.append(list);
  panel.append(el("h2", "已完成的模型调用"));
  if (!item.runs.length)
    panel.append(
      el("p", "暂无已提交调用记录；进行中的调用完成后才会出现。", "muted"),
    );
  for (const run of item.runs) {
    panel.append(
      el(
        "p",
        `${label(run.role)} · ${run.provider} / ${run.model} · 第 ${run.route_index} 路 · ${label(run.outcome)} · ${(run.duration_ms / 1000).toFixed(1)} 秒`,
      ),
    );
    if (run.error_code) panel.append(el("div", run.error_code, "blocker"));
    panel.append(
      el("div", time(run.completed_at) + " · " + run.source_uri, "paths"),
    );
  }
  panel.append(el("h2", "产物与报告"));
  documentList(panel, item.documents);
}
function render() {
  if (!snapshot) return;
  const expanded = new Set(
    [...document.querySelectorAll("details[open]")].map((n) => n.dataset.key),
  );
  document.getElementById("company").textContent = snapshot.company_name;
  document.getElementById("heading").textContent =
    page === "team" ? "团队成员" : "需求与交付";
  const content = document.getElementById("content");
  content.replaceChildren();
  if (page === "team") renderTeam(content);
  else renderRequests(content);
  renderDetail();
  for (const node of document.querySelectorAll("details"))
    if (expanded.has(node.dataset.key)) node.open = true;
}
for (const target of ["team", "requests"])
  document.getElementById("nav-" + target).addEventListener("click", () => {
    page = target;
    selected = null;
    for (const key of ["team", "requests"]) {
      const n = document.getElementById("nav-" + key);
      n.classList.toggle("selected", key === page);
      if (key === page) n.setAttribute("aria-current", "page");
      else n.removeAttribute("aria-current");
    }
    render();
  });
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  document.getElementById("refresh").disabled = true;
  const status = document.getElementById("connection");
  const controller = new AbortController(),
    timeout = setTimeout(() => controller.abort(), 40000);
  try {
    const response = await fetch("/api/v1/team", {
      cache: "no-store",
      signal: controller.signal,
    });
    if (!response.ok) throw new Error("read failed");
    const next = await response.json();
    if (
      next.schema_version !== "v0.1" ||
      !Array.isArray(next.tasks) ||
      !Array.isArray(next.agents) ||
      !Array.isArray(next.requests)
    )
      throw new Error("invalid snapshot");
    const changed =
      !snapshot ||
      JSON.stringify({ ...snapshot, as_of: null }) !==
        JSON.stringify({ ...next, as_of: null });
    snapshot = next;
    if (changed) render();
    status.className = "";
    status.textContent =
      "真实记录 · 最近读取 " + time(snapshot.as_of) + " · 每 5 秒刷新";
  } catch {
    status.className = "error";
    status.textContent = snapshot
      ? "刷新失败，以下为旧数据 · 上次成功读取 " + time(snapshot.as_of)
      : "暂时无法读取数据。请检查生产配置、MySQL 连接，以及公司工作空间是否已准备。";
  } finally {
    clearTimeout(timeout);
    refreshing = false;
    document.getElementById("refresh").disabled = false;
  }
}
document.getElementById("refresh").addEventListener("click", refresh);
refresh();
setInterval(refresh, 5000);
