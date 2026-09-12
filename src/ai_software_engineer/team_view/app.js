"use strict";
let snapshot = null;
let page = "team";
let selected = null;
let refreshing = false;
let operations = [];
let consoleAvailable = null;
let consoleCompanyId = null;
let administrationAvailable = null;
let administrationCompanies = [];
let knowledgeDocuments = [];
let settingsSnapshot = null;
let settingsDraft = null;
let administrationNotice = null;
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
const pageCopy = {
  team: [
    "团队成员",
    "任务阶段来自持久化记录；“空闲中”只表示当前公司没有分配给该成员的未结束任务。",
  ],
  requests: [
    "需求与交付",
    "项目、需求、批准和继续交付都在这里完成；一个任务内的 Coder、QA、Reviewer 串行工作。",
  ],
  knowledge: [
    "公司知识库",
    "上传的文档保存在公司 sidecar，转换为可校验的 Markdown；只有在设置中选中并重启后，文档才会进入新需求上下文。",
  ],
  settings: [
    "设置",
    "配置会写入无密钥生产配置文件。页面标记“需要重启”时，当前运行中的团队不会被热切换。",
  ],
};
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
const operationKey = () => `browser-${Date.now()}-${++actionSerial}`;
const canControlCurrentCompany = () =>
  consoleAvailable === true &&
  snapshot &&
  snapshot.company_id === consoleCompanyId;
function assignmentBadge(task, assignment) {
  if (task.terminal) return badge(task.status);
  if (assignment.current_stage) return badge(task.status);
  const current = task.assignments.find((candidate) => candidate.current_stage);
  if (!current) return el("span", "已分配 · 等待调度", "badge");
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
  roots.placeholder = "/absolute/path/to/backend\n/absolute/path/to/frontend";
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
      ...operations.filter(
        (item) => item.operation_id !== payload.operation_id,
      ),
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
  if (
    snapshot &&
    consoleCompanyId &&
    snapshot.company_id !== consoleCompanyId
  ) {
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
    !["READY_FOR_DISCUSSION", "WAITING_PRODUCT_REPLY", "DONE"].includes(
      request.stage,
    )
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
      item.append(
        el("p", "Candidate branch · " + task.candidate_branch, "paths"),
      );
    item.append(
      button("查看 QA / Review 证据", () => showDetail("task", task.id)),
    );
    result.append(item);
  }
  if (!delivered)
    result.append(
      el(
        "p",
        "该需求没有需要修改的仓库，或候选提交尚未进入当前快照。",
        "muted",
      ),
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
  for (const request of snapshot.requests.filter(
    (item) => !materialized.has(item.id),
  ))
    content.append(requestCard(request));
  for (const [key, title] of [
    ["active", "执行中"],
    ["blocked", "阻塞中"],
    ["completed", "已完成"],
  ]) {
    const group = el("section", undefined, "task-group");
    const tasks = snapshot.tasks.filter((task) => taskGroup(task) === key);
    const heading = el("h2");
    heading.append(
      document.createTextNode(title),
      el("span", String(tasks.length), "badge"),
    );
    group.append(heading);
    if (!tasks.length) group.append(el("p", `暂无${title}任务。`, "muted"));
    for (const task of tasks) group.append(taskRow(task));
    content.append(group);
  }
}
async function adminFetch(url, options = {}) {
  const response = await fetch(url, { cache: "no-store", ...options });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error?.message || "管理操作失败。");
  return payload;
}
async function loadKnowledge(companyId) {
  knowledgeDocuments = await adminFetch(
    "/api/v1/admin/companies/" + encodeURIComponent(companyId) + "/knowledge",
  );
}
async function loadAdministration(companyId) {
  try {
    const [companies, settings] = await Promise.all([
      adminFetch("/api/v1/admin/companies"),
      adminFetch("/api/v1/admin/settings"),
    ]);
    administrationCompanies = companies;
    settingsSnapshot = settings;
    settingsDraft = structuredClone(settings.config);
    await loadKnowledge(companyId || settings.config.company_id);
    administrationAvailable = true;
  } catch {
    administrationAvailable = false;
    administrationCompanies = [];
    knowledgeDocuments = [];
    settingsSnapshot = null;
    settingsDraft = null;
  }
}
function administrationUnavailable(content) {
  content.append(
    el(
      "div",
      "当前服务没有启用管理能力。请使用 ase-console 启动本地 Web Console。",
      "operation-error",
    ),
  );
}
function renderKnowledge(content) {
  if (!administrationAvailable) {
    administrationUnavailable(content);
    return;
  }
  if (administrationNotice?.page === "knowledge")
    content.append(el("div", administrationNotice.text, "admin-notice"));
  const top = el("div", undefined, "row request-heading");
  top.append(
    el("h2", `${snapshot.company_name} · 已导入文档`),
    el("span", `${knowledgeDocuments.length} 份`, "badge"),
  );
  content.append(top);
  const form = el("form", undefined, "knowledge-upload admin-panel");
  const file = el("input");
  file.type = "file";
  file.accept = ".md,.txt,.pdf,.docx";
  file.required = true;
  const feedback = el("p", "", "form-feedback");
  const submit = el("button", "上传并转换", "primary");
  submit.type = "submit";
  form.append(
    field(
      "选择本地文档",
      file,
      "支持 Markdown、TXT、PDF、DOCX；单个原文件最大 10 MB，转换后的正文最大 256 KB。",
    ),
    feedback,
    submit,
  );
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const selectedFile = file.files && file.files[0];
    if (!selectedFile) return;
    submit.disabled = true;
    feedback.className = "form-feedback";
    feedback.textContent = "正在读取并校验文档…";
    try {
      await adminFetch(
        "/api/v1/admin/companies/" +
          encodeURIComponent(snapshot.company_id) +
          "/knowledge?filename=" +
          encodeURIComponent(selectedFile.name),
        {
          method: "POST",
          headers: { "Content-Type": "application/octet-stream" },
          body: selectedFile,
        },
      );
      await loadKnowledge(snapshot.company_id);
      administrationNotice = {
        page: "knowledge",
        text: "导入完成。请到设置页选择它并保存，重启后用于新需求。",
      };
      render();
    } catch (error) {
      feedback.className = "form-feedback error";
      feedback.textContent =
        error instanceof Error ? error.message : "文档导入失败。";
      submit.disabled = false;
    }
  });
  content.append(form);
  if (!knowledgeDocuments.length) {
    content.append(el("div", "尚未导入公司知识文档。", "empty"));
    return;
  }
  for (const item of knowledgeDocuments) {
    const manifest = item.manifest;
    const card = el("article", undefined, "knowledge-card");
    const head = el("div", undefined, "row");
    head.append(
      el("strong", manifest.source_name),
      el(
        "span",
        item.selected
          ? settingsSnapshot.restart_required
            ? "已选择 · 重启后生效"
            : "已用于新需求"
          : "尚未启用",
        item.selected ? "badge done" : "badge",
      ),
    );
    card.append(
      head,
      el(
        "p",
        `类型 ${manifest.media_type} · 原文件 ${manifest.source_bytes} bytes · 正文 ${manifest.normalized_bytes} bytes`,
        "muted",
      ),
      el("p", "来源 SHA-256 · " + manifest.source_sha256, "paths"),
      el("p", "知识路径 · " + manifest.normalized_relative_path, "paths"),
      el("p", "导入时间 · " + time(manifest.imported_at), "muted"),
    );
    if (!item.selected)
      card.append(
        button("前往设置并启用", async () => {
          page = "settings";
          await loadAdministration(settingsSnapshot.config.company_id);
          updateNavigation();
          render();
        }),
      );
    content.append(card);
  }
}
function bindInput(control, value, update, type = "text") {
  control.type = type;
  control.value = value ?? "";
  control.addEventListener("input", () => update(control.value));
  return control;
}
function selectInput(values, current, update) {
  const control = el("select");
  for (const [value, title] of values) {
    const option = el("option", title);
    option.value = value;
    option.selected = value === current;
    control.append(option);
  }
  control.value = current;
  control.addEventListener("change", () => update(control.value));
  return control;
}
function renderCompanyCreator(content) {
  const panel = el("section", undefined, "admin-panel");
  panel.append(el("h2", "接入新公司"));
  const form = el("form", undefined, "settings-grid");
  const companyId = el("input");
  companyId.placeholder = "company_acme";
  companyId.pattern = "company_[a-z0-9][a-z0-9_-]{1,63}";
  companyId.required = true;
  const name = el("input");
  name.placeholder = "公司显示名称";
  name.maxLength = 200;
  name.required = true;
  const feedback = el("p", "", "form-feedback full-row");
  const submit = el("button", "创建公司", "primary");
  submit.type = "submit";
  form.append(
    field("公司 ID", companyId, "创建后不可修改，用于隔离知识和交付事实。"),
  );
  form.append(field("公司名称", name));
  form.append(feedback, submit);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    try {
      await adminFetch("/api/v1/admin/companies", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          company_id: companyId.value.trim(),
          name: name.value.trim(),
        }),
      });
      await loadAdministration(settingsDraft.company_id);
      administrationNotice = {
        page: "settings",
        text: "公司已创建。可在下方将它设为活动公司。",
      };
      render();
    } catch (error) {
      feedback.className = "form-feedback error full-row";
      feedback.textContent =
        error instanceof Error ? error.message : "公司创建失败。";
      submit.disabled = false;
    }
  });
  panel.append(form);
  content.append(panel);
}
function renderSettings(content) {
  if (!administrationAvailable || !settingsSnapshot || !settingsDraft) {
    administrationUnavailable(content);
    return;
  }
  if (administrationNotice?.page === "settings")
    content.append(el("div", administrationNotice.text, "admin-notice"));
  renderCompanyCreator(content);
  const panel = el("section", undefined, "admin-panel");
  const top = el("div", undefined, "row");
  top.append(
    el("h2", "平台运行配置"),
    settingsSnapshot.restart_required
      ? el("span", "已保存 · 需要重启", "badge blocked")
      : el("span", "当前配置已生效", "badge done"),
  );
  panel.append(
    top,
    el("p", "配置文件 · " + settingsSnapshot.config_path, "paths"),
  );
  const form = el("form", undefined, "settings-form");
  const general = el("div", undefined, "settings-grid");
  const platformRoot = bindInput(
    el("input"),
    settingsDraft.platform_root,
    (value) => {
      if (value !== settingsDraft.platform_root)
        settingsDraft.company_knowledge_paths = [];
      settingsDraft.platform_root = value;
    },
  );
  const company = selectInput(
    administrationCompanies.map((item) => [
      item.company_id,
      `${item.name} · ${item.company_id}`,
    ]),
    settingsDraft.company_id,
    async (value) => {
      const selectedCompany = administrationCompanies.find(
        (item) => item.company_id === value,
      );
      if (!selectedCompany) return;
      settingsDraft.company_id = value;
      settingsDraft.company_name = selectedCompany.name;
      settingsDraft.company_knowledge_paths = [];
      await loadKnowledge(value);
      render();
    },
  );
  const dsn = bindInput(
    el("input"),
    settingsDraft.database.dsn_env,
    (value) => (settingsDraft.database.dsn_env = value),
  );
  const codex = bindInput(
    el("input"),
    settingsDraft.codex_executable,
    (value) => (settingsDraft.codex_executable = value),
  );
  const port = bindInput(
    el("input"),
    String(settingsDraft.console_port),
    (value) => (settingsDraft.console_port = Number(value)),
    "number",
  );
  port.min = "1";
  port.max = "65535";
  const live = el("input");
  live.type = "checkbox";
  live.checked = settingsDraft.live_model_execution;
  live.addEventListener(
    "change",
    () => (settingsDraft.live_model_execution = live.checked),
  );
  general.append(
    field(
      "平台数据目录",
      platformRoot,
      "必须是绝对路径；切换后会在新目录初始化当前公司，不迁移旧知识，并要求重启。",
    ),
    field("活动公司", company, "需求写操作只进入活动公司；切换后需要重启。"),
    field("MySQL DSN 环境变量名", dsn, "页面只保存变量名，不读取或显示 DSN。"),
    field("Codex 可执行文件", codex),
    field("Web Console 端口", port, "修改端口后使用新地址重启。"),
    field("启用真实模型执行", live),
  );
  form.append(general);
  const secrets = el("section", undefined, "settings-subsection");
  secrets.append(el("h3", "密钥状态"));
  for (const item of settingsSnapshot.secret_status)
    secrets.append(
      el(
        "p",
        `${item.environment_name} · ${item.configured ? "已提供" : "未提供"}`,
        item.configured ? "badge done" : "badge blocked",
      ),
    );
  form.append(secrets);
  const knowledge = el("section", undefined, "settings-subsection");
  knowledge.append(
    el("h3", "用于新需求的公司知识"),
    el(
      "p",
      "知识选择变化会改变后续准备摘要；已经批准的交付不会被静默重解释。",
      "muted",
    ),
  );
  if (!knowledgeDocuments.length)
    knowledge.append(el("p", "该公司尚未导入文档。", "muted"));
  for (const item of knowledgeDocuments) {
    const control = el("input");
    const path = item.manifest.normalized_relative_path;
    control.type = "checkbox";
    control.checked = settingsDraft.company_knowledge_paths.includes(path);
    control.addEventListener("change", () => {
      const selected = new Set(settingsDraft.company_knowledge_paths);
      if (control.checked) selected.add(path);
      else selected.delete(path);
      settingsDraft.company_knowledge_paths = [...selected].sort();
    });
    knowledge.append(field(item.manifest.source_name, control, path));
  }
  form.append(knowledge);
  const routes = el("section", undefined, "settings-subsection");
  const routesTop = el("div", undefined, "row");
  routesTop.append(
    el("h3", "模型路由（按顺序尝试）"),
    button("添加路由", () => {
      settingsDraft.model_routes.push({
        provider: "provider",
        model: "model",
        kind: "responses",
        endpoint: "https://example.invalid/v1/responses",
        api_key_env: "MODEL_API_KEY",
        reasoning_effort: "medium",
        enabled: false,
      });
      render();
    }),
  );
  routes.append(routesTop);
  settingsDraft.model_routes.forEach((route, index) => {
    const row = el("div", undefined, "route-card");
    const fields = el("div", undefined, "settings-grid");
    fields.append(
      field(
        "Provider",
        bindInput(
          el("input"),
          route.provider,
          (value) => (route.provider = value),
        ),
      ),
      field(
        "Model",
        bindInput(el("input"), route.model, (value) => (route.model = value)),
      ),
      field(
        "类型",
        selectInput(
          [
            ["codex_cli", "Codex CLI"],
            ["responses", "Responses API"],
          ],
          route.kind,
          (value) => {
            route.kind = value;
            if (value === "codex_cli") {
              route.endpoint = null;
              route.api_key_env = null;
            }
            render();
          },
        ),
      ),
      field(
        "Reasoning",
        selectInput(
          ["low", "medium", "high", "xhigh"].map((value) => [value, value]),
          route.reasoning_effort,
          (value) => (route.reasoning_effort = value),
        ),
      ),
    );
    if (route.kind === "responses")
      fields.append(
        field(
          "Endpoint",
          bindInput(
            el("input"),
            route.endpoint,
            (value) => (route.endpoint = value),
          ),
        ),
        field(
          "API Key 环境变量名",
          bindInput(
            el("input"),
            route.api_key_env,
            (value) => (route.api_key_env = value),
          ),
        ),
      );
    const enabled = el("input");
    enabled.type = "checkbox";
    enabled.checked = route.enabled;
    enabled.addEventListener("change", () => (route.enabled = enabled.checked));
    row.append(fields, field("启用", enabled));
    if (settingsDraft.model_routes.length > 1)
      row.append(
        button("移除路由", () => {
          settingsDraft.model_routes.splice(index, 1);
          render();
        }),
      );
    routes.append(row);
  });
  form.append(routes);
  const feedback = el("p", "", "form-feedback");
  const save = el("button", "保存设置", "primary");
  save.type = "submit";
  form.append(feedback, save);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    save.disabled = true;
    feedback.textContent = "正在校验并保存…";
    try {
      const saved = await adminFetch("/api/v1/admin/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config: settingsDraft }),
      });
      settingsSnapshot = saved;
      settingsDraft = structuredClone(saved.config);
      administrationNotice = {
        page: "settings",
        text: saved.restart_required
          ? "保存成功。请重启 Web Console 使新配置生效。"
          : "保存成功，当前配置未改变。",
      };
      render();
    } catch (error) {
      feedback.className = "form-feedback error";
      feedback.textContent =
        error instanceof Error ? error.message : "设置保存失败。";
      save.disabled = false;
    }
  });
  panel.append(form);
  content.append(panel);
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
  document.getElementById("heading").textContent = pageCopy[page][0];
  document.getElementById("explanation").textContent = pageCopy[page][1];
  document.getElementById("new-request").hidden =
    page !== "requests" || !canControlCurrentCompany();
  const content = document.getElementById("content");
  content.replaceChildren();
  if (page === "team") renderTeam(content);
  else if (page === "requests") renderRequests(content);
  else if (page === "knowledge") renderKnowledge(content);
  else renderSettings(content);
  renderComposer();
  renderOperationStatus();
  renderDetail();
  for (const node of document.querySelectorAll("details"))
    if (expanded.has(node.dataset.key)) node.open = true;
}
function updateNavigation() {
  for (const key of ["team", "requests", "knowledge", "settings"]) {
    const node = document.getElementById("nav-" + key);
    node.classList.toggle("selected", key === page);
    if (key === page) node.setAttribute("aria-current", "page");
    else node.removeAttribute("aria-current");
  }
}
for (const target of ["team", "requests", "knowledge", "settings"])
  document
    .getElementById("nav-" + target)
    .addEventListener("click", async () => {
      administrationNotice = null;
      page = target;
      selected = null;
      composing = false;
      if (target === "knowledge") await loadAdministration(snapshot.company_id);
      if (target === "settings") await loadAdministration();
      updateNavigation();
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
    const url = target
      ? "/api/v1/team/" + encodeURIComponent(target)
      : "/api/v1/team";
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
    if (page === "knowledge" && target !== undefined)
      await loadAdministration(next.company_id);
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
