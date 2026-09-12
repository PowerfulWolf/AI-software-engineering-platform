"use strict";
let snapshot = null;
let page = "team";
let selected = null;
let refreshing = false;
let operations = [];
let consoleAvailable = null;
let consoleCompanyId = null;
let composing = false;
let actionSerial = 0;
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
  RUNNING: "执行中",
  INTERRUPTED: "执行已中断",
  INVALID: "输出无效",
  TIMED_OUT: "执行超时",
  UNKNOWN: "未确认",
  CREATE_REQUIREMENT_PROJECT: "创建需求项目",
  PRODUCT_REPLY: "提交需求说明",
  PRODUCT_APPROVAL: "批准产品文档",
  CONTINUE_DELIVERY: "继续交付",
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
const operationTarget = (operation) =>
  operation.intent.delivery_id || operation.result?.delivery_id || null;
const activeOperation = (deliveryId) =>
  operations.find(
    (operation) =>
      operationTarget(operation) === deliveryId &&
      ["QUEUED", "RUNNING"].includes(operation.status),
  );
const latestApproval = (deliveryId, checkpoint) => {
  const consumedPlans = new Set(
    operations
      .filter(
        (operation) =>
          operationTarget(operation) === deliveryId &&
          operation.intent.action === "CONTINUE_DELIVERY" &&
          operation.intent.approved_plan_sha256,
      )
      .map((operation) => operation.intent.approved_plan_sha256),
  );
  return (
    [...operations]
      .sort((left, right) => right.updated_at.localeCompare(left.updated_at))
      .find(
        (operation) =>
          operationTarget(operation) === deliveryId &&
          operation.status === "SUCCEEDED" &&
          operation.result?.approval &&
          operation.intent.expected_checkpoint_sha256 === checkpoint &&
          !consumedPlans.has(operation.result.approval.plan_sha256),
      )?.result.approval || null
  );
};
const operationKey = () =>
  `browser-${Date.now()}-${++actionSerial}`;
const canControlCurrentCompany = () =>
  consoleAvailable === true &&
  snapshot &&
  snapshot.company_id === consoleCompanyId;
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
function taskGroup(task) {
  if (task.status === "DONE") return "completed";
  if (
    task.blocker ||
    task.status.includes("WAITING") ||
    ["BLOCKED", "FAILED"].includes(task.status)
  )
    return "blocked";
  if (task.terminal) return "completed";
  return "active";
}
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
function field(labelText, control, hint) {
  const wrapper = el("label", undefined, "field");
  wrapper.append(el("span", labelText));
  if (hint) wrapper.append(el("small", hint));
  wrapper.append(control);
  return wrapper;
}
function renderComposer() {
  const panel = document.getElementById("composer");
  panel.replaceChildren();
  panel.hidden = !composing;
  if (!composing) return;
  const top = el("div", undefined, "row");
  top.append(
    el("div", "新建需求项目", "section-title"),
    button(
      "取消",
      () => {
        composing = false;
        renderComposer();
      },
      "",
    ),
  );
  const form = el("form", undefined, "project-form");
  const name = el("input");
  name.name = "name";
  name.required = true;
  name.maxLength = 200;
  name.placeholder = "例如：统一登录体验升级";
  const roots = el("textarea");
  roots.name = "project_roots";
  roots.required = true;
  roots.rows = 5;
  roots.placeholder =
    "/absolute/path/to/backend\n/absolute/path/to/frontend";
  const feedback = el("p", "", "form-feedback");
  const submit = el("button", "创建并准备项目", "primary");
  submit.type = "submit";
  form.append(
    field("需求项目名称", name),
    field(
      "涉及的代码目录",
      roots,
      "每行一个绝对目录；同一仓库的多个模块和不同仓库可以一起填写。",
    ),
    feedback,
    submit,
  );
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const projectRoots = roots.value
      .split(/\r?\n/)
      .map((value) => value.trim())
      .filter(Boolean);
    if (!name.value.trim() || !projectRoots.length) {
      feedback.textContent = "请填写项目名称和至少一个绝对代码目录。";
      feedback.className = "form-feedback error";
      return;
    }
    submit.disabled = true;
    feedback.className = "form-feedback";
    feedback.textContent = "Project Manager 正在接单…";
    const accepted = await submitOperation({
      action: "CREATE_REQUIREMENT_PROJECT",
      name: name.value.trim(),
      project_roots: projectRoots,
    });
    if (accepted) {
      composing = false;
      renderComposer();
    } else {
      feedback.textContent = "创建失败，请查看上方操作状态后重试。";
      feedback.className = "form-feedback error";
      submit.disabled = false;
    }
  });
  panel.append(top, form);
  name.focus();
}
async function submitOperation(intent) {
  try {
    const response = await fetch("/api/v1/operations", {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        idempotency_key: operationKey(),
        intent,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      const message = payload.error?.message || "操作未被接受。";
      throw new Error(message);
    }
    operations = [
      ...operations.filter((item) => item.operation_id !== payload.operation_id),
      payload,
    ];
    renderOperationStatus();
    renderDetail();
    return payload;
  } catch (error) {
    const panel = document.getElementById("operations");
    panel.replaceChildren(
      el(
        "div",
        error instanceof Error ? error.message : "操作未被接受。",
        "operation-error",
      ),
    );
    return null;
  }
}
function renderOperationStatus() {
  const panel = document.getElementById("operations");
  panel.replaceChildren();
  if (consoleAvailable === false) {
    panel.append(
      el(
        "div",
        "当前连接的是只读看板。请启动后台 Web Console 后再创建或继续需求。",
        "operation-error",
      ),
    );
    return;
  }
  if (snapshot && consoleCompanyId && snapshot.company_id !== consoleCompanyId) {
    panel.append(
      el(
        "div",
        "当前后台服务未绑定这个公司；此公司暂时只能查看，不能提交交付操作。",
        "operation-error",
      ),
    );
    return;
  }
  const visible = [...operations]
    .sort((left, right) => right.updated_at.localeCompare(left.updated_at))
    .slice(0, 5);
  for (const operation of visible) {
    const card = el("div", undefined, "operation-status");
    const row = el("div", undefined, "row");
    row.append(
      el("strong", label(operation.intent.action)),
      badge(operation.status),
    );
    card.append(row);
    if (["QUEUED", "RUNNING"].includes(operation.status))
      card.append(
        el(
          "p",
          operation.status === "QUEUED"
            ? "已安全接单，等待 Project Manager 执行。"
            : "Project Manager 正在执行；可以刷新或关闭页面。",
          "muted",
        ),
      );
    if (operation.error_summary)
      card.append(el("div", operation.error_summary, "blocker"));
    if (operation.result?.delivery_id)
      card.append(
        button("打开需求工作区", () => {
          page = "requests";
          selected = { kind: "request", id: operation.result.delivery_id };
          render();
        }),
      );
    panel.append(card);
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
    const memberStatus = !agent.enabled
      ? ["已停用", "badge"]
      : agent.current_stage_delivery_ids.length
        ? ["执行中", "badge current"]
        : agent.assigned_delivery_ids.length
          ? ["等待当前阶段", "badge"]
          : ["空闲中", "badge done"];
    head.append(identity, el("span", memberStatus[0], memberStatus[1]));
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
      work.append(el("p", "当前公司没有分配给该成员的未结束任务。", "muted"));
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
      "成员属于组织；工作记录按上方选中的公司独立统计。“空闲中”只描述当前公司任务分配，不代表 Agent 进程在线。",
      "muted",
    ),
  );
}
function requestCard(request) {
  const card = el("article", undefined, "request"),
    head = el("div", undefined, "row");
  head.append(
    button(request.title, () => showDetail("request", request.id)),
    badge(request.stage),
  );
  card.append(head);
  const write = request.scopes.filter((s) => !s.reference_only),
    done = write.filter((s) => taskById(s.delivery_id)?.status === "DONE").length;
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
  return card;
}
function requestOperation(panel, request) {
  if (!canControlCurrentCompany()) return;
  const running = activeOperation(request.id);
  if (running) {
    panel.append(
      el(
        "div",
        running.status === "QUEUED"
          ? "该需求操作已排队，等待 Project Manager。"
          : "Project Manager 正在处理该需求，可以离开页面后再回来。",
        "operation-running",
      ),
    );
    return;
  }
  const approval = latestApproval(request.id, request.checkpoint_sha256);
  if (approval) {
    const box = el("section", undefined, "approval-box");
    box.append(el("h3", approval.title));
    for (const fact of approval.facts) box.append(el("p", fact, "paths"));
    box.append(
      el(
        "p",
        "批准后平台只执行上方计划；页面会把精确计划身份安全地带回 Project Manager。",
        "muted",
      ),
      button(
        "批准并继续",
        () =>
          submitOperation({
            action: "CONTINUE_DELIVERY",
            delivery_id: request.id,
            expected_checkpoint_sha256: request.checkpoint_sha256,
            approved_plan_sha256: approval.plan_sha256,
          }),
        "primary",
      ),
    );
    panel.append(box);
    return;
  }
  if (
    [
      "READY_FOR_DISCUSSION",
      "WAITING_PRODUCT_REPLY",
      "WAITING_PRODUCT_APPROVAL",
    ].includes(request.stage)
  ) {
    const form = el("form", undefined, "discussion-form");
    const message = el("textarea");
    message.required = true;
    message.rows = 5;
    message.maxLength = 20000;
    message.placeholder =
      request.stage === "READY_FOR_DISCUSSION"
        ? "描述你要完成的需求、业务背景和验收预期…"
        : "补充信息，或说明需要 Product Agent 修改的内容…";
    const feedback = el("p", "", "form-feedback");
    const submit = el(
      "button",
      request.stage === "READY_FOR_DISCUSSION" ? "提交需求" : "提交补充说明",
      "primary",
    );
    submit.type = "submit";
    form.append(field("和 Product Agent 讨论需求", message), feedback, submit);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!message.value.trim()) return;
      submit.disabled = true;
      feedback.textContent = "已提交，等待 Product Agent…";
      const accepted = await submitOperation({
        action: "PRODUCT_REPLY",
        delivery_id: request.id,
        expected_checkpoint_sha256: request.checkpoint_sha256,
        message: message.value.trim(),
      });
      if (!accepted) submit.disabled = false;
    });
    panel.append(form);
  }
  if (request.stage === "WAITING_PRODUCT_APPROVAL") {
    const approval = el("section", undefined, "approval-box");
    approval.append(
      el("h3", "产品文档已准备好"),
      el(
        "p",
        "请先阅读下方 ProductSpec。批准后 Designer、Planner、Coder、QA 和 Reviewer 将按该版本工作。",
        "muted",
      ),
      button(
        "批准 ProductSpec 并开始交付",
        () =>
          submitOperation({
            action: "PRODUCT_APPROVAL",
            delivery_id: request.id,
            expected_checkpoint_sha256: request.checkpoint_sha256,
          }),
        "primary",
      ),
    );
    panel.append(approval);
  } else if (
    ![
      "READY_FOR_DISCUSSION",
      "WAITING_PRODUCT_REPLY",
      "DONE",
    ].includes(request.stage)
  ) {
    panel.append(
      button(
        "继续交付",
        () =>
          submitOperation({
            action: "CONTINUE_DELIVERY",
            delivery_id: request.id,
            expected_checkpoint_sha256: request.checkpoint_sha256,
          }),
        "primary",
      ),
    );
  }
}
function deliveryResult(panel, request) {
  if (request.stage !== "DONE") return;
  const result = el("section", undefined, "delivery-result");
  result.append(
    el("h2", "交付结果"),
    el(
      "p",
      "以下候选提交已经通过独立 QA、Reviewer 和联合验收；平台没有自动合并或上线。",
      "muted",
    ),
  );
  let delivered = 0;
  for (const scope of request.scopes) {
    const task = taskById(scope.delivery_id);
    if (!task?.candidate_revision) continue;
    delivered += 1;
    const item = el("div", undefined, "candidate");
    item.append(
      el("strong", scope.root),
      el("p", "Candidate commit · " + task.candidate_revision, "paths"),
    );
    if (task.candidate_branch)
      item.append(el("p", "Candidate branch · " + task.candidate_branch, "paths"));
    item.append(button("查看 QA / Review 证据", () => showDetail("task", task.id)));
    result.append(item);
  }
  if (!delivered)
    result.append(
      el("p", "该需求没有需要修改的仓库，或候选提交尚未进入当前快照。", "muted"),
    );
  panel.append(result);
}
function renderRequests(content) {
  const top = el("div", undefined, "row request-heading");
  top.append(
    el("h2", "需求项目"),
    canControlCurrentCompany()
      ? button(
          "新建需求项目",
          () => {
            composing = true;
            renderComposer();
            document
              .getElementById("composer")
              .scrollIntoView({ behavior: "smooth", block: "start" });
          },
          "primary",
        )
      : el("span", "控制台未连接", "badge blocked"),
  );
  content.append(top);
  if (!snapshot.requests.length) {
    const n = el("div", undefined, "empty");
    n.append(
      el("p", "还没有需求。点击“新建需求项目”，选择涉及的代码目录后开始讨论。"),
    );
    content.append(n);
  }
  const materialized = new Set(snapshot.tasks.map((task) => task.request_id));
  for (const request of snapshot.requests.filter((item) => !materialized.has(item.id)))
    content.append(requestCard(request));
  for (const [key, title] of [
    ["active", "执行中"],
    ["blocked", "阻塞中"],
    ["completed", "已完成"],
  ]) {
    const group = el("section", undefined, "task-group");
    const tasks = snapshot.tasks.filter((task) => taskGroup(task) === key);
    const heading = el("h2");
    heading.append(document.createTextNode(title), el("span", String(tasks.length), "badge"));
    group.append(heading);
    if (!tasks.length) group.append(el("p", `暂无${title}任务。`, "muted"));
    for (const task of tasks) group.append(taskRow(task));
    content.append(group);
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
    requestOperation(panel, item);
    deliveryResult(panel, item);
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
  if (item.candidate_branch)
    panel.append(el("p", "候选分支 · " + item.candidate_branch, "paths"));
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
  const companies = document.getElementById("companies");
  companies.replaceChildren();
  for (const company of snapshot.companies || []) {
    const tab = button(company.name, () => refresh(company.id), "");
    const active = company.id === snapshot.company_id;
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-selected", String(active));
    if (active) tab.setAttribute("aria-current", "true");
    companies.append(tab);
  }
  document.getElementById("heading").textContent =
    page === "team" ? "团队成员" : "需求与交付";
  document.getElementById("new-request").hidden =
    page !== "requests" || !canControlCurrentCompany();
  const content = document.getElementById("content");
  content.replaceChildren();
  if (page === "team") renderTeam(content);
  else renderRequests(content);
  renderComposer();
  renderOperationStatus();
  renderDetail();
  for (const node of document.querySelectorAll("details"))
    if (expanded.has(node.dataset.key)) node.open = true;
}
for (const target of ["team", "requests"])
  document.getElementById("nav-" + target).addEventListener("click", () => {
    page = target;
    selected = null;
    composing = false;
    for (const key of ["team", "requests"]) {
      const n = document.getElementById("nav-" + key);
      n.classList.toggle("selected", key === page);
      if (key === page) n.setAttribute("aria-current", "page");
      else n.removeAttribute("aria-current");
    }
    render();
  });
document.getElementById("new-request").addEventListener("click", () => {
  composing = true;
  renderComposer();
});
async function refreshOperations() {
  try {
    const [infoResponse, operationsResponse] = await Promise.all([
      fetch("/api/v1/console", { cache: "no-store" }),
      fetch("/api/v1/operations", { cache: "no-store" }),
    ]);
    if (!infoResponse.ok || !operationsResponse.ok)
      throw new Error("console unavailable");
    const info = await infoResponse.json();
    const nextOperations = await operationsResponse.json();
    if (
      info.schema_version !== "v0.1" ||
      typeof info.company_id !== "string" ||
      !Array.isArray(nextOperations)
    )
      throw new Error("invalid console response");
    consoleAvailable = true;
    consoleCompanyId = info.company_id;
    operations = nextOperations;
  } catch {
    consoleAvailable = false;
    consoleCompanyId = null;
    operations = [];
  }
}
async function refresh(companyId) {
  if (refreshing) return;
  refreshing = true;
  document.getElementById("refresh").disabled = true;
  const status = document.getElementById("connection");
  const controller = new AbortController(),
    timeout = setTimeout(() => controller.abort(), 40000);
  try {
    const target = companyId || (snapshot && snapshot.company_id);
    const url = target ? "/api/v1/team/" + encodeURIComponent(target) : "/api/v1/team";
    const response = await fetch(url, {
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
    const priorOperations = JSON.stringify(operations);
    const priorConsoleCompany = consoleCompanyId;
    snapshot = next;
    await refreshOperations();
    if (
      changed ||
      priorOperations !== JSON.stringify(operations) ||
      priorConsoleCompany !== consoleCompanyId
    )
      render();
    status.className = "";
    status.textContent = consoleAvailable
      ? "团队与交付控制台已连接 · 最近读取 " +
        time(snapshot.as_of) +
        " · 每 5 秒刷新"
      : "只读团队记录已连接；交付控制台暂不可用。";
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
