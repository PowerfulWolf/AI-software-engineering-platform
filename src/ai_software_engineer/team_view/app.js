"use strict";
let snapshot = null;
let page = "team";
let selected = null;
let refreshing = false;
let operations = [];
let consoleAvailable = null;
let consoleTeamId = null;
let consoleDeliveryReady = null;
let administrationAvailable = null;
let administrationProjects = [];
let knowledgeDocuments = [];
let knowledgeIndexStatus = null;
let knowledgeScope = "team";
let knowledgeMode = "background";
let specDocuments = [];
let learningProposals = [];
let settingsSnapshot = null;
let settingsDraft = null;
let runtimeVariablesDraft = {};
let runtimeStatusSnapshot = null;
let runtimeStatusError = null;
let runtimeStatusLoading = false;
let administrationNotice = null;
let composing = false;
let pendingConfirmation = null;
let actionSerial = 0;
let requestFilter = "active";
let settingsSection = "general";
let settingsSaveResult = null;
const configurationApplyStorageKey = "ase-configuration-apply";
const configurationApplyTimeoutMs = 30000;
let configurationApplyPending = readConfigurationApplyPending();
let configurationApplyInFlight = configurationApplyPending !== null;
let configurationApplyResult = null;
let configurationApplyStartedAt = configurationApplyInFlight ? Date.now() : null;
let selectedAgentId = null;
let creatingProject = false;
let editingRequirement = null;
let recreatingRequirement = null;
let knowledgeImportMode = null;
let editingKnowledgeDocument = null;
let editingSpecDocument = null;
const dismissedOperationIds = new Set(
  (() => {
    try {
      const stored = globalThis.localStorage?.getItem(
        "ase-dismissed-console-operations",
      );
      const parsed = stored ? JSON.parse(stored) : [];
      return Array.isArray(parsed) && parsed.every((value) => typeof value === "string")
        ? parsed.slice(-100)
        : [];
    } catch {
      return [];
    }
  })(),
);
const maxKnowledgeImportFiles = 20;
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
  WAITING_DELIVERY_FINALIZATION: "等待交付确认",
  IMPLEMENTING: "实现中",
  CONTINUE_REQUIRED: "等待继续实现",
  QUEUED: "已重新排队",
  QA: "测试中",
  REVIEW: "评审中",
  VERIFY_QA: "候选测试中",
  VERIFY_REVIEW: "候选评审中",
  DONE: "已完成",
  CLOSED: "已关闭",
  BLOCKED: "已阻塞",
  FAILED: "失败",
  WAITING_HUMAN: "等待人工",
  coder: "实现",
  qa: "测试",
  reviewer: "评审",
  orchestrator: "任务编排",
  manager: "团队管理",
  product: "产品",
  designer: "设计",
  planner: "计划",
  SUCCEEDED: "执行成功",
  RUNNING: "执行中",
  INTERRUPTED: "执行已中断",
  INVALID: "输出无效",
  TIMED_OUT: "执行超时",
  UNKNOWN: "未确认",
  CREATE_PROJECT: "创建项目",
  CREATE_REQUIREMENT: "创建需求",
  UPDATE_REQUIREMENT: "编辑需求",
  CLOSE_REQUIREMENT: "关闭需求",
  RESTART_REQUIREMENT: "重新启动需求",
  DELETE_REQUIREMENT: "删除需求",
  PRODUCT_REPLY: "提交需求说明",
  PRODUCT_APPROVAL: "批准产品文档",
  CONTINUE_DELIVERY: "继续交付",
  QA_FAILURE: "QA 失败",
  REVIEW_REJECTION: "Review 拒绝",
  APPROVE: "已批准",
  REJECT: "已拒绝",
};
const label = (value) => labels[value] || value;
const productDiscussionStages = new Set([
  "READY_FOR_DISCUSSION",
  "PRODUCT_DISCOVERY",
  "WAITING_PRODUCT_REPLY",
  "WAITING_PRODUCT_APPROVAL",
]);
const deliveryOperationActions = new Set([
  "PRODUCT_REPLY",
  "PRODUCT_APPROVAL",
  "CONTINUE_DELIVERY",
]);
const deliveryRoleOrder = { coder: 0, qa: 1, reviewer: 2 };
const teamRoleOrder = {
  manager: 0,
  product: 1,
  designer: 2,
  planner: 3,
  coder: 4,
  qa: 5,
  reviewer: 6,
};
const specRoleOptions = [
  ["manager", "团队管理"],
  ["product", "产品"],
  ["designer", "设计"],
  ["planner", "计划"],
  ["coder", "实现"],
  ["qa", "测试"],
  ["reviewer", "评审"],
];
const specStageOptions = [
  ["preparing", "项目准备"],
  ["product_discovery", "产品梳理"],
  ["designing", "技术设计"],
  ["planning", "计划编排"],
  ["dispatching", "成员分配"],
  ["implementing", "代码实现"],
  ["qa", "质量验证"],
  ["review", "独立评审"],
  ["integrating", "联合验收"],
];
const agentModelRoles = [
  [
    "manager",
    "Manager Agent",
    "团队管理；当前版本主要使用确定性能力，模型配置为后续智能决策预留。",
  ],
  [
    "product",
    "Product Agent",
    "梳理需求并生成 ProductSpec；需要看懂需求截图。",
  ],
  ["designer", "Designer Agent", "根据已批准的产品文档生成技术设计。"],
  ["planner", "Planner Agent", "拆解执行计划并安排交付顺序。"],
  ["coder", "Coder Agent", "在隔离 worktree 中实现候选提交。"],
  ["qa", "QA Agent", "独立验证候选提交和验收标准。"],
  ["reviewer", "Reviewer Agent", "独立审查质量、风险和规范符合性。"],
];
const pageCopy = {
  team: [
    "团队成员",
    "唯一 Team 服务所有 Project；“空闲中”只表示当前没有分配给该成员的未结束任务。",
  ],
  requests: [
    "需求与交付",
    "先选择 Project，再创建 Requirement 并选择该 Project 下涉及的 1–N 个代码目录。",
  ],
  knowledge: [
    "知识库",
    "团队通用知识和项目背景知识用于理解上下文；开发规范是必须遵守的工程契约；学习建议必须经人工批准。",
  ],
  settings: [
    "设置",
    "配置平台目录、数据库与模型。保存后按页面提示决定是否重启本地服务。",
  ],
  status: [
    "平台状态",
    "查看当前配置、数据库、Codex、模型路由和团队知识是否已经准备就绪。",
  ],
};
const knowledgeLabelForScope = (scope) =>
  scope === "team" ? "通用知识" : "背景知识";
const projectName = () =>
  snapshot?.projects?.find((item) => item.id === currentProjectId())?.name ||
  "尚未选择 Project";
function updatePageContext() {
  const scope = document.getElementById("scope-label");
  const title = document.getElementById("scope-title");
  const projectLabel = document.getElementById("project-context-label");
  const contexts = {
    team: ["Team 级", snapshot.team_name, "工作负载筛选"],
    requests: ["Project 级", projectName(), "当前 Project"],
    knowledge:
      knowledgeScope === "team"
        ? ["Team 知识", snapshot.team_name, ""]
        : ["Project 知识", projectName(), ""],
    settings: ["平台级", "当前 Team Host", ""],
    status: ["平台级", "当前 Team Host", ""],
  };
  const [scopeText, titleText, projectText] = contexts[page];
  scope.textContent = scopeText;
  title.textContent = titleText;
  projectLabel.textContent = projectText;
  projectLabel.hidden = !projectText;
}
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
      (["DONE", "CLOSED"].includes(status)
        ? "done"
        : status.includes("WAITING") || ["BLOCKED", "FAILED"].includes(status)
          ? "blocked"
          : "current"),
  );
const operationTarget = (operation) =>
  operation.intent.delivery_id || operation.result?.delivery_id || null;
const currentProjectId = () => snapshot?.selected_project_id || null;
const activeOperation = (deliveryId) =>
  operations.find(
    (operation) =>
      operationTarget(operation) === deliveryId &&
      ["QUEUED", "RUNNING"].includes(operation.status),
  );
const latestOperation = (deliveryId) =>
  [...operations]
    .filter((operation) => operationTarget(operation) === deliveryId)
    .sort((left, right) => right.updated_at.localeCompare(left.updated_at))[0] ||
  null;
const operationNeedsHumanAttention = (operation) =>
  operation?.status === "SUCCEEDED" &&
  ["WAITING_HUMAN", "BLOCKED", "FAILED"].includes(operation.result?.stage) &&
  !operation.result?.approval;
const isSourceRevisionDrift = (operation) =>
  operation?.status === "FAILED" &&
  (operation.error_code === "SOURCE_REVISION_DRIFT" ||
    /source revision (?:drift|changed after Requirement preparation)/i.test(
      operation.error_summary || "",
    ));
const latestApproval = (deliveryId, checkpoint) => {
  return (
    [...operations]
      .sort((left, right) => right.updated_at.localeCompare(left.updated_at))
      .find(
        (operation) => {
          const approval = operation.result?.approval;
          if (
            operationTarget(operation) !== deliveryId ||
            operation.status !== "SUCCEEDED" ||
            !approval ||
            operation.intent.expected_checkpoint_sha256 !== checkpoint
          )
            return false;
          return !operations.some((candidate) => {
            const submittedApproval =
              candidate.intent.approved_plan_sha256 ||
              candidate.intent.approved_scope_sha256;
            return (
              operationTarget(candidate) === deliveryId &&
              candidate.intent.action === "CONTINUE_DELIVERY" &&
              submittedApproval === approval.plan_sha256 &&
              candidate.updated_at.localeCompare(operation.updated_at) > 0
            );
          });
        },
      )?.result.approval || null
  );
};
const operationKey = () => `browser-${Date.now()}-${++actionSerial}`;
const canControlCurrentTeam = () =>
  consoleAvailable === true &&
  consoleDeliveryReady === true &&
  snapshot &&
  snapshot.team_id === consoleTeamId;
function assignmentBadge(task, assignment) {
  if (task.terminal) return badge(task.status);
  if (assignment.current_stage) return badge(task.status);
  const current = task.assignments.find((candidate) => candidate.current_stage);
  if (!current) return el("span", "已分配 · 等待调度", "badge");
  const assignedOrder = deliveryRoleOrder[assignment.role];
  const currentOrder = deliveryRoleOrder[current.role];
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
const agentWorkById = (id) => {
  const task = taskById(id);
  if (task) return { kind: "task", id, item: task };
  const request = requestById(id);
  return request ? { kind: "request", id, item: request } : null;
};
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
function requestGroup(request) {
  return requestPresentation(request).group;
}
function requestTasks(request) {
  return snapshot.tasks.filter((task) => task.request_id === request.id);
}
function currentRequestTasks(request) {
  const currentByDelivery = new Map();
  for (const task of requestTasks(request)) {
    const deliveryId = task.source_delivery_id || task.id;
    const previous = currentByDelivery.get(deliveryId);
    if (
      !previous ||
      task.last_activity.localeCompare(previous.last_activity) > 0
    )
      currentByDelivery.set(deliveryId, task);
  }
  return [...currentByDelivery.values()];
}
function activeRequestTask(request) {
  if (
    !(
      request.stage.includes("WAITING") ||
      ["BLOCKED", "FAILED", "DELIVERING", "INTEGRATING"].includes(
        request.stage,
      )
    )
  )
    return null;
  return (
    requestTasks(request)
      .filter((task) => taskGroup(task) === "active")
      .sort((left, right) =>
        right.last_activity.localeCompare(left.last_activity),
      )[0] || null
  );
}
function requestPresentation(request) {
  const running = activeOperation(request.id);
  const deliveryOperation =
    running && deliveryOperationActions.has(running.intent.action)
      ? running
      : null;
  const activeTask = activeRequestTask(request);
  if (deliveryOperation || activeTask) {
    const operationStage =
      deliveryOperation?.intent.action === "PRODUCT_REPLY"
        ? "PRODUCT_DISCOVERY"
        : deliveryOperation?.intent.action === "PRODUCT_APPROVAL"
          ? "DESIGNING"
          : "DELIVERING";
    return {
      group: "active",
      status: activeTask?.status || operationStage,
      blocker: null,
      nextAction:
        activeTask?.next_action ||
        (deliveryOperation?.status === "QUEUED"
          ? "当前操作已排队，等待 Manager 执行。"
          : "当前操作正在执行。"),
    };
  }
  if (request.stage === "CLOSED")
    return {
      group: "closed",
      status: request.stage,
      blocker: null,
      nextAction: request.next_action,
    };
  if (request.stage === "DONE")
    return {
      group: "completed",
      status: request.stage,
      blocker: null,
      nextAction: request.next_action,
    };
  if (
    request.blocker ||
    request.stage.includes("WAITING") ||
    ["BLOCKED", "FAILED"].includes(request.stage)
  )
    return {
      group: "blocked",
      status: request.stage,
      blocker: request.blocker,
      nextAction: request.next_action,
    };
  return {
    group: "active",
    status: request.stage,
    blocker: null,
    nextAction: request.next_action,
  };
}

function agentQueueState(agent) {
  return {
    assigned_delivery_ids: [...agent.assigned_delivery_ids],
    current_stage_delivery_ids: [...agent.current_stage_delivery_ids],
    history_delivery_ids: [...agent.history_delivery_ids],
  };
}
function requestBlockingSummary(request) {
  if (requestPresentation(request).group !== "blocked") return null;
  // Verification attempts are audit history of the same native delivery, not
  // independent current blockers. Select its newest observation before filtering.
  const blockedTasks = currentRequestTasks(request).filter(
    (task) => taskGroup(task) === "blocked",
  );
  const reasons = new Map();
  for (const task of blockedTasks) {
    if (!task.blocker) continue;
    const scopes = reasons.get(task.blocker) || [];
    scopes.push(paths(task.scope));
    reasons.set(task.blocker, scopes);
  }
  if (!reasons.size && request.blocker) reasons.set(request.blocker, []);
  const operation = latestOperation(request.id);
  const approval = latestApproval(request.id, request.checkpoint_sha256);
  const operationReason =
    operation?.status === "FAILED"
      ? operation.error_summary
      : operationNeedsHumanAttention(operation)
        ? operation.result?.next_action
        : null;
  const nextActions = blockedTasks.map((task) => task.next_action).filter(
    (value, index, values) =>
      value &&
      !reasons.has(value) &&
      value !== operationReason &&
      values.indexOf(value) === index,
  );
  let suggestedAction = "处理上述原因后，再点击“继续交付”。";
  if (approval?.kind === "coder_scope")
    suggestedAction =
      "确认下方精确文件范围后点击“批准文件范围”；平台随后会生成恢复计划，并再次请求审批。";
  else if (approval?.kind === "coder_recovery")
    suggestedAction = "确认下方恢复任务信息后点击“批准并继续”。";
  else if (approval?.kind === "candidate_verification")
    suggestedAction = "确认下方独立验证计划后点击“批准并继续”。";
  else if (
    blockedTasks.some((task) =>
      String(task.blocker || "").includes(
        "QA verification could not complete in the current environment",
      ),
    )
  )
    suggestedAction =
      "点击下方“继续交付”，系统会保留现有候选代码并重新执行 QA/Review。";
  else if (
    blockedTasks.some((task) =>
      String(task.blocker || "").includes(
        "requested continuation after the configured run budget",
      ),
    )
  )
    suggestedAction =
      "点击下方“继续交付”，系统会基于当前 checkpoint 创建新的 Coder 恢复任务。";
  else if (nextActions.length)
    suggestedAction = nextActions.map(humanizeBlockingText).join("；");
  return {
    reasons: [...reasons.entries()].map(([reason, scopes]) => ({
      reason,
      scopes: [...new Set(scopes)],
    })),
    operationReason: reasons.has(operationReason) ? null : operationReason,
    approval,
    suggestedAction,
  };
}
function humanizeBlockingText(value) {
  const text = String(value || "").trim();
  if (!text) return "暂未记录具体原因。";
  if (
    text.includes("Coder requested continuation after the configured run budget")
  )
    return "Coder 已用完本轮连续执行次数，但实现尚未完成，需要创建恢复任务后继续。";
  if (
    text.includes(
      "QA verification could not complete in the current environment",
    )
  )
    return "QA 未能在当前环境完成验证；候选代码已保留，继续交付时只会重新执行 QA/Review。";
  if (
    text.includes(
      "failed Coder identity is missing, unsafe or ambiguous",
    ) ||
    text.includes(
      "recoverable Coder identity is missing, unsafe or ambiguous",
    )
  )
    return "系统未能确认唯一且可信的 Coder 执行记录，本次自动恢复已安全停止。";
  if (text === "REQUEST_HUMAN") return "需要人工处理后再继续交付。";
  if (text.startsWith("Repository ") && text.includes(" is BLOCKED"))
    return "至少一个代码仓库任务仍处于阻塞状态，联合交付尚未完成。";
  return text;
}
function requestBlockerSection(request) {
  const summary = requestBlockingSummary(request);
  if (!summary) return null;
  const section = el(
    "section",
    undefined,
    "detail-section request-blocking-section",
  );
  section.append(
    el("h2", "阻塞信息"),
    el(
      "p",
      "当前原因、最近恢复结果和建议操作都集中在这里。",
      "muted",
    ),
  );
  for (const item of summary.reasons) {
    const card = el("div", undefined, "request-blocking-primary");
    const scopeApproval = summary.approval?.kind === "coder_scope";
    card.append(
      el(
        "span",
        summary.approval ? "原始阻塞" : "当前阻塞",
        "request-blocking-kicker",
      ),
      el(
        "p",
        scopeApproval
          ? "Coder 的文件改动超出原任务授权范围，平台已保留工作现场并进入文件范围审批。"
          : humanizeBlockingText(item.reason),
        "request-blocking-reason",
      ),
    );
    if (item.scopes.length)
      card.append(
        el(
          "p",
          item.scopes.length === 1
            ? `影响目录 · ${item.scopes[0]}`
            : `涉及 ${item.scopes.length} 个仓库任务`,
          "request-blocking-scope paths",
        ),
      );
    section.append(card);
  }
  if (summary.operationReason) {
    const recovery = el("div", undefined, "request-recovery-note");
    recovery.append(
      el("strong", "最近一次恢复"),
      el("p", humanizeBlockingText(summary.operationReason)),
    );
    section.append(recovery);
  }
  const next = el("div", undefined, "request-blocking-next");
  next.append(
    el("span", "建议操作", "request-blocking-kicker"),
    el("p", summary.suggestedAction),
  );
  section.append(next);
  if (summary.approval)
    section.append(recoveryApprovalBox(request, summary.approval));
  return section;
}

function recoveryApprovalBox(request, approval) {
  const box = el("div", undefined, "approval-box request-blocking-approval");
  box.append(el("h3", approval.title));
  for (const fact of approval.facts) box.append(el("p", fact, "paths"));
  box.append(
    el(
      "p",
      approval.kind === "coder_scope"
        ? "批准后平台只会捕获上方精确文件，不会启动 Agent；捕获完成后仍需审批恢复计划。"
        : "批准后平台只执行上方计划；页面会把精确计划身份安全地带回 Manager。",
      "muted",
    ),
    button(
      approval.kind === "coder_scope" ? "批准文件范围" : "批准并继续",
      () =>
        submitOperation({
          action: "CONTINUE_DELIVERY",
          project_id: request.project_id,
          delivery_id: request.id,
          expected_checkpoint_sha256: request.checkpoint_sha256,
          ...(approval.kind === "coder_scope"
            ? { approved_scope_sha256: approval.plan_sha256 }
            : { approved_plan_sha256: approval.plan_sha256 }),
        }),
      "primary",
    ),
  );
  return box;
}
function paths(scope) {
  return scope.selected_paths
    .map((p) => (p === "." ? scope.root : scope.root + "/" + p))
    .join("\n");
}
function compactPath(value) {
  const parts = value.split("/").filter(Boolean);
  if (parts.length <= 3) return value;
  return `…/${parts.slice(-2).join("/")}`;
}
function compactPaths(value) {
  const values = value.split("\n");
  if (values.length === 1) return compactPath(values[0]);
  return `${compactPath(values[0])} 等 ${values.length} 个目录`;
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
function requestDialogue(parent, request) {
  const turns = request.dialogue || [];
  if (!turns.length && !productDiscussionStages.has(request.stage)) return null;
  const section = el("section", undefined, "detail-section product-dialogue");
  const heading = el("div", undefined, "row");
  heading.append(el("h2", "需求讨论"));
  if (turns.length) heading.append(el("span", `${turns.length} 轮消息`, "badge"));
  section.append(heading);
  if (turns.length) {
    const timeline = el("div", undefined, "dialogue-timeline");
    for (const turn of turns) {
      const message = el(
        "article",
        undefined,
        `dialogue-message ${turn.speaker === "user" ? "dialogue-user" : "dialogue-product"}`,
      );
      message.append(
        el("strong", turn.speaker === "user" ? "你" : "Product Agent"),
      );
      if (turn.text) message.append(el("p", turn.text, "dialogue-text"));
      if (turn.attachments?.length) {
        const attachments = el("div", undefined, "dialogue-attachments");
        for (const attachment of turn.attachments) {
          attachments.append(
            el(
              "span",
              `截图 · ${attachment.name} · ${Math.ceil(attachment.source_bytes / 1024)} KB`,
              "dialogue-attachment",
            ),
          );
        }
        message.append(attachments);
      }
      timeline.append(message);
    }
    section.append(timeline);
  }
  parent.append(section);
  return section;
}
function field(labelText, control, hint) {
  const wrapper = el("label", undefined, "field");
  wrapper.append(el("span", labelText));
  if (hint) wrapper.append(el("small", hint));
  wrapper.append(control);
  return wrapper;
}
function multiSelectField(labelText, hint, key, options, initialValues) {
  const selectedValues = new Set(initialValues);
  const checkboxes = new Map();
  const wrapper = el("div", undefined, "field");
  wrapper.append(el("span", labelText));
  if (hint) wrapper.append(el("small", hint));
  const control = el("details", undefined, "multi-select");
  control.dataset.key = key;
  const summary = el("summary");
  const updateSummary = () => {
    const selectedTitles = options
      .filter(([value]) => selectedValues.has(value))
      .map(([, title]) => title);
    summary.textContent = selectedTitles.length
      ? `${selectedTitles.join("、")}（${selectedTitles.length}）`
      : "请选择";
  };
  updateSummary();
  const choices = el("div", undefined, "multi-select-options");
  for (const [value, title] of options) {
    const choice = el("label", undefined, "multi-select-option");
    const checkbox = el("input");
    checkbox.type = "checkbox";
    checkbox.value = value;
    checkbox.checked = selectedValues.has(value);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) selectedValues.add(value);
      else selectedValues.delete(value);
      updateSummary();
    });
    checkboxes.set(value, checkbox);
    choice.append(checkbox, el("span", title));
    choices.append(choice);
  }
  control.append(summary, choices);
  wrapper.append(control);
  return {
    control: wrapper,
    values: () =>
      options
        .map(([value]) => value)
        .filter((value) => selectedValues.has(value)),
    setValues: (values) => {
      selectedValues.clear();
      for (const value of values) selectedValues.add(value);
      for (const [value, checkbox] of checkboxes)
        checkbox.checked = selectedValues.has(value);
      updateSummary();
    },
  };
}
function renderComposer() {
  const panel = document.getElementById("composer");
  panel.replaceChildren();
  panel.className = "";
  panel.hidden =
    !composing &&
    !creatingProject &&
    !editingRequirement &&
    !recreatingRequirement &&
    !knowledgeImportMode &&
    !pendingConfirmation &&
    !settingsSaveResult &&
    !editingKnowledgeDocument &&
    !editingSpecDocument;
  if (panel.hidden) return;
  panel.className = "modal-backdrop";
  const dialog = el("section", undefined, "modal-dialog");
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  if (settingsSaveResult) {
    const result = settingsSaveResult;
    const success = result.kind === "success";
    const canApply =
      success && result.restart_required && settingsSnapshot?.restart_required;
    const applyResult =
      success && result.restart_required ? configurationApplyResult : null;
    dialog.className = "modal-dialog settings-result-dialog";
    dialog.setAttribute("role", success ? "dialog" : "alertdialog");
    dialog.setAttribute(
      "aria-label",
      success ? "设置保存成功" : "设置保存失败",
    );
    const header = el("div", undefined, "settings-result-header");
    header.append(
      el(
        "span",
        success ? "✓" : "!",
        `settings-result-icon ${success ? "success" : "error"}`,
      ),
      el("div", success ? "设置保存成功" : "设置保存失败", "section-title"),
    );
    const close = button(
      "知道了",
      () => {
        settingsSaveResult = null;
        renderComposer();
      },
      success && !canApply ? "primary" : "",
    );
    const actions = el("div", undefined, "modal-actions");
    actions.append(close);
    if (canApply) {
      const apply = button(
        configurationApplyInFlight ? "正在应用…" : "应用配置",
        applySavedConfiguration,
        "primary",
      );
      apply.disabled = configurationApplyInFlight;
      actions.append(apply);
    }
    dialog.append(
      header,
      el(
        "p",
        success && result.restart_required && configurationApplyInFlight
          ? "配置已保存，正在重启并等待 Web Console 恢复连接。"
          : applyResult?.message || result.message,
        applyResult?.kind === "error" ? "operation-error" : "settings-result-message",
      ),
      actions,
    );
    panel.append(dialog);
    close.focus();
    return;
  }
  if (pendingConfirmation) {
    const confirmation = pendingConfirmation;
    const feedback = el("p", "", "form-feedback");
    const cancel = button("取消", () => {
      pendingConfirmation = null;
      renderComposer();
    });
    const proceed = button(
      confirmation.confirmText,
      async () => {
        proceed.disabled = true;
        try {
          await confirmation.action();
          pendingConfirmation = null;
          render();
        } catch (error) {
          feedback.className = "form-feedback error";
          feedback.textContent =
            error instanceof Error ? error.message : "操作失败。";
          proceed.disabled = false;
        }
      },
      "danger",
    );
    const actions = el("div", undefined, "modal-actions");
    actions.append(cancel, proceed);
    dialog.append(
      el("div", confirmation.title, "section-title"),
      el("p", confirmation.message, "modal-introduction"),
      feedback,
      actions,
    );
    panel.append(dialog);
    return;
  }
  if (editingKnowledgeDocument) {
    dialog.className = "modal-dialog modal-dialog-wide";
    const editing = editingKnowledgeDocument;
    const form = el(
      "form",
      undefined,
      "knowledge-content-edit-form knowledge-upload",
    );
    const content = el("textarea", undefined, "knowledge-content-editor");
    content.rows = 18;
    content.required = true;
    content.value = editing.content_markdown;
    content.addEventListener("input", () => {
      editing.content_markdown = content.value;
    });
    const feedback = el("p", "", "form-feedback");
    const cancel = button("取消", () => {
      editingKnowledgeDocument = null;
      renderComposer();
    });
    const submit = el("button", "保存更新", "primary");
    submit.type = "submit";
    const actions = el("div", undefined, "modal-actions");
    actions.append(cancel, submit);
    form.append(
      field(
        "Markdown 正文",
        content,
        "保存后会发布一份新记录并保留历史版本；已启用状态会自动继承。",
      ),
      feedback,
      actions,
    );
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!content.value.trim()) {
        feedback.className = "form-feedback error";
        feedback.textContent = "文档正文不能为空。";
        return;
      }
      submit.disabled = true;
      try {
        const base =
          editing.scope === "team"
            ? "/api/v1/admin/team/knowledge"
            : "/api/v1/admin/projects/" +
              encodeURIComponent(editing.project_id) +
              "/knowledge";
        const markdownName =
          editing.source_name.replace(/\.[^.]+$/, "") + ".md";
        await adminFetch(
          base +
            "/" +
            encodeURIComponent(editing.document_id) +
            "?filename=" +
            encodeURIComponent(markdownName),
          {
            method: "PUT",
            headers: { "Content-Type": "application/octet-stream" },
            body: content.value,
          },
        );
        editingKnowledgeDocument = null;
        await loadKnowledge();
        const knowledgeLabel = knowledgeLabelForScope(editing.scope);
        administrationNotice = {
          page: "knowledge",
          text: `${knowledgeLabel}更新已排队，解析完成后继承原启用状态；只影响之后准备的新需求。`,
        };
        render();
      } catch (error) {
        feedback.className = "form-feedback error";
        feedback.textContent =
          error instanceof Error
            ? error.message
            : `${knowledgeLabelForScope(editing.scope)}更新失败。`;
        submit.disabled = false;
      }
    });
    dialog.append(
      el(
        "div",
        `更新${knowledgeLabelForScope(editing.scope)}`,
        "section-title",
      ),
      el("p", editing.source_name, "muted modal-introduction"),
      form,
    );
    panel.append(dialog);
    content.focus();
    return;
  }
  if (editingSpecDocument) {
    dialog.className = "modal-dialog modal-dialog-wide";
    const editing = editingSpecDocument;
    const spec = editing.document;
    const form = el(
      "form",
      undefined,
      "spec-content-edit-form knowledge-upload",
    );
    const title = el("input");
    title.value = spec.title;
    title.required = true;
    title.maxLength = 200;
    const content = el("textarea", undefined, "spec-content-editor");
    content.rows = 18;
    content.required = true;
    content.value = spec.body_markdown;
    const roles = multiSelectField(
      "适用角色",
      "支持多选；至少选择一个角色。",
      `${editing.scope}-edit-spec-roles`,
      specRoleOptions,
      spec.roles,
    );
    const stages = multiSelectField(
      "适用阶段",
      "支持多选；至少选择一个交付阶段。",
      `${editing.scope}-edit-spec-stages`,
      specStageOptions,
      spec.stages,
    );
    const repositories = el("textarea");
    repositories.rows = 2;
    repositories.value = spec.repository_ids.join("\n");
    const paths = el("textarea");
    paths.rows = 2;
    paths.value = spec.path_globs.join("\n");
    const verification = el("textarea");
    verification.rows = 3;
    verification.placeholder = "可选：测试命令、静态检查或评审证据";
    verification.value = spec.verification;
    const feedback = el("p", "", "form-feedback");
    const cancel = button("取消", () => {
      editingSpecDocument = null;
      renderComposer();
    });
    const submit = el("button", "保存规范更新", "primary");
    submit.type = "submit";
    const actions = el("div", undefined, "modal-actions");
    actions.append(cancel, submit);
    form.append(
      field("规范名称", title),
      field("规范正文", content),
      roles.control,
      stages.control,
      field("适用仓库", repositories, "留空表示当前范围内全部仓库。"),
      field("适用路径", paths, "每行一个相对 glob。"),
      field("验证方式", verification, "可以暂时留空。"),
      feedback,
      actions,
    );
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const selectedRoles = roles.values();
      const selectedStages = stages.values();
      if (!selectedRoles.length || !selectedStages.length) {
        feedback.className = "form-feedback error";
        feedback.textContent = "适用角色和适用阶段都至少需要选择一项。";
        return;
      }
      submit.disabled = true;
      try {
        const endpoint =
          editing.scope === "team"
            ? "/api/v1/admin/team/specs"
            : "/api/v1/admin/projects/" +
              encodeURIComponent(editing.project_id) +
              "/specs";
        await adminFetch(endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            spec_key: spec.spec_key,
            title: title.value.trim(),
            body_markdown: content.value,
            roles: selectedRoles,
            stages: selectedStages,
            repository_ids: csvValues(repositories.value).sort(),
            path_globs: csvValues(paths.value),
            verification: verification.value.trim(),
          }),
        });
        editingSpecDocument = null;
        await loadKnowledge();
        administrationNotice = {
          page: "knowledge",
          text: "开发规范更新已保存但尚未启用。请检查后再启用更新。",
        };
        render();
      } catch (error) {
        feedback.className = "form-feedback error";
        feedback.textContent =
          error instanceof Error ? error.message : "开发规范更新失败。";
        submit.disabled = false;
      }
    });
    dialog.append(
      el("div", "更新开发规范", "section-title"),
      el(
        "p",
        "保存会创建可追溯的新版本，不会改写历史交付。",
        "muted modal-introduction",
      ),
      form,
    );
    panel.append(dialog);
    content.focus();
    return;
  }
  if (knowledgeImportMode === "background") {
    renderBackgroundKnowledgeImport(dialog);
    panel.append(dialog);
    return;
  }
  if (knowledgeImportMode === "specs") {
    renderSpecImport(dialog);
    panel.append(dialog);
    return;
  }
  const isEditingRequirement = Boolean(editingRequirement);
  const isRecreatingRequirement = Boolean(recreatingRequirement);
  const top = el("div", undefined, "row");
  top.append(
    el(
      "div",
      creatingProject
        ? "新建 Project"
        : isEditingRequirement
          ? "编辑需求"
          : isRecreatingRequirement
            ? "基于当前代码新建需求"
            : "新建需求",
      "section-title",
    ),
    button(
      "取消",
      () => {
        composing = false;
        creatingProject = false;
        editingRequirement = null;
        recreatingRequirement = null;
        renderComposer();
      },
      "",
    ),
  );
  if (creatingProject) {
    const form = el("form", undefined, "project-form project-create-form");
    const name = el("input");
    name.placeholder = "例如：订单履约平台";
    name.maxLength = 200;
    name.required = true;
    const feedback = el("p", "", "form-feedback");
    const submit = el("button", "创建 Project", "primary");
    submit.type = "submit";
    form.append(
      field(
        "Project 名称",
        name,
        "Project 用于归集代码目录、需求、背景知识和开发规范。",
      ),
      feedback,
      submit,
    );
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      submit.disabled = true;
      try {
        const created = await adminFetch("/api/v1/admin/projects", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: name.value.trim() }),
        });
        administrationNotice = {
          page: "requests",
          text: "Project 已创建并选中，现在可以创建 Requirement。",
        };
        creatingProject = false;
        await refresh(created.project_id);
        render();
      } catch (error) {
        feedback.className = "form-feedback error";
        feedback.textContent =
          error instanceof Error ? error.message : "Project 创建失败。";
        submit.disabled = false;
      }
    });
    dialog.append(
      top,
      el(
        "p",
        "创建后可继续登记一个或多个代码目录，并维护独立的项目知识与规范。",
        "muted modal-introduction",
      ),
      form,
    );
    panel.append(dialog);
    name.focus();
    return;
  }
  const form = el("form", undefined, "project-form");
  const name = el("input");
  name.name = "name";
  name.required = true;
  name.maxLength = 200;
  name.placeholder = "例如：统一登录体验升级";
  const sourceRequirement = editingRequirement || recreatingRequirement;
  if (sourceRequirement) name.value = sourceRequirement.title;
  const selectedRoots = sourceRequirement
    ? sourceRequirement.scopes.flatMap((scope) =>
        scope.selected_paths.map((selectedPath) =>
          selectedPath === "."
            ? scope.root
            : scope.root.replace(/\/$/, "") + "/" + selectedPath,
        ),
      )
    : [];
  const roots = el("div", undefined, "directory-selection");
  const rootList = el("div", undefined, "directory-chip-list");
  const chooseRoots = button(
    "选择代码目录",
    async () => {
      chooseRoots.disabled = true;
      feedback.className = "form-feedback";
      feedback.textContent = "正在打开本机目录选择器…";
      try {
        const result = await adminFetch("/api/v1/admin/directories/select", {
          method: "POST",
        });
        let exceededDirectoryLimit = false;
        for (const path of result.directories || []) {
          if (selectedRoots.includes(path)) continue;
          if (selectedRoots.length >= 32) exceededDirectoryLimit = true;
          else selectedRoots.push(path);
        }
        renderSelectedRoots();
        feedback.textContent = result.cancelled
          ? "未选择新目录。"
          : exceededDirectoryLimit
            ? "一次需求最多选择 32 个目录，超出部分未添加。"
            : "代码目录已选择。";
      } catch (error) {
        feedback.className = "form-feedback error";
        feedback.textContent =
          error instanceof Error ? error.message : "无法打开目录选择器。";
      } finally {
        chooseRoots.disabled = false;
      }
    },
    "secondary",
  );
  chooseRoots.type = "button";
  const renderSelectedRoots = () => {
    rootList.replaceChildren();
    if (!selectedRoots.length)
      rootList.append(el("p", "尚未选择代码目录。", "muted"));
    selectedRoots.forEach((path) => {
      const chip = el("div", undefined, "directory-chip");
      chip.append(
        el("span", path, "paths"),
        button("移除", () => {
          selectedRoots.splice(selectedRoots.indexOf(path), 1);
          renderSelectedRoots();
        }),
      );
      rootList.append(chip);
    });
  };
  roots.append(chooseRoots, rootList);
  renderSelectedRoots();
  const feedback = el("p", "", "form-feedback");
  const submit = el(
    "button",
    isEditingRequirement
      ? "保存需求修改"
      : isRecreatingRequirement
        ? "基于当前代码创建"
        : "创建并准备需求",
    "primary",
  );
  submit.type = "submit";
  form.append(
    field("需求名称", name),
    field(
      "涉及的代码目录",
      roots,
      "可一次选择多个目录；目录必须属于当前电脑，首次选择时由 Manager 完成登记。",
    ),
    feedback,
    submit,
  );
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const projectRoots = [...selectedRoots];
    if (!name.value.trim() || !projectRoots.length) {
      feedback.textContent = "请填写需求名称和至少一个绝对代码目录。";
      feedback.className = "form-feedback error";
      return;
    }
    submit.disabled = true;
    feedback.className = "form-feedback";
    feedback.textContent = "Manager 正在接单…";
    const accepted = await submitOperation(
      isEditingRequirement
        ? {
            action: "UPDATE_REQUIREMENT",
            project_id: editingRequirement.project_id,
            delivery_id: editingRequirement.id,
            expected_checkpoint_sha256:
              editingRequirement.checkpoint_sha256,
            name: name.value.trim(),
            repository_roots: projectRoots,
          }
        : {
            action: "CREATE_REQUIREMENT",
            project_id:
              recreatingRequirement?.project_id || snapshot.selected_project_id,
            name: name.value.trim(),
            repository_roots: projectRoots,
          },
    );
    if (accepted) {
      composing = false;
      editingRequirement = null;
      recreatingRequirement = null;
      renderComposer();
    } else {
      feedback.textContent = "创建失败，请查看上方操作状态后重试。";
      feedback.className = "form-feedback error";
      submit.disabled = false;
    }
  });
  dialog.append(
    top,
    el(
      "p",
      isEditingRequirement
        ? "保存后会生成新的需求版本并替换当前草稿；原始记录仍保留用于审计。"
        : isRecreatingRequirement
          ? "使用当前 Repository HEAD 创建新的 Requirement；旧需求及其讨论记录仍保留，创建成功后可删除旧需求。"
          : `需求归属当前 Project：${projectName()}。创建后由 Manager 从产品澄清开始推进。`,
      "muted modal-introduction",
    ),
    form,
  );
  panel.append(dialog);
  name.focus();
}
function confirmMutation(title, message, confirmText, action) {
  composing = false;
  creatingProject = false;
  editingRequirement = null;
  recreatingRequirement = null;
  knowledgeImportMode = null;
  editingKnowledgeDocument = null;
  editingSpecDocument = null;
  pendingConfirmation = { title, message, confirmText, action };
  renderComposer();
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
  panel.hidden = page !== "requests";
  if (panel.hidden) return;
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
  if (consoleAvailable === true && consoleDeliveryReady === false) {
    panel.append(
      el(
        "div",
        "控制台正在使用默认或待配置运行时。请先完成设置并重启，再创建或继续需求。",
        "operation-error",
      ),
    );
    return;
  }
  if (snapshot && consoleTeamId && snapshot.team_id !== consoleTeamId) {
    panel.append(
      el(
        "div",
        "当前后台服务未绑定这个 Team；此工作台暂时只能查看，不能提交交付操作。",
        "operation-error",
      ),
    );
    return;
  }
  const visible = [...operations]
    .filter((operation) => {
      if (
        (operation.status === "SUCCEEDED" &&
          !operationNeedsHumanAttention(operation)) ||
        dismissedOperationIds.has(operation.operation_id)
      )
        return false;
      if (
        operationNeedsHumanAttention(operation) &&
        latestOperation(operationTarget(operation))?.operation_id !==
          operation.operation_id
      )
        return false;
      if (!["FAILED", "INTERRUPTED"].includes(operation.status)) return true;
      return !operations.some(
        (candidate) =>
          candidate.status === "SUCCEEDED" &&
          candidate.intent.action === operation.intent.action &&
          operationTarget(candidate) === operationTarget(operation) &&
          candidate.updated_at > operation.updated_at,
      );
    })
    .sort((left, right) => right.updated_at.localeCompare(left.updated_at))
    .slice(0, 5);
  if (!visible.length) {
    panel.hidden = true;
    return;
  }
  for (const operation of visible) {
    const needsHumanAttention = operationNeedsHumanAttention(operation);
    const card = el("div", undefined, "operation-status");
    const row = el("div", undefined, "row");
    const state = el("div", undefined, "operation-status-actions");
    state.append(
      badge(needsHumanAttention ? operation.result.stage : operation.status),
    );
    if (
      ["FAILED", "INTERRUPTED"].includes(operation.status) ||
      needsHumanAttention
    )
      state.append(
        button("关闭", () => {
          dismissedOperationIds.add(operation.operation_id);
          try {
            globalThis.localStorage?.setItem(
              "ase-dismissed-console-operations",
              JSON.stringify([...dismissedOperationIds].slice(-100)),
            );
          } catch {
            // Browser storage is optional; the current page can still dismiss it.
          }
          renderOperationStatus();
        }),
      );
    row.append(el("strong", label(operation.intent.action)), state);
    card.append(row);
    if (["QUEUED", "RUNNING"].includes(operation.status))
      card.append(
        el(
          "p",
          operation.status === "QUEUED"
            ? "已安全接单，等待 Manager 执行。"
            : "交付流程正在执行；可以刷新或关闭页面。",
          "muted",
        ),
      );
    const target = operationTarget(operation);
    if (
      target &&
      (needsHumanAttention || ["FAILED", "INTERRUPTED"].includes(operation.status))
    )
      card.append(
        el(
          "p",
          "操作需要处理，具体原因已归入需求详情的“阻塞信息”。",
          "muted",
        ),
      );
    else if (operation.error_summary)
      card.append(el("div", operation.error_summary, "blocker"));
    if (target)
      card.append(
        button("打开需求工作区", () => {
          page = "requests";
          updateNavigation();
          showDetail("request", target);
        }),
      );
    panel.append(card);
  }
}
function agentWorkGroup(work) {
  return work.kind === "task" ? taskGroup(work.item) : requestGroup(work.item);
}
function collapseVerificationQueue(agent, assigned, history, currentIds) {
  if (!agent.roles.some((role) => ["qa", "reviewer"].includes(role)))
    return { assigned, history };
  const assignedIds = new Set(assigned.map((work) => work.id));
  const selected = new Map();
  for (const work of [...assigned, ...history]) {
    const requirementId =
      work.kind === "request" ? work.item.id : work.item.request_id || work.item.id;
    const priority = currentIds.has(work.id)
      ? 3
      : assignedIds.has(work.id)
        ? 2
        : 1;
    const candidate = {
      work,
      priority,
      activity: work.item.last_activity || "",
    };
    const existing = selected.get(requirementId);
    if (
      !existing ||
      candidate.priority > existing.priority ||
      (candidate.priority === existing.priority &&
        candidate.activity.localeCompare(existing.activity) > 0)
    )
      selected.set(requirementId, candidate);
  }
  const representatives = [...selected.values()].map((candidate) => candidate.work);
  return {
    assigned: representatives.filter((work) => assignedIds.has(work.id)),
    history: representatives.filter((work) => !assignedIds.has(work.id)),
  };
}
function taskRow(work, agentId) {
  const task = work.item;
  const n = el("article", undefined, "work-row");
  n.setAttribute("role", "button");
  n.setAttribute("tabindex", "0");
  n.setAttribute(
    "aria-label",
    `查看${work.kind === "task" ? "任务" : "需求"}详情：${task.title}`,
  );
  const openTask = () => showDetail(work.kind, task.id);
  n.addEventListener("click", openTask);
  n.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    openTask();
  });
  const row = el("div", undefined, "work-row-heading");
  const request =
    work.kind === "request" ? task : requestById(task.request_id);
  row.append(el("strong", request ? request.title : task.title, "work-row-title"));
  const a = task.assignments?.find((a) => a.agent_id === agentId);
  n.append(row);
  const fullPath =
    work.kind === "task"
      ? paths(task.scope)
      : task.scopes.map((scope) => paths(scope)).join(" · ");
  const scope = el("div", undefined, "work-row-scope");
  scope.append(
    el("span", "目录", "work-row-scope-label"),
    el("span", compactPaths(fullPath), "work-row-path"),
  );
  scope.setAttribute("title", fullPath);
  const overview = el("div", undefined, "work-row-overview");
  if (a) overview.append(el("span", label(a.role), "work-row-role"));
  else {
    const agent = snapshot.agents.find((candidate) => candidate.id === agentId);
    if (agent?.roles.length)
      overview.append(
        el("span", agent.roles.map(label).join(" / "), "work-row-role"),
      );
  }
  overview.append(scope);
  n.append(overview);
  return n;
}
function renderTeam(content) {
  const summary = el("section", undefined, "summary team-summary");
  for (const [count, title] of [
    [snapshot.agents.length, "位团队成员"],
    [
      snapshot.tasks.filter((t) => !t.terminal).length,
      "项当前 Project 未结束任务",
    ],
    [
      snapshot.requests.filter((r) => r.blocker).length,
      "项当前 Project 待处理需求",
    ],
  ]) {
    const n = el("span", undefined, "summary-card");
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
  const orderedAgents = snapshot.agents
    .map((agent, index) => ({ agent, index }))
    .sort((left, right) => {
      const leftOrder = Math.min(
        ...left.agent.roles.map((role) => teamRoleOrder[role] ?? 1000),
      );
      const rightOrder = Math.min(
        ...right.agent.roles.map((role) => teamRoleOrder[role] ?? 1000),
      );
      return leftOrder - rightOrder || left.index - right.index;
    })
    .map(({ agent }) => agent);
  if (!orderedAgents.length) return;
  const queueStates = new Map(
    orderedAgents.map((agent) => [agent.id, agentQueueState(agent)]),
  );
  if (!orderedAgents.some((agent) => agent.id === selectedAgentId))
    selectedAgentId =
      orderedAgents.find(
        (agent) => queueStates.get(agent.id).current_stage_delivery_ids.length,
      )?.id || orderedAgents[0].id;
  const heading = el("div", undefined, "section-heading");
  heading.append(
    el("div", "长期团队成员", "section-title"),
    el("span", `工作负载 · ${projectName()}`, "badge"),
  );
  content.append(heading);
  const workspace = el("div", undefined, "agent-workspace");
  const roster = el("aside", undefined, "agent-roster");
  roster.setAttribute("aria-label", "团队成员列表");
  for (const agent of orderedAgents) {
    const queueState = queueStates.get(agent.id);
    const memberStatus = !agent.enabled
      ? ["已停用", "badge"]
      : queueState.current_stage_delivery_ids.length
        ? ["执行中", "badge current"]
        : queueState.assigned_delivery_ids.length
          ? ["等待当前阶段", "badge"]
          : ["空闲中", "badge done"];
    const control = button(
      "",
      () => {
        selectedAgentId = agent.id;
        render();
      },
      selectedAgentId === agent.id ? "agent selected" : "agent",
    );
    const identity = el("span", undefined, "identity");
    const name = el("span");
    name.append(
      el("strong", agent.name),
      el("small", agent.roles.map(label).join(" / "), "muted"),
    );
    identity.append(el("span", agent.name.slice(0, 1), "avatar"), name);
    control.append(identity, el("span", memberStatus[0], memberStatus[1]));
    roster.append(control);
  }
  const agent = orderedAgents.find((item) => item.id === selectedAgentId);
  const board = el("section", undefined, "agent-board");
  const boardHeading = el("div", undefined, "row agent-board-heading");
  boardHeading.append(
    el("div", `${agent.name} · 任务队列`, "section-title"),
    el("span", `并发上限 ${agent.max_parallel_assignments}（配置值）`, "badge"),
  );
  board.append(boardHeading);
  const queueState = queueStates.get(agent.id);
  let assigned = queueState.assigned_delivery_ids
    .map(agentWorkById)
    .filter(Boolean);
  let history = queueState.history_delivery_ids
    .map(agentWorkById)
    .filter(Boolean);
  const currentIds = new Set(queueState.current_stage_delivery_ids);
  ({ assigned, history } = collapseVerificationQueue(
    agent,
    assigned,
    history,
    currentIds,
  ));
  const blockedIds = new Set(
    [...assigned, ...history]
      .filter((work) => agentWorkGroup(work) === "blocked")
      .map((work) => work.id),
  );
  const queues = [
    [
      "待完成",
      assigned.filter(
        (work) =>
          !blockedIds.has(work.id) &&
          !currentIds.has(work.id),
      ),
      "waiting",
    ],
    [
      "进行中",
      assigned.filter(
        (work) =>
          !blockedIds.has(work.id) && currentIds.has(work.id),
      ),
      "active",
    ],
    [
      "已阻塞",
      [...assigned, ...history].filter(
        (work, index, items) =>
          blockedIds.has(work.id) &&
          items.findIndex((candidate) => candidate.id === work.id) === index,
      ),
      "blocked",
    ],
    [
      "已完成",
      history.filter((work) => !blockedIds.has(work.id)),
      "completed",
    ],
  ];
  const columns = el("div", undefined, "agent-queue-board");
  for (const [title, tasks, state] of queues) {
    const column = el("section", undefined, `agent-queue ${state}`);
    const columnHeading = el("div", undefined, "agent-queue-heading");
    columnHeading.append(
      el("strong", title),
      el("span", String(tasks.length), "badge"),
    );
    column.append(columnHeading);
    if (!tasks.length) column.append(el("p", `暂无${title}任务。`, "muted"));
    for (const task of tasks) column.append(taskRow(task, agent.id));
    columns.append(column);
  }
  board.append(
    el(
      "p",
      `仅展示 ${projectName()} 的任务；Agent 仍归唯一 Team 所有。`,
      "muted",
    ),
    columns,
  );
  workspace.append(roster, board);
  content.append(workspace);
  content.append(
    el(
      "p",
      "成员属于唯一 Team，并可跨 Project 持续工作。“空闲中”描述任务分配，不代表 Agent 进程在线。",
      "muted",
    ),
  );
}
function requestCard(request) {
  const presentation = requestPresentation(request);
  const isSelected = selected?.kind === "request" && selected.id === request.id;
  const card = el(
      "article",
      undefined,
      isSelected ? "request request-selected" : "request",
    ),
    head = el("div", undefined, "row");
  const open = () => showDetail("request", request.id);
  card.setAttribute("role", "button");
  card.setAttribute("tabindex", "0");
  if (isSelected) card.setAttribute("aria-current", "true");
  card.addEventListener("click", open);
  card.addEventListener("keydown", (event) => {
    if (!["Enter", " "].includes(event.key)) return;
    event.preventDefault();
    open();
  });
  head.append(
    el("strong", request.title, "request-title"),
    badge(presentation.status),
  );
  card.append(el("p", request.id, "request-id"), head);
  const write = request.scopes.filter((s) => !s.reference_only),
    done = write.filter(
      (s) => taskById(s.delivery_id)?.status === "DONE",
    ).length;
  card.append(
    el(
      "p",
      `${request.scopes.length} 个代码目录 · ${done}/${write.length} 个改造任务完成`,
      "muted request-summary",
    ),
  );
  return card;
}
function requestOperation(panel, request, discussionSection) {
  if (!canControlCurrentTeam()) return;
  const appendOperation = (content) => {
    const section = el(
      "section",
      undefined,
      "detail-section request-operation",
    );
    section.append(content);
    panel.append(section);
  };
  const appendDiscussionContent = (content) => {
    if (discussionSection) discussionSection.append(content);
    else appendOperation(content);
  };
  const running = activeOperation(request.id);
  const isProductDiscussion = productDiscussionStages.has(request.stage);
  const sourceRevisionDrift = isSourceRevisionDrift(
    latestOperation(request.id),
  );
  const approvingProduct = running?.intent.action === "PRODUCT_APPROVAL";
  // A terminal browser operation may leave an admitted QA/Reviewer item visible until
  // Manager creates its successor plan. Only a live Console operation suppresses the
  // recovery action; the durable task projection alone must not strand the operator.
  if (running && !isProductDiscussion) return;
  if (running) {
    appendDiscussionContent(
      el(
        "div",
        running.status === "QUEUED"
          ? approvingProduct
            ? "ProductSpec 批准操作已排队，等待 Manager。"
            : "需求讨论已排队，等待 Product Agent。"
          : approvingProduct
            ? "Manager 正在批准 ProductSpec。"
            : "Product Agent 正在回复，可以离开页面后再回来。",
        "operation-running",
      ),
    );
  }
  if (sourceRevisionDrift && !running) {
    const box = el("div", undefined, "operation-error");
    box.append(
      el("h3", "代码版本已变化"),
      el(
        "p",
        "该需求绑定的代码版本与当前 Repository HEAD 不一致，不能继续当前流程。请基于当前代码创建一个新需求。",
      ),
      el(
        "p",
        "旧需求及讨论记录会继续保留，确认新需求创建成功后可以删除旧需求。",
        "muted",
      ),
      button(
        "基于当前代码新建需求",
        () => {
          creatingProject = false;
          editingRequirement = null;
          recreatingRequirement = request;
          composing = true;
          renderComposer();
        },
        "primary",
      ),
    );
    appendDiscussionContent(box);
    return;
  }
  const approval = latestApproval(request.id, request.checkpoint_sha256);
  if (approval && !running) {
    if (requestPresentation(request).group !== "blocked")
      appendOperation(recoveryApprovalBox(request, approval));
    return;
  }
  if (request.stage === "WAITING_PRODUCT_APPROVAL" && !running) {
    const approval = el("div", undefined, "approval-box");
    approval.append(
      el("h3", "产品文档已准备好"),
      el(
        "p",
        "请先阅读下方 ProductSpec。确认内容准确后批准；如果仍需调整，可在下方继续和 Product Agent 讨论。",
        "muted",
      ),
      button(
        "批准 ProductSpec 并开始交付",
        () =>
          submitOperation({
            action: "PRODUCT_APPROVAL",
            project_id: request.project_id,
            delivery_id: request.id,
            expected_checkpoint_sha256: request.checkpoint_sha256,
          }),
        "primary",
      ),
    );
    appendDiscussionContent(approval);
  }
  if (isProductDiscussion) {
    const form = el("form", undefined, "discussion-form");
    const message = el("textarea");
    let discussionTitle = "等待 Product Agent 回复";
    let messagePlaceholder =
      "上一条消息正在处理中，收到 Product Agent 回复后可继续输入。";
    let submitLabel = "继续需求讨论";
    if (running) {
      discussionTitle = approvingProduct
        ? "ProductSpec 批准处理中"
        : "等待 Product Agent 回复";
      messagePlaceholder = approvingProduct
        ? "ProductSpec 正在批准，完成前不能继续修改。"
        : "Product Agent 正在处理上一条消息，完成后可继续输入。";
      submitLabel = approvingProduct
        ? "正在批准 ProductSpec"
        : "Product Agent 正在回复";
    } else if (request.stage === "READY_FOR_DISCUSSION") {
      discussionTitle = "向 Product Agent 描述需求";
      messagePlaceholder = "描述你要完成的需求、业务背景和验收预期…";
      submitLabel = "提交需求";
    } else if (request.stage === "WAITING_PRODUCT_REPLY") {
      discussionTitle = "回复 Product Agent";
      messagePlaceholder = "回答 Product Agent 的问题，或继续补充需求信息…";
      submitLabel = "回复 Product Agent";
    } else if (request.stage === "WAITING_PRODUCT_APPROVAL") {
      discussionTitle = "继续讨论并修订";
      messagePlaceholder = "说明 ProductSpec 需要修改或补充的内容…";
      submitLabel = "提交修改并重新生成 ProductSpec";
    }
    const replyEnabled = request.stage !== "PRODUCT_DISCOVERY" && !running;
    message.rows = 5;
    message.maxLength = 20000;
    message.disabled = !replyEnabled;
    message.setAttribute("aria-label", discussionTitle);
    message.placeholder = messagePlaceholder;
    const feedback = el("p", "", "form-feedback");
    let selectedScreenshots = [];
    let screenshotPreviewUrls = [];
    const screenshotSection = el("div", undefined, "pasted-screenshot-section");
    const screenshotList = el("div", undefined, "screenshot-list");
    screenshotSection.append(el("strong", "已粘贴的需求截图"), screenshotList);
    const revokeScreenshotPreviews = () => {
      if (typeof URL === "undefined" || !URL.revokeObjectURL) return;
      screenshotPreviewUrls.forEach((url) => URL.revokeObjectURL(url));
      screenshotPreviewUrls = [];
    };
    const renderScreenshots = () => {
      revokeScreenshotPreviews();
      screenshotList.replaceChildren();
      screenshotSection.hidden = !selectedScreenshots.length;
      selectedScreenshots.forEach((item, index) => {
        const card = el("div", undefined, "screenshot-chip");
        if (typeof URL !== "undefined" && URL.createObjectURL) {
          const preview = el("img");
          const previewUrl = URL.createObjectURL(item.file);
          screenshotPreviewUrls.push(previewUrl);
          preview.src = previewUrl;
          preview.alt = item.name;
          card.append(preview);
        }
        card.append(
          el("span", `${item.name} · ${Math.ceil(item.file.size / 1024)} KB`),
          button("移除", () => {
            selectedScreenshots.splice(index, 1);
            feedback.className = "form-feedback";
            feedback.textContent = "";
            renderScreenshots();
          }),
        );
        screenshotList.append(card);
      });
    };
    const addPastedScreenshots = (files) => {
      if (!replyEnabled) return;
      const invalid = files.find(
        (file) =>
          !["image/png", "image/jpeg", "image/webp"].includes(file.type) ||
          file.size > 10000000,
      );
      if (invalid) {
        feedback.className = "form-feedback error";
        feedback.textContent =
          "截图仅支持 PNG、JPEG、WebP，且单张不能超过 10 MB。";
        return;
      }
      const available = Math.max(0, 4 - selectedScreenshots.length);
      const accepted = files.slice(0, available).map((file, index) => {
        const suffix = {
          "image/png": "png",
          "image/jpeg": "jpg",
          "image/webp": "webp",
        }[file.type];
        return {
          file,
          name:
            file.name?.trim() ||
            `clipboard-${Date.now()}-${selectedScreenshots.length + index + 1}.${suffix}`,
        };
      });
      selectedScreenshots.push(...accepted);
      feedback.className = "form-feedback";
      feedback.textContent =
        files.length > available
          ? "一次回复最多提交 4 张截图。"
          : "截图已添加。";
      renderScreenshots();
    };
    message.addEventListener("paste", (event) => {
      const clipboard = event.clipboardData;
      if (!clipboard) return;
      const files = clipboard.items
        ? [...clipboard.items]
            .filter(
              (item) => item.kind === "file" && item.type.startsWith("image/"),
            )
            .map((item) => item.getAsFile())
            .filter(Boolean)
        : [...(clipboard.files || [])].filter((file) =>
            file.type.startsWith("image/"),
          );
      if (files.length) addPastedScreenshots(files);
    });
    renderScreenshots();
    const submit = el("button", submitLabel, "primary");
    submit.type = request.stage === "PRODUCT_DISCOVERY" ? "button" : "submit";
    submit.disabled = Boolean(running);
    const discussionField = el("div", undefined, "field discussion-field");
    discussionField.append(
      el("h3", discussionTitle),
      el(
        "small",
        replyEnabled
          ? "输入文字，或将截图直接粘贴到这里；两者至少提供一项。"
          : running
            ? "Product Agent 正在处理上一条消息，完成后可继续输入。"
            : "上次 Product Agent 执行已中断，先恢复本轮回复后再继续输入。",
      ),
      message,
    );
    form.append(
      discussionField,
      screenshotSection,
      feedback,
      submit,
    );
    if (request.stage === "PRODUCT_DISCOVERY" && !running) {
      submit.addEventListener("click", () =>
        submitOperation({
          action: "CONTINUE_DELIVERY",
          project_id: request.project_id,
          delivery_id: request.id,
          expected_checkpoint_sha256: request.checkpoint_sha256,
        }),
      );
    }
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!replyEnabled) return;
      if (!message.value.trim() && !selectedScreenshots.length) {
        feedback.className = "form-feedback error";
        feedback.textContent = "请填写需求说明或添加至少一张截图。";
        return;
      }
      submit.disabled = true;
      feedback.className = "form-feedback";
      feedback.textContent = selectedScreenshots.length
        ? "正在保存截图…"
        : "已提交，等待 Product Agent…";
      try {
        const uploaded = [];
        for (const item of selectedScreenshots) {
          const attachment = await adminFetch(
            "/api/v1/admin/projects/" +
              encodeURIComponent(request.project_id) +
              "/requirements/" +
              encodeURIComponent(request.id) +
              "/screenshots?filename=" +
              encodeURIComponent(item.name) +
              "&checkpoint=" +
              encodeURIComponent(request.checkpoint_sha256),
            {
              method: "POST",
              headers: { "Content-Type": "application/octet-stream" },
              body: item.file,
            },
          );
          uploaded.push(attachment.id);
        }
        feedback.textContent = "已提交，等待 Product Agent…";
        const accepted = await submitOperation({
          action: "PRODUCT_REPLY",
          project_id: request.project_id,
          delivery_id: request.id,
          expected_checkpoint_sha256: request.checkpoint_sha256,
          message: message.value.trim(),
          screenshot_ids: uploaded,
        });
        if (accepted) revokeScreenshotPreviews();
        else submit.disabled = false;
      } catch (error) {
        feedback.className = "form-feedback error";
        feedback.textContent =
          error instanceof Error ? error.message : "截图保存失败。";
        submit.disabled = false;
      }
    });
    appendDiscussionContent(form);
  }
  if (
    !productDiscussionStages.has(request.stage) &&
    request.stage !== "DONE"
  ) {
    const action = button(
      "继续交付",
      () =>
        submitOperation({
          action: "CONTINUE_DELIVERY",
          project_id: request.project_id,
          delivery_id: request.id,
          expected_checkpoint_sha256: request.checkpoint_sha256,
        }),
      "primary",
    );
    appendOperation(action);
  }
}
function deliveryResult(panel, request) {
  if (request.stage !== "DONE") return;
  const section = el("section", undefined, "detail-section");
  const result = el("div", undefined, "delivery-result");
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
  section.append(result);
  panel.append(section);
}
function renderRequests(content) {
  content.className = "request-master-panel";
  if (administrationNotice?.page === "requests")
    content.append(el("div", administrationNotice.text, "admin-notice"));
  const top = el("div", undefined, "row request-heading");
  const actions = el("div", undefined, "request-heading-actions");
  actions.append(
    snapshot.selected_project_id
      ? el("span", `${snapshot.requests.length} 个需求`, "badge")
      : el("span", "尚未选择", "badge blocked"),
  );
  if (canControlCurrentTeam() && currentProjectId())
    actions.append(
      button(
        "新建需求",
        () => {
          creatingProject = false;
          composing = true;
          renderComposer();
        },
        "primary",
      ),
    );
  top.append(
    el(
      "h2",
      snapshot.selected_project_id ? "需求列表" : "请先创建或选择 Project",
    ),
    actions,
  );
  content.append(top);
  if (
    selected &&
    !(selected.kind === "task"
      ? taskById(selected.id)
      : requestById(selected.id))
  )
    selected = null;
  if (!snapshot.requests.length) {
    selected = null;
    const n = el("div", undefined, "empty request-empty");
    n.append(
      el("div", "还没有需求", "section-title"),
      el(
        "p",
        snapshot.selected_project_id
          ? "创建需求并选择涉及的代码目录，团队会从产品澄清开始推进。"
          : "还没有 Project。请在本页创建 Project 后再提交需求。",
      ),
    );
    if (canControlCurrentTeam() && currentProjectId())
      n.append(
        button(
          "新建第一个需求",
          () => {
            creatingProject = false;
            composing = true;
            renderComposer();
          },
          "primary",
        ),
      );
    content.append(n);
    return;
  }
  const groups = [
    ["active", "进行中"],
    ["blocked", "阻塞中"],
    ["closed", "已关闭"],
    ["completed", "已完成"],
  ];
  const counts = Object.fromEntries(
    groups.map(([key]) => [
      key,
      snapshot.requests.filter((request) => requestGroup(request) === key)
        .length,
    ]),
  );
  const navigation = el("div", undefined, "request-filter scope-switch");
  navigation.setAttribute("role", "tablist");
  navigation.setAttribute("aria-label", "需求状态");
  for (const [key, title] of groups) {
    const control = button(
      `${title} ${counts[key]}`,
      () => {
        requestFilter = key;
        render();
      },
      requestFilter === key ? "selected" : "",
    );
    control.setAttribute("role", "tab");
    control.setAttribute("aria-selected", String(requestFilter === key));
    navigation.append(control);
  }
  content.append(navigation);
  const group = el("section", undefined, "task-group request-list");
  const currentTitle = groups.find(([key]) => key === requestFilter)?.[1];
  const requests = snapshot.requests.filter(
    (request) => requestGroup(request) === requestFilter,
  );
  const selectedRequestId =
    selected?.kind === "task"
      ? taskById(selected.id)?.request_id
      : selected?.id;
  if (!requests.some((request) => request.id === selectedRequestId))
    selected = requests.length ? { kind: "request", id: requests[0].id } : null;
  if (!requests.length)
    group.append(el("p", `暂无${currentTitle}需求。`, "muted"));
  for (const request of requests) group.append(requestCard(request));
  content.append(group);
}
async function adminFetch(url, options = {}) {
  const response = await fetch(url, { cache: "no-store", ...options });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error?.message || "管理操作失败。");
  return payload;
}
function readConfigurationApplyPending() {
  try {
    const stored = globalThis.localStorage?.getItem(configurationApplyStorageKey);
    const parsed = stored ? JSON.parse(stored) : null;
    return parsed &&
      /^configuration_apply_[a-f0-9]{32}$/.test(parsed.request_id) &&
      Number.isInteger(parsed.effective_console_port)
      ? parsed
      : null;
  } catch {
    return null;
  }
}
function persistConfigurationApplyPending(value) {
  configurationApplyPending = value;
  try {
    if (value)
      globalThis.localStorage?.setItem(
        configurationApplyStorageKey,
        JSON.stringify(value),
      );
    else globalThis.localStorage?.removeItem(configurationApplyStorageKey);
  } catch {
    // Durable recovery is best-effort when browser storage is unavailable.
  }
}
function finishConfigurationApply(result) {
  configurationApplyInFlight = false;
  configurationApplyStartedAt = null;
  configurationApplyResult = result;
  persistConfigurationApplyPending(null);
  render();
}
function expireConfigurationApply() {
  configurationApplyInFlight = false;
  configurationApplyStartedAt = null;
  configurationApplyResult = {
    kind: "error",
    message:
      "Web Console 未在预期时间内恢复连接。配置仍已保存，请使用服务脚本检查状态后安全重试。",
  };
  render();
}
function reconnectToConfigurationPort(port) {
  const browserLocation = globalThis.location;
  if (
    !browserLocation ||
    !Number.isInteger(port) ||
    String(port) === browserLocation.port
  )
    return false;
  const reconnectUrl = new URL(browserLocation.href);
  reconnectUrl.port = String(port);
  const reconnect = () => {
    try {
      browserLocation.assign(reconnectUrl.href);
    } catch {
      // A failed navigation is retried within the same bounded restart window.
    }
    if (
      configurationApplyInFlight &&
      configurationApplyStartedAt !== null &&
      Date.now() - configurationApplyStartedAt < configurationApplyTimeoutMs
    )
      setTimeout(reconnect, 2500);
  };
  setTimeout(reconnect, 2500);
  return true;
}
async function refreshConfigurationApply() {
  if (!configurationApplyInFlight) return;
  if (
    configurationApplyStartedAt !== null &&
    Date.now() - configurationApplyStartedAt >= configurationApplyTimeoutMs
  ) {
    expireConfigurationApply();
    return;
  }
  try {
    const state = await adminFetch("/api/v1/admin/settings/apply");
    if (
      configurationApplyPending &&
      state.request_id !== configurationApplyPending.request_id
    ) {
      finishConfigurationApply({
        kind: "error",
        message: "无法确认已接受的配置应用请求，请使用服务脚本检查状态并安全重试。",
      });
      return;
    }
    if (state.status === "FAILED") {
      finishConfigurationApply({ kind: "error", message: state.safe_summary });
      return;
    }
    if (state.status === "SUCCEEDED") {
      const saved = await adminFetch("/api/v1/admin/settings");
      settingsSnapshot = saved;
      if (saved.restart_required) {
        configurationApplyInFlight = false;
        configurationApplyResult = null;
        persistConfigurationApplyPending(null);
        render();
        return;
      }
      settingsDraft = structuredClone(saved.config);
      normalizeAgentModelRoutes(settingsDraft);
      finishConfigurationApply({
        kind: "success",
        message: "配置已应用，Web Console 已使用保存的运行配置重新启动。",
      });
    }
  } catch {
    if (
      configurationApplyStartedAt !== null &&
      Date.now() - configurationApplyStartedAt >= configurationApplyTimeoutMs
    ) {
      expireConfigurationApply();
    }
  }
}
async function resumeConfigurationApply() {
  if (!configurationApplyPending) {
    try {
      const state = await adminFetch("/api/v1/admin/settings/apply");
      if (
        state.status === "PENDING" ||
        (state.status === "SUCCEEDED" && !settingsSnapshot?.restart_required) ||
        (state.status === "FAILED" && settingsSnapshot?.restart_required)
      ) {
        persistConfigurationApplyPending({
          request_id: state.request_id,
          effective_console_port: state.effective_console_port,
        });
        configurationApplyInFlight = true;
        configurationApplyStartedAt = Date.now();
        if (
          state.status !== "FAILED" &&
          reconnectToConfigurationPort(state.effective_console_port)
        )
          return;
      }
    } catch {
      return;
    }
  }
  if (configurationApplyPending) await refreshConfigurationApply();
}
async function applySavedConfiguration() {
  if (configurationApplyInFlight) return;
  configurationApplyInFlight = true;
  configurationApplyStartedAt = Date.now();
  configurationApplyResult = null;
  render();
  try {
    const state = await adminFetch("/api/v1/admin/settings/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    persistConfigurationApplyPending({
      request_id: state.request_id,
      effective_console_port: state.effective_console_port,
    });
    if (reconnectToConfigurationPort(state.effective_console_port)) return;
    setTimeout(refreshConfigurationApply, 1000);
  } catch (error) {
    finishConfigurationApply({
      kind: "error",
      message:
        error instanceof Error
          ? error.message
          : "配置仍已保存，但无法请求重启 Web Console。",
    });
  }
}
async function loadKnowledge() {
  if (knowledgeMode === "specs") {
    const base =
      knowledgeScope === "team"
        ? "/api/v1/admin/team/specs"
        : currentProjectId()
          ? "/api/v1/admin/projects/" +
            encodeURIComponent(currentProjectId()) +
            "/specs"
          : null;
    specDocuments = base ? await adminFetch(base) : [];
    return;
  }
  if (knowledgeMode === "learning") {
    learningProposals = currentProjectId()
      ? await adminFetch(
          "/api/v1/admin/projects/" +
            encodeURIComponent(currentProjectId()) +
            "/learnings",
        )
      : [];
    return;
  }
  if (knowledgeScope === "project") {
    const projectId = currentProjectId();
    knowledgeDocuments = projectId
      ? await adminFetch(
          "/api/v1/admin/projects/" +
            encodeURIComponent(projectId) +
            "/knowledge",
        )
      : [];
    knowledgeIndexStatus = projectId
      ? await adminFetch("/api/v1/admin/projects/" + encodeURIComponent(projectId) + "/knowledge/index")
      : null;
    return;
  }
  knowledgeDocuments = await adminFetch("/api/v1/admin/team/knowledge");
  knowledgeIndexStatus = await adminFetch("/api/v1/admin/team/knowledge/index");
}
async function loadAdministration() {
  try {
    const settings = await adminFetch("/api/v1/admin/settings");
    settingsSnapshot = settings;
    settingsDraft = structuredClone(settings.config);
    normalizeAgentModelRoutes(settingsDraft);
    runtimeVariablesDraft = {};
    administrationAvailable = true;
    await resumeConfigurationApply();
    try {
      administrationProjects = await adminFetch("/api/v1/admin/projects");
    } catch {
      administrationProjects = [];
    }
    try {
      await loadKnowledge();
    } catch {
      knowledgeDocuments = [];
      specDocuments = [];
      learningProposals = [];
    }
  } catch {
    administrationAvailable = false;
    administrationProjects = [];
    knowledgeDocuments = [];
    specDocuments = [];
    learningProposals = [];
    settingsSnapshot = null;
    settingsDraft = null;
    runtimeVariablesDraft = {};
    runtimeStatusSnapshot = null;
    runtimeStatusError = null;
  }
}
async function loadRuntimeStatus() {
  try {
    runtimeStatusSnapshot = await adminFetch("/api/v1/admin/status");
    runtimeStatusError = null;
  } catch (error) {
    runtimeStatusSnapshot = null;
    runtimeStatusError =
      error instanceof Error ? error.message : "平台状态暂时无法读取。";
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

  const descriptions = {
    background:
      knowledgeScope === "team"
        ? "跨 Project 共享的团队知识，不作为强制工程规则。"
        : "帮助团队理解当前 Project 的业务与技术背景，不作为强制工程规则。",
    specs: "新需求必须遵守的工程规则；验证方式可在明确后补充。",
    learning: "从 QA 失败和 Review 拒绝中提炼，经人工批准后再沉淀。",
  };
  const workspace = el("div", undefined, "knowledge-workspace");
  const ownership = el("aside", undefined, "knowledge-navigation");
  const ownershipHeader = el("div", undefined, "knowledge-navigation-header");
  ownershipHeader.append(
    el("strong", "知识库归属", "knowledge-navigation-title"),
    el("span", "先选择资产属于谁", "muted"),
  );
  const ownershipSwitch = el(
    "div",
    undefined,
    "knowledge-module-switch knowledge-ownership-switch",
  );
  ownershipSwitch.setAttribute("role", "tablist");
  ownershipSwitch.setAttribute("aria-label", "知识库归属");
  for (const [scope, title] of [
    ["team", "团队知识库"],
    ["project", "项目知识库"],
  ]) {
    const control = button(
      title,
      async () => {
        knowledgeScope = scope;
        if (scope === "team" && knowledgeMode === "learning")
          knowledgeMode = "background";
        administrationNotice = null;
        await loadKnowledge();
        render();
      },
      knowledgeScope === scope ? "selected" : "",
    );
    control.setAttribute("role", "tab");
    control.setAttribute("aria-selected", String(knowledgeScope === scope));
    ownershipSwitch.append(control);
  }
  ownership.append(
    ownershipHeader,
    ownershipSwitch,
    el(
      "p",
      knowledgeScope === "team"
        ? "整个 Team 共享一次，适用于所有 Project，不随 Project 切换而复制。"
        : "每个 Project 独立保存自己的背景、工程规范与学习记录。",
      "knowledge-navigation-hint",
    ),
  );
  if (knowledgeScope === "project") {
    const projectSelector = el(
      "section",
      undefined,
      "knowledge-project-selector",
    );
    const selectorHeader = el("div", undefined, "knowledge-navigation-header");
    selectorHeader.append(
      el("strong", "选择 Project", "knowledge-navigation-title"),
      el("span", "下方只展示所选 Project 的资产", "muted"),
    );
    const projectTabs = el(
      "div",
      undefined,
      "team-tabs knowledge-project-tabs",
    );
    projectTabs.setAttribute("role", "tablist");
    projectTabs.setAttribute("aria-label", "Project 知识库");
    for (const project of snapshot.projects || []) {
      const active = project.id === currentProjectId();
      const control = button(
        project.name,
        () => refresh(project.id),
        active ? "selected" : "",
      );
      control.setAttribute("role", "tab");
      control.setAttribute("aria-selected", String(active));
      if (active) control.setAttribute("aria-current", "true");
      projectTabs.append(control);
    }
    projectSelector.append(selectorHeader, projectTabs);
    ownership.append(projectSelector);
    if (!currentProjectId()) {
      const missing = el("section", undefined, "knowledge-main");
      missing.append(
        el("div", "请先在“需求与交付”中创建并选择一个 Project。", "empty"),
      );
      workspace.append(ownership, missing);
      content.append(workspace);
      return;
    }
  }

  const body = el("section", undefined, "knowledge-main");
  const navigation = el("section", undefined, "knowledge-content-navigation");
  const navigationHeader = el("div", undefined, "knowledge-navigation-header");
  navigationHeader.append(
    el("strong", "内容类型", "knowledge-navigation-title"),
    el("span", "选择要查看和维护的内容", "muted"),
  );
  const modeSwitch = el("div", undefined, "scope-switch knowledge-mode-switch");
  modeSwitch.setAttribute("role", "tablist");
  modeSwitch.setAttribute("aria-label", "知识内容类型");
  const modes = [
    ["background", knowledgeLabelForScope(knowledgeScope)],
    ["specs", "开发规范"],
  ];
  if (knowledgeScope === "project") modes.push(["learning", "学习改进"]);
  for (const [mode, title] of modes) {
    const control = button(
      title,
      async () => {
        knowledgeMode = mode;
        administrationNotice = null;
        await loadKnowledge();
        render();
      },
      knowledgeMode === mode ? "selected" : "",
    );
    control.setAttribute("role", "tab");
    control.setAttribute("aria-selected", String(knowledgeMode === mode));
    modeSwitch.append(control);
  }
  navigation.append(
    navigationHeader,
    modeSwitch,
    el("p", descriptions[knowledgeMode], "knowledge-navigation-hint"),
  );
  body.append(navigation);
  workspace.append(ownership, body);
  content.append(workspace);
  if (knowledgeMode === "specs") {
    renderSpecs(body);
    return;
  }
  if (knowledgeMode === "learning") {
    renderLearning(body);
    return;
  }
  renderBackgroundKnowledge(body);
}

function renderKnowledgeImportHeader(dialog, title, description) {
  dialog.className = "modal-dialog modal-dialog-wide";
  const top = el("div", undefined, "row");
  top.append(
    el("div", title, "section-title"),
    button(
      "取消",
      () => {
        knowledgeImportMode = null;
        renderComposer();
      },
      "",
    ),
  );
  dialog.append(top, el("p", description, "muted modal-introduction"));
}

function renderBackgroundKnowledgeImport(dialog) {
  const scope = knowledgeScope;
  const projectId = scope === "project" ? currentProjectId() : null;
  const knowledgeLabel = knowledgeLabelForScope(scope);
  renderKnowledgeImportHeader(
    dialog,
    `导入${knowledgeLabel}`,
    "可一次选择多份文档。若文件名与现有文档相同，平台会在替换前明确提示覆盖风险。",
  );
  const form = el("form", undefined, "knowledge-upload");
  const file = el("input");
  file.type = "file";
  file.accept = ".md,.txt,.pdf,.docx";
  file.multiple = true;
  file.required = true;
  const feedback = el("p", "", "form-feedback");
  const submit = el("button", "上传并转换", "primary");
  submit.type = "submit";
  form.append(
    field(
      "选择本地文档",
      file,
      "支持一次选择多个 Markdown、TXT、PDF、DOCX；单次最多 20 份，单个原文件最大 10 MB，转换后的正文最大 256 KB。",
    ),
    feedback,
    submit,
  );
  const uploadFiles = async (selectedFiles, replacements = new Map()) => {
    const base =
      scope === "team"
        ? "/api/v1/admin/team/knowledge"
        : "/api/v1/admin/projects/" +
          encodeURIComponent(projectId) +
          "/knowledge";
    const failures = [];
    let imported = 0;
    for (const [index, selectedFile] of selectedFiles.entries()) {
      feedback.textContent = `正在导入第 ${index + 1}/${selectedFiles.length} 份：${selectedFile.name}`;
      try {
        const replacement = replacements.get(selectedFile);
        const endpoint = replacement
          ? base +
            "/" +
            encodeURIComponent(replacement.manifest.document_id) +
            "?filename=" +
            encodeURIComponent(selectedFile.name)
          : base + "?filename=" + encodeURIComponent(selectedFile.name);
        await adminFetch(endpoint, {
          method: replacement ? "PUT" : "POST",
          headers: { "Content-Type": "application/octet-stream" },
          body: selectedFile,
        });
        imported += 1;
      } catch (error) {
        failures.push(
          `${selectedFile.name}：${error instanceof Error ? error.message : "导入失败"}`,
        );
      }
    }
    knowledgeImportMode = null;
    await loadKnowledge();
    administrationNotice = {
      page: "knowledge",
      text: failures.length
        ? `已接收 ${imported}/${selectedFiles.length} 份；${failures.length} 份上传失败。${failures[0]}`
        : replacements.size
          ? `已接收 ${imported} 份${knowledgeLabel}，其中 ${replacements.size} 份更新正在排队；解析完成后继承原启用状态。`
          : `已接收 ${imported} 份${knowledgeLabel}，正在后台解析。就绪后可启用于新需求。`,
    };
    render();
  };
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const selectedFiles = [...(file.files || [])];
    if (!selectedFiles.length) return;
    if (selectedFiles.length > maxKnowledgeImportFiles) {
      feedback.className = "form-feedback error";
      feedback.textContent = `单次最多导入 ${maxKnowledgeImportFiles} 份文档。`;
      return;
    }
    const normalizedNames = selectedFiles.map((item) =>
      item.name.normalize("NFC").toLowerCase(),
    );
    if (new Set(normalizedNames).size !== normalizedNames.length) {
      feedback.className = "form-feedback error";
      feedback.textContent = "同一批文件中存在重名文档，请保留一份后再上传。";
      return;
    }
    const replacements = new Map();
    for (const selectedFile of selectedFiles) {
      const matches = knowledgeDocuments.filter(
        (item) =>
          item.manifest.source_name.normalize("NFC").toLowerCase() ===
          selectedFile.name.normalize("NFC").toLowerCase(),
      );
      if (matches.length > 1) {
        feedback.className = "form-feedback error";
        feedback.textContent = `“${selectedFile.name}”对应多份现有文档，无法安全判断替换目标。`;
        return;
      }
      if (matches.length === 1) replacements.set(selectedFile, matches[0]);
    }
    if (replacements.size) {
      const names = [...replacements.keys()].map((item) => `“${item.name}”`);
      confirmMutation(
        "同名文档存在覆盖风险",
        `${names.join("、")}与现有文档同名。继续后会发布新内容、保留旧记录，并继承原启用状态。`,
        "确认替换并上传",
        () => uploadFiles(selectedFiles, replacements),
      );
      return;
    }
    submit.disabled = true;
    feedback.className = "form-feedback";
    try {
      await uploadFiles(selectedFiles);
    } catch (error) {
      feedback.className = "form-feedback error";
      feedback.textContent =
        error instanceof Error ? error.message : "文档导入失败。";
      submit.disabled = false;
    }
  });
  dialog.append(form);
  file.focus();
}

function renderKnowledgeIndex(content) {
  if (!knowledgeIndexStatus) return;
  const index = knowledgeIndexStatus;
  const panel = el("section", undefined, "knowledge-index-status");
  panel.append(el("h3", "知识解析与索引"));
  panel.append(el("p", `待处理 ${index.backlog} 份 · 失败 ${index.failed} 份 · 最长等待 ${Math.ceil(index.oldest_pending_seconds)} 秒`, "muted"));
  const labels = {QUEUED: "等待解析", PROCESSING: "正在解析", READY: "索引就绪", FAILED: "解析失败", RETIRED: "已退休"};
  const errors = {DOCUMENT_INVALID: "无法解析文档，请检查格式或重新上传。", INDEX_INVALID: "索引构建失败，原有可用索引已保留。", REPLACEMENT_STALE: "原文档已变更，请重新选择替换目标。"};
  for (const job of index.jobs.filter((value) => value.status !== "RETIRED").slice(-20)) {
    const row = el("div", undefined, "row knowledge-index-job");
    row.append(el("span", job.source_name), el("span", labels[job.status] || job.status, "badge"));
    if (job.status === "FAILED") {
      row.append(el("span", errors[job.error_code] || "解析失败，可重试。", "muted"));
      row.append(button("重试索引", async () => {
        const base = knowledgeScope === "team" ? "/api/v1/admin/team/knowledge" : "/api/v1/admin/projects/" + encodeURIComponent(currentProjectId()) + "/knowledge";
        try {
          await adminFetch(base + "/index/" + encodeURIComponent(job.job_id) + "/retry", {method: "POST"});
          await loadKnowledge();
          render();
        } catch (error) {
          administrationNotice = {page: "knowledge", text: error instanceof Error ? error.message : "索引重试失败。"};
          render();
        }
      }));
    }
    panel.append(row);
  }
  content.append(panel);
}

function renderBackgroundKnowledge(content) {
  if (knowledgeScope === "project" && !currentProjectId()) {
    content.append(el("div", "请先在页面顶部选择一个 Project。", "empty"));
    return;
  }

  const project = snapshot.projects.find(
    (item) => item.id === currentProjectId(),
  );
  const ownerName =
    knowledgeScope === "team"
      ? snapshot.team_name
      : project?.name || currentProjectId();
  const knowledgeLabel = knowledgeLabelForScope(knowledgeScope);
  const top = el("div", undefined, "row request-heading");
  const actions = el("div", undefined, "row knowledge-heading-actions");
  actions.append(
    el("span", `${knowledgeDocuments.length} 份`, "badge"),
    button(
      `导入${knowledgeLabel}`,
      () => {
        knowledgeImportMode = "background";
        renderComposer();
      },
      "primary",
    ),
  );
  top.append(
    el(
      "h2",
      `${ownerName} · ${knowledgeScope === "team" ? "团队通用知识" : "Project 知识"}`,
    ),
    actions,
  );
  content.append(top);
  renderKnowledgeIndex(content);
  content.append(
    el(
      "p",
      knowledgeScope === "team"
        ? "启用后用于所有 Project 的新需求。"
        : "启用后只用于当前 Project 的新需求，不影响其他 Project。",
      "muted",
    ),
  );
  if (!knowledgeDocuments.length) {
    content.append(
      el(
        "div",
        knowledgeScope === "team"
          ? "尚未导入团队通用知识文档。"
          : "当前 Project 尚未导入知识文档。",
        "empty",
      ),
    );
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
        item.selected ? "已用于新需求" : "尚未启用",
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
    const toggle = button(item.selected ? "停用" : "用于新需求", async () => {
      toggle.disabled = true;
      const documentIds = knowledgeDocuments
        .filter(
          (candidate) =>
            candidate.manifest.document_id !== manifest.document_id &&
            candidate.selected,
        )
        .map((candidate) => candidate.manifest.document_id);
      if (!item.selected) documentIds.push(manifest.document_id);
      const endpoint =
        knowledgeScope === "team"
          ? "/api/v1/admin/team/knowledge/selection"
          : "/api/v1/admin/projects/" +
            encodeURIComponent(currentProjectId()) +
            "/knowledge/selection";
      try {
        knowledgeDocuments = await adminFetch(endpoint, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ document_ids: documentIds }),
        });
        administrationNotice = {
          page: "knowledge",
          text: "知识选择已生效，无需重启；已存在需求不会被静默改写。",
        };
        render();
      } catch (error) {
        administrationNotice = {
          page: "knowledge",
          text: error instanceof Error ? error.message : "知识选择保存失败。",
        };
        render();
      }
    });
    const actions = el("div", undefined, "knowledge-card-actions");
    const update = button("更新文档", async () => {
      update.disabled = true;
      const endpoint =
        knowledgeScope === "team"
          ? "/api/v1/admin/team/knowledge/" +
            encodeURIComponent(manifest.document_id) +
            "/content"
          : "/api/v1/admin/projects/" +
            encodeURIComponent(currentProjectId()) +
            "/knowledge/" +
            encodeURIComponent(manifest.document_id) +
            "/content";
      try {
        editingKnowledgeDocument = await adminFetch(endpoint);
        renderComposer();
      } catch (error) {
        administrationNotice = {
          page: "knowledge",
          text: error instanceof Error ? error.message : "无法读取文档正文。",
        };
        render();
      }
    });
    const remove = button(
      "删除",
      () =>
        confirmMutation(
          `删除${knowledgeLabel}`,
          `“${manifest.source_name}”将从当前知识库和后续需求上下文中移除；历史交付仍保留原引用。`,
          "确认删除",
          async () => {
            const base =
              knowledgeScope === "team"
                ? "/api/v1/admin/team/knowledge"
                : "/api/v1/admin/projects/" +
                  encodeURIComponent(currentProjectId()) +
                  "/knowledge";
            knowledgeDocuments = await adminFetch(
              base + "/" + encodeURIComponent(manifest.document_id),
              { method: "DELETE" },
            );
            administrationNotice = {
              page: "knowledge",
              text: `${knowledgeLabel}已删除；历史交付引用保持不变。`,
            };
          },
        ),
      "danger-link",
    );
    actions.append(update, toggle, remove);
    card.append(actions);
    content.append(card);
  }
}

function csvValues(value) {
  return value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean);
}
function suggestedSpecKey(filename) {
  const stem = filename.replace(/\.[^.]+$/, "").toLowerCase();
  let value = stem
    .replace(/[^a-z0-9_.-]+/g, "-")
    .replace(/^[-._]+|[-._]+$/g, "");
  if (value.length < 2 || !/^[a-z]/.test(value)) {
    let hash = 2166136261;
    for (const character of stem) {
      hash ^= character.codePointAt(0);
      hash = Math.imul(hash, 16777619);
    }
    value = `spec-${(hash >>> 0).toString(36)}`;
  }
  return value.slice(0, 64);
}
function suggestedSpecTitle(filename) {
  return filename
    .replace(/\.[^.]+$/, "")
    .replace(/[-_.]+/g, " ")
    .trim();
}
function latestSpecs(values) {
  const latest = new Map();
  for (const item of values) {
    const current = latest.get(item.document.spec_key);
    if (!current || current.document.version < item.document.version)
      latest.set(item.document.spec_key, item);
  }
  return [...latest.values()].sort((left, right) =>
    left.document.title.localeCompare(right.document.title),
  );
}

function renderSpecImport(dialog) {
  const scope = knowledgeScope;
  const projectId = scope === "project" ? currentProjectId() : null;
  const logicalSpecs = latestSpecs(specDocuments);
  renderKnowledgeImportHeader(
    dialog,
    "导入开发规范",
    "可一次导入多份 Markdown/TXT。每个文件成为一条独立规范，并共用下方的适用范围。",
  );
  const form = el("form", undefined, "knowledge-upload spec-create-form");
  const file = el("input");
  file.type = "file";
  file.accept = ".md,.txt";
  file.multiple = true;
  file.required = true;
  const roles = multiSelectField(
    "适用角色",
    "支持多选；至少选择一个角色。",
    `${scope}-spec-roles`,
    specRoleOptions,
    specRoleOptions.map(([value]) => value),
  );
  const stages = multiSelectField(
    "适用阶段",
    "支持多选；至少选择一个交付阶段。",
    `${scope}-spec-stages`,
    specStageOptions,
    ["implementing", "qa", "review"],
  );
  const repositories = el("textarea");
  repositories.rows = 2;
  repositories.placeholder =
    "留空表示当前范围内全部仓库；也可每行一个 repository_id";
  const paths = el("textarea");
  paths.rows = 2;
  paths.value = "*";
  const verification = el("textarea");
  verification.rows = 3;
  verification.placeholder =
    "可选：如何证明已遵守这条规范，例如测试命令、静态检查或评审证据";
  const feedback = el("p", "", "form-feedback");
  const submit = el("button", "导入规范", "primary");
  submit.type = "submit";
  form.append(
    field(
      "选择规范文档",
      file,
      "支持一次选择多份 Markdown/TXT，单次最多 20 份；规范名称从文件名生成，之后可单独编辑。",
    ),
    roles.control,
    stages.control,
    field("适用仓库", repositories),
    field("适用路径", paths, "每行一个相对 glob。"),
    field("验证方式", verification, "可以暂时留空。"),
    feedback,
    submit,
  );
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const selectedFiles = [...(file.files || [])];
    if (!selectedFiles.length) return;
    if (selectedFiles.length > maxKnowledgeImportFiles) {
      feedback.className = "form-feedback error";
      feedback.textContent = `单次最多导入 ${maxKnowledgeImportFiles} 份开发规范。`;
      return;
    }
    const selectedRoles = roles.values();
    const selectedStages = stages.values();
    if (!selectedRoles.length || !selectedStages.length) {
      feedback.className = "form-feedback error";
      feedback.textContent = "适用角色和适用阶段都至少需要选择一项。";
      return;
    }
    const keys = selectedFiles.map((item) => suggestedSpecKey(item.name));
    if (new Set(keys).size !== keys.length) {
      feedback.className = "form-feedback error";
      feedback.textContent =
        "所选文件会生成重复的规范标识，请调整文件名后再导入。";
      return;
    }
    const importSpecs = async () => {
      const endpoint =
        scope === "team"
          ? "/api/v1/admin/team/specs"
          : "/api/v1/admin/projects/" +
            encodeURIComponent(projectId) +
            "/specs";
      const failures = [];
      let imported = 0;
      for (const [index, selectedFile] of selectedFiles.entries()) {
        feedback.textContent = `正在导入第 ${index + 1}/${selectedFiles.length} 份规范：${selectedFile.name}`;
        try {
          await adminFetch(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              spec_key: suggestedSpecKey(selectedFile.name),
              title: suggestedSpecTitle(selectedFile.name),
              body_markdown: await selectedFile.text(),
              roles: selectedRoles,
              stages: selectedStages,
              repository_ids: csvValues(repositories.value).sort(),
              path_globs: csvValues(paths.value),
              verification: verification.value.trim(),
            }),
          });
          imported += 1;
        } catch (error) {
          failures.push(
            `${selectedFile.name}：${error instanceof Error ? error.message : "导入失败"}`,
          );
        }
      }
      knowledgeImportMode = null;
      await loadKnowledge();
      administrationNotice = {
        page: "knowledge",
        text: failures.length
          ? `已导入 ${imported}/${selectedFiles.length} 份开发规范；${failures.length} 份失败。${failures[0]}`
          : `已导入 ${imported} 份开发规范但尚未启用。请检查适用范围后再启用。`,
      };
      render();
    };
    const collisions = logicalSpecs.filter((item) =>
      keys.includes(item.document.spec_key),
    );
    if (collisions.length) {
      confirmMutation(
        "同名规范存在新版本风险",
        `${collisions.map((item) => `“${item.document.title}”`).join("、")}已存在。继续会创建新版本，但不会自动启用或改写历史交付。`,
        "确认导入新版本",
        importSpecs,
      );
      return;
    }
    submit.disabled = true;
    feedback.className = "form-feedback";
    try {
      await importSpecs();
    } catch (error) {
      feedback.className = "form-feedback error";
      feedback.textContent =
        error instanceof Error ? error.message : "Spec 创建失败。";
      submit.disabled = false;
    }
  });
  dialog.append(form);
  file.focus();
}

function renderSpecs(content) {
  if (knowledgeScope === "project" && !currentProjectId()) {
    content.append(el("div", "请先在页面顶部选择一个 Project。", "empty"));
    return;
  }
  const project = snapshot.projects.find(
    (item) => item.id === currentProjectId(),
  );
  const ownerName =
    knowledgeScope === "team"
      ? snapshot.team_name
      : project?.name || currentProjectId();
  const logicalSpecs = latestSpecs(specDocuments);
  const top = el("div", undefined, "row request-heading");
  const actions = el("div", undefined, "row knowledge-heading-actions");
  actions.append(
    el("span", `${logicalSpecs.length} 条规范`, "badge"),
    button(
      "导入开发规范",
      () => {
        knowledgeImportMode = "specs";
        renderComposer();
      },
      "primary",
    ),
  );
  top.append(el("h2", `${ownerName} · 强约束开发规范`), actions);
  content.append(
    top,
    el(
      "p",
      "只有明确启用的规范才进入新需求。Team、Project 与仓库原生规范冲突时会停止并交给人工处理。",
      "muted",
    ),
  );
  if (!logicalSpecs.length) {
    content.append(el("div", "当前范围尚未创建开发规范。", "empty"));
    return;
  }
  for (const item of logicalSpecs) {
    const spec = item.document;
    const activeVersion = specDocuments.find(
      (candidate) =>
        candidate.active && candidate.document.spec_key === spec.spec_key,
    );
    const isCurrent = item.active;
    const card = el("article", undefined, "knowledge-card spec-card");
    const head = el("div", undefined, "row");
    head.append(
      el("strong", spec.title),
      el(
        "span",
        isCurrent ? "已启用" : activeVersion ? "有待启用更新" : "未启用",
        isCurrent ? "badge done" : "badge",
      ),
    );
    card.append(
      head,
      el(
        "p",
        `角色 · ${spec.roles.map(label).join(" / ")} · 阶段 · ${spec.stages.map(label).join(" / ")}`,
        "muted",
      ),
      el("p", `仓库 · ${spec.repository_ids.join(", ") || "全部"}`, "paths"),
      el("p", `路径 · ${spec.path_globs.join(", ")}`, "paths"),
      el("p", `验证 · ${spec.verification || "暂未设置"}`, "muted"),
    );
    const detail = el("details");
    detail.append(el("summary", "查看规范正文"), el("pre", spec.body_markdown));
    card.append(detail);
    const actions = el("div", undefined, "knowledge-card-actions");
    const update = button("更新规范", () => {
      editingSpecDocument = {
        scope: knowledgeScope,
        project_id: knowledgeScope === "project" ? currentProjectId() : null,
        document: structuredClone(spec),
      };
      renderComposer();
    });
    const toggle = button(
      isCurrent ? "停用" : activeVersion ? "启用更新" : "启用规范",
      async () => {
        toggle.disabled = true;
        const ids = specDocuments
          .filter(
            (candidate) =>
              candidate.active && candidate.document.spec_key !== spec.spec_key,
          )
          .map((candidate) => candidate.document.spec_id);
        if (!isCurrent) ids.push(spec.spec_id);
        const endpoint =
          knowledgeScope === "team"
            ? "/api/v1/admin/team/specs/activation"
            : "/api/v1/admin/projects/" +
              encodeURIComponent(currentProjectId()) +
              "/specs/activation";
        try {
          specDocuments = await adminFetch(endpoint, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ spec_ids: ids }),
          });
          administrationNotice = {
            page: "knowledge",
            text: "Spec 激活状态已更新；只影响之后重新准备的新需求，无需重启服务。",
          };
        } catch (error) {
          administrationNotice = {
            page: "knowledge",
            text: error instanceof Error ? error.message : "Spec 激活失败。",
          };
        }
        render();
      },
    );
    const remove = button(
      "删除",
      () =>
        confirmMutation(
          "删除开发规范",
          `“${spec.title}”将停止用于后续需求并从当前规范列表移除；历史交付仍保留原规范引用。`,
          "确认删除",
          async () => {
            const base =
              knowledgeScope === "team"
                ? "/api/v1/admin/team/specs"
                : "/api/v1/admin/projects/" +
                  encodeURIComponent(currentProjectId()) +
                  "/specs";
            specDocuments = await adminFetch(
              base + "/" + encodeURIComponent(spec.spec_key),
              { method: "DELETE" },
            );
            administrationNotice = {
              page: "knowledge",
              text: "开发规范已删除；历史交付引用保持不变。",
            };
          },
        ),
      "danger-link",
    );
    actions.append(update, toggle, remove);
    card.append(actions);
    content.append(card);
  }
}

function renderLearning(content) {
  if (!currentProjectId()) {
    content.append(el("div", "请先在页面顶部选择一个 Project。", "empty"));
    return;
  }
  const top = el("div", undefined, "row request-heading");
  top.append(
    el("h2", "当前 Project · 学习建议"),
    button(
      "扫描 QA / Review 失败",
      async () => {
        try {
          learningProposals = await adminFetch(
            "/api/v1/admin/projects/" +
              encodeURIComponent(currentProjectId()) +
              "/learnings/collect",
            { method: "POST" },
          );
          administrationNotice = {
            page: "knowledge",
            text: "扫描完成。学习建议仍需人工逐条批准，不会自动改变知识或规范。",
          };
        } catch (error) {
          administrationNotice = {
            page: "knowledge",
            text: error instanceof Error ? error.message : "学习建议扫描失败。",
          };
        }
        render();
      },
      "primary",
    ),
  );
  content.append(
    top,
    el(
      "p",
      "建议来自已持久化的 QA FAIL / Review REJECT Artifact。批准后才会形成新知识、Spec 版本或 Skill 设计稿。",
      "muted",
    ),
  );
  if (!learningProposals.length) {
    content.append(el("div", "尚无学习建议，可先扫描已有失败证据。", "empty"));
    return;
  }
  for (const view of learningProposals) {
    const proposal = view.proposal;
    const card = el("article", undefined, "knowledge-card learning-card");
    const head = el("div", undefined, "row");
    head.append(
      el("strong", proposal.title),
      el(
        "span",
        view.decision
          ? label(view.decision.action)
          : view.authorization
            ? "已授权，等待完成"
            : "待人工判断",
        view.decision?.action === "APPROVE" ? "badge done" : "badge",
      ),
    );
    card.append(
      head,
      el("p", proposal.observation),
      el("p", `建议 · ${proposal.proposed_improvement}`, "muted"),
      el(
        "p",
        `重复出现 ${proposal.occurrence_count} 次 · 来源 ${label(proposal.trigger)}`,
        "muted",
      ),
      el("p", `验证 · ${proposal.verification}`, "muted"),
    );
    for (const evidence of proposal.evidence)
      card.append(
        el(
          "p",
          `${evidence.repository_id} / ${evidence.task_id} / ${evidence.artifact_id}`,
          "paths",
        ),
      );
    if (!view.decision) {
      const actions = el("div", undefined, "learning-actions");
      const available = view.authorization
        ? [
            [
              view.authorization.target,
              view.authorization.action === "APPROVE"
                ? "继续完成已授权发布"
                : "继续完成拒绝记录",
            ],
          ]
        : [
            ["SPEC", "批准为 Project Spec"],
            ["KNOWLEDGE", "保存为背景知识"],
            ["SKILL", "批准为 Skill 设计稿"],
          ];
      for (const [target, title] of available)
        actions.append(
          button(title, () =>
            decideLearning(
              proposal,
              view.authorization?.action || "APPROVE",
              target,
            ),
          ),
        );
      if (!view.authorization)
        actions.append(
          button("拒绝建议", () => decideLearning(proposal, "REJECT", "SPEC")),
        );
      card.append(actions);
    } else {
      card.append(
        el(
          "p",
          view.decision.published_uri || view.decision.rationale,
          "paths",
        ),
      );
    }
    content.append(card);
  }
}

async function decideLearning(proposal, action, target) {
  try {
    const endpoint =
      "/api/v1/admin/projects/" +
      encodeURIComponent(currentProjectId()) +
      "/learnings/" +
      encodeURIComponent(proposal.proposal_id) +
      "/decision";
    await adminFetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        proposal_sha256: proposal.proposal_sha256,
        action,
        target,
        operator_id: "console-user",
        rationale:
          action === "APPROVE"
            ? "Approved in the Web Console after reviewing source evidence."
            : "Rejected in the Web Console after reviewing source evidence.",
      }),
    });
    await loadKnowledge();
    administrationNotice = {
      page: "knowledge",
      text:
        action === "APPROVE"
          ? "学习建议已批准并发布；只影响未来重新准备的需求。"
          : "学习建议已拒绝并保留审计记录。",
    };
  } catch (error) {
    administrationNotice = {
      page: "knowledge",
      text: error instanceof Error ? error.message : "学习建议决策失败。",
    };
  }
  render();
}
function bindInput(control, value, update, type = "text") {
  control.type = type;
  control.value = value ?? "";
  control.addEventListener("input", () => update(control.value));
  return control;
}
function selectInput(values, current, update, key, disabled = false) {
  const control = el(
    "details",
    undefined,
    `single-select${disabled ? " disabled" : ""}`,
  );
  control.dataset.key = key;
  control.dataset.value = current;
  const selected = values.find(([value]) => value === current);
  const selectedLabel = el(
    "span",
    selected?.[1] || "暂无可用选项",
    "single-select-value",
  );
  const summary = el("summary", undefined, "single-select-trigger");
  summary.append(selectedLabel, el("span", "", "single-select-chevron"));
  const menu = el("div", undefined, "single-select-menu");
  menu.setAttribute("role", "listbox");
  const optionNodes = [];
  for (const [value, title] of values) {
    const option = button(
      title,
      () => {
        if (disabled) return;
        control.dataset.value = value;
        selectedLabel.textContent = title;
        for (const [candidate, candidateValue] of optionNodes) {
          const active = candidateValue === value;
          candidate.className = `single-select-option${active ? " selected" : ""}`;
          candidate.setAttribute("aria-selected", String(active));
        }
        control.open = false;
        update(value);
      },
      `single-select-option${value === current ? " selected" : ""}`,
    );
    option.type = "button";
    option.setAttribute("role", "option");
    option.setAttribute("aria-selected", String(value === current));
    optionNodes.push([option, value]);
    menu.append(option);
  }
  if (!values.length)
    menu.append(el("p", "请先启用至少一条模型路由。", "muted"));
  if (disabled) {
    control.setAttribute("aria-disabled", "true");
    summary.addEventListener("click", (event) => event.preventDefault());
  }
  control.append(summary, menu);
  return control;
}
function modelRouteKey(route) {
  return `${route.provider}\u0000${route.model}\u0000${route.reasoning_effort || "medium"}`;
}
function modelRouteValidationMessage(config) {
  const firstRouteByKey = new Map();
  for (const [index, route] of (config.model_routes || []).entries()) {
    const provider = route.provider.trim();
    const model = route.model.trim();
    if (!provider || !model)
      return `第 ${index + 1} 条模型路由必须填写 Provider 和 Model。`;
    const reasoning = route.reasoning_effort || "medium";
    const key = modelRouteKey({ provider, model, reasoning_effort: reasoning });
    const firstIndex = firstRouteByKey.get(key);
    if (firstIndex !== undefined)
      return `第 ${index + 1} 条模型路由（${provider} / ${model} · ${reasoning}）与第 ${firstIndex + 1} 条重复。每个 Provider + Model + Reasoning 组合只能配置一次；请修改已有路由或删除重复项。`;
    firstRouteByKey.set(key, index);
  }
  return null;
}
function modelRouteReference(route) {
  return {
    provider: route.provider,
    model: route.model,
    reasoning_effort: route.reasoning_effort || "medium",
  };
}
function resolveModelRouteReference(reference, enabled) {
  const exact = enabled.find(
    (route) => modelRouteKey(route) === modelRouteKey(reference),
  );
  if (reference.reasoning_effort) return exact;
  const legacy = enabled.filter(
    (route) =>
      route.provider === reference.provider && route.model === reference.model,
  );
  return legacy.length === 1 ? legacy[0] : undefined;
}
function normalizeAgentModelRoutes(config) {
  if (!config) return;
  const enabled = (config.model_routes || []).filter((route) => route.enabled);
  if (!enabled.length) {
    config.agent_model_routes = [];
    return;
  }
  const existing = new Map(
    (config.agent_model_routes || []).map((policy) => [policy.role, policy]),
  );
  config.agent_model_routes = agentModelRoles.map(([role]) => {
    const current = existing.get(role)?.routes || [];
    const seen = new Set();
    const selected = [];
    for (const reference of current) {
      const route = resolveModelRouteReference(reference, enabled);
      if (!route || seen.has(modelRouteKey(route))) continue;
      seen.add(modelRouteKey(route));
      selected.push(modelRouteReference(route));
    }
    if (!selected.length) selected.push(modelRouteReference(enabled[0]));
    return { role, routes: selected };
  });
}
function selectAgentPrimaryModel(role, key) {
  const enabled = settingsDraft.model_routes.filter((route) => route.enabled);
  const selectedRoute = enabled.find((route) => modelRouteKey(route) === key);
  if (!selectedRoute) return;
  const policy = settingsDraft.agent_model_routes.find(
    (candidate) => candidate.role === role,
  );
  policy.routes = [
    modelRouteReference(selectedRoute),
    ...policy.routes
      .slice(1)
      .filter((route) => modelRouteKey(route) !== key),
  ];
}
function addAgentFallbackModel(role, key) {
  const enabled = settingsDraft.model_routes.filter((route) => route.enabled);
  const selectedRoute = enabled.find((route) => modelRouteKey(route) === key);
  const policy = settingsDraft.agent_model_routes.find(
    (candidate) => candidate.role === role,
  );
  if (
    !selectedRoute ||
    !policy ||
    policy.routes.some((route) => modelRouteKey(route) === key)
  )
    return;
  policy.routes.push(modelRouteReference(selectedRoute));
}
function moveAgentFallbackModel(role, index, offset) {
  const policy = settingsDraft.agent_model_routes.find(
    (candidate) => candidate.role === role,
  );
  const target = index + offset;
  if (!policy || index < 1 || target < 1 || target >= policy.routes.length)
    return;
  [policy.routes[index], policy.routes[target]] = [
    policy.routes[target],
    policy.routes[index],
  ];
}
function removeAgentFallbackModel(role, index) {
  const policy = settingsDraft.agent_model_routes.find(
    (candidate) => candidate.role === role,
  );
  if (!policy || index < 1 || index >= policy.routes.length) return;
  policy.routes.splice(index, 1);
}
function updateModelRouteIdentity(route, property, value) {
  const previous = modelRouteKey(route);
  route[property] = value;
  for (const policy of settingsDraft.agent_model_routes || []) {
    for (const reference of policy.routes || []) {
      if (modelRouteKey(reference) !== previous) continue;
      reference.provider = route.provider;
      reference.model = route.model;
      reference.reasoning_effort = route.reasoning_effort || "medium";
    }
  }
}
function renderProjectPicker(content) {
  const values = snapshot.projects || [];
  const current = values.find((item) => item.id === currentProjectId());
  const picker = el("details", undefined, "project-picker");
  picker.dataset.key = `project-picker-${page}`;
  const summary = el("summary", undefined, "project-picker-summary");
  const summaryText = el("span");
  summaryText.append(
    el("strong", current?.name || "尚未选择 Project"),
    el("small", `${values.length} 个 Project · 可搜索切换`, "muted"),
  );
  summary.append(summaryText, el("span", "⌄", "project-picker-chevron"));
  const menu = el("div", undefined, "project-picker-menu");
  const search = el("input");
  search.type = "search";
  search.placeholder = "搜索 Project";
  const options = el("div", undefined, "project-picker-options");
  const renderOptions = () => {
    options.replaceChildren();
    const query = search.value.trim().toLowerCase();
    const matches = values
      .filter((item) => item.name.toLowerCase().includes(query))
      .sort((left, right) => {
        if (left.id === currentProjectId()) return -1;
        if (right.id === currentProjectId()) return 1;
        return left.name.localeCompare(right.name);
      });
    if (!matches.length) {
      options.append(el("p", "没有匹配的 Project。", "muted"));
      return;
    }
    for (const project of matches) {
      const option = button(
        project.name,
        () => {
          picker.open = false;
          refresh(project.id);
        },
        project.id === currentProjectId()
          ? "project-picker-option selected"
          : "project-picker-option",
      );
      if (project.id === currentProjectId())
        option.append(el("span", "当前", "badge current"));
      options.append(option);
    }
  };
  search.addEventListener("input", renderOptions);
  renderOptions();
  menu.append(search, options);
  picker.append(summary, menu);
  content.append(picker);
}
function renderProjectCreator(content) {
  content.append(
    button(
      "新建 Project",
      () => {
        composing = false;
        creatingProject = true;
        renderComposer();
      },
      "primary",
    ),
  );
}
function renderSettings(content) {
  if (!administrationAvailable || !settingsSnapshot || !settingsDraft) {
    administrationUnavailable(content);
    return;
  }
  if (administrationNotice?.page === "settings")
    content.append(el("div", administrationNotice.text, "admin-notice"));
  if (consoleDeliveryReady !== true)
    content.append(
      el(
        "div",
        "当前交付运行时尚未就绪；请检查下方配置，保存后按提示重启服务。",
        "admin-notice",
      ),
    );
  if (settingsSnapshot.restart_required && configurationApplyInFlight) {
    const applyNotice = el("div", undefined, "admin-notice configuration-apply-notice");
    applyNotice.append(
      el(
        "span",
        "配置已保存，正在重启并等待 Web Console 恢复连接。",
      ),
    );
    content.append(applyNotice);
  } else if (configurationApplyResult?.kind === "success") {
    content.append(el("div", configurationApplyResult.message, "admin-notice"));
  }
  if (configurationApplyResult?.kind === "error")
    content.append(el("div", configurationApplyResult.message, "operation-error"));

  const workspace = el("div", undefined, "settings-workspace");
  const navigation = el("aside", undefined, "settings-navigation");
  navigation.append(
    el("strong", "平台设置", "settings-navigation-title"),
    el("p", "这些配置作用于当前 Team Host，不随 Project 切换。", "muted"),
  );
  for (const [key, title, description] of [
    ["general", "基础配置", "目录、Team、Codex 与端口"],
    ["database", "MySQL", "任务与运行事实数据库"],
    ["models", "模型路由", "Provider、模型与凭证"],
  ]) {
    const control = button(
      title,
      () => {
        settingsSection = key;
        administrationNotice = null;
        render();
      },
      settingsSection === key ? "selected" : "",
    );
    control.append(el("small", description));
    navigation.append(control);
  }

  const panel = el("section", undefined, "admin-panel settings-panel");
  const top = el("div", undefined, "row");
  top.append(
    el(
      "h2",
      settingsSection === "general"
        ? "基础配置"
        : settingsSection === "database"
          ? "MySQL 数据库"
          : "模型路由",
    ),
    settingsSnapshot.config_source === "default"
      ? el("span", "正在使用内置默认配置", "badge")
      : settingsSnapshot.restart_required
        ? el("span", "已保存 · 需要重启", "badge blocked")
        : el("span", "当前配置已生效", "badge done"),
  );
  panel.append(
    top,
    el("p", "配置文件 · " + settingsSnapshot.config_path, "paths"),
  );
  const form = el("form", undefined, "settings-form");
  if (settingsSection === "general") renderGeneralSettings(form);
  else if (settingsSection === "database") renderDatabaseSettings(form);
  else renderModelSettings(form);

  const feedback = el("p", "", "form-feedback");
  const save = el("button", "保存设置", "primary");
  save.type = "submit";
  const saveBar = el("div", undefined, "settings-save-bar");
  saveBar.append(
    el("span", "保存运行配置后需要重启服务；知识选择不需要重启。", "muted"),
    feedback,
    save,
  );
  form.append(saveBar);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const modelRouteError = modelRouteValidationMessage(settingsDraft);
    if (modelRouteError) {
      feedback.className = "form-feedback error";
      feedback.textContent = modelRouteError;
      settingsSaveResult = { kind: "error", message: modelRouteError };
      renderComposer();
      return;
    }
    save.disabled = true;
    feedback.className = "form-feedback";
    feedback.textContent = "正在校验并保存…";
    try {
      normalizeAgentModelRoutes(settingsDraft);
      const saved = await adminFetch("/api/v1/admin/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          config: settingsDraft,
          runtime_variables: Object.entries(runtimeVariablesDraft)
            .sort(([left], [right]) => {
              const order = [
                settingsDraft.database.dsn_env,
                ...settingsDraft.model_routes
                  .map((route) => route.api_key_env)
                  .filter(Boolean),
              ];
              return order.indexOf(left) - order.indexOf(right);
            })
            .map(([environment_name, value]) => ({
              environment_name,
              value,
            })),
        }),
      });
      settingsSnapshot = saved;
      settingsDraft = structuredClone(saved.config);
      normalizeAgentModelRoutes(settingsDraft);
      runtimeVariablesDraft = {};
      administrationNotice = null;
      configurationApplyResult = null;
      settingsSaveResult = {
        kind: "success",
        restart_required: saved.restart_required,
        message: saved.restart_required
          ? "保存成功。请使用“应用配置”重启 Web Console 并使新配置生效。"
          : "保存成功。",
      };
      render();
    } catch (error) {
      const message = error instanceof Error ? error.message : "设置保存失败。";
      feedback.className = "form-feedback error";
      feedback.textContent = message;
      save.disabled = false;
      settingsSaveResult = { kind: "error", message };
      renderComposer();
    }
  });
  panel.append(form);
  workspace.append(navigation, panel);
  content.append(workspace);
}

function renderGeneralSettings(form) {
  const general = el("div", undefined, "settings-grid");
  const platformRoot = bindInput(
    el("input"),
    settingsDraft.platform_root,
    (value) => {
      if (value !== settingsDraft.platform_root)
        settingsDraft.team_knowledge_paths = [];
      settingsDraft.platform_root = value;
    },
  );
  const team = bindInput(el("input"), settingsDraft.team_name, () => {});
  team.disabled = true;
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
      "必须是绝对路径；Team、Projects、worktrees 与 quarantine 都保存在该目录。",
    ),
    field(
      "唯一 Team",
      team,
      `${settingsDraft.team_id}；Team 是长期团队，不随 Project 切换。`,
    ),
    field("Codex 可执行文件", codex),
    field("Web Console 端口", port, "修改端口后使用新地址重启。"),
    field("启用真实模型执行", live),
  );
  form.append(general);
}

function renderDatabaseSettings(form) {
  form.append(
    el(
      "p",
      "填写完整连接字符串。留空表示保留已经保存的值；页面不会回显密码。",
      "muted",
    ),
  );
  const dsnName = settingsDraft.database.dsn_env;
  const dsn = bindInput(
    el("input"),
    runtimeVariablesDraft[dsnName] || "",
    (value) => {
      if (value) runtimeVariablesDraft[dsnName] = value;
      else delete runtimeVariablesDraft[dsnName];
    },
    "password",
  );
  dsn.autocomplete = "new-password";
  dsn.placeholder = settingsSnapshot.secret_status.some(
    (item) => item.environment_name === dsnName && item.configured,
  )
    ? "已保存；输入新 DSN 可替换"
    : "mysql+pymysql://用户名:密码@127.0.0.1:3307/数据库名";
  const connectionFeedback = el("p", "", "form-feedback");
  const testConnection = button("测试连接", async () => {
    testConnection.disabled = true;
    connectionFeedback.className = "form-feedback";
    connectionFeedback.textContent = "正在连接 MySQL…";
    try {
      const result = await adminFetch("/api/v1/admin/settings/test-mysql", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dsn: runtimeVariablesDraft[dsnName] || null }),
      });
      connectionFeedback.className = result.connected
        ? "form-feedback"
        : "form-feedback error";
      connectionFeedback.textContent = result.message;
    } catch (error) {
      connectionFeedback.className = "form-feedback error";
      connectionFeedback.textContent =
        error instanceof Error ? error.message : "MySQL 连接测试失败。";
    } finally {
      testConnection.disabled = false;
    }
  });
  testConnection.type = "button";
  form.append(
    field("MySQL DSN", dsn, `启动变量 ${dsnName} 由服务脚本自动维护。`),
    connectionFeedback,
    testConnection,
  );
}

function renderModelSettings(form) {
  const routesTop = el("div", undefined, "row");
  routesTop.append(
    el(
      "p",
      "按页面顺序尝试可用模型；同一模型可配置不同推理程度，每个 Provider + Model + Reasoning 组合只能出现一次。",
      "muted",
    ),
    button("添加路由", () => {
      settingsDraft.model_routes.push({
        provider: "provider",
        model: "model",
        kind: "responses",
        endpoint: "https://example.invalid/v1/responses",
        api_key_env: "MODEL_API_KEY",
        reasoning_effort: "medium",
        image_input: false,
        enabled: false,
      });
      render();
    }),
  );
  form.append(routesTop);
  settingsDraft.model_routes.forEach((route, index) => {
    const row = el("div", undefined, "route-card");
    const fields = el("div", undefined, "settings-grid");
    fields.append(
      field(
        "Provider",
        bindInput(el("input"), route.provider, (value) =>
          updateModelRouteIdentity(route, "provider", value),
        ),
      ),
      field(
        "Model",
        bindInput(el("input"), route.model, (value) =>
          updateModelRouteIdentity(route, "model", value),
        ),
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
          `model-route-${index}-kind`,
        ),
      ),
      field(
        "Reasoning",
        selectInput(
          ["low", "medium", "high", "xhigh"].map((value) => [value, value]),
          route.reasoning_effort,
          (value) => {
            updateModelRouteIdentity(route, "reasoning_effort", value);
            render();
          },
          `model-route-${index}-reasoning`,
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
        field(
          "API Key",
          (() => {
            const key = bindInput(
              el("input"),
              runtimeVariablesDraft[route.api_key_env] || "",
              (value) => {
                if (value) runtimeVariablesDraft[route.api_key_env] = value;
                else delete runtimeVariablesDraft[route.api_key_env];
              },
              "password",
            );
            key.autocomplete = "new-password";
            key.placeholder = settingsSnapshot.secret_status.some(
              (item) =>
                item.environment_name === route.api_key_env && item.configured,
            )
              ? "已保存；输入新值可替换"
              : "填写该模型服务的 API Key";
            return key;
          })(),
          "留空保留已保存值，页面不会回显。",
        ),
      );
    if (route.kind === "responses") {
      const imageInput = el("input");
      imageInput.type = "checkbox";
      imageInput.checked = route.image_input === true;
      imageInput.addEventListener(
        "change",
        () => (route.image_input = imageInput.checked),
      );
      fields.append(
        field(
          "支持图片输入",
          imageInput,
          "只有兼容 Responses 图片输入格式的服务才应开启。Codex CLI 默认支持。",
        ),
      );
    }
    const enabled = el("input");
    enabled.type = "checkbox";
    enabled.checked = route.enabled;
    enabled.addEventListener("change", () => {
      route.enabled = enabled.checked;
      normalizeAgentModelRoutes(settingsDraft);
      render();
    });
    row.append(fields, field("启用", enabled));
    if (settingsDraft.model_routes.length > 1)
      row.append(
        button("移除路由", () => {
          settingsDraft.model_routes.splice(index, 1);
          render();
        }),
      );
    form.append(row);
  });
  normalizeAgentModelRoutes(settingsDraft);
  const enabledRoutes = settingsDraft.model_routes.filter(
    (route) => route.enabled,
  );
  const assignments = el("section", undefined, "agent-model-settings");
  assignments.append(
    el("h3", "Agent 模型分配"),
    el(
      "p",
      "每个 Agent 必须选择一个主模型；备用模型可选，且只会按该 Agent 显式配置的顺序降级。",
      "muted",
    ),
  );
  const grid = el("div", undefined, "agent-model-grid");
  for (const [role, title, description] of agentModelRoles) {
    const policy = settingsDraft.agent_model_routes.find(
      (candidate) => candidate.role === role,
    );
    const card = el("div", undefined, "agent-model-card");
    card.dataset.role = role;
    const primary = policy?.routes?.[0];
    const primaryKey = primary ? modelRouteKey(primary) : "";
    const choices = enabledRoutes.map((route) => [
      modelRouteKey(route),
      `${route.provider} / ${route.model} · ${route.reasoning_effort}`,
    ]);
    const selector = selectInput(
      choices,
      primaryKey,
      (value) => {
        selectAgentPrimaryModel(role, value);
        render();
      },
      `agent-primary-model-${role}`,
      !choices.length,
    );
    const fallbacks = el("div", undefined, "agent-fallback-settings");
    fallbacks.append(el("strong", "备用模型（可选）", "agent-fallback-title"));
    const fallbackRoutes = policy?.routes?.slice(1) || [];
    if (!fallbackRoutes.length)
      fallbacks.append(
        el(
          "p",
          "当前未配置备用模型；主模型不可用时不会自动尝试模型池中的其他模型。",
          "muted agent-fallback-empty",
        ),
      );
    fallbackRoutes.forEach((route, fallbackOffset) => {
      const index = fallbackOffset + 1;
      const row = el("div", undefined, "agent-fallback-row");
      row.dataset.fallbackIndex = String(index);
      const identity = el("div", undefined, "agent-fallback-identity");
      identity.append(
        el("span", `备用 ${index}`, "route-position"),
        el(
          "span",
          `${route.provider} / ${route.model} · ${route.reasoning_effort || "medium"}`,
        ),
      );
      const actions = el("div", undefined, "agent-fallback-actions");
      const moveUp = button("上移", () => {
        moveAgentFallbackModel(role, index, -1);
        render();
      });
      moveUp.disabled = index === 1;
      const moveDown = button("下移", () => {
        moveAgentFallbackModel(role, index, 1);
        render();
      });
      moveDown.disabled = index === policy.routes.length - 1;
      actions.append(
        moveUp,
        moveDown,
        button("移除", () => {
          removeAgentFallbackModel(role, index);
          render();
        }),
      );
      row.append(identity, actions);
      fallbacks.append(row);
    });
    const selectedKeys = new Set(
      (policy?.routes || []).map((route) => modelRouteKey(route)),
    );
    const fallbackChoices = enabledRoutes
      .filter((route) => !selectedKeys.has(modelRouteKey(route)))
      .map((route) => [
        modelRouteKey(route),
        `${route.provider} / ${route.model} · ${route.reasoning_effort}`,
      ]);
    if (fallbackChoices.length)
      fallbacks.append(
        selectInput(
          [["", "添加备用模型"], ...fallbackChoices],
          "",
          (value) => {
            if (!value) return;
            addAgentFallbackModel(role, value);
            render();
          },
          `agent-fallback-model-${role}`,
        ),
      );
    card.append(
      el("strong", title),
      el("p", description, "muted"),
      field("主模型", selector),
      fallbacks,
    );
    grid.append(card);
  }
  assignments.append(grid);
  form.append(assignments);
}
function statusRow(title, value, ready) {
  const row = el("div", undefined, "status-row");
  row.append(
    el("strong", title),
    el(
      "span",
      value,
      ready === true
        ? "badge done"
        : ready === false
          ? "badge blocked"
          : "badge",
    ),
  );
  return row;
}
function modelRouteReadiness(route) {
  if (!route.enabled) return ["未启用", null];
  if (route.ready) return ["已就绪", true];
  return ["缺少运行配置", false];
}
function renderAgentModelRouteStatus(value) {
  const panel = el("section", undefined, "admin-panel");
  panel.append(
    el("h2", "Agent 模型路由"),
    el(
      "p",
      "展示每位长期成员当前配置的主模型与降级顺序；这是路由就绪状态，不代表 Agent 正在调用模型。",
      "muted",
    ),
  );
  const policies = value.agent_model_routes || [];
  if (!policies.length) {
    panel.append(el("div", "当前服务尚未提供 Agent 模型路由状态。", "empty"));
    return panel;
  }
  const grid = el("div", undefined, "agent-route-status-grid");
  for (const [role, title] of agentModelRoles) {
    const policy = policies.find((candidate) => candidate.role === role);
    const card = el("article", undefined, "agent-route-status-card");
    const head = el("div", undefined, "row");
    head.append(
      el("strong", title),
      el(
        "span",
        policy?.policy_source === "agent_policy" ? "独立策略" : "继承全局顺序",
        "badge",
      ),
    );
    card.append(head);
    if (!policy?.routes?.length) {
      card.append(el("p", "未配置可用模型。", "muted"));
      grid.append(card);
      continue;
    }
    const list = el("div", undefined, "agent-route-status-list");
    policy.routes.forEach((route, index) => {
      const [readiness, ready] = modelRouteReadiness(route);
      const row = el("div", undefined, "agent-route-status-row");
      row.append(
        el("span", index === 0 ? "主模型" : `备用 ${index}`, "route-position"),
        el(
          "span",
          `${route.provider} / ${route.model} · ${route.reasoning_effort}`,
          "agent-route-identity",
        ),
        el(
          "span",
          readiness,
          ready === true
            ? "badge done"
            : ready === false
              ? "badge blocked"
              : "badge",
        ),
      );
      list.append(row);
    });
    card.append(list);
    grid.append(card);
  }
  panel.append(grid);
  return panel;
}
function renderStatus(content) {
  if (runtimeStatusLoading) {
    content.append(el("div", "正在读取平台运行状态…", "admin-notice"));
    return;
  }
  if (!administrationAvailable) {
    administrationUnavailable(content);
    return;
  }
  if (!runtimeStatusSnapshot) {
    content.append(
      el(
        "div",
        runtimeStatusError || "平台状态暂时无法读取。",
        "operation-error",
      ),
    );
    return;
  }
  const value = runtimeStatusSnapshot;
  const ready =
    value.delivery_runtime === "READY" &&
    value.database.connection === "CONNECTED" &&
    value.team_prepared;
  const summary = el(
    "section",
    undefined,
    ready
      ? "status-summary status-summary-ready"
      : "status-summary status-summary-blocked",
  );
  summary.append(
    el("strong", ready ? "平台可以接收交付任务" : "平台仍有待处理配置"),
    el(
      "p",
      ready
        ? "数据库、Team workspace 与交付运行时均已就绪。"
        : "请根据下方橙色状态处理配置或重启问题。",
      "muted",
    ),
  );
  const overview = el("section", undefined, "admin-panel");
  overview.append(
    el("h2", "配置与启动"),
    statusRow(
      "当前配置",
      value.config_source === "default"
        ? "内置默认配置"
        : value.restart_required
          ? "已保存，等待重启"
          : "已生效",
      value.config_source === "default" ? null : !value.restart_required,
    ),
    el("p", "配置文件 · " + value.config_path, "paths"),
    el("p", "运行变量 · " + value.runtime_environment_path, "paths"),
  );
  const runtime = el("section", undefined, "admin-panel");
  runtime.append(
    el("h2", "运行依赖"),
    statusRow(
      "交付运行时",
      value.delivery_runtime === "READY" ? "已就绪" : "待配置或重启",
      value.delivery_runtime === "READY",
    ),
    statusRow(
      "真实模型执行",
      value.live_model_execution ? "已启用" : "未启用",
      value.live_model_execution,
    ),
    statusRow(
      "MySQL",
      value.database.connection === "CONNECTED"
        ? `连接正常 · ${value.database.source}`
        : value.database.connection === "NOT_CONFIGURED"
          ? "尚未配置"
          : `连接失败 · ${value.database.source}`,
      value.database.connection === "CONNECTED",
    ),
    statusRow(
      "Codex CLI",
      value.codex.available
        ? `可执行 · ${value.codex.resolved_path}`
        : `不可用 · ${value.codex.executable}`,
      value.codex.available,
    ),
    statusRow(
      "Team workspace",
      value.team_prepared ? "已准备" : "尚未准备",
      value.team_prepared,
    ),
    statusRow(
      "团队知识",
      `已导入 ${value.team_knowledge_imported} 份 · 已启用 ${value.team_knowledge_selected} 份`,
      value.team_prepared ? null : false,
    ),
  );
  const agentRoutes = renderAgentModelRouteStatus(value);
  const routes = el("section", undefined, "admin-panel");
  routes.append(
    el("h2", "可用模型目录"),
    el(
      "p",
      "这里检查 Provider、模型执行器和凭证是否可用；具体由哪位 Agent 优先使用，请以上方策略为准。",
      "muted",
    ),
  );
  for (const route of value.model_routes)
    routes.append(
      statusRow(
        `${route.provider} / ${route.model} · ${route.reasoning_effort}`,
        !route.enabled ? "未启用" : route.ready ? "已就绪" : "缺少运行配置",
        !route.enabled ? null : route.ready,
      ),
    );
  const grid = el("div", undefined, "status-grid");
  grid.append(overview, runtime);
  content.append(summary, grid, agentRoutes, routes);
}
function showDetail(kind, id) {
  selected = { kind, id };
  if (page === "requests") {
    const request =
      kind === "request"
        ? requestById(id)
        : requestById(taskById(id)?.request_id);
    if (request) requestFilter = requestGroup(request);
  }
  render();
  document
    .getElementById("detail")
    .scrollIntoView({ behavior: "smooth", block: "start" });
}
function deliveryFlow(request) {
  const steps = ["产品", "设计", "计划", "实现", "测试", "评审", "交付"];
  const requestStages = {
    READY_FOR_DISCUSSION: 0,
    PRODUCT_DISCOVERY: 0,
    WAITING_PRODUCT_REPLY: 0,
    WAITING_PRODUCT_APPROVAL: 0,
    DESIGNING: 1,
    PLANNING: 2,
    DISPATCHING: 2,
    DELIVERING: 3,
    VERIFY_QA: 4,
    VERIFY_REVIEW: 5,
    INTEGRATING: 6,
    WAITING_DELIVERY_FINALIZATION: 6,
    DONE: 6,
    CLOSED: 6,
  };
  const presentedStage = requestPresentation(request).status;
  const effectiveStage = ["VERIFY_QA", "VERIFY_REVIEW"].includes(presentedStage)
    ? presentedStage
    : request.stage;
  let current = requestStages[effectiveStage] ?? 0;
  const taskStatuses = request.scopes
    .map((scope) => taskById(scope.delivery_id)?.status)
    .filter(Boolean);
  if (!["VERIFY_QA", "VERIFY_REVIEW"].includes(effectiveStage)) {
    if (taskStatuses.includes("REVIEW")) current = 5;
    else if (taskStatuses.includes("QA")) current = 4;
    else if (
      taskStatuses.some((status) =>
        ["IMPLEMENTING", "CONTINUE_REQUIRED", "QUEUED"].includes(status),
      )
    )
      current = 3;
  }
  const flow = el("ol", undefined, "delivery-flow");
  steps.forEach((title, index) => {
    const step = el("li", undefined, index < current ? "done" : "");
    if (index === current) step.className = "current";
    step.append(el("span", String(index + 1)), el("strong", title));
    flow.append(step);
  });
  return flow;
}
function renderDetail() {
  const panel = document.getElementById("detail");
  panel.replaceChildren();
  panel.className = "";
  panel.hidden =
    (!selected && page !== "requests") ||
    (page === "requests" && !snapshot.requests.length);
  if (panel.hidden) return;
  if (!selected) {
    if (page === "requests") {
      panel.className = "detail-placeholder";
      panel.append(
        el("h2", "交付详情"),
        el(
          "p",
          "从左侧选择一个需求或仓库任务，查看交付阶段、下一步操作、候选分支和验证证据。",
          "muted",
        ),
      );
    }
    return;
  }
  const item =
    selected.kind === "task" ? taskById(selected.id) : requestById(selected.id);
  if (!item) {
    panel.append(el("p", "当前快照中找不到这条记录。"));
    return;
  }
  const top = el("div", undefined, "row");
  const topActions = el("div", undefined, "detail-heading-actions");
  if (
    selected.kind === "request" &&
    !activeOperation(item.id) &&
    canControlCurrentTeam()
  ) {
    if (item.stage === "READY_FOR_DISCUSSION")
      topActions.append(
        button(
          "编辑需求",
          () => {
            creatingProject = false;
            recreatingRequirement = null;
            editingRequirement = item;
            composing = true;
            renderComposer();
          },
          "secondary",
        ),
      );
    if (item.stage === "BLOCKED")
      topActions.append(
        button(
          "关闭需求",
          () =>
            confirmMutation(
              "关闭需求",
              `确认关闭“${item.title}”吗？交付会停止，需求与交付历史仍会保留。`,
              "确认关闭",
              async () => {
                const accepted = await submitOperation({
                  action: "CLOSE_REQUIREMENT",
                  project_id: item.project_id,
                  delivery_id: item.id,
                  expected_checkpoint_sha256: item.checkpoint_sha256,
                });
                if (!accepted) throw new Error("关闭操作未被接受。");
              },
            ),
          "secondary",
        ),
      );
    if (item.stage === "CLOSED")
      topActions.append(
        button(
          "重新启动需求",
          () =>
            confirmMutation(
              "重新启动需求",
              `确认重新启动“${item.title}”吗？需求会回到待继续交付状态，并保留此前的全部交付历史。`,
              "确认重新启动",
              async () => {
                const accepted = await submitOperation({
                  action: "RESTART_REQUIREMENT",
                  project_id: item.project_id,
                  delivery_id: item.id,
                  expected_checkpoint_sha256: item.checkpoint_sha256,
                });
                if (!accepted) throw new Error("重新启动操作未被接受。");
              },
            ),
          "primary",
        ),
      );
    if (
      productDiscussionStages.has(item.stage) ||
      ["BLOCKED", "CLOSED"].includes(item.stage)
    )
      topActions.append(
        button(
          "删除需求",
          () =>
            confirmMutation(
              "删除需求",
              `确认从当前 Project 删除“${item.title}”吗？历史记录会保留，但该需求将不能继续交付。`,
              "确认删除",
              async () => {
                const accepted = await submitOperation({
                  action: "DELETE_REQUIREMENT",
                  project_id: item.project_id,
                  delivery_id: item.id,
                  expected_checkpoint_sha256: item.checkpoint_sha256,
                });
                if (!accepted) throw new Error("删除操作未被接受。");
              },
            ),
          "danger",
        ),
      );
  }
  topActions.append(
    button(
      selected.kind === "request" ? "关闭详情" : "关闭",
      () => {
        selected = null;
        render();
      },
      "",
    ),
  );
  top.append(
    el(
      "h2",
      selected.kind === "task" ? "任务详情" : "需求详情",
      selected.kind === "request" ? "detail-panel-heading" : "",
    ),
    topActions,
  );
  if (selected.kind === "request") {
    const presentation = requestPresentation(item);
    panel.className = "request-detail-panel";
    const overview = el("section", undefined, "request-detail-overview");
    overview.append(
      top,
      el("h3", item.title, "request-detail-title"),
      el("p", item.id, "paths request-detail-id"),
      badge(presentation.status),
    );
    if (presentation.group !== "blocked")
      overview.append(
        el(
          "p",
          "下一步 · " + presentation.nextAction,
          "muted request-detail-next",
        ),
      );
    panel.append(overview);
    const blocking = requestBlockerSection(item);
    if (blocking) panel.append(blocking);
    if (item.stage === "WAITING_HUMAN") {
      const gaps = el("section", undefined, "detail-section");
      gaps.append(el("h2", "知识缺口"));
      gaps.append(button("查看待确认的知识", async () => {
        try {
          const base = "/api/v1/admin/projects/" + encodeURIComponent(item.project_id) +
            "/requirements/" + encodeURIComponent(item.id);
          const records = await adminFetch(base + "/knowledge-gaps");
          for (const gap of records) {
            const card = el("form", undefined, "knowledge-upload");
            const answer = el("textarea");
            answer.required = true;
            answer.maxLength = 4096;
            answer.placeholder = "补充已核实的事实；提交表示批准该解答用于当前需求。";
            const source = el("input");
            source.required = true;
            source.placeholder = "事实来源或人工决策说明";
            const submit = el("button", "批准解答", "primary");
            submit.type = "submit";
            card.append(el("h3", gap.question), el("p", gap.required_decision), answer, source, submit);
            card.addEventListener("submit", async (event) => {
              event.preventDefault();
              submit.disabled = true;
              try {
                const content = answer.value.trim();
                const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(content));
                const sha256 = Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, "0")).join("");
                await adminFetch(base + "/knowledge-resolutions", {method: "POST", headers: {"Content-Type": "application/json"},
                  body: JSON.stringify({gap_id: gap.gap_id, answer: content,
                    sources: [{uri: source.value.trim(), content, sha256}],
                    approval_reference: "local-console:" + gap.gap_id})});
                card.replaceChildren(el("p", "解答已批准，原始证据保留。"), button("继续需求", () => submitOperation({
                  action: "CONTINUE_DELIVERY", project_id: item.project_id, delivery_id: item.id,
                }), "primary"));
              } catch (error) {
                card.append(el("p", error.message || "解答未被接受。", "error"));
                submit.disabled = false;
              }
            });
            gaps.append(card);
          }
          if (!records.length) gaps.append(el("p", "当前没有已记录的知识缺口。"));
        } catch (error) {
          gaps.append(el("p", error.message || "无法读取知识缺口。", "error"));
        }
      }, "secondary"));
      panel.append(gaps);
    }
    const flow = el("section", undefined, "detail-section");
    flow.append(el("h2", "交付流程"), deliveryFlow(item));
    panel.append(flow);
    const scopes = el("section", undefined, "detail-section");
    scopes.append(el("h2", "涉及代码目录"));
    const currentTasks = currentRequestTasks(item);
    for (const scope of item.scopes) {
      const scopeCard = el("div", undefined, "request-scope-card");
      scopeCard.append(el("p", paths(scope), "paths"));
      const task = currentTasks.find(
        (candidate) =>
          (candidate.source_delivery_id || candidate.id) === scope.delivery_id,
      );
      if (task)
        scopeCard.append(
          button("查看仓库任务 · " + label(task.status), () =>
            showDetail("task", task.id),
          ),
        );
      else scopeCard.append(el("span", "尚未生成交付任务", "badge"));
      scopes.append(scopeCard);
    }
    panel.append(scopes);
    const discussionSection = requestDialogue(panel, item);
    requestOperation(panel, item, discussionSection);
    deliveryResult(panel, item);
    const artifacts = el("section", undefined, "detail-section stage-artifacts");
    artifacts.append(el("h2", "阶段产物"));
    documentList(artifacts, item.documents);
    panel.append(artifacts);
    return;
  }
  panel.className = "task-detail-modal";
  const dialog = el(
    "section",
    undefined,
    "modal-dialog modal-dialog-wide task-detail-dialog",
  );
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.setAttribute("aria-label", "任务详情");
  dialog.append(
    top,
    el("h3", item.title),
    el("p", item.id, "paths"),
    badge(item.status || item.stage),
  );
  dialog.append(
    el("p", paths(item.scope), "paths"),
    el("p", "最近活动 · " + time(item.last_activity), "muted"),
  );
  if (item.candidate_revision)
    dialog.append(el("p", "候选版本 · " + item.candidate_revision, "paths"));
  if (item.candidate_branch)
    dialog.append(el("p", "候选分支 · " + item.candidate_branch, "paths"));
  dialog.append(el("h2", "成员与分配模型"));
  for (const a of item.assignments)
    dialog.append(
      el(
        "p",
        `${snapshot.agents.find((x) => x.id === a.agent_id)?.name || a.agent_id} · ${label(a.role)} · ${a.planned_provider} / ${a.planned_model}${a.current_stage ? " · 当前阶段" : ""}`,
      ),
    );
  dialog.append(el("h2", "执行与阶段时间线"));
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
  dialog.append(list);
  dialog.append(el("h2", "已完成的模型调用"));
  if (!item.runs.length)
    dialog.append(
      el("p", "暂无已提交调用记录；进行中的调用完成后才会出现。", "muted"),
    );
  for (const run of item.runs) {
    dialog.append(
      el(
        "p",
        `${label(run.role)} · ${run.provider} / ${run.model} · 第 ${run.route_index} 路 · ${label(run.outcome)} · ${(run.duration_ms / 1000).toFixed(1)} 秒`,
      ),
    );
    if (run.error_code) dialog.append(el("div", run.error_code, "blocker"));
    dialog.append(
      el("div", time(run.completed_at) + " · " + run.source_uri, "paths"),
    );
  }
  dialog.append(el("h2", "产物与报告"));
  documentList(dialog, item.documents);
  panel.append(dialog);
}
function render() {
  if (!snapshot) return;
  const expanded = new Set(
    [...document.querySelectorAll("details[open]")].map((n) => n.dataset.key),
  );
  document.getElementById("team").textContent = snapshot.team_name;
  document.getElementById("main").dataset.page = page;
  const projects = document.getElementById("projects");
  projects.replaceChildren();
  renderProjectPicker(projects);
  projects.hidden = !["team", "requests"].includes(page);
  document.getElementById("context-controls").hidden = projects.hidden;
  const projectCreator = document.getElementById("project-creator");
  projectCreator.replaceChildren();
  projectCreator.hidden = page !== "requests" || !canControlCurrentTeam();
  if (!projectCreator.hidden) renderProjectCreator(projectCreator);
  document.getElementById("heading").textContent = pageCopy[page][0];
  document.getElementById("explanation").textContent = pageCopy[page][1];
  updatePageContext();
  const content = document.getElementById("content");
  content.replaceChildren();
  content.className = "";
  if (page === "team") renderTeam(content);
  else if (page === "requests") renderRequests(content);
  else if (page === "knowledge") renderKnowledge(content);
  else if (page === "settings") renderSettings(content);
  else renderStatus(content);
  renderComposer();
  renderOperationStatus();
  renderDetail();
  for (const node of document.querySelectorAll("details"))
    if (expanded.has(node.dataset.key)) node.open = true;
}
function updateNavigation() {
  for (const key of ["team", "requests", "knowledge", "settings", "status"]) {
    const node = document.getElementById("nav-" + key);
    node.classList.toggle("selected", key === page);
    if (key === page) node.setAttribute("aria-current", "page");
    else node.removeAttribute("aria-current");
  }
}
for (const target of ["team", "requests", "knowledge", "settings", "status"])
  document
    .getElementById("nav-" + target)
    .addEventListener("click", async () => {
      administrationNotice = null;
      page = target;
      selected = null;
      composing = false;
      creatingProject = false;
      editingRequirement = null;
      recreatingRequirement = null;
      knowledgeImportMode = null;
      pendingConfirmation = null;
      settingsSaveResult = null;
      editingKnowledgeDocument = null;
      editingSpecDocument = null;
      if (target === "knowledge") await loadAdministration();
      if (target === "settings") await loadAdministration();
      if (target === "status") {
        runtimeStatusLoading = true;
        updateNavigation();
        render();
        await loadAdministration();
        if (administrationAvailable) await loadRuntimeStatus();
        runtimeStatusLoading = false;
      }
      updateNavigation();
      render();
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
      info.schema_version !== "v0.2" ||
      typeof info.team_id !== "string" ||
      typeof info.delivery_ready !== "boolean" ||
      !Array.isArray(nextOperations)
    )
      throw new Error("invalid console response");
    consoleAvailable = true;
    consoleTeamId = info.team_id;
    consoleDeliveryReady = info.delivery_ready;
    operations = nextOperations;
  } catch {
    consoleAvailable = false;
    consoleTeamId = null;
    consoleDeliveryReady = null;
    operations = [];
  }
}
async function refresh(projectId, includeRuntimeStatus = false) {
  if (refreshing) return;
  refreshing = true;
  document.getElementById("refresh").disabled = true;
  const status = document.getElementById("connection");
  const controller = new AbortController(),
    timeout = setTimeout(() => controller.abort(), 40000);
  try {
    const target = projectId || (snapshot && snapshot.selected_project_id);
    const url = target
      ? "/api/v1/team?project_id=" + encodeURIComponent(target)
      : "/api/v1/team";
    const response = await fetch(url, {
      cache: "no-store",
      signal: controller.signal,
    });
    if (!response.ok) throw new Error("read failed");
    const next = await response.json();
    if (
      next.schema_version !== "v0.2" ||
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
    const priorKnowledgeIndex = JSON.stringify(knowledgeIndexStatus);
    const priorConsoleTeam = consoleTeamId;
    const priorConsoleReady = consoleDeliveryReady;
    const priorRuntimeStatus = JSON.stringify(runtimeStatusSnapshot);
    const selectedBeforeRefresh = selected;
    snapshot = next;
    await refreshOperations();
    if (configurationApplyInFlight && page === "settings")
      await refreshConfigurationApply();
    if (
      selectedBeforeRefresh?.kind === "request" &&
      !requestById(selectedBeforeRefresh.id)
    ) {
      const replacement = [...operations]
        .sort((left, right) => right.updated_at.localeCompare(left.updated_at))
        .find(
          (operation) =>
            operation.status === "SUCCEEDED" &&
            operation.intent.action === "UPDATE_REQUIREMENT" &&
            operation.intent.delivery_id === selectedBeforeRefresh.id &&
            operation.result?.delivery_id &&
            requestById(operation.result.delivery_id),
        );
      selected = replacement
        ? { kind: "request", id: replacement.result.delivery_id }
        : null;
    }
    if (page === "knowledge" && target !== undefined)
      await loadAdministration();
    if (includeRuntimeStatus && page === "status" && administrationAvailable)
      await loadRuntimeStatus();
    const modalActive =
      composing ||
      creatingProject ||
      editingRequirement ||
      recreatingRequirement ||
      knowledgeImportMode ||
      pendingConfirmation ||
      settingsSaveResult ||
      editingKnowledgeDocument ||
      editingSpecDocument;
    if (
      !modalActive &&
      (changed ||
        priorOperations !== JSON.stringify(operations) ||
        priorConsoleTeam !== consoleTeamId ||
        priorConsoleReady !== consoleDeliveryReady ||
        priorKnowledgeIndex !== JSON.stringify(knowledgeIndexStatus) ||
        priorRuntimeStatus !== JSON.stringify(runtimeStatusSnapshot))
    )
      render();
    status.className = "";
    status.textContent = consoleAvailable
      ? (consoleDeliveryReady
          ? "团队与交付控制台已连接"
          : "设置控制台已连接 · 交付运行时待配置或重启") +
        " · 最近读取 " +
        time(snapshot.as_of) +
        " · 每 5 秒刷新"
      : "只读团队记录已连接；交付控制台暂不可用。";
  } catch {
    status.className = "error";
    status.textContent = snapshot
      ? "刷新失败，以下为旧数据 · 上次成功读取 " + time(snapshot.as_of)
      : "暂时无法读取数据。请检查生产配置、MySQL 连接，以及 Team/Project workspace 是否已准备。";
  } finally {
    clearTimeout(timeout);
    refreshing = false;
    document.getElementById("refresh").disabled = false;
  }
}
document
  .getElementById("refresh")
  .addEventListener("click", () => refresh(undefined, true));
refresh();
setInterval(refresh, 5000);
