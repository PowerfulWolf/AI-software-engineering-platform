"use strict";
let snapshot = null;
let page = "team";
let selected = null;
let pausedTaskDetailKey = null;
let refreshing = false;
let refreshFlight = null;
let requestedProjectId = null;
let activeRefreshProject = null;
let refreshQueued = false;
let requestedRuntimeStatus = false;
let operations = [];
let operationsAvailable = false;
let consoleAvailable = null;
let consoleConnectionFailed = false;
let consoleTeamId = null;
let consoleDeliveryReady = null;
let consoleOperationContractVersion = null;
let consoleSupportedActions = null;
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
let operationNotice = null;
let renderedNotificationSignature = null;
let notificationReturnFocus = null;
const discussionFormCaches = new Map();
let settingsDraftBaseline = null;
let knowledgeReadSerial = 0;
let administrationLoadPromise = null;
let knowledgeLoading = false;
let knowledgeError = null;
let knowledgeLoadedContext = null;
let composing = false;
let pendingConfirmation = null;
let actionSerial = 0;
let requestFilter = "active";
let settingsSection = "general";
let expandedModelRouteIndex = null;
const expandedAgentModelRoles = new Set();
let settingsSaveResult = null;
const settingsContractVersion = 2;
const settingsVersionMismatchMessage =
  "设置页面与当前服务版本不匹配。请重启 Web Console 后刷新页面，再保存配置。";
const consoleOperationContractVersionExpected = 1;
const consoleOperationVersionMismatchMessage =
  "页面暂不能提交后续新操作：页面与服务版本不匹配。请在当前操作和角色执行结束、服务空闲时重启 Web Console 并刷新页面；原需求和已保存进度保留。";
function consoleSupportsOperation(action) {
  return consoleOperationContractVersion >= consoleOperationContractVersionExpected &&
    Array.isArray(consoleSupportedActions) && consoleSupportedActions.includes(action);
}
function consoleSupportsLegacyRescue() {
  return consoleOperationContractVersion >= 2 &&
    consoleSupportsOperation("PROPOSE_EXECUTION_BASELINE") && consoleSupportsOperation("EXECUTE_EXECUTION_BASELINE");
}
function consoleSupportsLocalRescue() {
  return consoleOperationContractVersion >= 3 && consoleSupportsLegacyRescue();
}
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
const knowledgeGapSections = new Map();
// Signatures stay in memory; draft values and credentials must never become DOM attributes.
const renderedSurfaces = new WeakMap();
const renderedBlocks = new WeakMap();
function viewBlock(node, key, facts) {
  renderedBlocks.set(node, {key, signature: JSON.stringify(facts)});
  return node;
}
function viewGroup(node, key) {
  renderedBlocks.set(node, {key, signature: null});
  return node;
}
function reconcileViewChildren(current, next) {
  const existing = new Map([...current.childNodes].flatMap(node => {
    const block = renderedBlocks.get(node);
    return block ? [[block.key, node]] : [];
  }));
  const desired = [...next.childNodes];
  desired.forEach((node, index) => {
    const block = renderedBlocks.get(node);
    const old = block && existing.get(block.key);
    let replacement = node;
    if (old) {
      const previous = renderedBlocks.get(old);
      if (block.signature !== null && previous.signature === block.signature)
        replacement = old;
      else if (block.signature === null && previous.signature === null && old.tagName === node.tagName) {
        old.className = node.className;
        old.hidden = node.hidden;
        reconcileViewChildren(old, node);
        replacement = old;
      }
    }
    const position = current.childNodes[index] || null;
    if (position !== replacement) {
      if (replacement.parentNode === current && typeof current.moveBefore === "function")
        current.moveBefore(replacement, position);
      else current.insertBefore(replacement, position);
    }
  });
  while (current.childNodes.length > desired.length) current.lastChild.remove();
}
function renderView(container, key, facts, build, incremental) {
  const previous = renderedSurfaces.get(container);
  if (incremental && previous?.key === key && previous.signature === JSON.stringify(facts())) return;
  if (incremental && previous?.key === key && typeof container.insertBefore === "function") {
    const next = el("div");
    build(next);
    container.className = next.className;
    container.hidden = next.hidden;
    reconcileViewChildren(container, next);
  } else {
    container.replaceChildren();
    build(container);
  }
  renderedSurfaces.set(container, {key, signature: JSON.stringify(facts())});
}
function pollingControlFacts() {
  return [consoleAvailable, consoleTeamId, consoleDeliveryReady, consoleOperationContractVersion,
    consoleSupportedActions, operationsAvailable,
    snapshot?.team_id, currentProjectId(), projectSwitchPending()];
}
function pollingContentFacts() {
  const common = [page, pollingControlFacts(), administrationNotice];
  if (page === "settings") return [...common, administrationAvailable, settingsSnapshot,
    settingsSection, configurationApplyInFlight, configurationApplyResult];
  if (page === "status") return [...common, administrationAvailable, runtimeStatusSnapshot,
    runtimeStatusLoading, runtimeStatusError];
  if (page === "knowledge") return [...common, snapshot?.team_name, snapshot?.projects,
    knowledgeScope, knowledgeMode, knowledgeDocuments, knowledgeIndexStatus, specDocuments,
    learningProposals, knowledgeLoading, knowledgeError];
  return [...common, snapshot?.team_name, snapshot?.projects, snapshot?.agents, snapshot?.tasks,
    snapshot?.requests, operations, selected, selectedAgentId, requestFilter];
}
function pollingKnowledgeFacts() {
  return [knowledgeDocuments, knowledgeIndexStatus, specDocuments, learningProposals,
    knowledgeLoading, knowledgeError];
}
function pollingDetailFacts() {
  const item = selected?.kind === "task" ? taskById(selected.id)
    : selected ? requestById(selected.id) : null;
  const tasks = selected?.kind === "request" && item ? requestTasks(item) : [];
  return [page, selected, item, tasks, snapshot?.agents, pollingControlFacts(),
    item ? operations.filter(operation => operationTarget(operation) === item.id) : [],
    page === "requests" && Boolean(snapshot?.requests.length)];
}
const acknowledgedOperationNoticeKeys = new Set(
  (() => {
    try {
      const stored = globalThis.localStorage?.getItem(
        "ase-acknowledged-operation-notices",
      );
      const parsed = stored ? JSON.parse(stored) : [];
      return Array.isArray(parsed) && parsed.every((value) => typeof value === "string")
        ? parsed.slice(-200)
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
  RETRY_BUDGET_EXHAUSTED: "执行预算已用尽",
  PLANNER_RETRY_REQUIRED: "计划执行待重试",
  WAITING_PRODUCT_APPROVAL: "等待产品批准",
  DESIGNING: "技术设计",
  DESIGN_RETRY_REQUIRED: "设计待重试",
  DESIGN_RECOVERY_REQUIRED: "设计待恢复",
  DESIGN_BUDGET_EXHAUSTED: "设计预算已用尽",
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
  VERIFIED: "候选验证已通过",
  VERIFICATION_SUPERSEDED: "历史验证已替代",
  DONE: "已完成",
  CLOSED: "已关闭",
  BLOCKED: "已阻塞",
  FAILED: "失败",
  WAITING_HUMAN: "等待人工",
  KNOWLEDGE_APPROVED: "已确认的知识 · 待继续",
  WAITING_DEPENDENCY: "等待依赖",
  READY: "等待调度",
  LEASED: "已领取",
  RETRY_SCHEDULED: "等待重试",
  WAITING_ENGINEERING: "等待工程处理",
  WAITING_TEAM: "团队处理中",
  WAITING_PRODUCT_DECISION: "需要产品确认",
  EXECUTION_UNKNOWN: "执行状态待确认",
  ENGINEERING_STOPPED: "交付已停止",
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
  EXECUTION_INTERRUPTED: "执行中断",
  PREPARING_EXECUTION: "准备执行",
  CREATE_PROJECT: "创建项目",
  CREATE_REQUIREMENT: "创建需求",
  UPDATE_REQUIREMENT: "编辑需求",
  CLOSE_REQUIREMENT: "关闭需求",
  RESTART_REQUIREMENT: "重新启动需求",
  DELETE_REQUIREMENT: "删除需求",
  PRODUCT_REPLY: "提交需求说明",
  PRODUCT_APPROVAL: "批准产品文档",
  CONTINUE_DELIVERY: "继续交付",
  RECOVER_DESIGN: "恢复设计",
  RECHECK_DESIGN: "重新核对设计",
  INSPECT_DELIVERY_WAIT: "调查工程等待",
  HANDLE_DELIVERY_WAIT: "让平台处理中断",
  RESOLVE_DELIVERY_WAIT: "处理工程等待",
  PROPOSE_EXECUTION_BASELINE: "调查执行基线更新",
  EXECUTE_EXECUTION_BASELINE: "更新原需求执行基线",
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
  "RECOVER_DESIGN",
  "RECHECK_DESIGN",
]);
const deliveryRoleOrder = { coder: 0, qa: 1, reviewer: 2 };
const deliveryRoleStage = { coder: 3, qa: 4, reviewer: 5 };
const roleForTaskStatus = {IMPLEMENTING: "coder", QA: "qa", REVIEW: "reviewer", VERIFY_QA: "qa", VERIFY_REVIEW: "reviewer"};
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
    "分析跨阶段阻塞并提出协调、恢复与验证方案；执行受权限、预算和精确审批约束，不能代替 QA/Reviewer 验收。",
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
    team: ["Team 级", snapshot?.team_name || "Team 记录暂不可用", "工作负载筛选"],
    requests: ["Project 级", projectName(), "当前 Project"],
    knowledge:
      knowledgeScope === "team"
        ? ["Team 知识", snapshot?.team_name || "Team 记录暂不可用", ""]
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
  n.type = "button";
  n.addEventListener("click", (event) => {
    if (text === "取消" && !mayCloseComposer()) return;
    return runUiAction(n.closest?.(".modal-dialog"), () => action(event));
  });
  return n;
};
const deliveryButton = (text, action, className = "link") => {
  const control = button(text, (...args) => {
    if (control.isConnected === false) {
      operationNotice = {kind: "error", title: "交付操作已失效",
        message: "此操作已随页面更新失效。请查看当前需求，重新核对页面显示的方案后再确认。"};
      renderNotification();
      return null;
    }
    if (canControlCurrentTeam()) return action(...args);
  }, className);
  control.setAttribute("data-delivery-control", "true");
  return control;
};
const suspendedDeliveryControls = new WeakMap();
function setDeliveryControlDisabled(control, disabled) {
  const ready = canControlCurrentTeam();
  if (ready) suspendedDeliveryControls.delete(control);
  else suspendedDeliveryControls.set(control, Boolean(disabled));
  control.disabled = Boolean(disabled) || !ready;
}
function syncDeliveryControls() {
  const ready = canControlCurrentTeam();
  document.getElementById("project-creator").hidden = page !== "requests" || !ready;
  for (const control of document.querySelectorAll('[data-delivery-control="true"]')) {
    if (!ready) {
      if (!suspendedDeliveryControls.has(control))
        suspendedDeliveryControls.set(control, Boolean(control.disabled));
      control.disabled = true;
    } else if (suspendedDeliveryControls.has(control)) {
      control.disabled = suspendedDeliveryControls.get(control);
      suspendedDeliveryControls.delete(control);
    }
  }
}
const time = (value) =>
  value ? new Date(value).toLocaleString() : "暂无活动记录";
const badge = (status) =>
  el(
    "span",
    label(status),
    "badge " +
      (["DONE", "CLOSED"].includes(status)
        ? "done"
        : status.includes("WAITING") || ["BLOCKED", "FAILED", "EXECUTION_INTERRUPTED", "INTERRUPTED", "ENGINEERING_STOPPED"].includes(status)
          ? ["INTERRUPTED", "ENGINEERING_STOPPED"].includes(status) ? "blocked execution-interrupted" : "blocked"
          : ["READY", "LEASED", "QUEUED", "RETRY_SCHEDULED", "CONTINUE_REQUIRED", "PREPARING_EXECUTION"].includes(status)
            ? "" : "current"),
  );
const operationTarget = (operation) =>
  operation.intent.delivery_id || operation.result?.delivery_id || null;
const currentProjectId = () => snapshot?.selected_project_id || null;
const projectSwitchPending = () =>
  requestedProjectId !== null && requestedProjectId !== currentProjectId();
const activeOperation = (deliveryId, projectId = null) =>
  operations.find(
    (operation) =>
      operationTarget(operation) === deliveryId &&
      (!projectId || operation.intent.project_id === projectId) &&
      ["QUEUED", "RUNNING"].includes(operation.status),
  );
const latestOperation = (deliveryId) =>
  [...operations]
    .filter((operation) => operationTarget(operation) === deliveryId)
    .sort((left, right) => right.updated_at.localeCompare(left.updated_at))[0] ||
  null;
const operationNeedsHumanAttention = (operation) =>
  operation?.status === "SUCCEEDED" &&
  (["WAITING_HUMAN", "BLOCKED", "FAILED"].includes(operation.result?.stage) ||
    ["NEEDS_AUTHORIZATION", "PLATFORM_ATTENTION", "WAITING_PREREQUISITES", "BUDGET_EXHAUSTED"]
      .includes(operation.result?.engineering_wait_handling?.status)) &&
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
            (operation.result.delivery_id === deliveryId
              ? operation.result.checkpoint_sha256
              : operation.intent.expected_checkpoint_sha256) !== checkpoint
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
function deliveryControlUnavailableReason() {
  if (projectSwitchPending()) return {
    title: "正在切换项目",
    reason: "正在切换项目，暂不能对当前需求提交操作。",
    next_action: "请等待目标项目加载完成，核对当前项目和需求后再操作。",
  };
  if (consoleAvailable !== true) return {
    title: "交付控制不可用",
    reason: consoleAvailable === false ? "当前服务未提供交付控制接口。"
      : "暂时无法连接或确认后台 Web Console。",
    next_action: consoleAvailable === false ? "请连接后台 Web Console，再刷新当前需求。原需求和开发进度保留。"
      : "请等待后台服务恢复连接，页面将自动重新读取；仍无法连接时由 ASE 平台维护者检查服务。原需求和开发进度保留。",
  };
  if (!operationsAvailable) return {
    title: "交付操作记录读取失败",
    reason: "平台暂时无法读取已保存的交付操作记录，因此不能确认当前恢复方案与审批状态。",
    next_action: "请由 ASE 平台维护者检查并修复操作记录读取；恢复后刷新当前需求，再核对恢复方案。不要重复准备方案或重建需求。",
  };
  if (consoleDeliveryReady !== true) return {
    title: "交付运行时尚未就绪",
    reason: "交付运行时尚未就绪，暂不能提交恢复或交付操作。",
    next_action: "请到设置或状态页查看未就绪原因，按页面提示处理；运行时就绪后刷新当前需求。原需求和开发进度保留。",
  };
  if (!snapshot) return {
    title: "团队数据暂不可读取",
    reason: "团队数据暂不可读取，尚不能核对当前页面与后台服务的绑定。",
    next_action: "请待团队数据恢复后刷新页面，再核对当前 Team、项目和需求后操作。",
  };
  if (snapshot.team_id !== consoleTeamId) return {
    title: "Team 绑定不一致",
    reason: "页面与后台服务的 Team 绑定不一致，暂时只能查看。",
    next_action: "请连接当前 Team 对应的后台 Web Console，核对 Team 与项目后刷新当前需求。",
  };
  return null;
}
const canControlCurrentTeam = () => deliveryControlUnavailableReason() === null;
function deliveryControlUnavailableNotice(reason) {
  const notice = viewBlock(el("div", undefined, "engineering-controls-unavailable"),
    "engineering-controls-unavailable", reason);
  notice.setAttribute("role", "status");
  notice.append(el("strong", reason.title), el("p", reason.reason),
    el("p", "下一步 · " + reason.next_action, "muted"));
  return notice;
}
function assignmentBadge(task, assignment) {
  if (task.terminal) return badge(task.status);
  const status = taskPresentationStatus(task);
  if (task.execution && task.role_queue?.some(step => step.role === assignment.role && step.status !== "CLOSED") &&
      (assignment.current_stage || status !== "RUNNING"))
    return badge(status);
  const waiting = waitingExecutionStep(task);
  if (waiting?.role === assignment.role) return badge(waiting.status);
  if (interruptedExecution(task) && task.role_queue.some(step =>
    step.role === assignment.role && interruptedStep(step))) return badge("EXECUTION_INTERRUPTED");
  if (assignment.current_stage) return badge(status);
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
function interruptedStep(step) {
  return step.lease_liveness === "LEASE_EXPIRED" &&
    (["RUNNING", "LEASED"].includes(step.status) ||
      (step.status === "RETRY_SCHEDULED" && step.wait_reason?.startsWith("lease_expired:")));
}
function interruptedExecution(task) {
  if (task.execution) return task.execution.reason_code === "EXECUTION_CLAIM_EXPIRED" ||
    task.execution.state === "INTERRUPTED";
  return !task.terminal && task.role_queue?.some(interruptedStep);
}
function waitingExecutionStep(task) {
  return !task.terminal && task.role_queue?.find(step =>
    ["WAITING_HUMAN", "WAITING_DEPENDENCY"].includes(step.status));
}
function executionPresentationStatus(execution) {
  if (execution.state === "COMPLETED" && execution.reason_code === "CANDIDATE_VERIFIED")
    return "VERIFIED";
  if (execution.state === "WAITING") return {
    product: "WAITING_PRODUCT_DECISION", team: "WAITING_TEAM", engineering: "WAITING_ENGINEERING",
  }[execution.responsibility];
  return {RUNNING: "RUNNING", QUEUED: "READY", RETRY_SCHEDULED: "RETRY_SCHEDULED",
    INTERRUPTED: "INTERRUPTED", STOPPED: "ENGINEERING_STOPPED", UNKNOWN: "EXECUTION_UNKNOWN",
    COMPLETED: "DONE", SUPERSEDED: "VERIFICATION_SUPERSEDED"}[execution.state] || "EXECUTION_UNKNOWN";
}
function engineeringDetails(title = "工程详情", key = title) {
  const details = el("details", undefined, "engineering-details");
  details.dataset.key = `engineering:${key}`;
  details.append(el("summary", title));
  return details;
}
const engineeringResolutionLabels = {
  RETRY_FROM_CHECKPOINT: "继续原交付",
  REPLAY_RECORDED_RESULT: "使用已保存结果继续",
  RESUME_UNINVOKED: "继续未开始的工作",
  REVERIFY_CANDIDATE: "重新测试当前候选",
  RETRY_VERIFIER_PREPARATION: "重试验证准备",
};
const engineeringProofMissingGuidance = {
  TASK_PROCESS_LIVE: ["原工作仍在运行", "平台执行服务", "等待原工作结束，避免同时启动第二次执行。", "原工作结束并保存记录后再检查。"],
  INVOCATION_UNRECORDED: ["原执行的启动记录不完整", "平台维护者", "核对并补齐平台实际执行记录，不能把没有记录当作未执行。", "平台修复记录后再检查。"],
  OUTCOME_UNKNOWN: ["原工作是否完成尚未确认", "平台执行服务", "找回已保存的结果，或记录实际中断后再判断能否继续。", "原执行结束或平台保存结果后再检查。"],
  OUTCOME_REJECTED: ["原产出未通过平台校验", "平台维护者", "修复产出校验或执行契约问题；不能重复接纳已被拒绝的结果。", "问题修复且原执行记录已确认后再检查。"],
  STOP_UNRECORDED: ["原执行是否已结束还没有可靠记录", "平台执行服务或维护者", "平台需记录原执行的实际结束情况，再使用保留的进度继续。", "平台已补齐结束记录后再检查。"],
  PROCESS_LIVE_OR_UNKNOWN: ["原工作可能仍在运行", "平台执行服务", "先确认原工作已结束，避免重复执行影响原进度。", "原工作结束且状态记录更新后再检查。"],
  CHECKPOINT_UNAVAILABLE: ["保留进度的完整性尚未确认", "平台维护者", "核对已保存的开发进度和工作区；保留现有文件，不能直接清空或重建需求。", "保留进度完成核对后再检查。"],
  CHECKPOINT_DRIFT: ["保留的工作区已经变化", "工程团队", "核对变化与需求授权范围，确认可以使用的开发进度。", "工作区变化处理完成后再检查。"],
  PREREQUISITES_UNVERIFIED: ["执行或测试环境尚未就绪", "工程团队", "完成缺失工具、测试入口或受控环境的准备。", "环境准备完成后再检查。"],
  BUDGET_EXHAUSTED: ["当前执行额度已用完", "需求负责人", "决定是否追加执行额度；继续处理不会自动增加额度。", "新的额度授权生效后再检查。"],
  ORIGINAL_CLAIM_UNAVAILABLE: ["原执行的权限记录不完整", "平台维护者", "修复原执行身份与权限记录，不能通过人工确认跳过。", "平台修复记录后再检查。"],
  VERIFICATION_EVIDENCE_UNAVAILABLE: ["之前的测试记录或候选版本不完整", "工程团队", "核对已保存的测试报告与代码版本，补齐原验证证据。", "原验证证据核对完成后再检查。"],
  VERIFIER_PREPARATION_UNAVAILABLE: ["之前的验证准备记录不完整", "平台维护者", "核对验证准备过程与执行记录，保留当前代码候选。", "平台修复验证准备记录后再检查。"],
  NATIVE_EXECUTION_UNCERTAIN: ["原验证尚未确认结束", "平台执行服务", "先确认原测试或构建的实际结果，再继续独立验收。", "原验证结束且结果已保存后再检查。"],
};
const engineeringHandlingStatuses = new Set(["RESOLVED", "WAITING_EXECUTION", "NEEDS_AUTHORIZATION",
  "PLATFORM_ATTENTION", "WAITING_PREREQUISITES", "BUDGET_EXHAUSTED"]);
const engineeringCollectionFailureNotice = "部分执行事实已核验，但收集校验失败，当前不能继续。平台需处理校验问题后重新检查。";
function engineeringWaitSteps(request) {
  if (["DONE", "CLOSED"].includes(request.stage)) return [];
  return currentRequestTasks(request).filter(task => !task.terminal).flatMap(task =>
    (task.role_queue || []).filter(step =>
      ["WAITING_HUMAN", "WAITING_DEPENDENCY"].includes(step.status) &&
      step.wait_disposition?.responsibility === "engineering" &&
      step.wait_disposition.facts.work_item_id === step.work_item_id &&
      (!task.task_id || step.wait_disposition.facts.task_id === task.task_id)
    ).map(step => ({task, step})));
}
function engineeringWaitIntent(request, step) {
  const facts = step.wait_disposition.facts;
  return {
    project_id: request.project_id,
    delivery_id: request.id,
    expected_checkpoint_sha256: request.checkpoint_sha256,
    work_item_id: step.work_item_id,
    expected_disposition_sha256: step.wait_disposition_sha256,
    expected_task_intent_sha256: facts.task_intent_sha256,
    expected_source_revision: facts.source_revision,
    expected_checkpoint_sequence: facts.checkpoint_sequence,
  };
}
function sameEngineeringWaitIntent(intent, bound) {
  return Object.entries(bound).every(([key, value]) => intent?.[key] === value);
}
function latestEngineeringWaitOperation(request, step, actions = ["INSPECT_DELIVERY_WAIT", "HANDLE_DELIVERY_WAIT"]) {
  const bound = engineeringWaitIntent(request, step);
  return [...operations].sort((a, b) => b.updated_at.localeCompare(a.updated_at))
    .find(item => actions.includes(item.intent.action) &&
      sameEngineeringWaitIntent(item.intent, bound));
}
function matchingEngineeringWaitProof(proof, request, step) {
  const bound = engineeringWaitIntent(request, step);
  if (!proof || !Array.isArray(proof.missing) || !Array.isArray(proof.permitted_resolutions) ||
      proof.task_id !== step.wait_disposition.facts.task_id ||
      proof.work_item_id !== bound.work_item_id ||
      proof.disposition_sha256 !== bound.expected_disposition_sha256 ||
      proof.task_intent_sha256 !== bound.expected_task_intent_sha256 ||
      proof.source_revision !== bound.expected_source_revision ||
      proof.checkpoint_sequence !== bound.expected_checkpoint_sequence ||
      !/^[a-f0-9]{64}$/.test(proof.proof_sha256)) return null;
  return proof;
}
function engineeringWaitHandlingFromOperation(operation, request, step) {
  const handling = operation?.status === "SUCCEEDED" && operation.intent.action === "HANDLE_DELIVERY_WAIT"
    ? operation.result?.engineering_wait_handling : null;
  const proof = handling && matchingEngineeringWaitProof(handling.investigation, request, step);
  if (!handling || !proof || operation.result.checkpoint_sha256 !== request.checkpoint_sha256 ||
      handling.kind !== "delivery_wait_handling" || handling.schema_version !== "v1" ||
      typeof handling.manual_resolution_allowed !== "boolean" || !engineeringHandlingStatuses.has(handling.status) ||
      !/^[a-f0-9]{64}$/.test(handling.handling_sha256 || "") ||
      handling.task_id !== proof.task_id || handling.work_item_id !== proof.work_item_id ||
      handling.disposition_sha256 !== proof.disposition_sha256 ||
      handling.task_intent_sha256 !== proof.task_intent_sha256 || handling.source_revision !== proof.source_revision ||
      handling.checkpoint_sequence !== proof.checkpoint_sequence) return null;
  return handling;
}
function engineeringWaitHandling(request, step) {
  const handling = engineeringWaitHandlingFromOperation(
    latestEngineeringWaitOperation(request, step, ["HANDLE_DELIVERY_WAIT"]), request, step,
  );
  const proof = engineeringWaitProof(request, step);
  return handling && proof && sameEngineeringWaitProofFacts(handling.investigation, proof) ? handling : null;
}
function sameEngineeringWaitProofFacts(left, right) {
  const omitted = new Set(["proof_sha256", "inspected_at", "prerequisite_receipt_sha256"]);
  const canonical = value => {
    if (Array.isArray(value)) return value.map(canonical);
    if (value && typeof value === "object") return Object.fromEntries(Object.keys(value).sort()
      .map(key => [key, canonical(value[key])]));
    return value;
  };
  const facts = proof => canonical(Object.fromEntries(Object.entries(proof)
    .filter(([key]) => !omitted.has(key))));
  return JSON.stringify(facts(left)) === JSON.stringify(facts(right));
}
function engineeringWaitProof(request, step) {
  const operation = latestEngineeringWaitOperation(request, step);
  if (operation?.status !== "SUCCEEDED" || operation.result?.checkpoint_sha256 !== request.checkpoint_sha256) return null;
  return operation.intent.action === "HANDLE_DELIVERY_WAIT" ? engineeringWaitHandlingFromOperation(operation, request, step)?.investigation || null
    : matchingEngineeringWaitProof(operation.result?.engineering_wait_investigation, request, step);
}
function engineeringWaitDecision(request, step, proof) {
  if (!proof) return null;
  const bound = engineeringWaitIntent(request, step);
  const handling = engineeringWaitHandling(request, step);
  if (handling?.status === "RESOLVED" && handling.resolution?.proof_sha256 === handling.investigation.proof_sha256 &&
      engineeringResolutionLabels[handling.resolution.resolution_kind]) return handling.resolution;
  return operations.find(item => item.status === "SUCCEEDED" &&
    item.intent.action === "RESOLVE_DELIVERY_WAIT" && sameEngineeringWaitIntent(item.intent, bound) &&
    item.result?.engineering_wait_resolution?.proof_sha256 === proof.proof_sha256)?.result.engineering_wait_resolution || null;
}
function engineeringWaitCanResolve(request, step, proof) {
  const handling = engineeringWaitHandling(request, step);
  const bound = engineeringWaitIntent(request, step);
  const lastHandling = [...operations].sort((a, b) => b.updated_at.localeCompare(a.updated_at))
    .find(item => item.intent.action === "HANDLE_DELIVERY_WAIT" && sameEngineeringWaitIntent(item.intent, bound));
  const permission = !lastHandling || engineeringWaitHandlingFromOperation(lastHandling, request, step)?.manual_resolution_allowed === true;
  return proof && !proof.missing?.length && !engineeringWaitDecision(request, step, proof) &&
    permission &&
    (!handling || handling.status === "NEEDS_AUTHORIZATION" && handling.manual_resolution_allowed === true) &&
    (proof.permitted_resolutions || []).length > 0 &&
    proof.permitted_resolutions.every(kind => Boolean(engineeringResolutionLabels[kind]));
}
async function submitEngineeringWaitOperation(intent) {
  const request = requestById(intent.delivery_id);
  const current = request && engineeringWaitSteps(request).find(({step}) =>
    sameEngineeringWaitIntent(intent, engineeringWaitIntent(request, step)));
  const proof = current && engineeringWaitProof(request, current.step);
  if (!current || !["INSPECT_DELIVERY_WAIT", "HANDLE_DELIVERY_WAIT", "RESOLVE_DELIVERY_WAIT"].includes(intent.action) ||
      (intent.action === "RESOLVE_DELIVERY_WAIT" &&
      (!proof || proof.proof_sha256 !== intent.proof_sha256 ||
       !(proof.permitted_resolutions || []).includes(intent.resolution_kind) ||
       !engineeringWaitCanResolve(request, current.step, proof)))) {
    operationNotice = {kind: "error", title: "工程等待事实已变化",
      message: "请刷新当前需求并重新调查，旧调查不能用于处理新的执行现场。"};
    renderDetail();
    renderNotification();
    return null;
  }
  return submitOperation(intent);
}
function engineeringGuidanceList(...descriptions) {
  const list = el("ol", undefined, "engineering-guidance-list");
  for (const description of descriptions) {
    for (const point of description.split(/(?<=[。；])\s*|\n+/u)) {
      if (point.trim()) list.append(el("li", point.trim()));
    }
  }
  return list;
}
function appendEngineeringInvestigation(target, proof, {historical = false, collectionFailed = false, legacyRescue = false, rescueFailure = null, controlUnavailable = null} = {}) {
  if (historical) {
    target.append(el("p", "当次调查 · " + humanizeBlockingText(proof.next_action || "调查结果未提供处理建议。")),
      el("p", "这是该次调查保存的结果；当前原因与操作以页面上方为准。", "muted"));
    if (proof.missing?.length) target.append(el("p", "当次未完成项 · " + proof.missing.map(item =>
      engineeringProofMissingGuidance[item]?.[0] || "平台返回了未识别的检查项，不能据此继续").join("；")));
    return;
  }
  const missing = proof.missing || [];
  if (collectionFailed) target.append(el("p", engineeringCollectionFailureNotice, "error"));
  if (legacyRescue) {
    target.append(engineeringGuidanceList("旧执行没有留下完整结果、结束和现场记录，不能把它当作已完成，也不能靠重复调查补齐。",
      controlUnavailable ? "当前恢复操作不可用，具体原因和下一步见下方；操作恢复后须重新读取并核对方案，不能使用旧页面的审批。"
        : rescueFailure ? "本次恢复方案准备尚未完成，具体失败和平台处理下一步见下方；当前没有可批准的恢复方案。"
        : "可使用下方“保留进度的恢复方案”：平台检查当前本机执行并封存完整合法草稿，展示所需工程确认；授权后才可继续同一需求。"));
    return;
  }
  if (missing.length) {
    target.append(el("strong", "当前尚未解决的事项"));
    const list = el("ul", undefined, "engineering-wait-issues");
    for (const item of missing) {
      const [title, owner, action, recheck] = engineeringProofMissingGuidance[item] || [
        "平台返回了未识别的检查项", "平台维护者", "平台需要修复这项检查结果；当前不能安全继续。",
        "平台修复检查结果后再检查。",
      ];
      const entry = el("li", undefined, "engineering-wait-issue");
      entry.append(el("strong", title), el("p", "处理方 · " + owner, "muted"), el("p", action),
        el("p", "何时复查 · " + recheck, "muted"));
      list.append(entry);
    }
    target.append(list);
  } else if (!collectionFailed) {
    const permitted = (proof.permitted_resolutions || []).map(item => engineeringResolutionLabels[item]).filter(Boolean);
    const known = permitted.length === proof.permitted_resolutions?.length;
    target.append(el("p", permitted.length && known ? "检查已通过，可按以下方案继续 · " + permitted.join("、")
      : "当前没有可安全执行的继续方案，需平台维护者处理。"));
  }
}
function engineeringWaitCurrentFacts(request, step, proof, handling, decision, active) {
  const bound = engineeringWaitIntent(request, step);
  const activeHandling = active?.intent.action === "HANDLE_DELIVERY_WAIT" && sameEngineeringWaitIntent(active.intent, bound);
  const missing = proof?.missing || [];
  const unavailable = missing.some(item => ["CHECKPOINT_UNAVAILABLE", "CHECKPOINT_DRIFT"].includes(item));
  const saved = proof && [proof.interruption_receipt_sha256, proof.process_stop_sha256, proof.workspace_inventory_sha256]
    .every(value => /^[a-f0-9]{64}$/.test(value || "")) && !missing.includes("PROCESS_LIVE_OR_UNKNOWN");
  const facts = {
    happened: humanizeBlockingText(step.wait_disposition.reason || request.execution?.reason || "当前工作已暂停，平台需先确认原执行情况。"),
    preservation: unavailable ? "原文件仍需核对，当前没有可安全复用的完整进度结论。平台不会自动清空旧工作区。"
      : saved ? "已记录可核验的开发进度，处理会保留原工作区和历史记录。"
      : "平台不会因本次处理自动清空原工作区；可复用进度仍需由检查结果确认。",
    platform: "可以检查原执行，并在现有授权允许时处理和继续。不会改变需求范围，也不会替代测试与评审。",
    user: "你可以点击“让平台处理中断”。如果需要额外授权，页面会明确列出待决定的方案。",
  };
  if (activeHandling) {
    facts.platform = active.status === "QUEUED" ? "处理中断的操作已接收，等待平台执行。" : "平台正在处理中断，原等待状态会保留到新的执行事实成立。";
    facts.user = "当前不需要决定，请等待这次处理返回结果。";
  } else if (active) {
    facts.platform = "当前另有操作尚未结束，需要先等待该操作返回结果。";
    facts.user = "请等待当前操作结束，再处理这项等待。";
  } else if (decision) {
    facts.platform = "继续决定已保存。当前页面仍显示等待，是否恢复以接下来的实际执行记录为准。";
    facts.user = "当前不需要重复决定，请查看新的执行进展。";
  } else if (handling) {
    facts.platform = humanizeBlockingText(handling.summary || "本次平台处理已完成，仍需根据检查结果继续。");
    facts.user = humanizeBlockingText(handling.user_action || "当前没有可执行的用户决定，请按页面所列处理方完成前提。");
  } else if (proof?.missing?.length) {
    facts.user = "你无需判断内部执行记录。可以让平台尝试处理；若平台仍无法继续，会说明处理方和具体事项。";
  } else if (engineeringWaitCanResolve(request, step, proof)) {
    facts.platform = "已检查原执行和保留进度，现有规则要求工程授权者确认所列方案后继续。";
    facts.user = "需要工程授权者确认按页面所列方案继续；不需要手工核验内部记录。";
  }
  const task = engineeringWaitSteps(request).find(item => item.step.work_item_id === step.work_item_id)?.task;
  if (!active && !decision && task && engineeringLegacyRescueFacts(request, task, step, proof, handling)) {
    const rescue = engineeringLegacyRescueFacts(request, task, step, proof, handling);
    const failure = engineeringLegacyRescueFailure(request, task, step, rescue);
    const preparation = engineeringLegacyRescuePreparation(request, task, step, rescue);
    facts.platform = failure
      ? `恢复方案准备${failure.status === "INTERRUPTED" ? "被中断" : "失败"}：${failure.summary}`
      : preparation?.summary || "可准备保留进度的恢复方案，检查当前本机执行并封存完整合法草稿；旧执行结果仍保持未知。";
    facts.user = failure
      ? failure.next_action
      : consoleSupportsLegacyRescue()
        ? preparation?.next_action || "点击“准备保留进度的恢复方案”。先查看平台检查结果和精确方案，再由工程授权者确认实际执行已结束；不要凭服务重启推断旧执行停止。"
        : "当前服务尚不支持保留进度的恢复方案。请在服务空闲时更新并重启 Web Console，再刷新页面；原需求和草稿保留。";
  }
  if (consoleAvailable === true && !consoleSupportsOperation("HANDLE_DELIVERY_WAIT")) {
    if (!active && !decision && !handling) {
      facts.platform = "当前页面的处理操作未获当前服务支持，请先更新运行中的服务。";
      facts.user = consoleOperationVersionMismatchMessage;
    } else facts.user += " " + consoleOperationVersionMismatchMessage;
  }
  const controlUnavailable = deliveryControlUnavailableReason();
  if (controlUnavailable) {
    facts.platform = active || decision ? facts.platform + " " + controlUnavailable.reason : controlUnavailable.reason;
    facts.user = controlUnavailable.next_action;
  }
  return facts;
}
async function copyEngineeringWaitReport(request, handling) {
  const proof = handling.investigation;
  const controlUnavailable = deliveryControlUnavailableReason();
  const current = engineeringWaitSteps(request).find(({task, step}) =>
    engineeringWaitHandling(request, step)?.handling_sha256 === handling.handling_sha256 &&
    matchingEngineeringWaitProof(proof, request, step) && engineeringLegacyRescueFacts(request, task, step, proof, handling));
  const rescue = Boolean(current);
  const preparation = current && engineeringLegacyRescuePreparation(request, current.task, current.step,
    engineeringLegacyRescueFacts(request, current.task, current.step, proof, handling));
  const failure = current && engineeringLegacyRescueFailure(request, current.task, current.step,
    engineeringLegacyRescueFacts(request, current.task, current.step, proof, handling));
  const missing = (proof?.missing || []).map(item => {
    const [title, owner, action, recheck] = engineeringProofMissingGuidance[item] || [
      "平台返回了未识别的检查项", "平台维护者", "平台需要修复这项检查结果；当前不能安全继续。",
      "平台修复检查结果后再检查。",
    ];
    return ["待处理事项 · " + title, "处理方 · " + (failure ? "ASE 平台维护者" : rescue ? "ASE 平台与工程授权者" : owner),
      "具体处理 · " + (controlUnavailable ? controlUnavailable.next_action
        : failure ? "先处理本次恢复方案准备失败；旧执行的缺失事实仍保留，不能通过重复调查补造。"
        : rescue ? "使用需求详情中的“准备保留进度的恢复方案”，由平台检查当前本机执行并封存合法草稿；查看检查结果后再决定，不补造原执行记录。" : action),
      "何时复查 · " + (failure ? "平台修复本次失败后，再重新检查恢复前提。"
        : rescue ? "按恢复前提检查所列下一步处理后再检查；重复检查不会补出旧执行结果。" : recheck)].join("\n");
  });
  const report = ["ASE 交付处理报告", "需求 · " + request.title,
    ...(controlUnavailable ? ["操作可用性 · " + controlUnavailable.title + "；" + controlUnavailable.reason] : []),
    ...(handling.collection_failed === true ? ["当前结果 · " + engineeringCollectionFailureNotice] : []),
    "本次处理 · " + (failure ? `恢复方案准备${failure.status === "INTERRUPTED" ? "被中断" : "失败"}：${failure.summary}`
      : preparation?.summary || humanizeBlockingText(handling.summary || "未提供处理说明")),
    "用户操作 · " + (controlUnavailable ? controlUnavailable.next_action : failure ? failure.next_action
      : preparation?.next_action || (rescue ? "在当前需求详情点击“准备保留进度的恢复方案”；先看平台检查结果，方案准备完成后由工程授权者明确确认所列实际停止前提，再批准继续原需求。" : humanizeBlockingText(handling.user_action || "无"))),
    "复查时机 · " + (failure ? "平台修复本次失败后，再重新检查恢复前提；重复调查不能修复内部异常。"
      : rescue ? "按恢复前提检查所列下一步处理后重新检查；旧执行结果仍保持未知。" : humanizeBlockingText(handling.recheck_when || "处理记录或执行前提更新后")),
    ...(failure ? ["恢复准备操作 · " + failure.operation_id, "准备操作状态 · " + failure.status,
      "错误编号 · " + failure.error_code, "安全排障说明 · " + failure.detail,
      "原调查说明 · " + humanizeBlockingText(handling.summary || "未提供处理说明")] : []),
    ...(preparation ? ["当前恢复检查 · " + preparation.summary, "检查处理方 · " + preparation.responsible_party,
      "检查下一步 · " + preparation.next_action] : []),
    ...missing,
    "任务 · " + handling.task_id,
    "工作项 · " + handling.work_item_id,
    "原执行 · " + (proof?.original_run_id || "未记录"),
    "处理报告摘要 · " + handling.handling_sha256].join("\n");
  try {
    await navigator.clipboard.writeText(report);
    operationNotice = {kind: "info", title: "处理报告已复制", message: "可将报告交给平台维护者定位问题。"};
  } catch {
    operationNotice = {kind: "error", title: "无法复制处理报告", message: "浏览器未允许复制。请展开排障信息，选择处理说明和报告摘要复制。"};
  }
  renderNotification();
}
function engineeringWaitBox(request, task, step) {
  const management = viewGroup(el("section", undefined, "engineering-wait-panel"),
    "engineering-wait:" + step.work_item_id);
  management.setAttribute("data-key", "engineering:" + step.work_item_id);
  const heading = viewBlock(el("div", undefined, "engineering-wait-heading"), "engineering-wait-heading", step.role);
  heading.append(el("h3", label(step.role) + "阶段等待处理"),
    el("span", "ASE 平台处理", "engineering-action-owner"));
  management.append(heading, viewBlock(el("p",
    "平台负责核对执行与保留进度。这里只需要决定明确列出的授权事项，无需理解内部恢复方式。",
    "muted engineering-wait-description"), "engineering-wait-description", step.role));
  const bound = engineeringWaitIntent(request, step);
  if (!/^[a-f0-9]{64}$/.test(bound.expected_disposition_sha256 || "")) {
    management.append(el("p", "当前等待缺少精确处置身份。请刷新页面；仍缺失时由工程团队检查服务版本与记录。", "error"));
    return management;
  }
  const proof = engineeringWaitProof(request, step);
  const proofSha256 = proof?.proof_sha256;
  const decision = engineeringWaitDecision(request, step, proof);
  const handling = engineeringWaitHandling(request, step);
  const running = activeOperation(request.id, request.project_id);
  const controlUnavailable = deliveryControlUnavailableReason();
  const facts = engineeringWaitCurrentFacts(request, step, proof, handling, decision, running);
  const rescue = engineeringLegacyRescueFacts(request, task, step, proof, handling);
  const rescueFailure = engineeringLegacyRescueFailure(request, task, step, rescue);
  const overview = viewBlock(el("dl", undefined, "engineering-wait-facts"), "engineering-wait-facts", facts);
  for (const [key, title] of [["happened", "发生了什么"], ["preservation", "开发进度"], ["platform", "平台可以做什么"], ["user", "你需要做什么"]]) {
    const row = el("div");
    const description = el("dd");
    description.append(engineeringGuidanceList(facts[key]));
    row.append(el("dt", title), description);
    overview.append(row);
  }
  management.append(overview);
  if (proof) {
    const collectionFailed = handling?.collection_failed === true;
    const result = viewBlock(el("div", undefined, "engineering-investigation-result"), "engineering-wait-proof", [proof, collectionFailed, Boolean(rescue), rescueFailure, controlUnavailable]);
    appendEngineeringInvestigation(result, proof, {collectionFailed, legacyRescue: Boolean(rescue), rescueFailure, controlUnavailable});
    management.append(result);
  }
  if (controlUnavailable) management.append(deliveryControlUnavailableNotice(controlUnavailable));
  if (decision) {
    management.append(el("p", "继续决定已记录；实际进度与验收以新的执行记录为准。", "muted"));
  } else if (canControlCurrentTeam() && !running) {
    const canResolve = engineeringWaitCanResolve(request, step, proof);
    const actions = viewBlock(el("div", undefined, "engineering-wait-actions"), "engineering-wait-actions",
      [bound, proof, handling, Boolean(rescue), canResolve, canControlCurrentTeam(), consoleOperationContractVersion, consoleSupportedActions]);
    if (consoleSupportsOperation("HANDLE_DELIVERY_WAIT") && !canResolve &&
      !["NEEDS_AUTHORIZATION", "PLATFORM_ATTENTION", "BUDGET_EXHAUSTED", "WAITING_PREREQUISITES"].includes(handling?.status))
      actions.append(deliveryButton("让平台处理中断", () => submitEngineeringWaitOperation({
        ...bound, action: "HANDLE_DELIVERY_WAIT",
      }), "primary"));
    if (consoleSupportsOperation("INSPECT_DELIVERY_WAIT")) {
      const inspect = deliveryButton(proof || handling ? "重新检查状态" : "调查工程等待", () =>
        submitEngineeringWaitOperation({...bound, action: "INSPECT_DELIVERY_WAIT"}), "secondary");
      if (proof || handling) {
        const recheck = el("span", undefined, "engineering-wait-recheck-action");
        const condition = rescue ? "先按“恢复前提检查”列出的下一步完成处理。"
          : handling?.recheck_when ? humanizeBlockingText(handling.recheck_when)
          : "原执行结束、平台记录修复或执行前提发生变化后，再进行检查。";
        const help = settingsHelp("重新检查状态", [
          "1. " + condition,
          "2. 完成上述处理后，点击“重新检查状态”，重新核对已有记录和恢复前提。",
          "3. 此操作只检查状态。服务重启或重复调查不会补齐旧执行记录，也不会自动恢复交付。",
        ].join("\n\n"));
        help.classList.add("engineering-wait-recheck-help");
        recheck.append(inspect, help);
        actions.append(recheck);
      } else actions.append(inspect);
    }
    if (canResolve && consoleSupportsOperation("RESOLVE_DELIVERY_WAIT"))
      for (const kind of proof.permitted_resolutions || []) {
        const title = engineeringResolutionLabels[kind];
        if (title) actions.append(deliveryButton(title, () => submitEngineeringWaitOperation({
          ...bound, action: "RESOLVE_DELIVERY_WAIT", resolution_kind: kind, proof_sha256: proofSha256,
        }), "primary"));
      }
    management.append(actions);
  } else if (running) {
    management.append(el("p", "操作尚未结束；原等待只有在新的执行事实成立后才解除。", "muted"));
  }
  if (handling?.status === "PLATFORM_ATTENTION") management.append(viewBlock(button("复制处理报告", () =>
    copyEngineeringWaitReport(request, handling), "secondary engineering-wait-report"), "engineering-wait-report", [request.title, handling]));
  const technical = viewGroup(engineeringDetails("调查绑定详情", step.work_item_id + ":binding"),
    "engineering-wait-binding:" + step.work_item_id);
  technical.classList.add("engineering-wait-binding");
  technical.append(el("p", "任务 · " + (task.task_id || task.id), "paths"),
    el("p", "工作项 · " + bound.work_item_id, "paths"),
    el("p", "执行基线 · " + bound.expected_source_revision, "paths"),
    el("p", "处置摘要 · " + bound.expected_disposition_sha256, "paths"));
  if (proof) technical.append(el("p", "调查摘要 · " + proof.proof_sha256, "paths"),
    el("p", "调查时间 · " + time(proof.inspected_at), "muted"),
    el("p", "调查原始说明 · " + humanizeBlockingText(proof.next_action || "未提供"), "muted"));
  if (handling) technical.append(el("p", "平台处理时间 · " + time(handling.handled_at), "muted"),
    el("p", "处理报告摘要 · " + handling.handling_sha256, "paths"),
    el("p", "处理说明 · " + humanizeBlockingText(handling.summary || "未提供"), "muted"));
  appendEngineeringBaseline(management, request, task, step);
  appendEngineeringLegacyRescue(management, request, task, step, proof, handling);
  management.append(technical);
  return management;
}
function engineeringBaselineFacts(request, task, step) {
  const facts = step.wait_disposition?.facts;
  if (task.terminal || task.status !== "IMPLEMENTING" || step.role !== "coder" ||
      !["READY", "RETRY_SCHEDULED", "WAITING_HUMAN", "WAITING_DEPENDENCY"].includes(step.status) ||
      step.lease_liveness === "LEASE_VALID" || !facts || facts.task_id !== task.task_id ||
      facts.work_item_id !== step.work_item_id ||
      !Number.isInteger(task.task_revision) || task.task_revision < 1 ||
      task.task_revision !== facts.checkpoint_sequence ||
      task.task_intent_sha256 !== facts.task_intent_sha256 ||
      !/^[a-f0-9]{64}$/.test(task.task_intent_sha256 || "") ||
      !/^[a-f0-9]{40}$/.test(facts.source_revision || "")) return null;
  return {project_id: request.project_id, delivery_id: request.id,
    expected_checkpoint_sha256: request.checkpoint_sha256, task_id: task.task_id,
    expected_task_intent_sha256: task.task_intent_sha256, expected_task_revision: task.task_revision,
    expected_work_item_id: step.work_item_id, expected_source_revision: facts.source_revision};
}
function engineeringBaselinePlan(request, task, step, purpose = "source_rebind") {
  const bound = engineeringBaselineFacts(request, task, step);
  if (!bound) return null;
  const operation = engineeringBaselineProposalOperation(bound, purpose);
  const plan = operation?.status === "SUCCEEDED" ? operation.result?.execution_baseline_plan : null;
  if (!plan || operation.result.checkpoint_sha256 !== request.checkpoint_sha256 ||
      (plan.purpose || "source_rebind") !== purpose ||
      !/^[a-f0-9]{64}$/.test(plan.plan_sha256 || "") ||
      plan.facts?.task?.id !== bound.task_id || plan.facts.task_revision !== bound.expected_task_revision ||
      plan.facts.work_item_id !== bound.expected_work_item_id ||
      plan.dirty_capture?.source_revision !== bound.expected_source_revision ||
      plan.target_base_ref !== operation.intent.target_base_ref || plan.input_mode !== operation.intent.input_mode ||
      !["preserve_draft", "coder_reapply"].includes(plan.input_mode)) return null;
  return plan;
}
function engineeringLegacyRescueFacts(request, task, step, proof = engineeringWaitProof(request, step),
    handling = engineeringWaitHandling(request, step)) {
  const baseline = engineeringBaselineFacts(request, task, step);
  const required = ["OUTCOME_UNKNOWN", "STOP_UNRECORDED", "CHECKPOINT_UNAVAILABLE"];
  if (!baseline || !proof || handling?.collection_failed === true ||
      typeof proof.original_run_id !== "string" || !/^run_[a-z0-9_]+$/.test(proof.original_run_id) ||
      proof.missing.length !== required.length || new Set(proof.missing).size !== required.length ||
      !required.every(item => proof.missing.includes(item)) || proof.permitted_resolutions.length ||
      engineeringWaitDecision(request, step, proof)) return null;
  return {baseline, wait: engineeringWaitIntent(request, step), proof_sha256: proof.proof_sha256,
    original_run_id: proof.original_run_id};
}
function engineeringLegacyRescuePlan(request, task, step, rescue) {
  const plan = engineeringBaselinePlan(request, task, step, "legacy_workspace_rescue");
  const containment = plan?.facts.legacy_containment;
  const startedAt = containment?.original_start?.started_at;
  const bootedAt = containment?.boot?.booted_at;
  const method = containment?.method || "os_reboot";
  if (!plan || !rescue || plan.input_mode !== "preserve_draft" || plan.conflicted ||
      plan.target_base_ref !== rescue.baseline.expected_source_revision ||
      containment?.original_start?.request?.run_id !== rescue.original_run_id ||
      containment?.original_start?.work_item_id !== rescue.baseline.expected_work_item_id ||
      !Number.isFinite(Date.parse(startedAt)) || !Number.isFinite(Date.parse(bootedAt)) ||
      ![containment?.containment_sha256, containment?.original_start?.start_sha256,
        containment?.boot?.machine_sha256, containment?.boot?.boot_session_sha256]
        .every(value => /^[a-f0-9]{64}$/.test(value || ""))) return null;
  if (method === "os_reboot") {
    if (Date.parse(bootedAt) <= Date.parse(startedAt) || containment.local_execution_survey) return null;
  } else if (method === "operator_confirmed_local_stop") {
    const survey = containment.local_execution_survey;
    if (!survey || !Array.isArray(survey.blockers) || survey.blockers.length ||
        survey.worktree_path !== plan.dirty_capture.worktree_path ||
        survey.machine_sha256 !== containment.boot.machine_sha256 ||
        survey.boot_session_sha256 !== containment.boot.boot_session_sha256 ||
        ![survey.account_sha256, survey.survey_sha256].every(value => /^[a-f0-9]{64}$/.test(value || "")) ||
        typeof survey.scanner_version !== "string" || !survey.scanner_version ||
        !Number.isFinite(Date.parse(survey.observed_at)) || Date.parse(survey.observed_at) < Date.parse(startedAt)) return null;
  } else return null;
  return plan;
}
function engineeringLegacyRescuePreparation(request, task, step, rescue) {
  if (!rescue) return null;
  const operation = engineeringBaselineProposalOperation(rescue.baseline, "legacy_workspace_rescue");
  const preparation = operation?.status === "SUCCEEDED" ? operation.result?.legacy_rescue_preparation : null;
  if (!preparation || operation.result.checkpoint_sha256 !== request.checkpoint_sha256 ||
      preparation.task_id !== task.task_id || preparation.work_item_id !== step.work_item_id ||
      preparation.source_revision !== rescue.baseline.expected_source_revision ||
      !["READY", "WAITING"].includes(preparation.status) || typeof preparation.summary !== "string" ||
      !preparation.summary || typeof preparation.next_action !== "string" || !preparation.next_action ||
      !["平台执行服务", "工程授权者"].includes(preparation.responsible_party)) return null;
  return preparation;
}
function engineeringBaselineProposalOperation(bound, purpose = "source_rebind") {
  if (!bound) return null;
  return [...operations].sort((a, b) => b.updated_at.localeCompare(a.updated_at))
    .find(item => item.intent?.action === "PROPOSE_EXECUTION_BASELINE" &&
      (item.intent.purpose || "source_rebind") === purpose && sameEngineeringWaitIntent(item.intent, bound) &&
      (purpose !== "legacy_workspace_rescue" || item.intent.target_base_ref === bound.expected_source_revision &&
        item.intent.input_mode === "preserve_draft"));
}
function legacyRescueFailureNotice(operation) {
  if (!operation || !["FAILED", "INTERRUPTED"].includes(operation.status)) return null;
  const code = operation.error_code || "UNKNOWN_FAILURE";
  const typedCapture = code === "LEGACY_WORKSPACE_CAPTURE_REJECTED";
  const internal = code === "MANAGER_FAILURE" || code === "UNKNOWN_FAILURE";
  const detail = operation.error_summary || "本次操作没有保存安全错误说明。";
  const summary = internal ? "平台在准备恢复方案时发生内部异常，尚未封存完整可核验的保留进度。"
    : typedCapture && operation.error_summary ? humanizeBlockingText(operation.error_summary)
      : operation.status === "INTERRUPTED" ? "平台服务在恢复方案准备完成前停止，本次准备已中断。"
        : "平台未能完成恢复方案准备，需核对本次失败记录。";
  return {
    operation_id: operation.operation_id,
    status: operation.status,
    error_code: code,
    summary,
    detail,
    next_action: internal
      ? "请将操作编号、错误编号和排障说明交给 ASE 平台维护者；修复平台后再重新检查。当前没有恢复方案，也没有保存审批。"
      : typedCapture
        ? "请按失败说明处理保留工作区或让平台维护者核对现场；确认平台修复后再重新检查。当前没有恢复方案，也没有保存审批。"
        : "请将本次失败交给 ASE 平台维护者核对；修复或确认前提后再重新检查。当前没有恢复方案，也没有保存审批。",
  };
}
function engineeringLegacyRescueFailure(request, task, step, rescue) {
  const bound = engineeringBaselineFacts(request, task, step);
  if (!rescue || !bound || !sameEngineeringWaitIntent(rescue.baseline, bound)) return null;
  const operation = engineeringBaselineProposalOperation(bound, "legacy_workspace_rescue");
  return operation && legacyRescueFailureNotice(operation);
}
function engineeringLegacyRescueExecuted(request, task, plan) {
  return plan && operations.some(item => item.status === "SUCCEEDED" &&
    item.intent.action === "EXECUTE_EXECUTION_BASELINE" && item.intent.project_id === request.project_id &&
    item.intent.delivery_id === request.id && item.intent.task_id === task.task_id &&
    item.intent.expected_plan_sha256 === plan.plan_sha256);
}
async function submitEngineeringLegacyRescueOperation(intent, originalRescue) {
  const request = requestById(intent.delivery_id);
  const current = request && engineeringWaitSteps(request).find(({task, step}) => {
    const rescue = engineeringLegacyRescueFacts(request, task, step);
    return rescue && sameEngineeringWaitIntent(rescue.baseline, originalRescue.baseline) &&
      sameEngineeringWaitIntent(rescue.wait, originalRescue.wait) &&
      rescue.proof_sha256 === originalRescue.proof_sha256 && rescue.original_run_id === originalRescue.original_run_id;
  });
  const rescue = current && engineeringLegacyRescueFacts(request, current.task, current.step);
  const plan = current && engineeringLegacyRescuePlan(request, current.task, current.step, rescue);
  const propose = intent.action === "PROPOSE_EXECUTION_BASELINE";
  const execute = intent.action === "EXECUTE_EXECUTION_BASELINE";
  if (!canControlCurrentTeam() || !consoleSupportsLegacyRescue()) {
    const unavailable = deliveryControlUnavailableReason();
    operationNotice = {kind: "error", title: "恢复操作未被受理", message: unavailable
      ? unavailable.reason + " " + unavailable.next_action : consoleOperationVersionMismatchMessage};
    renderNotification();
    return null;
  }
  if (!current || activeOperation(request.id, request.project_id) ||
      (!propose && !execute) || propose && (intent.purpose !== "legacy_workspace_rescue" ||
        intent.target_base_ref !== rescue.baseline.expected_source_revision || intent.input_mode !== "preserve_draft") ||
      execute && (!plan || plan.plan_sha256 !== intent.expected_plan_sha256 ||
        (plan.facts.legacy_containment.method === "operator_confirmed_local_stop"
          ? !consoleSupportsLocalRescue() || intent.confirm_local_execution_stopped !== true || intent.confirm_legacy_containment != null
          : intent.confirm_legacy_containment !== true || intent.confirm_local_execution_stopped != null) ||
        engineeringLegacyRescueExecuted(request, current.task, plan))) {
    operationNotice = {kind: "error", title: "保留进度的恢复事实已变化",
      message: "请查看当前需求并重新准备方案；旧方案或未确认的前提不能启动下一轮。"};
    renderDetail();
    renderNotification();
    return null;
  }
  return submitOperation(intent);
}
function appendEngineeringLegacyRescue(target, request, task, step, proof, handling) {
  const rescue = engineeringLegacyRescueFacts(request, task, step, proof, handling);
  if (!rescue) return;
  const plan = engineeringLegacyRescuePlan(request, task, step, rescue);
  const preparation = engineeringLegacyRescuePreparation(request, task, step, rescue);
  const failure = engineeringLegacyRescueFailure(request, task, step, rescue);
  const local = plan?.facts.legacy_containment.method === "operator_confirmed_local_stop";
  const planSha256 = plan?.plan_sha256;
  const active = activeOperation(request.id, request.project_id);
  const supported = consoleSupportsLegacyRescue();
  const executed = engineeringLegacyRescueExecuted(request, task, plan);
  const controlUnavailable = deliveryControlUnavailableReason();
  const panel = viewGroup(el("section", undefined, "engineering-baseline-panel engineering-baseline-pending engineering-rescue-panel"),
    "engineering-rescue:" + step.work_item_id);
  panel.dataset.key = "engineering:" + step.work_item_id + ":rescue";
  panel.append(viewBlock(el("h4", "保留进度的恢复方案", "engineering-baseline-title"), "rescue-title", true),
    viewBlock(engineeringGuidanceList("这是同一需求的工程恢复，不会新建需求或丢弃原分支的合法草稿。旧执行结果仍未知；下一轮使用剩余工作额度，完成后继续独立 QA 和 Review。"),
      "rescue-description", true));
  if (plan) {
    const containment = plan.facts.legacy_containment;
    const summary = viewBlock(el("div"), "rescue-summary", plan);
    summary.append(el("p", local
      ? "平台已完整保存合法草稿，本机检查未发现会占用现场的执行。该检查不能证明旧调用已经停止，仍需工程授权者确认原调用及全部派生工具已结束。批准前不会启动下一轮。"
      : "平台已封存当前完整合法草稿并检查电脑启动记录。批准前仍不会启动下一轮，也不代表需求已完成。"),
      el("p", "原执行开始 · " + time(containment.original_start.started_at)),
      el("p", local ? "本机检查时间 · " + time(containment.local_execution_survey.observed_at)
        : "方案核验的整机启动 · " + time(containment.boot.booted_at)));
    const technical = engineeringDetails("恢复方案的工程绑定", step.work_item_id + ":rescue-plan");
    technical.append(el("p", "计划摘要 · " + plan.plan_sha256, "paths"),
      el("p", "原执行 · " + containment.original_start.request.run_id, "paths"),
      el("p", "隔离观察摘要 · " + containment.containment_sha256, "paths"),
      el("p", "原分支 · " + (plan.facts.task.branch_name || "未提供"), "paths"),
      el("p", "保留代码基线 · " + plan.target_base_ref, "paths"));
    summary.append(technical);
    panel.append(summary);
  } else if (preparation?.status === "WAITING") {
    const summary = viewBlock(el("div", undefined, "engineering-rescue-check"), "rescue-check", preparation);
    summary.append(el("strong", "恢复前提尚未满足"), el("p", preparation.summary),
      el("p", "处理方 · " + preparation.responsible_party, "muted"), el("p", "下一步 · " + preparation.next_action),
      el("p", "本次检查没有生成恢复方案、保存审批或启动 Coder；原需求和草稿保留。", "muted"));
    panel.append(summary);
  }
  if (controlUnavailable) panel.append(deliveryControlUnavailableNotice(controlUnavailable));
  if (executed) {
    panel.append(viewBlock(el("p", "恢复工程决定已保存。旧执行历史仍保留，是否继续与最终验收以新的执行记录为准。", "muted"), "rescue-executed", plan.plan_sha256));
  } else if (active) {
    panel.append(viewBlock(el("p", active.intent.purpose === "legacy_workspace_rescue"
      ? "平台正在检查恢复前提并封存当前草稿，请等待本次处理结果。"
      : "当前操作尚未结束，恢复方案不会同时启动另一次执行。", "muted"), "rescue-active", active));
  } else if (failure) {
    const summary = viewBlock(el("div", undefined, "engineering-rescue-failure"), "rescue-failure",
      [failure, rescue, canControlCurrentTeam(), consoleOperationContractVersion, consoleSupportedActions]);
    summary.append(el("strong", `恢复方案准备${failure.status === "INTERRUPTED" ? "被中断" : "失败"}`),
      el("p", failure.summary, "error"),
      el("p", "平台错误编号 · " + failure.error_code, "paths"),
      el("p", "平台安全排障说明 · " + failure.detail, "muted"),
      el("p", failure.next_action, "muted"),
      el("p", "本次失败没有生成恢复方案、保存审批或启动 Coder；原需求、旧执行历史和保留草稿均保持不变。", "muted"));
    if (supported && canControlCurrentTeam()) summary.append(deliveryButton("修复后重新检查恢复前提", () =>
      submitEngineeringLegacyRescueOperation({
        ...rescue.baseline, action: "PROPOSE_EXECUTION_BASELINE", purpose: "legacy_workspace_rescue",
        target_base_ref: rescue.baseline.expected_source_revision, input_mode: "preserve_draft",
      }, rescue), "secondary"));
    panel.append(summary);
  } else if (!controlUnavailable && (!supported || local && !consoleSupportsLocalRescue())) {
    panel.append(viewBlock(el("p", "当前服务尚不支持此恢复路径。请在服务空闲时更新并重启 Web Console，再刷新页面；原需求和草稿保留。", "muted"),
      "rescue-unavailable", [consoleOperationContractVersion, consoleSupportedActions]));
  } else if (canControlCurrentTeam()) {
    const controls = viewBlock(el("div", undefined, "engineering-baseline-form"), "rescue-controls",
      [rescue, plan, preparation, canControlCurrentTeam(), consoleOperationContractVersion, consoleSupportedActions]);
    if (plan) {
      const field = el("label", undefined, "settings-checkbox-control");
      const confirmation = el("input");
      confirmation.type = "checkbox";
      confirmation.checked = false;
      confirmation.setAttribute("aria-label", local ? "确认原调用及全部派生工具已结束" : "确认原执行在同一电脑且已整机重启");
      field.append(confirmation, el("span", local
        ? "我以工程授权者身份确认：原调用一直在当前同一电脑、同一账户本地执行，未迁移或远程执行；原调用及全部派生工具已结束，不会再修改保留的现场。我接受旧结果仍为未知，并批准使用剩余工作额度再次执行。此确认是独立人工工程授权，不是平台补出的旧停止记录。"
        : "我以工程授权者身份确认：原执行一直在当前同一电脑本地运行，未迁移或远程执行；原执行之后已重启整台电脑，并认可平台显示的时间依据。"));
      const approve = deliveryButton("批准保留进度并继续原需求", () => submitEngineeringLegacyRescueOperation({
        action: "EXECUTE_EXECUTION_BASELINE", project_id: request.project_id, delivery_id: request.id,
        expected_checkpoint_sha256: request.checkpoint_sha256, task_id: task.task_id,
        expected_plan_sha256: planSha256,
        ...(local ? {confirm_local_execution_stopped: confirmation.checked === true}
          : {confirm_legacy_containment: confirmation.checked === true}),
        reference: local
          ? "工程授权者确认原调用始终同机同账户本地未迁移或远程、原调用及全部派生工具已结束且不会再修改现场；接受旧结果未知，批准保留完整合法草稿使用剩余额度再次执行"
          : "工程授权者确认原执行同机本地且已整机重启，批准保留完整合法草稿继续原需求",
      }, rescue), "primary");
      approve.disabled = true;
      confirmation.addEventListener("change", () => {approve.disabled = confirmation.checked !== true;});
      controls.append(field, approve);
      controls.append(deliveryButton("重新准备恢复方案", () => submitEngineeringLegacyRescueOperation({
        ...rescue.baseline, action: "PROPOSE_EXECUTION_BASELINE", purpose: "legacy_workspace_rescue",
        target_base_ref: rescue.baseline.expected_source_revision, input_mode: "preserve_draft",
      }, rescue), "secondary"));
    } else {
      const preparationSteps = engineeringGuidanceList("先由平台检查当前本机执行和保留进度。检查通过后会展示精确方案与需要确认的前提；检查本身不会继续交付。");
      preparationSteps.classList.add("muted");
      controls.append(preparationSteps,
        deliveryButton(preparation?.status === "WAITING" ? "重新检查恢复前提" : "准备保留进度的恢复方案", () => submitEngineeringLegacyRescueOperation({
          ...rescue.baseline, action: "PROPOSE_EXECUTION_BASELINE", purpose: "legacy_workspace_rescue",
          target_base_ref: rescue.baseline.expected_source_revision, input_mode: "preserve_draft",
        }, rescue), "primary"));
    }
    panel.append(controls);
  }
  target.append(panel);
}
async function submitEngineeringBaselineOperation(intent, originalBound) {
  const request = requestById(intent.delivery_id);
  const current = request && engineeringWaitSteps(request).find(({task, step}) =>
    sameEngineeringWaitIntent(engineeringBaselineFacts(request, task, step), originalBound));
  const plan = current && engineeringBaselinePlan(request, current.task, current.step);
  if (!current || (intent.action === "EXECUTE_EXECUTION_BASELINE" &&
      (!plan || plan.plan_sha256 !== intent.expected_plan_sha256 || plan.conflicted))) {
    operationNotice = {kind: "error", title: "执行基线事实已变化",
      message: "请刷新当前需求并重新调查；旧计划不能用于更新新的工作现场。"};
    renderDetail();
    renderNotification();
    return null;
  }
  if (intent.action === "PROPOSE_EXECUTION_BASELINE" && !/^[a-f0-9]{40}$/.test(intent.target_base_ref || "")) {
    operationNotice = {kind: "error", title: "目标代码版本不完整",
      message: "工程负责人需填写已提交代码的完整 40 位版本，平台会核验精确输入和原分支。"};
    renderNotification();
    return null;
  }
  return submitOperation(intent);
}
function appendEngineeringBaseline(target, request, task, step) {
  const bound = engineeringBaselineFacts(request, task, step);
  if (!bound) return;
  const plan = engineeringBaselinePlan(request, task, step);
  const planSha256 = plan?.plan_sha256;
  const targetBaseRef = plan?.target_base_ref;
  const inputMode = plan?.input_mode;
  const active = activeOperation(request.id, request.project_id);
  const executed = plan && operations.some(item => item.status === "SUCCEEDED" &&
    item.intent.action === "EXECUTE_EXECUTION_BASELINE" && item.intent.task_id === task.task_id &&
    item.intent.project_id === request.project_id &&
    item.intent.delivery_id === request.id && item.intent.expected_plan_sha256 === plan.plan_sha256);
  const fold = viewGroup(plan && !executed
    ? el("section", undefined, "engineering-baseline-panel engineering-baseline-pending")
    : engineeringDetails("可选工程操作 · 更新原分支基线", step.work_item_id + ":baseline"),
    "engineering-baseline:" + step.work_item_id);
  fold.classList.add("engineering-baseline-panel");
  if (plan && !executed) {
    fold.setAttribute("data-key", "engineering:" + step.work_item_id + ":baseline");
    fold.append(el("h4", "工程处理 · 更新原分支基线", "engineering-baseline-title"));
  }
  fold.append(viewBlock(el("p",
    "需要同步平台修复时，可在原需求分支更新代码基线。调查先生成计划并保留完整草稿与历史；批准后才更新，之后仍需独立 QA 和 Review。",
    "muted engineering-baseline-description"), "engineering-baseline-description", Boolean(plan)));
  if (plan) {
    fold.append(el("p", plan.conflicted ? "原草稿与目标代码存在冲突，原现场保留。需明确提出让 Coder 读取完整旧补丁后适配的新计划。" :
      plan.input_mode === "coder_reapply" ? "当前计划从目标代码建立干净执行输入，由 Coder 读取完整旧补丁并适配。" :
      "当前计划在原需求分支保留草稿并更新执行基线。"),
      el("p", "原需求分支 · " + (plan.facts.task.branch_name || "未提供"), "paths"),
      el("p", "目标代码版本 · " + plan.target_base_ref, "paths"));
    const technical = engineeringDetails("执行基线计划绑定", step.work_item_id + ":baseline-plan");
    technical.append(el("p", "计划摘要 · " + plan.plan_sha256, "paths"),
      el("p", "当前执行输入 · " + bound.expected_source_revision, "paths"));
    fold.append(technical);
  }
  if (executed) {
    fold.append(el("p", "此精确计划已执行，后续进度和验收以新的执行记录为准。", "muted"));
  } else if (canControlCurrentTeam() && !active) {
    const form = viewBlock(el("div", undefined, "engineering-baseline-form"), "engineering-baseline-controls",
      [bound, plan, canControlCurrentTeam()]);
    const field = el("label", undefined, "engineering-baseline-field");
    field.append(el("span", "目标代码版本"));
    const input = el("input");
    input.type = "text";
    input.maxLength = 40;
    input.value = plan?.target_base_ref || "";
    input.autocomplete = "off";
    input.spellcheck = false;
    input.setAttribute("aria-label", "目标代码完整版本");
    const help = el("small", "填写已提交代码的完整 40 位 SHA，由平台核验目标版本。", "engineering-baseline-help");
    help.id = "engineering-baseline-help-" + step.work_item_id;
    input.setAttribute("aria-describedby", help.id);
    field.append(input, help);
    const actions = el("div", undefined, "engineering-baseline-actions");
    actions.append(deliveryButton("调查并保留原草稿", () => submitEngineeringBaselineOperation({
      ...bound, action: "PROPOSE_EXECUTION_BASELINE", target_base_ref: input.value.trim(), input_mode: "preserve_draft",
    }, bound), "secondary"));
    if (plan?.conflicted) actions.append(deliveryButton("提出 Coder 适配完整旧补丁的计划", () =>
      submitEngineeringBaselineOperation({...bound, action: "PROPOSE_EXECUTION_BASELINE",
        target_base_ref: targetBaseRef, input_mode: "coder_reapply"}, bound), "secondary"));
    if (plan && !plan.conflicted) actions.append(deliveryButton("批准并更新原分支基线", () =>
      submitEngineeringBaselineOperation({action: "EXECUTE_EXECUTION_BASELINE", project_id: request.project_id,
        delivery_id: request.id, expected_checkpoint_sha256: request.checkpoint_sha256, task_id: task.task_id,
        expected_plan_sha256: planSha256,
        reference: inputMode === "coder_reapply" ? "批准 Coder 从精确目标版本适配完整旧补丁" :
          "批准在原需求分支保留草稿并更新到精确目标版本"}, bound), "primary"));
    form.append(field, actions);
    fold.append(form);
  } else if (active) {
    fold.append(el("p", "工程基线操作正在处理，交付进度以之后的角色事实为准。", "muted"));
  }
  target.append(fold);
}
function deliveryPhase(item) {
  const task = item.request_id ? item : currentRequestTasks(item)
    .filter(task => !task.terminal).sort((a, b) => b.last_activity.localeCompare(a.last_activity))[0];
  const status = task?.status || item.knowledge_wait_stage || item.stage || item.status;
  return {IMPLEMENTING: "实现", QA: "测试", REVIEW: "评审", CONTINUE_REQUIRED: "实现",
    QUEUED: "实现", DELIVERING: "实现", VERIFY_QA: "候选测试", VERIFY_REVIEW: "候选评审", INTEGRATING: "联合验收"}[status] || label(status);
}
function operationPurpose(operation) {
  if (operation.intent.purpose === "legacy_workspace_rescue")
    return "检查本机执行与恢复前提，封存同一需求的完整合法草稿，准备工程恢复方案。";
  if (operation.intent.action === "EXECUTE_EXECUTION_BASELINE" &&
      (operation.intent.confirm_legacy_containment === true || operation.intent.confirm_local_execution_stopped === true))
    return "按精确工程决定保留进度继续同一需求，保留旧执行未知结果和完整历史。";
  return {
    PRODUCT_REPLY: "记录产品回复并继续梳理需求。",
    PRODUCT_APPROVAL: "确认本版产品规格并推进后续交付。",
    CONTINUE_DELIVERY: "接续已保存的交付进度。",
    RECOVER_DESIGN: "处理本次技术设计恢复。",
    RECHECK_DESIGN: "核对保留的设计问题与产品需求。",
  }[operation.intent.action] || null;
}
function operationActionLabel(operation) {
  if (operation.intent.purpose === "legacy_workspace_rescue") return "准备保留进度的恢复方案";
  if (operation.intent.action === "EXECUTE_EXECUTION_BASELINE" &&
      (operation.intent.confirm_legacy_containment === true || operation.intent.confirm_local_execution_stopped === true))
    return "批准保留进度并继续原需求";
  return label(operation.intent.action);
}
function currentEngineeringRescueAdvice(operation, request) {
  const handling = operation.result?.engineering_wait_handling;
  if (!request || request.project_id !== operation.intent.project_id || !handling) return null;
  const current = engineeringWaitSteps(request).find(({task, step}) =>
    engineeringWaitHandling(request, step)?.handling_sha256 === handling.handling_sha256 &&
    engineeringLegacyRescueFacts(request, task, step));
  if (!current) return null;
  const controlUnavailable = deliveryControlUnavailableReason();
  if (controlUnavailable) return controlUnavailable.title + "：" + controlUnavailable.reason + "\n" + controlUnavailable.next_action;
  const rescue = engineeringLegacyRescueFacts(request, current.task, current.step);
  const failure = engineeringLegacyRescueFailure(request, current.task, current.step, rescue);
  if (failure) return `恢复方案准备${failure.status === "INTERRUPTED" ? "被中断" : "失败"}：${failure.summary}\n${failure.next_action}`;
  const preparation = engineeringLegacyRescuePreparation(request, current.task, current.step, rescue);
  if (preparation) return preparation.summary + "\n" + preparation.next_action;
  return "原执行记录仍不完整，旧执行结果保持未知。" + (consoleSupportsLegacyRescue()
    ? "请进入需求详情，点击“准备保留进度的恢复方案”。先查看平台的本机检查结果和精确方案，再由工程授权者确认所列实际停止前提；检查不会自动启动下一轮。"
    : "当前服务尚不支持保留进度的恢复方案，请在服务空闲时更新并重启 Web Console，再刷新页面；原需求和草稿保留。");
}
function recordedOperationOutcome(operation) {
  if (operation.status !== "SUCCEEDED" || !deliveryOperationActions.has(operation.intent.action)) return null;
  const stage = operation.result?.stage;
  const outcomes = {
    BLOCKED: "当次交付已阻塞", FAILED: "当次交付失败", WAITING_HUMAN: "当次交付等待处理",
    WAITING_DEPENDENCY: "当次交付等待依赖", WAITING_PRODUCT_REPLY: "当次需求等待补充",
    WAITING_PRODUCT_APPROVAL: "当次产品规格等待批准", WAITING_DELIVERY_FINALIZATION: "当次交付等待确认",
    DONE: "当次需求已交付", CLOSED: "当次需求已关闭",
  };
  const stoppedStage = ["PRODUCT_DISCOVERY", "DESIGNING", "PLANNING", "DELIVERING", "INTEGRATING"].includes(stage);
  const outcome = Object.hasOwn(outcomes, stage) ? outcomes[stage] : stoppedStage ? "当次停留阶段 · " + label(stage) : null;
  if (!outcome) return null;
  return {title: "操作已结束 · " + outcome,
    className: ["BLOCKED", "FAILED"].includes(stage) || stage.startsWith("WAITING_") ? "error" : ""};
}
function currentOperationProgress(operation, request) {
  if (!request || operation.status !== "RUNNING" || !deliveryOperationActions.has(operation.intent.action) ||
      operationTarget(operation) !== request.id || operation.intent.project_id !== request.project_id ||
      activeOperation(request.id, request.project_id)?.operation_id !== operation.operation_id) return null;
  const node = requestNodeExecution(request);
  const execution = request.execution;
  const responsibility = node.responsibility || (node.requiresEngineeringCheck ? "engineering"
    : ["WAITING_PRODUCT_REPLY", "WAITING_PRODUCT_APPROVAL"].includes(request.stage) ? "product" : execution?.responsibility);
  return {
    title: `当前阶段 · ${deliveryPhase(request)} · ${node.label}`,
    reason: node.upstreamProcessing ? "当前节点正在执行，请等待本阶段处理完成。"
      : humanizeBlockingText(node.reason || execution?.reason || request.blocker),
    responsibility: {product: "产品负责人", team: "ASE 团队", engineering: "工程团队"}[responsibility] || null,
    nextAction: node.upstreamProcessing ? "请等待本轮处理完成。"
      : humanizeBlockingText(node.nextAction || execution?.next_action || request.next_action),
  };
}
function productExecutionSummary(item, {guidance = true} = {}) {
  if (!item.execution) return null;
  const execution = item.execution;
  const node = item.stage ? requestNodeExecution(item) : taskExecutionPresentation(item);
  const section = el("div", undefined, "product-execution-summary");
  section.append(
    el("p", "交付阶段 · " + deliveryPhase(item), "execution-phase"),
    el("p", "当前执行 · " + (node?.label || label(executionPresentationStatus(execution))), "execution-state"),
    el("p", "处理方 · " + {product: "产品负责人", team: "ASE 团队", engineering: "工程团队"}[node?.responsibility || (node?.requiresEngineeringCheck ? "engineering" : execution.responsibility)], "muted"),
  );
  if (guidance) section.append(
    el("p", node?.upstreamProcessing ? "当前节点正在执行，请等待本阶段处理完成。" : humanizeBlockingText(node?.reason || execution.reason)),
    el("p", "下一步 · " + (node?.upstreamProcessing ? "请等待本轮处理完成。" : humanizeBlockingText(node?.nextAction || execution.next_action)), "muted"),
  );
  if (execution.available_at)
    section.append(el("p", "计划重试时间 · " + time(execution.available_at), "muted"));
  if (execution.action_required && execution.responsibility === "product")
    section.append(el("p", "需要你确认业务决定。", "product-decision-required"));
  return section;
}
function taskExecutionPresentation(task) {
  const status = taskPresentationStatus(task);
  if (status === "WAITING_ENGINEERING" && task.execution?.state === "WAITING" &&
      task.execution.responsibility === "engineering")
    return {...engineeringExecutionCheck(), reason: task.execution.reason, nextAction: task.execution.next_action};
  if (status === "WAITING_ENGINEERING") return engineeringExecutionCheck();
  if (status === "RUNNING") return runningRolePresentation();
  if (status === "READY") return queuedRolePresentation();
  if (status === "RETRY_SCHEDULED") return {state: "paused", label: "待重试", status, responsibility: "team",
    reason: "模型执行重试已排队。", nextAction: "请等待计划重试，平台将按记录的时间继续。"};
  if (status === "PREPARING_EXECUTION") return {state: "paused", label: "准备执行", status, responsibility: "team",
    reason: "平台正在准备已批准的执行计划。", nextAction: "请等待本轮准备完成。"};
  return {label: label(status), status};
}
function runningRolePresentation() {
  return {state: "running", label: "执行中", status: "RUNNING", responsibility: "team",
    reason: "当前角色正在执行，请等待本轮处理完成。", nextAction: "请等待本轮角色执行完成。"};
}
function queuedRolePresentation() {
  return {state: "paused", label: "等待调度", status: "READY", responsibility: "team",
    reason: "当前工作已排队，等待团队调度。", nextAction: "请等待团队领取当前工作。"};
}
function taskPresentationStatus(task) {
  if (task.terminal) return task.status || task.stage;
  const waiting = waitingExecutionStep(task);
  if (waiting) return task.execution?.state === "WAITING" ? executionPresentationStatus(task.execution) : waiting.status;
  if (interruptedExecution(task)) return "EXECUTION_INTERRUPTED";
  if (["QUEUED", "CONTINUE_REQUIRED"].includes(task.status)) return task.status;
  if (task.execution && !["UNKNOWN", "RUNNING"].includes(task.execution.state)) return executionPresentationStatus(task.execution);
  const steps = (task.role_queue || []).filter(step => step.role === roleForTaskStatus[task.status]);
  if (steps.some(step => step.status === "RUNNING" && step.lease_liveness === "LEASE_VALID")) return "RUNNING";
  if (steps.some(step => ["READY", "LEASED", "RETRY_SCHEDULED"].includes(step.status)))
    return steps.some(step => step.status === "RETRY_SCHEDULED") ? "RETRY_SCHEDULED" : "READY";
  if (preparingTaskExecution(task)) return "PREPARING_EXECUTION";
  if (["UNKNOWN", "RUNNING"].includes(task.execution?.state) || roleForTaskStatus[task.status]) return "WAITING_ENGINEERING";
  return task.status || task.stage;
}
function preparingTaskExecution(task) {
  if (task.terminal || !["NEW", "PLANNING"].includes(task.status) || task.blocker ||
      waitingExecutionStep(task) || interruptedExecution(task) ||
      ["WAITING", "STOPPED", "INTERRUPTED"].includes(task.execution?.state)) return false;
  const request = requestById(task.request_id);
  const operation = request && activeOperation(request.id, request.project_id);
  return Boolean(operation?.status === "RUNNING" && operation.intent.project_id === request.project_id &&
    deliveryOperationActions.has(operation.intent.action));
}
function waitingRequestTask(request) {
  if (["DONE", "CLOSED"].includes(request.stage)) return null;
  return currentRequestTasks(request).find(task => waitingExecutionStep(task)) || null;
}
function interruptedRequestTask(request) {
  if (request.knowledge_gap?.is_current || ["DONE", "CLOSED"].includes(request.stage)) return null;
  return currentRequestTasks(request).find(interruptedExecution) || null;
}
const interruptedExecutionReason = "执行租约已失效，当前执行已中断；交付阶段和已保存改动仍保留。";
const interruptedExecutionNext = "请通过“继续交付”检查并恢复当前执行。";
function taskGroup(task) {
  if (task.status === "DONE") return "completed";
  if (!task.terminal && taskPresentationStatus(task) === "WAITING_ENGINEERING") return "blocked";
  if (task.execution && !task.terminal) {
    if (["WAITING", "STOPPED", "INTERRUPTED"].includes(task.execution.state) ||
        task.execution.reason_code === "EXECUTION_CLAIM_EXPIRED") return "blocked";
    return "active";
  }
  if (
    task.blocker || interruptedExecution(task) ||
    task.role_queue?.some((step) => step.status.startsWith("WAITING_")) ||
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
  const currentDeliveryIds = new Set((request.scopes || [])
    .map(scope => scope.delivery_id).filter(Boolean));
  const currentByDelivery = new Map();
  for (const task of requestTasks(request)) {
    const deliveryId = task.source_delivery_id || task.id;
    if (!currentDeliveryIds.has(deliveryId)) continue;
    const previous = currentByDelivery.get(deliveryId);
    if (
      !previous ||
      task.last_activity.localeCompare(previous.last_activity) > 0
    )
      currentByDelivery.set(deliveryId, task);
  }
  return [...currentByDelivery.values()];
}
function isHistoricalRequestTask(task) {
  const request = snapshot.requests.find(item => item.id === task.request_id &&
    item.project_id === task.project_id);
  return Boolean(request && !currentRequestTasks(request).some(current => current.id === task.id));
}
function failedDeliveryRoleStages(request) {
  if (!(request.failed_stages || []).includes("DELIVERING") &&
      !(terminalBlockedRequestTask(request) && requestPresentation(request).group === "blocked"))
    return new Set();
  const stages = new Set();
  for (const task of currentRequestTasks(request)) {
    if (!task.terminal || !["BLOCKED", "FAILED"].includes(task.status)) continue;
    const roles = (task.role_queue || [])
      .map((step) => step.role)
      .filter((role) => deliveryRoleStage[role] !== undefined);
    const role = roles.at(-1);
    if (role) stages.add(deliveryRoleStage[role]);
  }
  return stages;
}
function activeRequestTask(request) {
  if (request.stage === "WAITING_HUMAN" && request.knowledge_gap?.is_current)
    return null;
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
    currentRequestTasks(request)
      .filter((task) => taskGroup(task) === "active")
      .sort((left, right) =>
        right.last_activity.localeCompare(left.last_activity),
      )[0] || null
  );
}
function terminalBlockedRequestTask(request) {
  if (request.knowledge_gap?.is_current ||
      !["BLOCKED", "FAILED", "DELIVERING", "INTEGRATING"].includes(request.stage))
    return null;
  return currentRequestTasks(request)
    .filter(task => task.terminal && task.blocker && taskGroup(task) === "blocked")
    .sort((left, right) => right.last_activity.localeCompare(left.last_activity))[0] || null;
}
function operationChildBlocker(request, operation) {
  const task = terminalBlockedRequestTask(request);
  // A retained failure from before this request is the input to recovery. Only
  // a new durable failure can supersede an operation that is still finishing.
  return task && operation?.status === "RUNNING" &&
    Date.parse(task.last_activity) > Date.parse(operation.requested_at) ? task : null;
}
function requestNodeExecution(request) {
  if (request.stage === "DONE") return {state: "done", label: "已完成", status: "DONE"};
  if (request.stage === "CLOSED") return {state: "closed", label: "已关闭", status: "CLOSED"};
  const execution = request.execution;
  const tasks = currentRequestTasks(request);
  const active = activeOperation(request.id, request.project_id);
  const operation = active && active.intent.project_id === request.project_id &&
    deliveryOperationActions.has(active.intent.action) ? active : null;
  const waiting = tasks.find(task => waitingExecutionStep(task));
  const expired = tasks.find(task => !task.terminal &&
    (interruptedExecution(task) || task.role_queue?.some(interruptedStep)));
  const childBlocker = operationChildBlocker(request, operation) ||
    (!operation ? terminalBlockedRequestTask(request) : null);
  if (["WAITING_PRODUCT_REPLY", "WAITING_PRODUCT_APPROVAL"].includes(request.stage))
    return {state: "blocked", label: request.stage === "WAITING_PRODUCT_REPLY" ? "需确认" : "待审批", status: request.stage};
  if (request.stage === "WAITING_DELIVERY_FINALIZATION")
    return {state: "blocked", label: "待确认", status: request.stage, reason: request.blocker};
  if (approvedKnowledge(request))
    return {state: "blocked", label: "已确认的知识 · 待继续", status: "KNOWLEDGE_APPROVED"};
  if (waiting || ["WAITING_HUMAN", "WAITING_DEPENDENCY"].includes(request.stage) ||
      ["WAITING", "STOPPED", "INTERRUPTED"].includes(execution?.state) ||
      execution?.reason_code === "EXECUTION_CLAIM_EXPIRED" || expired || childBlocker)
    return {state: "blocked", label: execution?.state === "WAITING"
      ? label(executionPresentationStatus(execution)) : "已阻塞",
      status: execution?.state === "WAITING" ? executionPresentationStatus(execution)
        : waiting ? waitingExecutionStep(waiting).status : expired || execution?.reason_code === "EXECUTION_CLAIM_EXPIRED"
        ? "EXECUTION_INTERRUPTED" : childBlocker?.status || (execution ? executionPresentationStatus(execution) : request.stage),
      reason: waiting?.blocker || childBlocker?.blocker || execution?.reason || request.blocker};
  if (tasks.some(task => !task.terminal && ["QUEUED", "CONTINUE_REQUIRED"].includes(task.status)))
    return {state: "paused", label: tasks.some(task => task.status === "CONTINUE_REQUIRED") ? "待继续" : "已排队", status: "READY"};
  if (execution?.state === "RETRY_SCHEDULED" || tasks.some(task => !task.terminal &&
      task.role_queue?.some(step => step.status === "RETRY_SCHEDULED")))
    return {state: "paused", label: "待重试", status: "RETRY_SCHEDULED", responsibility: "team",
      reason: "模型执行重试已排队。", nextAction: "请等待计划重试，平台将按记录的时间继续。"};
  const roleSteps = tasks.filter(task => !task.terminal).flatMap(task =>
    (task.role_queue || []).filter(step => step.role === roleForTaskStatus[task.status]));
  const hasNativeStage = tasks.some(task => !task.terminal && roleForTaskStatus[task.status]);
  if (operation?.status === "QUEUED" || execution?.state === "QUEUED" ||
      roleSteps.some(step => ["READY", "LEASED"].includes(step.status)))
    return {...queuedRolePresentation(), label: "已排队"};
  const currentTasks = tasks.filter(task => !task.terminal);
  if (currentTasks.length && currentTasks.every(preparingTaskExecution))
    return {state: "paused", label: "准备执行", status: "PREPARING_EXECUTION", responsibility: "team",
      reason: "平台正在准备已批准的执行计划。",
      nextAction: "平台正在准备已批准的执行计划，请等待本轮准备完成。"};
  const upstream = ["PRODUCT_DISCOVERY", "DESIGNING", "PLANNING", "INTEGRATING"].includes(request.stage);
  if (upstream && !hasNativeStage && operation?.status === "RUNNING")
    return {state: "running", label: "执行中", status: "RUNNING", upstreamProcessing: true, responsibility: "team"};
  if (roleSteps.some(step =>
      step.status === "RUNNING" && step.lease_liveness === "LEASE_VALID"))
    return runningRolePresentation();
  if (!operation && request.design_recovery_available && request.stage_budget?.exhausted !== "capacity")
    return {state: "blocked", label: "设计待恢复", status: "DESIGN_RECOVERY_REQUIRED", reason: request.blocker};
  const approval = !operation && latestApproval(request.id, request.checkpoint_sha256);
  if (approval) return {state: "blocked", label: "待工程确认", status: "WAITING_ENGINEERING", reason: approval.title};
  if (!operation && designBudgetExhausted(request))
    return {state: "blocked", label: request.stage === "DESIGNING" ? "设计预算已用尽" : "执行预算已用尽",
      status: request.stage === "DESIGNING" ? "DESIGN_BUDGET_EXHAUSTED" : "RETRY_BUDGET_EXHAUSTED", reason: designBudgetSummary(request)};
  if (!operation && request.design_recheck_pending)
    return {state: "blocked", label: "待继续核对设计", status: "DESIGNING", reason: request.next_action};
  if (tasks.some(task => !task.terminal))
    return engineeringExecutionCheck();
  const failed = latestOperation(request.id);
  if (!operation && ["FAILED", "INTERRUPTED"].includes(failed?.status) && deliveryOperationActions.has(failed.intent.action) &&
      (!failed.intent.project_id || failed.intent.project_id === request.project_id))
    return {state: "blocked", label: failed.status === "INTERRUPTED" ? "操作已中断" : "已阻塞",
      status: failed.status === "INTERRUPTED" ? "EXECUTION_INTERRUPTED" : request.stage,
      reason: failed.error_summary, operationInterrupted: failed.status === "INTERRUPTED",
      responsibility: failed.status === "INTERRUPTED" && canResumeUpstreamStage(request) ? "team" : undefined,
      nextAction: failed.status === "INTERRUPTED" && canResumeUpstreamStage(request)
        ? upstreamContinuationGuidance(request) : undefined};
  if (!operation && request.coordination && (!request.coordination.stage || request.coordination.stage === request.stage))
    return {state: "blocked", label: "等待处理", status: request.stage, reason: request.coordination.draft.summary};
  if (!operation && (request.blocker || ["BLOCKED", "FAILED"].includes(request.stage)))
    return {state: "blocked", label: "已阻塞", status: request.stage, reason: request.blocker};
  if (request.stage === "READY_FOR_DISCUSSION") return {state: "paused", label: "待开始", status: request.stage};
  if (canResumeUpstreamStage(request) || (!operation && request.stage === "PRODUCT_DISCOVERY"))
    return {state: "paused", label: "待继续", status: request.stage, responsibility: "team",
      reason: "本阶段尚未执行完成，已保存的交付进度与审批仍保留。",
      nextAction: request.stage === "PRODUCT_DISCOVERY" ? "点击“继续需求讨论”接续上一条已保存的消息。" : upstreamContinuationGuidance(request)};
  return engineeringExecutionCheck();
}
function engineeringExecutionCheck() {
  return {state: "blocked", label: "等待工程处理", status: "WAITING_ENGINEERING", requiresEngineeringCheck: true,
    reason: "当前工作缺少可核验的执行状态，由工程团队核验后继续。",
    nextAction: "工程团队核验当前执行和现场后继续，当前无需产品操作。"};
}
function upstreamContinuationGuidance(request) {
  return `点击“${request.stage === "PLANNING" ? "继续计划" : "继续设计"}”接续已批准的需求，原审批与已用预算保留。`;
}
function requestNodeBadge(request) {
  const node = requestNodeExecution(request);
  return el("span", `${deliveryPhase(request)} · ${node.label}`, `badge request-node-badge ${node.state}`);
}
function requestPresentation(request) {
  if (request.execution && !productDiscussionStages.has(request.stage)) {
    const execution = request.execution;
    const node = requestNodeExecution(request);
    const group = request.stage === "CLOSED" ? "closed" : request.stage === "DONE" ? "completed"
      : node.state === "blocked" ? "blocked" : "active";
    return {group, status: ["DONE", "CLOSED"].includes(request.stage) ? request.stage
      : node.status,
      blocker: group === "blocked" ? node.reason || execution.reason : null,
      nextAction: node.upstreamProcessing ? "请等待本轮阶段处理完成。" : node.nextAction || execution.next_action};
  }
  if (!productDiscussionStages.has(request.stage)) {
    const node = requestNodeExecution(request);
    if (node.requiresEngineeringCheck || node.operationInterrupted)
      return {group: "blocked", status: node.status, blocker: node.reason, nextAction: node.nextAction || request.next_action};
  }
  const waitingTask = waitingRequestTask(request);
  if (waitingTask)
    return {group: "blocked", status: approvedKnowledge(request)
      ? "KNOWLEDGE_APPROVED" : waitingExecutionStep(waitingTask).status,
      blocker: approvedKnowledge(request) ? null : waitingTask.blocker || request.blocker,
      nextAction: request.next_action || waitingTask.next_action};
  if (interruptedRequestTask(request))
    return {group: "blocked", status: "EXECUTION_INTERRUPTED",
      blocker: interruptedExecutionReason, nextAction: interruptedExecutionNext};
  const latestResult = latestOperation(request.id)?.result;
  if (
    latestResult?.diagnostic &&
    latestResult.stage === "WAITING_HUMAN" &&
    latestResult.checkpoint_sha256 === request.checkpoint_sha256
  )
    return {
      group: "blocked",
      status: "WAITING_HUMAN",
      blocker: latestResult.diagnostic,
      nextAction: latestResult.diagnostic,
    };
  const running = activeOperation(request.id);
  const deliveryOperation =
    running && deliveryOperationActions.has(running.intent.action)
      ? running
      : null;
  const activeTask = activeRequestTask(request);
  const blockedTask = operationChildBlocker(request, deliveryOperation) ||
    (!deliveryOperation && !activeTask ? terminalBlockedRequestTask(request) : null);
  if (blockedTask)
    return {group: "blocked", status: blockedTask.status,
      blocker: blockedTask.blocker, nextAction: blockedTask.next_action};
  if (deliveryOperation || activeTask) {
    const operationStage =
      deliveryOperation?.intent.action === "PRODUCT_REPLY"
        ? "PRODUCT_DISCOVERY"
        : deliveryOperation?.intent.action === "PRODUCT_APPROVAL"
          ? "DESIGNING"
          : ["RECOVER_DESIGN", "RECHECK_DESIGN"].includes(deliveryOperation?.intent.action)
            ? "DESIGNING"
          : "DELIVERING";
    return {
      group: "active",
      status: activeTask?.status || (["PRODUCT_DISCOVERY", "DESIGNING", "PLANNING", "INTEGRATING"].includes(request.stage) ? request.stage : operationStage),
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
  if (request.design_recovery_available && request.stage_budget?.exhausted !== "capacity")
    return {
      group: "blocked",
      status: "DESIGN_RECOVERY_REQUIRED",
      blocker: request.blocker,
      nextAction: "点击“恢复设计”，保留已批准需求并重新开放设计尝试。",
    };
  if (designBudgetExhausted(request) && !latestApproval(request.id, request.checkpoint_sha256))
    return {
      group: "blocked",
      status: request.stage === "DESIGNING" ? "DESIGN_BUDGET_EXHAUSTED" : "RETRY_BUDGET_EXHAUSTED",
      blocker: designBudgetSummary(request),
      nextAction: "请在设置中提高对应预算，保存并重启服务后继续。",
    };
  const failedDesignOperation = latestOperation(request.id);
  if (request.coordination && !latestApproval(request.id, request.checkpoint_sha256))
    return {
      group: "blocked", status: request.stage,
      blocker: request.coordination.draft.summary, nextAction: request.next_action,
    };
  if (request.design_recheck_pending)
    return {group: "blocked", status: "DESIGNING", blocker: null,
      nextAction: "已保留原产品批准。点击“继续交付”开始重新核对设计，不会自动批准问题中的变更建议。"};
  if (
    ["DESIGNING", "PLANNING"].includes(request.stage) &&
    !latestApproval(request.id, request.checkpoint_sha256) &&
    failedDesignOperation?.status === "FAILED" &&
    operationTarget(failedDesignOperation) === request.id &&
    ["PRODUCT_APPROVAL", "CONTINUE_DELIVERY", "RECOVER_DESIGN"].includes(
      failedDesignOperation.intent.action,
    )
  )
    return {
      group: "blocked",
      status: request.stage === "DESIGNING" ? "DESIGN_RETRY_REQUIRED" : "PLANNER_RETRY_REQUIRED",
      blocker: failedDesignOperation.error_summary || "模型角色操作未完成。",
      nextAction: stageFailureGuidance(failedDesignOperation).action,
    };
  if (approvedKnowledge(request))
    return { group: "blocked", status: "KNOWLEDGE_APPROVED", blocker: null,
      nextAction: "解答已批准，点击“继续交付”恢复原需求。" };
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

function canContinueDelivery(request) {
  if (engineeringWaitSteps(request).length) return false;
  if (requestNodeExecution(request).requiresEngineeringCheck) return false;
  if (request.design_recheck_pending)
    return !designBudgetExhausted(request) && !activeOperation(request.id);
  return (
    !designBudgetExhausted(request) &&
    !["DESIGNING", "PLANNING"].includes(request.stage) &&
    !productDiscussionStages.has(request.stage) &&
    (requestPresentation(request).group === "blocked" ||
      currentRequestTasks(request).some((task) => taskGroup(task) === "blocked"))
  );
}

function canRecoverDesign(request) {
  return Boolean(request.design_recovery_available) &&
    request.stage_budget?.exhausted !== "capacity" && !activeOperation(request.id);
}

function canResumeUpstreamStage(request) {
  if (!["DESIGNING", "PLANNING"].includes(request.stage) || activeOperation(request.id) ||
      currentRequestTasks(request).some(task => !task.terminal) ||
      request.knowledge_gap?.is_current || request.blocker ||
      request.design_recheck_pending || request.coordination && (!request.coordination.stage || request.coordination.stage === request.stage) ||
      request.design_recovery_available || designBudgetExhausted(request) ||
      latestApproval(request.id, request.checkpoint_sha256) ||
      ["WAITING", "STOPPED", "INTERRUPTED", "RETRY_SCHEDULED", "QUEUED"].includes(request.execution?.state) ||
      request.execution?.reason_code === "EXECUTION_CLAIM_EXPIRED") return false;
  const operation = latestOperation(request.id);
  if (!operation) return true;
  if ((operation.intent.project_id && operation.intent.project_id !== request.project_id) ||
      !deliveryOperationActions.has(operation.intent.action) || isSourceRevisionDrift(operation)) return false;
  return operation.status === "SUCCEEDED" && !operationNeedsHumanAttention(operation) ||
    operation.status === "INTERRUPTED" && operation.error_code === "HOST_INTERRUPTED";
}

function canRetryDesign(request) {
  const operation = latestOperation(request.id);
  return (
    ["DESIGNING", "PLANNING"].includes(request.stage) &&
    !latestApproval(request.id, request.checkpoint_sha256) &&
    !request.design_recovery_available &&
    !designBudgetExhausted(request) &&
    !currentRequestTasks(request).some(task => !task.terminal) &&
    !["WAITING", "STOPPED", "INTERRUPTED", "QUEUED", "RETRY_SCHEDULED"].includes(request.execution?.state) &&
    request.execution?.reason_code !== "EXECUTION_CLAIM_EXPIRED" &&
    operation?.status === "FAILED" &&
    !isSourceRevisionDrift(operation) &&
    (!operation.intent.project_id || operation.intent.project_id === request.project_id) &&
    operationTarget(operation) === request.id &&
    ["PRODUCT_APPROVAL", "CONTINUE_DELIVERY", "RECOVER_DESIGN"].includes(operation.intent.action) &&
    !activeOperation(request.id)
  );
}

function designBudgetExhausted(request) {
  if (request.stage_budget) return Boolean(request.stage_budget.exhausted);
  return request.stage === "DESIGNING" && Boolean(request.design_budget?.exhausted);
}

function designBudgetSummary(request) {
  if (request.stage_budget) {
    const budget = request.stage_budget;
    const capacityCount = budget.capacity_timeouts ?? 0;
    const capacityLimit = budget.max_capacity_timeouts ?? 3;
    const time = `；本地执行触顶 ${capacityCount}/${capacityLimit}`;
    const next = capacityCount >= capacityLimit ? "，已达上限"
      : `，当前可用执行窗口 ${budget.next_timeout_seconds ?? 600} 秒`;
    return `${budget.role} 工作尝试 ${budget.attempts}/${budget.max_attempts}；临时故障 ${budget.transient_failures}/${budget.max_transient_failures}${time}${next}。`;
  }
  const budget = request.design_budget;
  if (!budget) return "Design 预算已用尽。";
  return `设计尝试 ${budget.design_attempts}/${budget.max_design_attempts}；临时故障 ${budget.transient_failures}/${budget.max_transient_failures}。`;
}

function agentQueueState(agent) {
  return {
    assigned_delivery_ids: [...agent.assigned_delivery_ids],
    current_stage_delivery_ids: [...agent.current_stage_delivery_ids],
    history_delivery_ids: [...agent.history_delivery_ids],
  };
}

function stageFailureGuidance(operation) {
  const code = operation?.error_code;
  if (code === "MODEL_EXECUTION_LIMIT")
    return {
      reason: "本地模型执行达到本轮时间上限，未确认是服务故障；审批和 checkpoint 已保留。",
      action: "平台按配置将下一次执行窗口加倍，不超过设置的时间与次数上限；触顶后请检查诊断或调整配置并重启。",
    };
  if (code === "PLANNER_TEST_MATRIX_REJECTED")
    return {
      reason: "Planner 测试覆盖不符合设计要求，计划未被接受；拒绝记录与已用预算已保留。",
      action: "检查缺失的测试类型后重试 Planner；平台会在剩余工作预算内要求修正，无需重新确认产品。",
    };
  if (code === "MODEL_INVALID_OUTPUT")
    return {
      reason: "模型输出格式未通过校验，阶段未推进。",
      action: "检查输出格式错误后重试；重试仍受对应角色工作预算限制。",
    };
  if (["COMMAND_REJECTED", "MODEL_POLICY_VIOLATION"].includes(code))
    return {
      reason: "平台校验未通过，阶段未推进；原审批和 checkpoint 已保留。",
      action: "检查失败记录中的具体约束，修正后重试；此错误不代表模型服务不可用。",
    };
  if (["MODEL_PROVIDER_UNAVAILABLE", "MODEL_PROVIDER_ERROR", "MODEL_TIMEOUT",
    "MODEL_RATE_LIMITED", "MODEL_QUOTA_EXHAUSTED", "MODEL_AUTHENTICATION_ERROR"].includes(code))
    return {
      reason: "模型服务调用失败，原审批和 checkpoint 已保留。",
      action: "检查模型服务、凭证或额度，恢复后重试。",
    };
  return {
    reason: "上一次操作未完成，原审批、checkpoint 和已用预算已保留。",
    action: "检查失败记录确定原因后重试；未记录具体错误类型，不能判断为模型服务故障。",
  };
}

function requestBlockingSummary(request) {
  if (requestPresentation(request).group !== "blocked") return null;
  const node = requestNodeExecution(request);
  if (node.requiresEngineeringCheck)
    return {reasons: [{reason: node.reason, scopes: []}], operationReason: null,
      approval: latestApproval(request.id, request.checkpoint_sha256), suggestedAction: node.nextAction,
      approvedKnowledge: false, responsibility: "engineering"};
  if (request.execution && request.execution.responsibility !== "product") {
    return {
      reasons: [{reason: node.reason || request.execution.reason, scopes: []}],
      operationReason: null,
      approval: latestApproval(request.id, request.checkpoint_sha256),
      suggestedAction: node.nextAction || request.execution.next_action,
      approvedKnowledge: false,
      responsibility: node.requiresEngineeringCheck ? "engineering" : request.execution.responsibility,
    };
  }
  if (canRetryDesign(request)) {
    const operation = latestOperation(request.id);
    const guidance = stageFailureGuidance(operation);
    return {
      reasons: [{
        reason: guidance.reason,
        scopes: [],
      }],
      operationReason: operation?.error_summary || null,
      approval: null,
      suggestedAction: guidance.action,
      approvedKnowledge: true,
    };
  }
  if (canRecoverDesign(request)) {
    const operation = latestOperation(request.id);
    return {
      reasons: [{
        reason: "Design 预算已用尽，已有批准的知识解答，可执行有记录的恢复。",
        scopes: [],
      }],
      operationReason: operation?.status === "FAILED" ? operation.error_summary : null,
      approval: null,
      suggestedAction: "点击“恢复设计”，平台会保留需求、讨论和 ProductSpec 审批后重新进入 Design。",
      approvedKnowledge: true,
    };
  }
  if (designBudgetExhausted(request) && !latestApproval(request.id, request.checkpoint_sha256)) {
    return {
      reasons: [{reason: designBudgetSummary(request), scopes: []}],
      operationReason: latestOperation(request.id)?.error_summary || null,
      approval: null,
      suggestedAction: request.stage_budget?.exhausted === "capacity"
        ? "本地执行时间已扩至上限。请检查逐路由模型诊断和任务规模；当前无法直接继续，不要反复点击重试。"
        : "检查失败记录后，在设置 → 通用设置中提高对应预算，保存并重启服务后重试。",
      approvedKnowledge: false,
    };
  }
  if (request.stage === "WAITING_HUMAN" && request.knowledge_gap?.is_current) {
    const approved = approvedKnowledge(request);
    const operation = latestOperation(request.id);
    return {
      reasons: [{reason: approved ? "知识解答已批准，原需求等待继续。" : "有待确认的知识，请补充并批准解答。", scopes: []}],
      operationReason: operation?.status === "FAILED" ? operation.error_summary : null,
      approval: null,
      suggestedAction: approved ? "无需重复解答。点击“继续交付”，平台将使用已批准的解答恢复原需求。"
        : request.design_recheck_available ? "如果这是代码事实或设计问题，可点击“重新核对设计”；真正缺少产品决策时仍需批准解答。"
        : "在下方“待确认的知识”中填写解答和决策依据，点击“批准解答”。",
      approvedKnowledge: approved,
    };
  }
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
  else if (approval?.kind === "pre_execution_restart")
    suggestedAction = "Coder 尚未启动；确认下方新 Task 重启计划后点击“批准并继续”。";
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
  const exact = {
    "Operation input is invalid.": "本次请求未被受理，不是原需求新增的阻塞。页面与服务的操作契约可能不匹配，或提交内容不符合当前契约。请在当前操作和角色执行结束、服务空闲时重启 Web Console 并刷新页面；原需求和已保存进度保留。如仍无法提交，请携带处理报告核对请求字段。",
    "The console host stopped before the operation completed.": "服务在本次操作完成前已停止，操作已中断。已保存的交付进度和审批仍保留。",
    "Designer did not publish a verified planning handoff": "设计到计划的交接尚未通过校验，当前交付已阻塞。由工程团队核验具体原因并处理。",
    "Prepare every selected directory.": "准备所有已选择的代码目录。",
    "Requirement project prepared. Discuss your requirement in this workspace.": "需求项目已准备好，请在此工作区描述并讨论需求。",
    "Discover one product across all prepared directories.": "Product Agent 将梳理所有已准备代码目录的统一需求。",
    "Revise the unified ProductSpec.": "Product Agent 将根据本次回复修订统一产品规格。",
    "Reply to the Product Agent questions.": "请回答 Product Agent 的问题。",
    "Review product_spec and approve this exact checkpoint, or reply with revisions.": "请审阅本版产品规格并批准，或回复需要修改的内容。",
    "Design all participating repositories against the approved product.": "Designer 将依据已批准的产品规格设计所有参与交付的代码仓库。",
    "Plan the bounded repository order and joint integration checks.": "Planner 将制定有界的仓库交付顺序与联合集成检查计划。",
    "Execute each repository with independent QA and Reviewer.": "按计划交付各代码仓库，并由独立 QA 和 Reviewer 验证。",
    "Resume with the exact approved knowledge resolution.": "使用本次已批准的精确知识解答继续交付。",
    "Resolve the recorded project specification conflicts before a new intake.": "请先处理已记录的项目规范冲突，再开始接收新需求。",
    "Requirement closed by user; delivery history is retained.": "需求已由用户关闭，交付历史仍完整保留。",
    "Requirement restarted; continue delivery from the retained checkpoint.": "需求已重新打开，请从保留的交付进度继续。",
    "Design recheck requested. Continue to inspect the retained questions against approved Product facts and exact repository revisions. This is not approval of proposed behavior changes; budgets are unchanged.": "已请求重新核对设计。请继续依据已批准的产品事实和精确仓库版本检查保留的问题。这不代表批准拟议的行为变更，执行预算保持不变。",
    "Designer stopped safely (DesignerOutputRejected)": "技术设计输出未通过校验（DesignerOutputRejected），请检查设计及失败记录。",
    REQUEST_HUMAN: "需要人工处理后再继续交付。",
    "A child delivery or integration requires recovery.": "子交付或联合集成需要恢复。",
    "Delivery is blocked by a child delivery or integration requiring recovery. The child finding requests human involvement; no repair or usable approval is established by the supplied hashes alone.": "子交付或联合集成需要恢复，当前交付已阻塞。子任务发现需要人工介入；仅凭现有摘要无法建立可用修复或批准。",
    "Required context exceeds the configured input budget; no model retry.": "所需上下文超过配置的输入上限，不能重试模型。",
    "prepared joint context exceeds budget": "需求的必需上下文超过配置上限。请工程负责人核验上下文预算和已选知识、规范，再重新执行当前操作。",
    "BUDGET_EXHAUSTED: Required context exceeds the configured input budget; no automatic retry.": "BUDGET_EXHAUSTED：所需上下文超过配置的输入上限，不能自动重试。",
    "Candidate verification stopped before a sealed result was produced.": "候选验证在封存结果生成前停止。",
    "Candidate verification passed; continue the delivery acceptance policy.": "候选验证已通过，请继续执行交付验收策略。",
    "Continue the delivery to create and approve a fresh verification plan.": "请继续交付，以创建并批准新的验证计划。",
    "A successor verification plan replaced this consumed plan.": "后续验证计划已替代本次已消费的计划。",
    "QA candidate verification is active or awaiting resume.": "QA 候选验证正在执行或等待恢复。",
    "Reviewer candidate verification is active or awaiting resume.": "Reviewer 候选验证正在执行或等待恢复。",
    "Verify the complete pinned candidate set together.": "请对已固定的完整候选集合执行联合验证。",
    "Joint integration failed. Preserve candidates and inspect command evidence; do not merge independently.": "联合集成失败。请保留候选并检查命令证据，不要单独合并。",
    "Joint candidates passed repository QA/Review and integration. Review the candidate set before merging; nothing was pushed.": "所有候选已通过仓库 QA、Review 和联合集成。合并前请检查候选集合；平台没有推送代码。",
    "The repository candidate passed native QA and Review. Review the candidate before merging; nothing was pushed.": "仓库候选已通过原生 QA 和 Review。合并前请检查候选；平台没有推送代码。",
    "Resume only incomplete repository deliveries.": "仅恢复尚未完成的仓库交付。",
    "No automatic continuation is available; inspect the terminal Task and use explicit recovery if it contains uncommitted Coder work.": "当前没有可自动继续的路径；请检查终态 Task，如有未提交的 Coder 改动则使用明确的恢复流程。",
    "No automatic continuation is available.": "当前没有可自动继续的路径。",
    "Review and approve the exact Coder recovery plan.": "请检查并批准精确的 Coder 恢复计划。",
    "Review and approve the exact omitted file paths.": "请检查并批准精确的遗漏文件路径。",
    "Approve one new Coder Run on the exact stopped workspace.": "请在已停止的精确工作区上批准一次新的 Coder 执行。",
    "Approve the exact omitted file paths before capturing retained work.": "请先批准精确的遗漏文件路径，再封存保留的改动。",
    "Inspect the captured Coder changes, then rerun request resume with this exact plan digest and an approval reference.": "请检查已封存的 Coder 改动，然后携带该精确计划摘要和批准引用重新请求恢复。",
    "Waiting for recovery": "等待恢复。",
    "Current recovery source or target facts do not match": "当前恢复来源或目标事实不匹配。",
    "Manager operation failed; inspect durable delivery facts.": "Manager 操作失败，请检查持久化的交付事实。",
    "Manager rejected the operation; inspect current delivery facts.": "Manager 拒绝了该操作，请检查当前交付事实。",
    "The previous joint integration command failed. Produce a fresh, complete integration plan using the recorded command evidence.": "上一次联合集成命令失败。请依据已记录的命令证据生成新的完整联合集成计划。",
    "candidate review prompt exceeds its configured Context budget": "候选验证上下文超过配置预算，平台在模型调用前安全停止；请缩小精确验证范围或生成新的验证计划。",
    "candidate read snapshot exceeds its bounded context budget": "候选读取快照超过有界上下文预算，平台未调用模型；请缩小精确验证范围或生成新的验证计划。",
    "required candidate source exceeds its bounded budget": "候选必需源码超过有界预算，平台未调用模型；请修订精确验证范围后再继续。",
    ContextBudgetExceeded: "候选验证上下文超过配置预算，平台未调用模型；请修订精确验证范围后再继续。",
    "Responses provider returned HTTP 409": "Responses 模型服务返回 HTTP 409，当前模型调用未完成；请检查路由状态后再继续。",
    AUTHENTICATION_ERROR: "模型服务认证失败，当前阶段未完成；请检查模型凭据和路由配置后再继续。",
    RATE_LIMITED: "模型服务触发限流，当前阶段未完成；请等待限流恢复或使用已配置的备用路由。",
    TIMEOUT: "模型服务或执行器超时，当前阶段未完成；请检查服务可用性后再继续。",
    UNKNOWN_EVIDENCE_REFERENCE: "模型产物引用了不存在的证据，QA/Review 结果未被接受；请让 Coder 按该 finding 修正后重新验证。",
    ARTIFACT_VALIDATION: "角色产物未通过完整性校验，平台拒绝推进阶段；请保留原记录并按失败原因恢复。",
  };
  if (Object.prototype.hasOwnProperty.call(exact, text)) return exact[text];
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
  if (
    /^Repository [^\s]+ is BLOCKED; inspect its native checkpoint\. Completed repositories are retained; joint delivery is not DONE\.$/.test(
      text,
    )
  )
    return "至少一个代码仓库任务仍处于阻塞状态，联合交付尚未完成。";
  const repository = text.match(/^Repository (.+?) is BLOCKED; (.*)$/);
  if (repository) {
    if (repository[2].startsWith("PLANNING (INVARIANT_VIOLATION): Planner stopped safely"))
      return `代码仓库 ${repository[1]} 已阻塞；计划阶段校验失败（INVARIANT_VIOLATION），Planner 已安全停止。`;
    return `代码仓库 ${repository[1]} 已阻塞；请检查该仓库的交付检查点。`;
  }
  const roleFailure = text.match(
    /^(?:(?:TRANSIENT_INFRA|POLICY_VIOLATION|INVALID_OUTPUT|VERIFICATION_INCONCLUSIVE|WORK_INTERRUPTED):\s*)?(Coder|QA|Reviewer) failed at attempt (\d+): (.*)$/,
  );
  if (roleFailure) {
    const detail = roleFailure[3];
    const reason = detail.startsWith("工程执行已中断。草稿已保留。")
      ? "工程执行中断，草稿已保留，由工程团队核对并处理"
      : detail.includes("candidate review prompt exceeds its configured Context budget")
      ? "候选验证上下文超过配置预算，平台在模型调用前安全停止"
      : detail.includes("candidate read snapshot exceeds its bounded context budget")
        ? "候选读取快照超过有界上下文预算，平台未调用模型"
        : detail.includes("required candidate source exceeds its bounded budget")
          ? "候选必需源码超过有界预算，平台未调用模型"
          : detail.includes("ContextBudgetExceeded")
            ? "候选验证上下文超过配置预算，平台未调用模型"
            : detail.includes("Responses provider returned HTTP 409")
              ? "Responses 模型服务返回 HTTP 409，当前模型调用未完成"
              : detail.includes("AUTHENTICATION_ERROR")
                ? "模型服务认证失败，当前阶段未完成"
                : detail.includes("RATE_LIMITED")
                  ? "模型服务触发限流，当前阶段未完成"
                  : detail.includes("TIMEOUT") || detail.toLowerCase().includes("provider timeout")
                    ? "模型服务或执行器超时，当前阶段未完成"
                    : detail.includes("UNKNOWN_EVIDENCE_REFERENCE")
                      ? "模型产物引用了不存在的证据，QA/Review 结果未被接受"
                      : detail.includes("ARTIFACT_VALIDATION")
                        ? "角色产物未通过完整性校验，平台拒绝推进阶段"
                        : detail.includes("failed provider route left repository changes")
      ? (() => {
          const http = detail.match(/provider_diagnostic=Responses provider returned HTTP (\d{3})/);
          if (http) return `提供方路由失败后仓库仍有改动；模型服务返回 HTTP ${http[1]}，改动已保留，等待精确恢复审批`;
          if (detail.includes("provider_diagnostic=Responses provider is unavailable"))
            return "提供方路由失败后仓库仍有改动；模型服务暂不可用，改动已保留，等待精确恢复审批";
          return "提供方路由失败后仓库仍有改动，改动已保留，等待精确恢复审批";
        })()
      : detail.includes("Codex CLI provider execution failed")
        ? "Codex CLI 模型服务执行失败"
        : detail.includes("interrupted execution left repository changes") || detail.includes("left a dirty worktree")
          ? "执行中断后工作区仍有未确认改动，平台已暂停并等待精确恢复审批"
        : "执行失败，原始诊断已封存";
    const run = detail.match(/\brun_[0-9a-z]+\b/);
    const digests = [...detail.matchAll(/\b[0-9a-f]{64}\b/g)].slice(0, 2).map((item) => item[0]);
    const facts = [run?.[0] ? `执行记录 ${run[0]}` : "", ...digests.map((digest) => `证据摘要 ${digest}`)]
      .filter(Boolean);
    return `${roleFailure[1]} 第 ${roleFailure[2]} 次执行失败：${reason}${facts.length ? `；${facts.join("；")}` : ""}。`;
  }
  const localKnowledgeTimeout = text.match(
    /^(?:TRANSIENT_INFRA:\s*)?(coder|qa|reviewer) knowledge preparation reached local time limit$/i,
  );
  if (localKnowledgeTimeout) {
    const roles = { coder: "Coder", qa: "QA", reviewer: "Reviewer" };
    return `${roles[localKnowledgeTimeout[1].toLowerCase()]} 知识准备达到本地执行时限，尚未开始该角色执行；请检查并批准精确恢复计划。`;
  }
  const knowledgeFailure = text.match(
    /^(?:(?:TRANSIENT_INFRA|BUDGET_EXHAUSTED|POLICY_VIOLATION):\s*)?(Coder|QA|Reviewer) knowledge (preparation|assessment|intent) failed:\s*([A-Z0-9_:-]+)$/i,
  );
  if (knowledgeFailure) {
    const phases = { preparation: "准备", assessment: "评估", intent: "意图分析" };
    const roles = { coder: "Coder", qa: "QA", reviewer: "Reviewer" };
    return `${roles[knowledgeFailure[1].toLowerCase()]} 知识${phases[knowledgeFailure[2].toLowerCase()]}失败（原因代码：${knowledgeFailure[3].toUpperCase()}），请检查模型服务后再继续。`;
  }
  if (text === "Delivery is blocked because a sub-delivery or joint integration requires recovery and the child finding requests human handling.")
    return "子交付或联合集成需要恢复，子任务发现需要人工处理。";
  const recoveryRoute = text.match(
    /^Route the blocked delivery to the existing exact recovery approval associated with approval_sha256 ([0-9a-f]{64})\. Do not reset task state or replay any consumed approval\.$/,
  );
  if (recoveryRoute)
    return `请将阻塞交付转入已存在且精确匹配的恢复审批（审批摘要 ${recoveryRoute[1]}）。不要重置任务状态，也不要重复使用已消费的审批。`;
  if (text === "Resume the existing delivery task only after the exact recovery approval is confirmed and the authorized recovery path is available.")
    return "确认精确恢复审批并具备授权恢复路径后，才能恢复现有交付任务。";
  if (text.startsWith("Coder recovery stopped safely:"))
    return "Coder 恢复已安全停止，请检查失败记录和恢复证据后再继续。";
  if (text.startsWith("Coder 恢复已安全停止："))
    return "Coder 恢复已安全停止，请检查失败记录和恢复证据后再继续。";
  if (text.startsWith("BUDGET_EXHAUSTED") && text.includes("上下文"))
    return "上下文预算已用尽，平台不会自动重试模型；请缩小精确验证范围后再继续。";
  if (text.startsWith("Pre-execution restart stopped safely:"))
    return "Coder 启动前重启已安全停止，请检查失败记录和恢复证据后再继续。";
  if (text.startsWith("Coder 启动前重启已安全停止："))
    return "Coder 启动前重启已安全停止，请检查失败记录和恢复证据后再继续。";
  if (text.startsWith("failed Coder identity is missing, unsafe or ambiguous") ||
      text.startsWith("recoverable Coder identity is missing, unsafe or ambiguous"))
    return "系统未能确认唯一且可信的 Coder 执行记录，本次自动恢复已安全停止。";
  if (text.startsWith("Rejected plan "))
    return "计划未通过校验，阶段已阻塞；请在恢复时修正计划并保留原错误证据。";
  if (text.startsWith("SPEC_CONFLICT"))
    return "项目规范与平台安全策略冲突，需要人工决定后才能继续。";
  if (text.startsWith("Manager:"))
    return "Manager 协调：请检查当前前提并完成恢复。";
  if (text.startsWith("Approve ")) return "请批准精确的恢复计划后继续。";
  if (text.startsWith("Review and approve ")) return "请检查并批准精确计划后继续。";
  if (text.startsWith("Inspect ")) return "请检查当前交付记录和证据后再继续。";
  if (text.startsWith("Continue ")) return "请继续交付以恢复当前流程。";
  if (text === "Continue") return "请继续交付以恢复当前流程。";
  return text;
}
function requestBlockerSection(request) {
  const summary = requestBlockingSummary(request);
  if (!summary) return null;
  const section = viewGroup(el(
    "section",
    undefined,
    "detail-section request-blocking-section",
  ), "request-blockers");
  section.append(
    el("h3", summary.approvedKnowledge ? "下一步" : "阻塞信息"),
    el(
      "p",
      "以下是本次交付的当前原因与建议操作；历史轮次请查看页面下方的记录。",
      "muted",
    ),
  );
  for (const item of summary.reasons) {
    const card = el("div", undefined, "request-blocking-primary");
    const scopeApproval = summary.approval?.kind === "coder_scope";
    card.append(
      el(
        "span",
        summary.approvedKnowledge ? "当前状态" : summary.approval ? "原始阻塞" : "当前阻塞",
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
    el("p", humanizeBlockingText(summary.suggestedAction)),
  );
  section.append(next);
  if (summary.approval)
    section.append(recoveryApprovalBox(request, summary.approval));
  for (const {task, step} of engineeringWaitSteps(request))
    section.append(engineeringWaitBox(request, task, step));
  return section;
}

function recoveryApprovalBox(request, approval) {
  const management = engineeringDetails("工程管理 · 需工程授权者处理");
  management.append(el("p", "以下操作供工程授权者使用；产品负责人无需决定技术恢复方式。服务检查可信本机主体的工程职责，并记录实际批准者。", "muted"));
  const box = el("div", undefined, "approval-box request-blocking-approval");
  box.append(el("h3", approval.title));
  for (const fact of approval.facts) box.append(el("p", fact, "paths"));
  box.append(
    el(
      "p",
      approval.kind === "coder_scope"
        ? "批准后平台按上方精确范围准备恢复计划，不会启动 Agent；执行前仍需审批恢复计划。"
        : "批准后平台只执行上方计划；页面会把精确计划身份安全地带回 Manager。",
      "muted",
    ),
    deliveryButton(
      approval.kind === "coder_scope" ? "批准文件范围" : "批准并继续",
      () =>
        submitOperation({
          action: "CONTINUE_DELIVERY",
          project_id: request.project_id,
          delivery_id: request.id,
          expected_checkpoint_sha256: request.checkpoint_sha256,
          ...(approval.kind === "coder_scope"
            ? { approved_scope_sha256: approval.plan_sha256,
                ...(approval.coder_scope_request
                  ? { coder_scope_request: approval.coder_scope_request } : {}) }
            : approval.kind === "prerequisite_repair"
              ? { approved_repair_sha256: approval.plan_sha256 }
            : { approved_plan_sha256: approval.plan_sha256 }),
        }),
      "primary",
    ),
  );
  management.append(box);
  return management;
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
    const d = viewBlock(el("details", undefined, "artifact-document"), `document:${doc.source_uri}`, doc);
    d.dataset.key = doc.source_uri;
    d.append(
      el("summary", doc.name),
    );
    d.append(
      el(
        "pre",
        doc.content || "当前提供已提交文档的身份引用；正文尚未接入此视图。",
      ),
    );
    const identity = engineeringDetails("文档来源与校验摘要", doc.source_uri + ":identity");
    identity.append(el("p", doc.source_uri, "paths"), el("p", "SHA-256 · " + doc.sha256, "paths"));
    d.append(identity);
    parent.append(d);
  }
}
function requestDialogue(parent, request) {
  const turns = request.dialogue || [];
  if (!turns.length && !productDiscussionStages.has(request.stage)) return null;
  const section = viewGroup(el("section", undefined, "detail-section product-dialogue"), "discussion");
  const heading = el("div", undefined, "row");
  heading.append(el("h3", "需求讨论"));
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
function hasOpenComposer() {
  return Boolean(
    composing || creatingProject || editingRequirement || recreatingRequirement ||
    knowledgeImportMode || pendingConfirmation || settingsSaveResult ||
    editingKnowledgeDocument || editingSpecDocument,
  );
}
// UI command ownership is the form/dialog node, never a mutable global editor flag.
const uiCommands = new WeakMap();
const dirtyComposers = new WeakSet();
const observedComposers = new WeakSet();
const modalOpeners = new Map();
let inertNodes = [];
let currentModal = null;
function runUiAction(owner, action) {
  if (owner && uiCommands.has(owner)) return;
  const controls = owner?.querySelectorAll
    ? [...owner.querySelectorAll("button, input, textarea, select")].map(node => [node, suspendedDeliveryControls.get(node) ?? node.disabled]) : [];
  const result = action();
  if (!owner || !result?.then) return result;
  uiCommands.set(owner, controls);
  owner.setAttribute("aria-busy", "true");
  for (const [node] of controls) {
    if (node.getAttribute("data-delivery-control") === "true") setDeliveryControlDisabled(node, true);
    else node.disabled = true;
  }
  const status = el("p", "正在提交，请等待结果。提交后关闭窗口不会撤销命令。", "command-pending muted");
  status.setAttribute("role", "status");
  owner.append(status);
  syncModalState();
  return result.finally(() => {
    uiCommands.delete(owner);
    owner.removeAttribute("aria-busy");
    status.remove();
    for (const [node, disabled] of controls) {
      if (node.getAttribute("data-delivery-control") === "true") setDeliveryControlDisabled(node, disabled);
      else node.disabled = disabled;
    }
    if (owner.matches?.(".settings-form") && page === "settings") render();
    syncModalState();
  });
}
function onFormSubmit(form, action) {
  form.addEventListener("submit", event => {
    event.preventDefault();
    return runUiAction(form.closest?.(".modal-dialog") || form, () => action(event));
  });
}
function mayCloseComposer() {
  const dialog = document.getElementById("composer").firstElementChild;
  if (!dialog) return true;
  if (uiCommands.has(dialog)) return false;
  return !dirtyComposers.has(dialog) || globalThis.confirm("还有未保存的编辑，确定放弃并关闭吗？");
}
function topModal() {
  for (const id of ["notification", "composer", "detail"]) {
    const panel = document.getElementById(id);
    if (!panel.hidden) {
      const dialog = panel.querySelector?.('[aria-modal="true"]');
      if (dialog) return dialog;
    }
  }
  return null;
}
function modalControls(dialog) {
  return [...dialog.querySelectorAll("button, input, textarea, select, a[href], summary, [tabindex]")]
    .filter(node => !node.disabled && node.tabIndex >= 0 && node.getClientRects().length && !node.closest("[hidden]"));
}
function focusModal(dialog) {
  const target = modalControls(dialog)[0] || dialog;
  if (target === dialog) dialog.tabIndex = -1;
  target.focus();
}
function syncModalState() {
  // The lightweight contract harness has no layout/focus APIs; browser tests cover this seam.
  if (!document.body?.contains) return;
  const modal = topModal();
  for (const node of inertNodes) node.inert = false;
  inertNodes = [];
  if (modal) {
    let branch = modal;
    while (branch.parentElement) {
      for (const sibling of branch.parentElement.children) {
        if (sibling !== branch) { sibling.inert = true; inertNodes.push(sibling); }
      }
      branch = branch.parentElement;
      if (branch === document.body) break;
    }
  }
  const composer = document.getElementById("composer").firstElementChild;
  if (composer && !observedComposers.has(composer)) {
    observedComposers.add(composer);
    for (const event of ["input", "change"])
      composer.addEventListener(event, () => dirtyComposers.add(composer));
  }
  const old = currentModal;
  currentModal = modal;
  // Capture openers before builders focus new controls (render wrappers do this).
  for (const [dialog, opener] of modalOpeners) {
    if (dialog.isConnected) continue;
    modalOpeners.delete(dialog);
    if (old !== dialog) continue;
    let target = opener.node?.isConnected ? opener.node : null;
    if (!target && opener.id) target = document.getElementById(opener.id);
    if (!target && opener.text) target = [...document.querySelectorAll("button")]
      .find(node => node.textContent === opener.text && !node.closest("[hidden]") && !node.inert);
    if (target && (!modal || modal.contains(target))) target.focus();
  }
  if (modal && !modal.contains(document.activeElement)) focusModal(modal);
}
function rememberModalOpener(panel, opener) {
  const dialog = panel.querySelector?.('[aria-modal="true"]');
  if (dialog && !modalOpeners.has(dialog)) {
    // Keep the original opener when a polled task dialog is rebuilt.
    const previous = [...modalOpeners].find(([node, value]) => !node.isConnected && value.panel === panel.id);
    modalOpeners.set(dialog, previous?.[1] || {
      panel: panel.id, node: opener, id: opener?.id, text: opener?.tagName === "BUTTON" ? opener.textContent : null,
    });
  }
}
document.addEventListener?.("keydown", event => {
  const modal = topModal();
  if (!modal) return;
  if (event.key === "Escape") {
    event.preventDefault(); event.stopPropagation();
    if (uiCommands.has(modal)) return;
    const close = [...modal.querySelectorAll("button")]
      .find(node => ["取消", "知道了", "关闭"].includes(node.textContent) && !node.disabled);
    close?.click();
  } else if (event.key === "Tab") {
    const controls = modalControls(modal);
    const index = controls.indexOf(document.activeElement);
    event.preventDefault(); event.stopPropagation();
    if (!controls.length) focusModal(modal);
    else controls[(index + (event.shiftKey ? -1 : 1) + controls.length) % controls.length].focus();
  }
}, true);
document.addEventListener?.("focusin", () => {
  const modal = topModal();
  if (modal && !modal.contains(document.activeElement)) focusModal(modal);
});
globalThis.addEventListener?.("beforeunload", event => {
  const composer = document.getElementById("composer").firstElementChild;
  if (settingsHaveDraft() || (composer && (dirtyComposers.has(composer) || uiCommands.has(composer))) ||
      [...discussionFormCaches.values()].some(draft => draft.dirty())) {
    event.preventDefault(); event.returnValue = "";
  }
});
function renderComposer() {
  const panel = document.getElementById("composer");
  if (hasOpenComposer() && uiCommands.has(panel.firstElementChild)) return;
  const opener = document.activeElement;
  buildComposer();
  rememberModalOpener(panel, opener);
  syncModalState();
}
function buildComposer() {
  const panel = document.getElementById("composer");
  panel.replaceChildren();
  panel.className = "";
  panel.hidden = !hasOpenComposer();
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
        if (configurationApplyResult?.kind === "success")
          configurationApplyResult = null;
        render();
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
          : applyResult?.message ||
            (success && result.restart_required && settingsSnapshot?.restart_required === false
              ? "配置已生效。"
              : result.message),
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
    const deliveryConfirmation = page === "requests";
    const feedback = el("p", "", "form-feedback");
    const cancel = button("取消", () => {
      pendingConfirmation = null;
      renderComposer();
    });
    const proceed = button(
      confirmation.confirmText,
      async () => {
        if (deliveryConfirmation) setDeliveryControlDisabled(proceed, true);
        else proceed.disabled = true;
        try {
          await confirmation.action();
          if (pendingConfirmation !== confirmation) return;
          pendingConfirmation = null;
          render();
        } catch (error) {
          feedback.className = "form-feedback error";
          feedback.textContent =
            error instanceof Error ? error.message : "操作失败。";
          if (deliveryConfirmation) setDeliveryControlDisabled(proceed, false);
          else proceed.disabled = false;
        }
      },
      "danger",
    );
    if (deliveryConfirmation) proceed.setAttribute("data-delivery-control", "true");
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
    onFormSubmit(form, async (event) => {
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
        if (editingKnowledgeDocument !== editing) return;
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
    onFormSubmit(form, async (event) => {
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
        if (editingSpecDocument !== editing) return;
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
    submit.setAttribute("data-delivery-control", "true");
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
    onFormSubmit(form, async (event) => {
      event.preventDefault();
      setDeliveryControlDisabled(submit, true);
      try {
        if (!canControlCurrentTeam())
          throw new Error("交付控制状态暂不可用，请刷新后重试。");
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
        setDeliveryControlDisabled(submit, false);
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
        if (result.directories?.length) dirtyComposers.add(dialog);
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
          dirtyComposers.add(dialog);
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
  submit.setAttribute("data-delivery-control", "true");
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
  onFormSubmit(form, async (event) => {
    event.preventDefault();
    const projectRoots = [...selectedRoots];
    if (!name.value.trim() || !projectRoots.length) {
      feedback.textContent = "请填写需求名称和至少一个绝对代码目录。";
      feedback.className = "form-feedback error";
      return;
    }
    setDeliveryControlDisabled(submit, true);
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
      setDeliveryControlDisabled(submit, false);
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
function operationNoticeKey(operation) {
  const state = ["QUEUED", "RUNNING"].includes(operation.status)
    ? "ACTIVE"
    : operationNeedsHumanAttention(operation)
      ? "ACTION_REQUIRED"
      : operation.status;
  return `${operation.operation_id}:${state}`;
}
function persistAcknowledgedOperationNotices() {
  try {
    globalThis.localStorage?.setItem(
      "ase-acknowledged-operation-notices",
      JSON.stringify([...acknowledgedOperationNoticeKeys].slice(-200)),
    );
  } catch {
    // Browser storage is optional; the current page still acknowledges the dialog.
  }
}
function acknowledgeOperationNotice(notice) {
  if (notice?.key) {
    acknowledgedOperationNoticeKeys.add(notice.key);
    persistAcknowledgedOperationNotices();
  }
  if (operationNotice === notice || (notice?.key && operationNotice?.key === notice.key))
    operationNotice = null;
}
async function notificationJump(notice) {
  if (hasOpenComposer()) return;
  acknowledgeOperationNotice(notice);
  renderNotification();
  if (notice.target) {
    page = "requests";
    updateNavigation();
    showDetail("request", notice.target);
    return;
  }
  if (notice.page) {
    await navigatePage(notice.page);
    return;
  }
}
function operationNoticeFor(operation) {
  const context = operation.intent.project_id
    ? projectName() : "团队";
  const targetId = operationTarget(operation);
  const request = snapshot && targetId ? requestById(targetId) : null;
  const target = request && request.project_id === operation.intent.project_id
    ? targetId : null;
  const progress = currentOperationProgress(operation, request);
  const needsHumanAttention = operationNeedsHumanAttention(operation);
  const knowledgeApproved =
    needsHumanAttention &&
    operation.result?.stage === "WAITING_HUMAN" &&
    request &&
    operation.result.checkpoint_sha256 === request.checkpoint_sha256 &&
    approvedKnowledge(request);
  const rescueFailure = operation.intent.action === "PROPOSE_EXECUTION_BASELINE" && operation.intent.purpose === "legacy_workspace_rescue"
    ? legacyRescueFailureNotice(operation) : null;
  if (["QUEUED", "RUNNING"].includes(operation.status))
    return {
      key: operationNoticeKey(operation),
      operationId: operation.operation_id,
      state: "ACTIVE",
      kind: "info",
      title: `${context} · ${operationActionLabel(operation)} · ${label(operation.status)}`,
      message:
        operation.status === "QUEUED"
          ? operation.intent.action === "HANDLE_DELIVERY_WAIT"
            ? "处理中断的操作已接收，等待平台执行。关闭弹窗不会改变当前等待。"
            : "操作已安全接收，正在等待 Manager 执行。关闭弹窗不会中断任务。"
          : progress
            ? [progress.title, progress.reason, progress.responsibility && "处理方 · " + progress.responsibility,
              progress.nextAction && "下一步 · " + progress.nextAction, "关闭弹窗不会改变交付状态。"].filter(Boolean).join("\n")
          : operation.intent.action === "HANDLE_DELIVERY_WAIT"
            ? "平台正在处理中断。只有已核实、且现有授权允许的路径才会继续；当前等待与验收结果不会由提示覆盖。"
          : operation.intent.action === "INSPECT_DELIVERY_WAIT"
            ? "工程团队正在核验原执行与现场。调查期间保留原等待状态，调查不会产生验收结论。"
          : operation.intent.action === "RESOLVE_DELIVERY_WAIT"
            ? "工程团队正在记录精确处理决定并继续原交付。是否恢复及验收通过以新的执行记录为准。"
          : operation.intent.action === "PROPOSE_EXECUTION_BASELINE"
            ? operation.intent.purpose === "legacy_workspace_rescue"
              ? "平台正在检查本机执行与恢复前提并封存完整合法草稿；尚未启动下一轮，也未改变旧执行的未知结果。"
              : "工程团队正在核验原分支、完整草稿和目标代码版本，尚未改变交付或验收结论。"
          : operation.intent.action === "EXECUTE_EXECUTION_BASELINE"
            ? operation.intent.confirm_legacy_containment === true || operation.intent.confirm_local_execution_stopped === true
              ? "平台正在记录工程授权并保留进度继续同一需求；是否恢复和验收通过以新的角色执行记录为准。"
              : "工程团队正在按精确计划更新原需求执行基线，交付进度以之后的角色执行记录为准。"
          : "交付流程正在执行。你可以关闭弹窗或页面，任务会继续运行。",
    };
  if (["FAILED", "INTERRUPTED"].includes(operation.status))
    return {
      key: operationNoticeKey(operation),
      operationId: operation.operation_id,
      state: operation.status,
      kind: "error",
      title: `${context} · ${operationActionLabel(operation)} · ${label(operation.status)}`,
      message: rescueFailure
        ? [rescueFailure.summary, rescueFailure.next_action, "操作编号 · " + rescueFailure.operation_id,
          "错误编号 · " + rescueFailure.error_code, "安全排障说明 · " + rescueFailure.detail].join("\n")
        : humanizeBlockingText(operation.error_summary || "操作未完成，请查看需求详情后处理。"),
      target,
      jumpLabel: target ? "打开需求工作区" : null,
    };
  if (needsHumanAttention)
    return {
      key: operationNoticeKey(operation),
      operationId: operation.operation_id,
      state: "ACTION_REQUIRED",
      kind: "warning",
      title: `${context} · ${operationActionLabel(operation)} · 需要处理`,
      message: knowledgeApproved
        ? "知识解答已批准。请进入需求工作区继续原需求。"
        : operation.result?.engineering_wait_handling
          ? currentEngineeringRescueAdvice(operation, request) || [operation.result.engineering_wait_handling.summary, operation.result.engineering_wait_handling.user_action]
            .filter(Boolean).map(humanizeBlockingText).join("\n")
        : operation.result?.diagnostic
          ? humanizeBlockingText(operation.result.diagnostic)
          : "操作需要你的处理，具体原因和下一步已收口到需求详情。",
      target,
      jumpLabel: target ? "打开需求工作区" : null,
    };
  return null;
}
function systemOperationNotices() {
  const notices = [];
  if (consoleAvailable === false)
    notices.push({
      key: "system:console-read-only",
      kind: "error",
      title: "交付控制不可用",
      message: "当前服务未提供交付控制接口。请连接后台 Web Console 后再创建或继续需求。",
      page: "status",
      jumpLabel: "查看运行状态",
    });
  if (consoleConnectionFailed)
    notices.push({
      key: "system:console-disconnected",
      kind: "error",
      title: "交付控制连接中断",
      message: "暂时无法连接或确认后台 Web Console。页面暂不能提交交付操作，将自动重试并在恢复后重新读取任务状态。",
      page: "status",
      jumpLabel: "查看运行状态",
    });
  if (!operationsAvailable)
    notices.push({
      key: "system:operations-unavailable",
      kind: "error",
      title: "交付记录读取失败",
      message: "交付操作记录暂时无法读取；恢复连接后可继续操作。",
    });
  if (consoleAvailable === true && consoleDeliveryReady === false)
    notices.push({
      key: "system:delivery-not-ready",
      kind: "warning",
      title: "交付运行时尚未就绪",
      message: "请先完成设置并应用配置，再创建或继续需求。",
      page: "settings",
      jumpLabel: "前往设置",
    });
  if (snapshot && consoleTeamId && snapshot.team_id !== consoleTeamId)
    notices.push({
      key: "system:team-mismatch",
      kind: "error",
      title: "Team 绑定不一致",
      message: "当前后台服务未绑定这个 Team；此工作台暂时只能查看，不能提交交付操作。",
      page: "status",
      jumpLabel: "查看运行状态",
    });
  return notices;
}
function renderNotification() {
  const opener = document.activeElement;
  buildNotification();
  rememberModalOpener(document.getElementById("notification"), opener);
  syncModalState();
}
function buildNotification() {
  const panel = document.getElementById("notification");
  const notice = operationNotice ||
    (administrationNotice?.page === page
      ? {
          kind: /失败|无法|错误/.test(administrationNotice.text) ? "error" : "info",
          title: /失败|无法|错误/.test(administrationNotice.text)
            ? "操作失败"
            : "操作提示",
          message: administrationNotice.text,
          administration: true,
        }
      : null);
  const navigationBlocked = Boolean(notice?.jumpLabel && hasOpenComposer());
  const signature = notice ? JSON.stringify({ notice, navigationBlocked }) : null;
  panel.hidden = !notice;
  if (signature === renderedNotificationSignature) return;
  // A newly displayed operation/system notice consumes the older management feedback.
  // Otherwise acknowledging it reveals a stale success dialog underneath.
  if (operationNotice) administrationNotice = null;
  const wasOpen = renderedNotificationSignature !== null;
  renderedNotificationSignature = signature;
  panel.replaceChildren();
  panel.className = "";
  if (!notice) {
    if (notificationReturnFocus?.isConnected) notificationReturnFocus.focus();
    notificationReturnFocus = null;
    return;
  }
  if (!wasOpen) notificationReturnFocus = document.activeElement;
  panel.className = "modal-backdrop notification-backdrop";
  const dialog = el("section", undefined, "modal-dialog operation-notice-dialog");
  dialog.setAttribute("role", notice.kind === "error" ? "alertdialog" : "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.setAttribute("aria-label", notice.title);
  const header = el("div", undefined, "settings-result-header");
  header.append(
    el(
      "span",
      notice.kind === "error" ? "!" : notice.kind === "warning" ? "i" : "✓",
      `settings-result-icon ${notice.kind === "error" ? "error" : notice.kind === "warning" ? "warning" : "success"}`,
    ),
    el("div", notice.title, "section-title"),
  );
  const close = button(
    "知道了",
    () => {
      if (notice.administration) administrationNotice = null;
      else acknowledgeOperationNotice(notice);
      renderNotification();
    },
    notice.jumpLabel && !navigationBlocked ? "" : "primary",
  );
  const actions = el("div", undefined, "modal-actions");
  actions.append(close);
  if (notice.jumpLabel && !navigationBlocked)
    actions.append(
      button(notice.jumpLabel, () => notificationJump(notice), "primary"),
    );
  dialog.append(
    header,
    el("p", notice.message, "settings-result-message"),
  );
  if (navigationBlocked)
    dialog.append(el("p", "当前表单仍在编辑。请先完成或取消编辑，再通过页面导航查看处理。", "muted"));
  dialog.append(actions);
  panel.append(dialog);
  close.focus();
}
async function submitOperation(intent) {
  const ownerProjectId = intent.project_id || null;
  try {
    if (!canControlCurrentTeam())
      throw new Error("交付控制状态暂不可用，请刷新后重试。");
    if (!consoleSupportsOperation(intent.action))
      throw new Error("本次请求未被受理，不是原需求新增的阻塞。" + consoleOperationVersionMismatchMessage);
    if ((intent.purpose === "legacy_workspace_rescue" || intent.confirm_legacy_containment === true) &&
        !consoleSupportsLegacyRescue())
      throw new Error("本次恢复请求未被受理，不是原需求新增的阻塞。" + consoleOperationVersionMismatchMessage);
    if (Object.hasOwn(intent, "confirm_local_execution_stopped") && !consoleSupportsLocalRescue())
      throw new Error("本次本机恢复请求未被受理，不是原需求新增的阻塞。" + consoleOperationVersionMismatchMessage);
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
    // A newly accepted delivery action supersedes any older page-level
    // administration feedback. Do not reveal that stale dialog after the
    // operation notice is acknowledged.
    administrationNotice = null;
    renderOperationStatus();
    renderDetail();
    return payload;
  } catch (error) {
    administrationNotice = null;
    if (ownerProjectId && ownerProjectId !== currentProjectId()) return null;
    operationNotice = {
      kind: "error",
      title: `${label(intent.action)} · 操作未被接受`,
      message: humanizeBlockingText(error instanceof Error ? error.message : "操作未被接受。"),
    };
    renderNotification();
    return null;
  }
}
function renderOperationStatus() {
  const panel = document.getElementById("operations");
  panel.replaceChildren();
  panel.hidden = true;
  const visible = [...operations]
    .filter((operation) => {
      if (operation.intent.project_id && operation.intent.project_id !== currentProjectId()) return false;
      if (
        operation.status === "SUCCEEDED" &&
        !operationNeedsHumanAttention(operation)
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
          candidate.intent.action === operation.intent.action &&
          candidate.intent.project_id === operation.intent.project_id &&
          operationTarget(candidate) === operationTarget(operation) &&
          candidate.updated_at > operation.updated_at,
      );
    })
    .sort((left, right) => right.updated_at.localeCompare(left.updated_at))
    .map(operationNoticeFor)
    .filter(Boolean);
  if (operationsAvailable && operationNotice?.operationId)
    operationNotice = visible.find(
      (notice) => notice.operationId === operationNotice.operationId,
    ) || null;
  const systemNotices = systemOperationNotices();
  const systemNotice = systemNotices[0] || null;
  const systemKeys = [...acknowledgedOperationNoticeKeys].filter((key) =>
    key.startsWith("system:"),
  );
  for (const key of systemKeys) {
    if (!systemNotices.some((notice) => notice.key === key))
      acknowledgedOperationNoticeKeys.delete(key);
  }
  if (systemKeys.length) persistAcknowledgedOperationNotices();
  if (operationNotice?.key?.startsWith("system:")) {
    if (operationNotice.key !== systemNotice?.key) {
      operationNotice = null;
      renderNotification();
    }
  }
  // Reconcile already-visible notices everywhere; introduce system prompts on Requests.
  if (
    page === "requests" &&
    systemNotice &&
    (!operationNotice || operationNotice.state === "ACTIVE") &&
    !acknowledgedOperationNoticeKeys.has(systemNotice.key)
  ) {
    operationNotice = systemNotice;
    renderNotification();
    return;
  }
  if (systemNotice) {
    renderNotification();
    return;
  }
  const actionable = visible.find(
    (notice) =>
      notice.state !== "ACTIVE" &&
      !acknowledgedOperationNoticeKeys.has(notice.key),
  );
  if (operationNotice?.state === "ACTIVE" && actionable) {
    operationNotice = actionable;
    renderNotification();
    return;
  }
  if (!operationNotice && page === "requests") {
    const next = visible.find(
      (notice) => !acknowledgedOperationNoticeKeys.has(notice.key),
    );
    if (next) {
      operationNotice = next;
    }
  }
  renderNotification();
}
function agentWorkGroup(work) {
  return work.kind === "task" ? taskGroup(work.item) : requestGroup(work.item);
}
function agentWorkState(work) {
  if (work.kind === "request") return requestNodeExecution(work.item).state;
  if (taskGroup(work.item) === "blocked") return "blocked";
  const status = taskPresentationStatus(work.item);
  if (["RUNNING", "IMPLEMENTING", "QA", "REVIEW"].includes(status)) return "running";
  return work.item.terminal ? "done" : "paused";
}
function agentMemberStatus(agent) {
  if (!agent.enabled) return ["已停用", "badge"];
  const current = agent.current_stage_delivery_ids.map(agentWorkById).filter(Boolean);
  const states = current.map(agentWorkState);
  if (states.includes("running")) return ["执行中", "badge current"];
  if (states.includes("blocked")) return ["已阻塞", "badge blocked"];
  if (states.includes("paused")) {
    const labels = new Set(current.filter(work => agentWorkState(work) === "paused").map(work =>
      work.kind === "request" ? requestNodeExecution(work.item).label : label(taskPresentationStatus(work.item))));
    return [labels.size === 1 ? [...labels][0] : "待执行", "badge"];
  }
  return agent.assigned_delivery_ids.length ? ["等待当前阶段", "badge"] : ["空闲中", "badge done"];
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
  const agent = snapshot.agents.find(candidate => candidate.id === agentId);
  const historicalRequest = work.kind === "request" && agent?.history_delivery_ids.includes(task.id) &&
    !agent.assigned_delivery_ids.includes(task.id);
  const historicalTask = work.kind === "task" && isHistoricalRequestTask(task);
  if (historicalTask) row.append(el("span", "历史记录", "badge"));
  else if (a) row.append(assignmentBadge(task, a));
  else if (historicalRequest) row.append(el("span", "本轮已完成", "badge done"));
  else if (work.kind === "request") row.append(requestNodeBadge(task));
  else row.append(badge(taskPresentationStatus(task)));
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
    if (agent?.roles.length)
      overview.append(
        el("span", agent.roles.map(label).join(" / "), "work-row-role"),
      );
  }
  overview.append(scope);
  n.append(overview);
  viewBlock(n, `work:${work.kind}:${task.id}`, [work.kind, task.id, request?.title || task.title,
    fullPath, a?.role, snapshot.agents.find(agent => agent.id === agentId)?.roles,
    historicalRequest, historicalTask, work.kind === "request" ? requestNodeExecution(task) : taskPresentationStatus(task), a]);
  return n;
}
function renderTeam(content) {
  const summary = el("section", undefined, "summary team-summary");
  const blockedRequestCount = snapshot.requests.filter(request => requestGroup(request) === "blocked").length;
  const unfinishedTaskCount = snapshot.tasks.filter(task => !task.terminal && !isHistoricalRequestTask(task)).length;
  for (const [count, title] of [
    [snapshot.agents.length, "位团队成员"],
    [
      unfinishedTaskCount,
      "项当前 Project 未结束任务",
    ],
    [
      blockedRequestCount,
      "项当前 Project 待处理需求",
    ],
  ]) {
    const n = el("span", undefined, "summary-card");
    n.append(el("strong", String(count)), document.createTextNode(title));
    summary.append(n);
  }
  viewBlock(summary, "team-summary", [snapshot.agents.length,
    unfinishedTaskCount, blockedRequestCount]);
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
  viewBlock(heading, "team-heading", projectName());
  content.append(heading);
  const workspace = viewGroup(el("div", undefined, "agent-workspace"), "agent-workspace");
  const roster = viewGroup(el("aside", undefined, "agent-roster"), "agent-roster");
  roster.setAttribute("aria-label", "团队成员列表");
  for (const agent of orderedAgents) {
    const queueState = queueStates.get(agent.id);
    const memberStatus = agentMemberStatus(agent);
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
    viewBlock(control, `agent:${agent.id}`, [agent, queueState, memberStatus, selectedAgentId]);
    roster.append(control);
  }
  const agent = orderedAgents.find((item) => item.id === selectedAgentId);
  const board = viewGroup(el("section", undefined, "agent-board"), `agent-board:${agent.id}`);
  const boardHeading = el("div", undefined, "row agent-board-heading");
  boardHeading.append(
    el("div", `${agent.name} · 任务队列`, "section-title"),
    el("span", `并发上限 ${agent.max_parallel_assignments}（配置值）`, "badge"),
  );
  viewBlock(boardHeading, "agent-board-heading", [agent.name, agent.max_parallel_assignments]);
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
      .filter((work) => agentWorkGroup(work) === "blocked" &&
        (work.kind !== "task" || !isHistoricalRequestTask(work.item)) &&
        (work.kind !== "request" || assigned.some(item => item.id === work.id)))
      .map((work) => work.id),
  );
  const queues = [
    [
      "待完成",
      assigned.filter(
        (work) =>
          !blockedIds.has(work.id) &&
          (!currentIds.has(work.id) || agentWorkState(work) !== "running"),
      ),
      "waiting",
    ],
    [
      "进行中",
      assigned.filter(
        (work) =>
          !blockedIds.has(work.id) && currentIds.has(work.id) && agentWorkState(work) === "running",
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
  const columns = viewGroup(el("div", undefined, "agent-queue-board"), "agent-queues");
  for (const [title, tasks, state] of queues) {
    const column = viewGroup(el("section", undefined, `agent-queue ${state}`), `queue:${state}`);
    const columnHeading = el("div", undefined, "agent-queue-heading");
    columnHeading.append(
      el("strong", title),
      el("span", String(tasks.length), "badge"),
    );
    viewBlock(columnHeading, "queue-heading", [title, tasks.length]);
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
    requestNodeBadge(request),
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
  viewBlock(card, `request:${request.id}`, [request.id, request.title, presentation.status,
    deliveryPhase(request), requestNodeExecution(request), isSelected, request.scopes.length, write.length, done]);
  return card;
}
function requestOperation(panel, request, discussionSection) {
  if (!canControlCurrentTeam()) return;
  const appendOperation = (content, normalContinuation = false) => {
    const section = el(
      "section",
      undefined,
      "detail-section request-operation",
    );
    if (!normalContinuation && request.execution?.responsibility !== "product" && request.execution &&
        !productDiscussionStages.has(request.stage) && content.tagName?.toLowerCase() !== "details") {
      const management = engineeringDetails("工程管理", request.id + ":operation");
      management.append(el("p", "由工程授权者处理此操作；产品负责人无需决定技术恢复方式。", "muted"), content);
      section.append(management);
    } else section.append(content);
    panel.append(section);
  };
  const appendDiscussionContent = (content) => {
    if (discussionSection && productDiscussionStages.has(request.stage)) discussionSection.append(content);
    else appendOperation(content);
  };
  const running = activeOperation(request.id);
  const isProductDiscussion = productDiscussionStages.has(request.stage);
  const sourceRevisionDrift = isSourceRevisionDrift(
    latestOperation(request.id),
  );
  const discussionKey = JSON.stringify([
    request.project_id, request.id, request.checkpoint_sha256, request.stage,
    running?.operation_id || null, sourceRevisionDrift, request.stage_budget,
  ]);
  const identity = JSON.stringify([request.project_id, request.id]);
  let discussionFormCache = discussionFormCaches.get(identity);
  if (discussionFormCache && discussionFormCache.key !== discussionKey) {
    discussionFormCache.dispose();
    discussionFormCaches.delete(identity);
    discussionFormCache = null;
  }
  const approvingProduct = running?.intent.action === "PRODUCT_APPROVAL";
  // A terminal browser operation may leave an admitted QA/Reviewer item visible until
  // Manager creates its successor plan. Only a live Console operation suppresses the
  // recovery action; the durable task projection alone must not strand the operator.
  if (running && !isProductDiscussion) return;
  if (!running && designBudgetExhausted(request) && !canRecoverDesign(request) &&
      !latestApproval(request.id, request.checkpoint_sha256)) return;
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
    const box = engineeringDetails("工程管理 · 需求基线需要处理", request.id + ":baseline");
    box.append(
      el("h3", "需求工程基线无法验证"),
      el(
        "p",
        "工程团队需要恢复并核验该需求保留的基线工作区，处理前暂停执行。普通代码更新不要求产品重新创建需求。",
      ),
      el(
        "p",
        "以下重建入口供工程人员在确认原基线无法恢复后使用。旧需求及讨论记录继续保留。",
        "muted",
      ),
      deliveryButton(
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
      deliveryButton(
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
    const failedOperation = latestOperation(request.id);
    const interrupted = request.stage === "PRODUCT_DISCOVERY" && !running;
    if (interrupted) {
      const failure = el("div", undefined, "operation-error product-failure");
      const code = failedOperation?.error_code;
      const guidance = {
        MODEL_AUTHENTICATION_ERROR: "检查该模型服务的登录或凭证；Codex CLI 可在终端执行 codex login。修复后点击“继续需求讨论”。",
        MODEL_QUOTA_EXHAUSTED: "等待额度恢复，或在设置中为 Product 配置有额度的模型并应用配置，然后点击“继续需求讨论”。",
        MODEL_RATE_LIMITED: "模型服务限流，请稍后点击“继续需求讨论”，不要连续重复提交。",
        MODEL_TIMEOUT: "本轮等待模型回复超时；可稍后点击“继续需求讨论”。若反复超时，请检查模型服务连接。",
        MODEL_EXECUTION_LIMIT: "本地执行窗口已触顶。下一次调用会按配置加倍扩容，不超过最长时限；触顶次数耗尽后请检查模型诊断、任务规模与时间配置。",
        MODEL_PROVIDER_UNAVAILABLE: "按详情检查 Codex 可执行文件、文件权限或模型服务连接；修复后点击“继续需求讨论”。",
        MODEL_PROVIDER_ERROR: "按服务返回的详情检查模型名称、访问权限和路由配置；修复并应用配置后点击“继续需求讨论”。",
        MODEL_INVALID_OUTPUT: "模型未返回有效的结构化结果。可恢复本轮回复一次；若重复失败，请附此操作编号排查输出格式。",
        MODEL_POLICY_VIOLATION: "执行违反安全策略；请附此操作编号排查权限问题，不要绕过审批或反复重试。",
        HOST_INTERRUPTED: "服务在本轮回复完成前中断。服务恢复后点击“继续需求讨论”。",
      };
      const legacy = !failedOperation?.error_summary ||
        failedOperation.error_summary === "Manager operation failed; inspect durable delivery facts." ||
        failedOperation.error_summary === "Manager rejected the operation; inspect current delivery facts.";
      failure.append(
        el("strong", "Product 回复未完成"),
        el("p", `失败原因：${humanizeBlockingText(request.coordination?.draft.summary || (legacy ? "旧记录未保存具体失败原因，无法判断是否为额度、登录或服务问题。" : failedOperation.error_summary))}`),
        el("p", `下一步：${humanizeBlockingText(request.coordination ? request.next_action : guidance[code] || (legacy ? "更新并重启服务后，点击“继续需求讨论”恢复本轮回复；若仍失败，页面会展示新的错误详情。" : "请附此操作编号排查具体异常，修复后再继续本轮讨论。"))}`),
        el("p", "已保存的消息和代码基线会保留，无需重新输入或新建需求。", "muted"),
      );
      if (failedOperation?.operation_id)
        failure.append(el("small", `操作编号：${failedOperation.operation_id}${code ? ` · ${code}` : ""}`));
      appendDiscussionContent(failure);
    }
    // Unrelated polling must not replace unsent text, pasted files or an in-flight submit.
    // Reuse only for the exact Requirement checkpoint and execution gate.
    if (discussionFormCache?.key === discussionKey) {
      appendDiscussionContent(discussionFormCache.form);
      return;
    }
    const form = el("form", undefined, "discussion-form");
    const message = el("textarea");
    let discussionTitle = "等待 Product Agent 回复";
    let messagePlaceholder =
      "上一条消息正在处理中，收到 Product Agent 回复后可继续输入。";
    let submitLabel = "继续需求讨论";
    if (interrupted) {
      discussionTitle = "恢复 Product 回复";
      messagePlaceholder = "上一条消息已保存；请按失败说明处理后继续本轮讨论，无需重复输入。";
    }
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
    const replyEnabled = request.stage !== "PRODUCT_DISCOVERY" && !running && !designBudgetExhausted(request);
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
    submit.setAttribute("data-delivery-control", "true");
    submit.type = request.stage === "PRODUCT_DISCOVERY" ? "button" : "submit";
    setDeliveryControlDisabled(submit, Boolean(running));
    const discussionField = el("div", undefined, "field discussion-field");
    discussionField.append(
      el("h3", discussionTitle),
      el(
        "small",
        replyEnabled
          ? "输入文字，或将截图直接粘贴到这里；两者至少提供一项。"
          : running
            ? "Product Agent 正在处理上一条消息，完成后可继续输入。"
            : "处理上方失败原因后，点击“继续需求讨论”恢复上一条消息的回复。",
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
    onFormSubmit(form, async (event) => {
      event.preventDefault();
      if (!replyEnabled) return;
      if (!message.value.trim() && !selectedScreenshots.length) {
        feedback.className = "form-feedback error";
        feedback.textContent = "请填写需求说明或添加至少一张截图。";
        return;
      }
      setDeliveryControlDisabled(submit, true);
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
        if (accepted) {
          message.value = "";
          selectedScreenshots = [];
          renderScreenshots();
        } else setDeliveryControlDisabled(submit, false);
      } catch (error) {
        feedback.className = "form-feedback error";
        feedback.textContent =
          error instanceof Error ? error.message : "截图保存失败。";
        setDeliveryControlDisabled(submit, false);
      }
    });
    discussionFormCaches.set(identity, {
      key: discussionKey, form, dispose: revokeScreenshotPreviews,
      dirty: () => Boolean(message.value.trim() || selectedScreenshots.length),
    });
    appendDiscussionContent(form);
  }
  if (request.design_recheck_available && !activeOperation(request.id)) {
    appendOperation(deliveryButton("重新核对设计", () => confirmMutation(
      "重新核对设计", "保留已批准的产品需求、原问题与全部历史，将代码事实和设计问题交回 Designer 核实。此操作不批准任何行为变更，不重置预算，也不会立即调用模型。",
      "重新核对设计", () => submitOperation({
        action: "RECHECK_DESIGN", project_id: request.project_id,
        delivery_id: request.id, expected_checkpoint_sha256: request.checkpoint_sha256,
      }),
    ), "secondary"));
  }
  if (canResumeUpstreamStage(request)) {
    appendOperation(deliveryButton(request.stage === "PLANNING" ? "继续计划" : "继续设计", () => submitOperation({
      action: "CONTINUE_DELIVERY", project_id: request.project_id, delivery_id: request.id,
      expected_checkpoint_sha256: request.checkpoint_sha256,
    }), "primary"), true);
  } else if (canRetryDesign(request)) {
    const action = deliveryButton(
      request.stage === "PLANNING" ? "重试 Planner" : "重试 Design",
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
  } else if (canRecoverDesign(request)) {
    const action = deliveryButton(
      "恢复设计",
      () =>
        submitOperation({
          action: "RECOVER_DESIGN",
          project_id: request.project_id,
          delivery_id: request.id,
          expected_checkpoint_sha256: request.checkpoint_sha256,
        }),
      "primary",
    );
    appendOperation(action);
  } else if (canContinueDelivery(request)) {
    const action = deliveryButton(
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
    el("h3", "交付结果"),
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
  const top = el("div", undefined, "row request-heading");
  const actions = el("div", undefined, "request-heading-actions");
  actions.append(
    snapshot.selected_project_id
      ? el("span", `${snapshot.requests.length} 个需求`, "badge")
      : el("span", "尚未选择", "badge blocked"),
  );
  if (canControlCurrentTeam() && currentProjectId())
    actions.append(
      deliveryButton(
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
        deliveryButton(
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
  const selectedRequest = selected?.kind === "task"
    ? requestById(taskById(selected.id)?.request_id) : selected ? requestById(selected.id) : null;
  if (selectedRequest) requestFilter = requestGroup(selectedRequest);
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
        selected = null;
        render();
      },
      requestFilter === key ? "selected" : "",
    );
    control.setAttribute("role", "tab");
    control.setAttribute("aria-selected", String(requestFilter === key));
    navigation.append(control);
  }
  content.append(navigation);
  const group = viewGroup(el("section", undefined, "task-group request-list"), "request-list");
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
  if (result.kind === "success") {
    if (settingsSaveResult?.kind === "success")
      settingsSaveResult.message = result.message;
    setTimeout(() => {
      if (configurationApplyResult !== result) return;
      configurationApplyResult = null;
      if (page === "settings") render();
    }, 5000);
  }
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
      await refreshConsoleInfo();
      runtimeStatusSnapshot = null;
      if (page === "status") await loadRuntimeStatus();
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
function knowledgeContext() {
  return JSON.stringify([knowledgeScope, knowledgeMode, currentProjectId()]);
}
async function loadKnowledge() {
  const context = knowledgeContext(), serial = ++knowledgeReadSerial;
  const mode = knowledgeMode, scope = knowledgeScope, projectId = currentProjectId();
  const isCurrent = () => serial === knowledgeReadSerial && context === knowledgeContext();
  if (knowledgeLoadedContext !== context) {
    knowledgeDocuments = []; specDocuments = []; learningProposals = [];
    knowledgeIndexStatus = null;
  }
  knowledgeLoading = true;
  knowledgeError = null;
  const owner = scope === "team" ? "/api/v1/admin/team" : projectId
    ? "/api/v1/admin/projects/" + encodeURIComponent(projectId) : null;
  try {
    let documents = [], index = null;
    if (owner) {
      const resource = mode === "specs" ? "/specs" : mode === "learning" ? "/learnings" : "/knowledge";
      [documents, index] = await Promise.all([
        adminFetch(owner + resource),
        mode === "background" ? adminFetch(owner + "/knowledge/index") : null,
      ]);
    }
    if (!isCurrent()) return false;
    if (mode === "specs") specDocuments = documents;
    else if (mode === "learning") learningProposals = documents;
    else { knowledgeDocuments = documents; knowledgeIndexStatus = index; }
    knowledgeLoadedContext = context;
    return true;
  } catch (error) {
    if (!isCurrent()) return false;
    knowledgeDocuments = []; specDocuments = []; learningProposals = [];
    knowledgeIndexStatus = null;
    knowledgeError = error instanceof Error ? error.message : "知识读取失败，请重试。";
    return true;
  } finally {
    if (isCurrent()) knowledgeLoading = false;
  }
}
function settingsHaveDraft() {
  return settingsDraft && (JSON.stringify(settingsDraft) !== settingsDraftBaseline ||
    Object.keys(runtimeVariablesDraft).length > 0);
}
async function loadAdministration() {
  if (!administrationLoadPromise) administrationLoadPromise = (async () => {
    try {
      const settings = await adminFetch("/api/v1/admin/settings");
      settingsSnapshot = settings;
      if (!settingsHaveDraft()) {
        settingsDraft = structuredClone(settings.config);
        normalizeModelConnectionModes(settingsDraft);
        normalizeAgentModelRoutes(settingsDraft);
        settingsDraftBaseline = JSON.stringify(settingsDraft);
      }
      administrationAvailable = true;
      await refreshConsoleInfo();
      await resumeConfigurationApply();
      let projects;
      try { projects = await adminFetch("/api/v1/admin/projects"); }
      catch { projects = []; }
      administrationProjects = projects;
    } catch {
      administrationAvailable = false;
      // A read outage must never erase unsaved configuration or write-only secrets.
    }
  })();
  const pending = administrationLoadPromise;
  try { await pending; }
  finally {
    if (administrationLoadPromise === pending) administrationLoadPromise = null;
  }
  // Share only Team administration facts. Knowledge reads belong to the current
  // scope, so an old Project request must never hold up a new Project navigation.
  if (page === "knowledge" && administrationAvailable) await loadKnowledge();
}
async function loadRuntimeStatus(signal) {
  try {
    runtimeStatusSnapshot = await adminFetch("/api/v1/admin/status", { signal });
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

  const descriptions = {
    background:
      knowledgeScope === "team"
        ? "跨 Project 共享的团队知识，不作为强制工程规则。"
        : "帮助团队理解当前 Project 的业务与技术背景，不作为强制工程规则。",
    specs: "新需求必须遵守的工程规则；验证方式可在明确后补充。",
    learning: "从开发发现、独立验证和人工澄清中积累，经确认后供后续需求复用。",
  };
  const workspace = viewGroup(el("div", undefined, "knowledge-workspace"), `knowledge:${knowledgeContext()}`);
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
        const loading = loadKnowledge();
        render();
        if (await loading) render({ preserveComposer: hasOpenComposer() });
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
  viewBlock(ownership, "knowledge-navigation", [knowledgeScope, knowledgeMode,
    currentProjectId(), snapshot.projects]);
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

  const body = viewGroup(el("section", undefined, "knowledge-main"), `knowledge-main:${knowledgeMode}`);
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
        const loading = loadKnowledge();
        render();
        if (await loading) render({ preserveComposer: hasOpenComposer() });
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
  viewBlock(navigation, "knowledge-content-navigation", [knowledgeScope, knowledgeMode]);
  body.append(navigation);
  workspace.append(ownership, body);
  content.append(workspace);
  if (knowledgeLoading || knowledgeError) {
    body.append(el("p", knowledgeLoading ? "正在读取当前知识库…" : knowledgeError,
      knowledgeLoading ? "muted" : "operation-error"));
    if (knowledgeError) body.append(button("重试读取", async () => {
      const loading = loadKnowledge();
      render();
      if (await loading) render({ preserveComposer: hasOpenComposer() });
    }));
    return;
  }
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
  const ownerContext = knowledgeContext();
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
    if (ownerContext !== knowledgeContext() || page !== "knowledge") return;
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
  onFormSubmit(form, async (event) => {
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
      const ownerContext = knowledgeContext();
      row.append(button("重试索引", async () => {
        const scope = knowledgeScope, projectId = currentProjectId();
        const base = scope === "team" ? "/api/v1/admin/team/knowledge" : "/api/v1/admin/projects/" + encodeURIComponent(projectId) + "/knowledge";
        try {
          await adminFetch(base + "/index/" + encodeURIComponent(job.job_id) + "/retry", {method: "POST"});
          if (ownerContext !== knowledgeContext() || page !== "knowledge") return;
          await loadKnowledge();
          if (ownerContext !== knowledgeContext()) return;
          render({ preserveComposer: hasOpenComposer() });
        } catch (error) {
          if (ownerContext !== knowledgeContext() || page !== "knowledge") return;
          administrationNotice = {page: "knowledge", text: error instanceof Error ? error.message : "索引重试失败。"};
          render({ preserveComposer: hasOpenComposer() });
        }
      }));
    }
    panel.append(row);
  }
  content.append(panel);
}

function renderBackgroundKnowledge(content) {
  const scope = knowledgeScope, projectId = currentProjectId(), context = knowledgeContext();
  const documents = knowledgeDocuments;
  const stillCurrent = () => page === "knowledge" && context === knowledgeContext();

  if (scope === "project" && !projectId) {
    content.append(el("div", "请先在页面顶部选择一个 Project。", "empty"));
    return;
  }

  const project = snapshot.projects.find(
    (item) => item.id === projectId,
  );
  const ownerName =
    scope === "team"
      ? snapshot.team_name
      : project?.name || projectId;
  const knowledgeLabel = knowledgeLabelForScope(scope);
  const top = el("div", undefined, "row request-heading");
  const actions = el("div", undefined, "row knowledge-heading-actions");
  actions.append(
    el("span", `${documents.length} 份`, "badge"),
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
      `${ownerName} · ${scope === "team" ? "团队通用知识" : "Project 知识"}`,
    ),
    actions,
  );
  content.append(top);
  renderKnowledgeIndex(content);
  content.append(
    el(
      "p",
      scope === "team"
        ? "启用后用于所有 Project 的新需求。"
        : "启用后只用于当前 Project 的新需求，不影响其他 Project。",
      "muted",
    ),
  );
  if (!documents.length) {
    content.append(
      el(
        "div",
        scope === "team"
          ? "尚未导入团队通用知识文档。"
          : "当前 Project 尚未导入知识文档。",
        "empty",
      ),
    );
    return;
  }
  for (const item of documents) {
    const manifest = item.manifest;
    const card = viewBlock(el("article", undefined, "knowledge-card"), `knowledge:${manifest.document_id}`,
      [item, context, documents.map(value => [value.manifest.document_id, value.selected])]);
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
      const documentIds = documents
        .filter(
          (candidate) =>
            candidate.manifest.document_id !== manifest.document_id &&
            candidate.selected,
        )
        .map((candidate) => candidate.manifest.document_id);
      if (!item.selected) documentIds.push(manifest.document_id);
      const endpoint =
        scope === "team"
          ? "/api/v1/admin/team/knowledge/selection"
          : "/api/v1/admin/projects/" +
            encodeURIComponent(projectId) +
            "/knowledge/selection";
      try {
        await adminFetch(endpoint, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ document_ids: documentIds }),
        });
        if (!stillCurrent()) return;
        if (!await loadKnowledge() || !stillCurrent()) return;
        administrationNotice = {
          page: "knowledge",
          text: "知识选择已生效，无需重启；已存在需求不会被静默改写。",
        };
        render({ preserveComposer: hasOpenComposer() });
      } catch (error) {
        if (!stillCurrent()) return;
        if (!await loadKnowledge() || !stillCurrent()) return;
        administrationNotice = {
          page: "knowledge",
          text: error instanceof Error ? error.message : "知识选择保存失败。",
        };
        render({ preserveComposer: hasOpenComposer() });
      }
    });
    const actions = el("div", undefined, "knowledge-card-actions");
    const update = button("更新文档", async () => {
      update.disabled = true;
      const endpoint =
        scope === "team"
          ? "/api/v1/admin/team/knowledge/" +
            encodeURIComponent(manifest.document_id) +
            "/content"
          : "/api/v1/admin/projects/" +
            encodeURIComponent(projectId) +
            "/knowledge/" +
            encodeURIComponent(manifest.document_id) +
            "/content";
      try {
        const serial = knowledgeReadSerial;
        const editing = await adminFetch(endpoint);
        if (!stillCurrent() || serial !== knowledgeReadSerial || hasOpenComposer()) return;
        editingKnowledgeDocument = editing;
        renderComposer();
      } catch (error) {
        if (!stillCurrent()) return;
        if (!await loadKnowledge() || !stillCurrent()) return;
        administrationNotice = {
          page: "knowledge",
          text: error instanceof Error ? error.message : "无法读取文档正文。",
        };
        render({ preserveComposer: hasOpenComposer() });
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
              scope === "team"
                ? "/api/v1/admin/team/knowledge"
                : "/api/v1/admin/projects/" +
                  encodeURIComponent(projectId) +
                  "/knowledge";
            await adminFetch(
              base + "/" + encodeURIComponent(manifest.document_id),
              { method: "DELETE" },
            );
            if (!stillCurrent()) return;
            if (!await loadKnowledge() || !stillCurrent()) return;
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
  onFormSubmit(form, async (event) => {
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
  const scope = knowledgeScope, projectId = currentProjectId(), context = knowledgeContext();
  const documents = specDocuments;
  const stillCurrent = () => page === "knowledge" && context === knowledgeContext();

  if (scope === "project" && !projectId) {
    content.append(el("div", "请先在页面顶部选择一个 Project。", "empty"));
    return;
  }
  const project = snapshot.projects.find(
    (item) => item.id === projectId,
  );
  const ownerName =
    scope === "team"
      ? snapshot.team_name
      : project?.name || projectId;
  const logicalSpecs = latestSpecs(documents);
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
    const activeVersion = documents.find(
      (candidate) =>
        candidate.active && candidate.document.spec_key === spec.spec_key,
    );
    const isCurrent = item.active;
    const card = viewGroup(el("article", undefined, "knowledge-card spec-card"), `spec:${spec.spec_id}`);
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
    const detail = viewBlock(el("details"), `spec-body:${spec.spec_id}`, spec);
    detail.dataset.key = `spec:${scope}:${projectId}:${spec.spec_id}`;
    detail.append(el("summary", "查看规范正文"), el("pre", spec.body_markdown));
    card.append(detail);
    const actions = el("div", undefined, "knowledge-card-actions");
    const update = button("更新规范", () => {
      editingSpecDocument = {
        scope,
        project_id: scope === "project" ? projectId : null,
        document: structuredClone(spec),
      };
      renderComposer();
    });
    const toggle = button(
      isCurrent ? "停用" : activeVersion ? "启用更新" : "启用规范",
      async () => {
        toggle.disabled = true;
        const ids = documents
          .filter(
            (candidate) =>
              candidate.active && candidate.document.spec_key !== spec.spec_key,
          )
          .map((candidate) => candidate.document.spec_id);
        if (!isCurrent) ids.push(spec.spec_id);
        const endpoint =
          scope === "team"
            ? "/api/v1/admin/team/specs/activation"
            : "/api/v1/admin/projects/" +
              encodeURIComponent(projectId) +
              "/specs/activation";
        try {
          await adminFetch(endpoint, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ spec_ids: ids }),
          });
          if (!stillCurrent()) return;
          if (!await loadKnowledge() || !stillCurrent()) return;
          administrationNotice = {
            page: "knowledge",
            text: "Spec 激活状态已更新；只影响之后重新准备的新需求，无需重启服务。",
          };
        } catch (error) {
          if (!stillCurrent()) return;
          if (!await loadKnowledge() || !stillCurrent()) return;
          administrationNotice = {
            page: "knowledge",
            text: error instanceof Error ? error.message : "Spec 激活失败。",
          };
        }
        render({ preserveComposer: hasOpenComposer() });
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
              scope === "team"
                ? "/api/v1/admin/team/specs"
                : "/api/v1/admin/projects/" +
                  encodeURIComponent(projectId) +
                  "/specs";
            await adminFetch(
              base + "/" + encodeURIComponent(spec.spec_key),
              { method: "DELETE" },
            );
            if (!stillCurrent()) return;
            if (!await loadKnowledge() || !stillCurrent()) return;
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
      "收集项目发现与失败经验",
      async () => {
        const ownerProjectId = currentProjectId();
        try {
          const proposals = await adminFetch(
            "/api/v1/admin/projects/" +
              encodeURIComponent(ownerProjectId) +
              "/learnings/collect",
            { method: "POST" },
          );
          if (ownerProjectId !== currentProjectId() || page !== "knowledge") return;
          learningProposals = proposals;
          administrationNotice = {
            page: "knowledge",
            text: "扫描完成。学习建议仍需人工逐条批准，不会自动改变知识或规范。",
          };
        } catch (error) {
          if (ownerProjectId !== currentProjectId() || page !== "knowledge") return;
          administrationNotice = {
            page: "knowledge",
            text: error instanceof Error ? error.message : "学习建议扫描失败。",
          };
        }
        render({ preserveComposer: hasOpenComposer() });
      },
      "primary",
    ),
  );
  content.append(
    top,
    el(
      "p",
      "建议来自有证据的角色报告或人工确认。保存为背景知识后供后续需求检索，已冻结的需求不变；历史知识不能代替本次独立验收。Skill 设计稿不会自动安装或扩权。",
      "muted",
    ),
  );
  if (!learningProposals.length) {
    content.append(el("div", "尚无学习建议，可收集角色报告中的项目发现与失败经验。", "empty"));
    return;
  }
  for (const view of learningProposals) {
    const proposal = view.proposal;
    const card = viewBlock(el("article", undefined, "knowledge-card learning-card"),
      `learning:${proposal.proposal_id}`, [view, currentProjectId()]);
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
        `重复出现 ${proposal.occurrence_count} 次 · 来源 ${learningTriggerLabel(proposal.trigger)}`,
        "muted",
      ),
      el("p", `验证 · ${proposal.verification}`, "muted"),
    );
    card.append(el("p", `作用域 · 当前 Project ${proposal.project_id}`, "muted"));
    for (const evidence of proposal.evidence) {
      card.append(
        el(
          "p",
          evidence.resolution_id
            ? `需求 ${evidence.requirement_id} / 知识缺口 ${evidence.gap_id} / 确认 ${evidence.resolution_id}`
            : `${evidence.repository_id} / ${evidence.task_id} / ${evidence.artifact_id}`,
          "paths",
        ),
      );
      if (evidence.observation_id) {
        card.append(
          el("p", `发现 ${evidence.observation_id} · ${label(evidence.role)} · 候选 ${evidence.source_revision}`, "paths"),
          el("p", `适用范围 · ${evidence.applicability}`, "muted"),
        );
      }
      if (evidence.artifact_sha256)
        card.append(el("p", `来源摘要 · ${evidence.artifact_sha256}`, "paths"));
      for (const uri of evidence.evidence_uris || [])
        card.append(el("p", uri, "paths"));
    }
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
            ["KNOWLEDGE", "保存为背景知识"],
            ["SPEC", "批准为 Project Spec"],
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

function learningTriggerLabel(trigger) {
  return {
    QA_FAILURE: "QA 失败经验",
    REVIEW_REJECTION: "Review 驳回经验",
    KNOWLEDGE_RESOLUTION: "人工确认的知识",
    PROJECT_OBSERVATION: "开发中的项目发现",
  }[trigger] || label(trigger);
}

async function decideLearning(proposal, action, target) {
  const ownerProjectId = currentProjectId();
  const ownerContext = knowledgeContext();
  try {
    const endpoint =
      "/api/v1/admin/projects/" +
      encodeURIComponent(ownerProjectId) +
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
            ? "已在 Web Console 中核对来源证据并批准。"
            : "已在 Web Console 中核对来源证据并拒绝。",
      }),
    });
    if (ownerContext !== knowledgeContext() || page !== "knowledge") return;
    if (!await loadKnowledge() || ownerContext !== knowledgeContext() || page !== "knowledge") return;
    administrationNotice = {
      page: "knowledge",
      text:
        action === "APPROVE"
          ? "学习建议已批准并发布；只影响未来重新准备的需求。"
          : "学习建议已拒绝并保留审计记录。",
    };
  } catch (error) {
    if (ownerContext !== knowledgeContext() || page !== "knowledge") return;
    administrationNotice = {
      page: "knowledge",
      text: error instanceof Error ? error.message : "学习建议决策失败。",
    };
  }
  render({ preserveComposer: hasOpenComposer() });
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
    selected?.[2] || selected?.[1] || "暂无可用选项",
    "single-select-value",
  );
  const summary = el("summary", undefined, "single-select-trigger");
  summary.append(selectedLabel, el("span", "", "single-select-chevron"));
  const menu = el("div", undefined, "single-select-menu");
  menu.setAttribute("role", "listbox");
  control.addEventListener("toggle", () => {
    if (!control.open) return;
    control.classList.remove("opens-up");
    menu.style.maxHeight = "";
    const trigger = summary.getBoundingClientRect();
    const panel = control.closest(".settings-panel");
    const panelBounds = panel?.getBoundingClientRect();
    const footer = panel?.querySelector(".settings-save-bar");
    const lowerEdge = Math.min(
      window.innerHeight,
      panelBounds?.bottom ?? window.innerHeight,
      footer?.getBoundingClientRect().top ?? window.innerHeight,
    );
    const below = lowerEdge - trigger.bottom - 7;
    const above = trigger.top - Math.max(0, panelBounds?.top ?? 0) - 7;
    const opensUp = below < menu.getBoundingClientRect().height && above > below;
    control.classList.toggle("opens-up", opensUp);
    menu.style.maxHeight = `${Math.max(0, Math.min(240, (opensUp ? above : below) - 8))}px`;
  });
  const optionNodes = [];
  for (const [value, title, compactTitle] of values) {
    const option = button(
      title,
      () => {
        if (disabled) return;
        control.dataset.value = value;
        selectedLabel.textContent = compactTitle || title;
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
function effectiveModelConnectionMode(route, config = settingsDraft) {
  if ((route.route_kind || route.kind) !== "codex_cli") return null;
  return route.connection_mode || (config?.codex_cli_proxy_base_url ? "proxy" : "direct");
}
function modelRouteLabel(route, config = settingsDraft) {
  const kind = route.route_kind || route.kind;
  return kind === "codex_cli"
    ? `Codex CLI · ${effectiveModelConnectionMode(route, config) === "proxy" ? "CLIProxyAPI" : "普通 CLI"}`
    : "Responses API";
}
function recordedModelConnectionLabel(route) {
  if ((route.route_kind || route.kind) === "responses") return "Responses API";
  if (route.connection_mode === "proxy") return "CLIProxyAPI";
  if (route.connection_mode === "direct") return "普通 CLI";
  return "连接方式未记录";
}
function modelRouteKey(route, config = settingsDraft) {
  return JSON.stringify([
    route.provider,
    route.model,
    route.reasoning_effort || "medium",
    route.route_kind || route.kind || "",
    effectiveModelConnectionMode(route, config),
  ]);
}
function modelRouteValidationMessage(config) {
  if (config.codex_cli_proxy_api_key_env && !config.codex_cli_proxy_base_url)
    return "请先填写 Codex CLI 本地代理地址，再配置代理 API Key。";
  const firstRouteByKey = new Map();
  for (const [index, route] of (config.model_routes || []).entries()) {
    const provider = route.provider.trim();
    const model = route.model.trim();
    if (!provider || !model)
      return `第 ${index + 1} 条模型路由必须填写 Provider 和 Model。`;
    const reasoning = route.reasoning_effort || "medium";
    if (route.kind === "codex_cli" && effectiveModelConnectionMode(route, config) === "proxy" && !config.codex_cli_proxy_base_url)
      return `第 ${index + 1} 条路由使用 CLIProxyAPI，请先配置本地代理地址。`;
    if (route.kind === "responses" && route.connection_mode)
      return `第 ${index + 1} 条 Responses 路由不能设置 Codex CLI 连接方式。`;
    const key = modelRouteKey({ ...route, provider, model, reasoning_effort: reasoning }, config);
    const firstIndex = firstRouteByKey.get(key);
    if (firstIndex !== undefined)
      return `第 ${index + 1} 条模型路由（${provider} / ${model} · ${reasoning} · ${modelRouteLabel(route, config)}）与第 ${firstIndex + 1} 条重复。请修改已有路由或删除重复项。`;
    firstRouteByKey.set(key, index);
  }
  return null;
}
function normalizeModelConnectionModes(config) {
  for (const route of config.model_routes || []) {
    if (route.kind === "codex_cli")
      route.connection_mode = effectiveModelConnectionMode(route, config);
  }
}
function modelRouteReference(route) {
  return {
    provider: route.provider,
    model: route.model,
    reasoning_effort: route.reasoning_effort || "medium",
    route_kind: route.kind,
    connection_mode: effectiveModelConnectionMode(route),
  };
}
function resolveModelRouteReference(reference, enabled) {
  const matches = enabled.filter(
    (route) =>
      route.provider === reference.provider &&
      route.model === reference.model &&
      (!reference.reasoning_effort || route.reasoning_effort === reference.reasoning_effort) &&
      (!reference.route_kind || route.kind === reference.route_kind) &&
      (!reference.connection_mode || effectiveModelConnectionMode(route) === reference.connection_mode),
  );
  return matches.length === 1 ? matches[0] : undefined;
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
  const unambiguous = settingsDraft.model_routes.filter(
    (candidate) => modelRouteKey(candidate) === previous,
  ).length === 1;
  const priorKind = route.kind;
  route[property] = value;
  if (property === "kind")
    route.connection_mode = value === "codex_cli"
      ? (priorKind === "codex_cli" ? effectiveModelConnectionMode(route) : "direct")
      : null;
  if (!unambiguous) return;
  for (const policy of settingsDraft.agent_model_routes || []) {
    for (const reference of policy.routes || []) {
      if (modelRouteKey(reference) !== previous) continue;
      reference.provider = route.provider;
      reference.model = route.model;
      reference.reasoning_effort = route.reasoning_effort || "medium";
      reference.route_kind = route.kind;
      reference.connection_mode = effectiveModelConnectionMode(route);
    }
  }
}
let settingsHelpSequence = 0;
function settingsHelp(labelText, explanation) {
  const wrapper = el("span", undefined, "settings-help");
  const trigger = el("button", "i", "settings-help-trigger");
  trigger.type = "button";
  trigger.setAttribute("aria-label", `${labelText}说明`);
  trigger.setAttribute("aria-expanded", "false");
  trigger.setAttribute("aria-haspopup", "dialog");
  const panel = el("span", undefined, "settings-help-panel");
  panel.id = `settings-help-${++settingsHelpSequence}`;
  panel.setAttribute("popover", "auto");
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-label", `${labelText}说明`);
  trigger.setAttribute("aria-controls", panel.id);
  panel.append(el("span", explanation, "settings-help-text"));
  const close = button("关闭", (event) => {
    event?.preventDefault?.();
    event?.stopPropagation?.();
    panel.hidePopover();
    trigger.focus();
  }, "settings-help-close");
  close.type = "button";
  panel.append(close);
  trigger.addEventListener("click", (event) => {
    event?.preventDefault?.();
    event?.stopPropagation?.();
    if (panel.matches(":popover-open")) {
      panel.hidePopover();
      return;
    }
    panel.showPopover();
    const anchor = trigger.getBoundingClientRect();
    const width = panel.getBoundingClientRect().width;
    const height = panel.getBoundingClientRect().height;
    panel.style.left = `${Math.max(12, Math.min(anchor.right - width, window.innerWidth - width - 12))}px`;
    panel.style.top = `${anchor.bottom + height + 12 <= window.innerHeight
      ? anchor.bottom + 8
      : Math.max(12, anchor.top - height - 8)}px`;
  });
  panel.addEventListener("beforetoggle", (event) => {
    trigger.setAttribute("aria-expanded", String(event.newState === "open"));
  });
  wrapper.append(trigger, panel);
  return wrapper;
}
function settingsField(labelText, control, hint, extra = null) {
  const row = el("div", undefined, "settings-field-row");
  const copy = el("div", undefined, "settings-field-copy");
  copy.append(el("strong", labelText));
  if (hint) copy.append(settingsHelp(labelText, hint));
  const value = el("div", undefined, "settings-field-control");
  control.setAttribute("aria-label", labelText);
  value.append(control);
  if (extra) value.append(extra);
  row.append(copy, value);
  return row;
}
function settingsRouteField(labelText, control, hint) {
  const wrapper = el("div", undefined, "field settings-route-field");
  const heading = el("div", undefined, "settings-route-field-heading");
  heading.append(el("strong", labelText));
  if (hint) heading.append(settingsHelp(labelText, hint));
  control.setAttribute("aria-label", labelText);
  wrapper.append(heading, control);
  return wrapper;
}
function settingsCheckbox(control, text) {
  const wrapper = el("label", undefined, "settings-checkbox-control");
  wrapper.append(control, el("span", text));
  return wrapper;
}
function settingsModule(title, description, children, action = null) {
  const section = el("section", undefined, "settings-section");
  const header = el("div", undefined, "settings-section-header");
  header.append(el("h3", title, "settings-section-title"));
  const tools = el("div", undefined, "settings-section-tools");
  if (description) tools.append(settingsHelp(title, description));
  if (action) tools.append(action);
  header.append(tools);
  section.append(header, ...children);
  return section;
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
          return refresh(project.id);
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
    deliveryButton(
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
  if (settingsSnapshot.settings_contract_version !== settingsContractVersion)
    content.append(el(
      "div",
      settingsVersionMismatchMessage,
      "admin-notice operation-error",
    ));
  if (consoleDeliveryReady === false)
    content.append(
      el(
        "div",
        "当前交付运行时尚未就绪；请检查下方配置和运行依赖。",
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
  } else if (
    !settingsSnapshot.restart_required && configurationApplyResult?.kind === "success"
  ) {
    const notice = el("div", undefined, "admin-notice");
    notice.setAttribute("role", "status");
    notice.append(
      el("span", configurationApplyResult.message),
      button("关闭配置提示", () => {
        configurationApplyResult = null;
        render();
      }),
    );
    content.append(notice);
  }
  if (configurationApplyResult?.kind === "error")
    content.append(el("div", configurationApplyResult.message, "operation-error"));

  const workspace = viewGroup(el("div", undefined, "settings-workspace"), "settings-workspace");
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

  const panel = viewGroup(el("section", undefined, "admin-panel settings-panel"), "settings-panel");
  const pageHeader = el("div", undefined, "settings-page-header");
  const top = el("div", undefined, "settings-page-title-row");
  const [title, description] =
    settingsSection === "general"
      ? ["基础配置", "管理平台身份、运行环境以及各角色的执行与临时故障额度。"]
      : settingsSection === "database"
        ? ["MySQL 数据库", "配置任务、运行事实与队列使用的数据库连接。"]
        : ["模型路由", "先维护可用模型目录，再为每个 Agent 选择主模型和备用顺序。"];
  const titleCopy = el("div");
  titleCopy.append(
    el("h2", title),
    settingsHelp(title, description),
  );
  top.append(
    titleCopy,
    settingsSnapshot.config_source === "default"
      ? el("span", "正在使用内置默认配置", "badge")
      : settingsSnapshot.restart_required
        ? el("span", "已保存 · 需要重启", "badge blocked")
        : el("span", "当前配置已生效", "badge done"),
  );
  const metadata = el("div", undefined, "settings-metadata");
  metadata.append(
    el("span", "配置文件"),
    el("code", settingsSnapshot.config_path),
  );
  pageHeader.append(top, metadata);
  panel.append(pageHeader);
  const form = el("form", undefined, "settings-form");
  if (settingsSection === "general") renderGeneralSettings(form);
  else if (settingsSection === "database") renderDatabaseSettings(form);
  else renderModelSettings(form);

  const feedback = el("p", "", "form-feedback");
  const save = el("button", "保存设置", "primary");
  save.type = "submit";
  const saveBar = el("div", undefined, "settings-save-bar");
  saveBar.append(
    el("span", "运行配置有变更时，保存后按提示应用；知识选择即时生效。", "muted"),
    feedback,
    save,
  );
  form.append(saveBar);
  onFormSubmit(form, async (event) => {
    event.preventDefault();
    if (settingsSnapshot.settings_contract_version !== settingsContractVersion) {
      settingsSaveResult = { kind: "error", message: settingsVersionMismatchMessage };
      renderComposer();
      return;
    }
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
                settingsDraft.codex_cli_proxy_api_key_env,
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
      normalizeModelConnectionModes(settingsDraft);
      normalizeAgentModelRoutes(settingsDraft);
      settingsDraftBaseline = JSON.stringify(settingsDraft);
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
  viewBlock(form, "settings-form", [settingsDraftBaseline, settingsSection,
    settingsSnapshot.settings_contract_version]);
  workspace.append(navigation, panel);
  content.append(workspace);
}

function renderGeneralSettings(form) {
  const general = el("div", undefined, "settings-field-list");
  const runtime = el("div", undefined, "settings-field-list");
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
    settingsField(
      "平台数据目录",
      platformRoot,
      "必须是绝对路径；Team、Projects、worktrees 与 quarantine 都保存在该目录。",
    ),
    settingsField(
      "唯一 Team",
      team,
      `${settingsDraft.team_id}；Team 是长期团队，不随 Project 切换。`,
    ),
  );
  runtime.append(
    settingsField(
      "Codex 可执行文件",
      codex,
      "本机 Codex CLI 的绝对路径。",
    ),
    settingsField(
      "Web Console 端口",
      port,
      "重启后使用新地址访问。",
    ),
    settingsField(
      "允许调用真实模型",
      settingsCheckbox(live, "允许 Agent 发起真实模型请求"),
      "全局安全开关；关闭后拒绝所有模型任务。修改后需要重启。",
    ),
  );
  form.append(
    settingsModule(
      "平台身份",
      "平台数据和长期 Team 的固定归属。",
      [general],
    ),
    settingsModule(
      "运行环境",
      "修改后需要按页面提示重启 Team Host。",
      [runtime],
    ),
  );
  if (settingsDraft.execution_retry_policy) {
    const policy = settingsDraft.execution_retry_policy;
    policy.manager ??= {max_attempts: 2, max_transient_failures: 5, max_coordination_rounds: 3};
    policy.execution_time ??= Object.fromEntries(
      ["manager", "product", "designer", "planner"].map(role =>
        [role, {initial_seconds: 600, max_seconds: 2400, max_capacity_timeouts: 3}]),
    );
    const budgets = el("div", undefined, "retry-policy-table");
    const tableHead = el("div", undefined, "retry-policy-row retry-policy-head");
    tableHead.append(
      el("span", "角色"),
      el("span", "工作次数"),
      el("span", "临时故障"),
      el("span", "规则"),
    );
    budgets.append(tableHead);
    for (const [role, title, subtitle, workTitle] of [
      ["manager", "Manager", "阻塞诊断与协调", "方案 / 修正尝试上限"],
      ["product", "Product", "需求讨论", "讨论 / 产物尝试上限"],
      ["designer", "Designer", "技术设计", "设计尝试上限"],
      ["planner", "Planner", "执行计划", "计划尝试上限"],
      ["coder", "Coder", "实现与修正", "实现轮次上限"],
      ["qa", "QA", "质量验证", null],
      ["reviewer", "Reviewer", "代码审查", null],
    ]) {
      const row = el("div", undefined, "retry-policy-row");
      const roleCopy = el("span", undefined, "retry-policy-role");
      roleCopy.append(el("strong", title), el("small", subtitle));
      const work = workTitle
        ? bindInput(
            el("input"),
            String(policy[role].max_attempts),
            (value) => (policy[role].max_attempts = Number(value)),
            "number",
          )
        : el("span", "—", "retry-policy-empty");
      if (workTitle) {
        work.min = "1";
        work.max = "100";
        work.step = "1";
        work.required = true;
        work.name = `retry-${role}-max_attempts`;
        work.setAttribute("aria-label", `${title} 工作次数`);
      }
      const transient = bindInput(
        el("input"),
        String(policy[role].max_transient_failures),
        (value) => (policy[role].max_transient_failures = Number(value)),
        "number",
      );
      transient.min = "1";
      transient.max = "100";
      transient.step = "1";
      transient.required = true;
      transient.name = `retry-${role}-max_transient_failures`;
      transient.setAttribute("aria-label", `${title} 临时故障上限`);
      row.append(
        roleCopy,
        work,
        transient,
        el(
          "span",
          workTitle ||
            (role === "qa"
              ? "有效缺陷回到 Coder"
              : "有效驳回回到 Coder"),
          "retry-policy-note",
        ),
      );
      budgets.append(row);
    }
    form.append(
      settingsModule(
        "执行与重试策略",
        "工作次数包含首次执行；服务故障、本地时间触顶和产物修正独立计数。Manager 只在已授权范围内自动协调；修改不会清零历史或跳过审批。",
        [budgets],
      ),
    );
    const windows = el("div", undefined, "retry-policy-table");
    const timeHead = el("div", undefined, "retry-policy-row retry-policy-head");
    for (const title of ["角色", "初始时限 / 秒", "最长时限 / 秒", "触顶次数上限"])
      timeHead.append(el("span", title));
    windows.append(timeHead);
    for (const role of ["manager", "product", "designer", "planner"]) {
      const row = el("div", undefined, "retry-policy-row");
      row.append(el("strong", role[0].toUpperCase() + role.slice(1), "retry-policy-role"));
      for (const [key, title, max] of [["initial_seconds", "初始时限", 86400],
        ["max_seconds", "最长时限", 86400], ["max_capacity_timeouts", "触顶次数上限", 100]]) {
        const input = bindInput(el("input"), String(policy.execution_time[role][key]),
          value => policy.execution_time[role][key] = Number(value), "number");
        input.min = "1"; input.max = String(max); input.step = "1"; input.required = true;
        input.name = `execution-time-${role}-${key}`;
        input.setAttribute("aria-label", `${role} ${title}`);
        row.append(input);
      }
      windows.append(row);
    }
    const rounds = bindInput(el("input"), String(policy.manager.max_coordination_rounds),
      value => policy.manager.max_coordination_rounds = Number(value), "number");
    rounds.min = "1"; rounds.max = "100"; rounds.step = "1"; rounds.required = true;
    rounds.name = "retry-manager-max_coordination_rounds";
    const coordination = settingsField("Manager 协调轮次", rounds,
      "同一需求、同一阶段可诊断的不同阻塞输入数量。刷新、重启或重新点击不会重置；新的执行或修复审批仍由你决定。");
    coordination.classList.add("execution-coordination-row");
    const timeFields = el("div", undefined, "execution-time-fields");
    timeFields.append(windows, coordination);
    form.append(settingsModule("执行时间与协调边界",
      "本地时间触顶后，下一次调用窗口加倍。最长时限不得小于初始时限；触顶次数包含最后一次失败。保存并重启生效，不延长已终止的进程。",
      [timeFields],
    ));
  }
}

function renderDatabaseSettings(form) {
  const dsnName = settingsDraft.database.dsn_env;
  const environmentName = bindInput(el("input"), dsnName, () => {});
  environmentName.disabled = true;
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
  const action = el("div", undefined, "settings-action-row");
  action.append(testConnection, connectionFeedback);
  const connectionFields = el("div", undefined, "settings-field-list");
  connectionFields.append(
    settingsField(
      "启动变量",
      environmentName,
      "服务脚本加载的固定环境变量名。",
    ),
    settingsField(
      "MySQL DSN",
      dsn,
      "留空表示保留已保存值；输入新 DSN 才会替换。",
    ),
    settingsField(
      "连接验证",
      action,
      "使用当前输入值；留空时测试已保存的连接。测试不会回显 DSN。保存运行配置后，按提示重启 Team Host 使新连接生效。",
    ),
  );
  form.append(
    settingsModule(
      "连接配置",
      "凭证只写入本机 runtime.env，页面不会回显已保存的值。",
      [connectionFields],
    ),
  );
}

function renderModelSettings(form) {
  const proxyKeyName = "ASE_CODEX_PROXY_API_KEY";
  const proxy = bindInput(
    el("input"),
    settingsDraft.codex_cli_proxy_base_url || "",
    (value) => {
      settingsDraft.codex_cli_proxy_base_url = value.trim() || null;
      if (!settingsDraft.codex_cli_proxy_base_url) {
        settingsDraft.codex_cli_proxy_api_key_env = null;
        delete runtimeVariablesDraft[proxyKeyName];
      }
    },
  );
  proxy.placeholder = "http://127.0.0.1:8317/v1";
  const proxyKey = bindInput(
    el("input"),
    runtimeVariablesDraft[proxyKeyName] || "",
    (value) => {
      if (value) {
        runtimeVariablesDraft[proxyKeyName] = value;
        settingsDraft.codex_cli_proxy_api_key_env = proxyKeyName;
      } else {
        delete runtimeVariablesDraft[proxyKeyName];
        if (settingsSnapshot.config.codex_cli_proxy_api_key_env !== proxyKeyName)
          settingsDraft.codex_cli_proxy_api_key_env = null;
      }
    },
    "password",
  );
  proxyKey.autocomplete = "new-password";
  proxyKey.placeholder = settingsSnapshot.secret_status.some(
    (item) => item.environment_name === proxyKeyName && item.configured,
  )
    ? "已保存；输入新 Key 可替换"
    : "输入 CLIProxyAPI 的 API Key";
  const proxyFields = el("div", undefined, "settings-field-list");
  proxyFields.append(
    settingsField(
      "Codex CLI 本地代理地址",
      proxy,
      "仅供选择 CLIProxyAPI 的 Codex CLI 路由使用；只支持本机回环 HTTP 地址。",
    ),
    settingsField(
      "代理 API Key",
      proxyKey,
      "留空保留已保存值；页面不会回显。未配置时沿用 Codex CLI 登录。",
    ),
  );
  const proxyChildren = [proxyFields];
  if (settingsDraft.codex_cli_proxy_api_key_env === proxyKeyName) {
    const clearKey = button("清除代理 Key（代理改用 CLI 登录）", () => {
      settingsDraft.codex_cli_proxy_api_key_env = null;
      delete runtimeVariablesDraft[proxyKeyName];
      proxyKey.value = "";
      clearKey.disabled = true;
    });
    clearKey.type = "button";
    const keyAction = el("div", undefined, "settings-action-row");
    keyAction.append(clearKey);
    proxyChildren.push(keyAction);
  }
  const addModelRoute = () => {
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
    expandedModelRouteIndex = settingsDraft.model_routes.length - 1;
    render();
    document.querySelector?.(".model-route-disclosure[open] input[aria-label='Provider']")?.focus();
  };
  const addRoute = button(
    "添加路由",
    addModelRoute,
    "settings-section-action",
  );
  addRoute.disabled = settingsDraft.model_routes.length >= 16;
  const routeList = el("div", undefined, "model-route-list");
  settingsDraft.model_routes.forEach((route, index) => {
    const row = el("details", undefined, "route-card model-route-disclosure");
    row.open = expandedModelRouteIndex === index;
    row.addEventListener("toggle", () => {
      if (row.isConnected === false) return;
      if (row.open) expandedModelRouteIndex = index;
      else if (expandedModelRouteIndex === index) expandedModelRouteIndex = null;
    });
    const summary = el("summary", undefined, "model-route-summary");
    const identity = el("span", undefined, "model-route-identity");
    identity.append(
      el("strong", route.provider || "未命名 Provider"),
      el("small", modelRouteLabel(route)),
    );
    summary.append(
      identity,
      el("span", route.model || "未命名模型", "model-route-model"),
      el("span", route.reasoning_effort || "medium", "model-route-pill"),
      el(
        "span",
        route.image_input === true
          ? "图像输入"
          : route.image_input === false
            ? "仅文本"
            : route.kind === "codex_cli"
              ? "图像输入"
              : "仅文本",
        "model-route-capability",
      ),
      el(
        "span",
        route.enabled ? "已启用" : "已停用",
        `model-route-pill${route.enabled ? " enabled" : ""}`,
      ),
      el("span", "", "model-route-chevron"),
    );
    const detail = el("div", undefined, "model-route-detail");
    const fields = el("div", undefined, "model-route-fields");
    fields.append(
      settingsRouteField(
        "Provider",
        bindInput(el("input"), route.provider, (value) =>
          updateModelRouteIdentity(route, "provider", value),
        ),
      ),
      settingsRouteField(
        "Model",
        bindInput(el("input"), route.model, (value) =>
          updateModelRouteIdentity(route, "model", value),
        ),
      ),
      settingsRouteField(
        "类型",
        selectInput(
          [
            ["codex_cli", "Codex CLI"],
            ["responses", "Responses API"],
          ],
          route.kind,
          (value) => {
            updateModelRouteIdentity(route, "kind", value);
            route.image_input = null;
            if (value === "codex_cli") {
              route.endpoint = null;
              route.api_key_env = null;
            }
            render();
          },
          `model-route-${index}-kind`,
        ),
      ),
      settingsRouteField(
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
    if (route.kind === "codex_cli")
      fields.append(
        settingsRouteField(
          "连接方式",
          selectInput(
            [["direct", "普通 CLI（本机登录）"], ["proxy", "CLIProxyAPI（本地代理）"]],
            effectiveModelConnectionMode(route),
            (value) => {
              updateModelRouteIdentity(route, "connection_mode", value);
              render();
            },
            `model-route-${index}-connection`,
          ),
          "仅当前路由生效；CLIProxyAPI 需要上方代理地址，Key 可选。",
        ),
      );
    if (route.kind === "responses")
      fields.append(
        settingsRouteField(
          "Endpoint",
          bindInput(
            el("input"),
            route.endpoint,
            (value) => (route.endpoint = value),
          ),
        ),
        settingsRouteField(
          "API Key 环境变量名",
          bindInput(
            el("input"),
            route.api_key_env,
            (value) => (route.api_key_env = value),
          ),
        ),
        settingsRouteField(
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
    const imageInput = el("input");
    imageInput.type = "checkbox";
    imageInput.checked = route.image_input === true ||
      (route.image_input == null && route.kind === "codex_cli");
    imageInput.addEventListener(
      "change",
      () => (route.image_input = imageInput.checked),
    );
    fields.append(
      settingsRouteField(
        "支持图片输入",
        imageInput,
        "Codex CLI 默认支持；Responses 服务需确认兼容图片输入格式后开启。",
      ),
    );
    const enabled = el("input");
    enabled.type = "checkbox";
    enabled.checked = route.enabled;
    enabled.addEventListener("change", () => {
      route.enabled = enabled.checked;
      normalizeAgentModelRoutes(settingsDraft);
      render();
    });
    const routeActions = el("div", undefined, "model-route-actions");
    routeActions.append(settingsCheckbox(enabled, "启用此路由"));
    if (settingsDraft.model_routes.length > 1)
      routeActions.append(
        button(
          "移除路由",
          () => {
            settingsDraft.model_routes.splice(index, 1);
            expandedModelRouteIndex = null;
            render();
          },
          "danger",
        ),
      );
    detail.append(fields, routeActions);
    row.append(summary, detail);
    routeList.append(row);
  });
  normalizeAgentModelRoutes(settingsDraft);
  const enabledRoutes = settingsDraft.model_routes.filter(
    (route) => route.enabled,
  );
  const assignments = el("div", undefined, "agent-model-list");
  for (const [role, title, description] of agentModelRoles) {
    const policy = settingsDraft.agent_model_routes.find(
      (candidate) => candidate.role === role,
    );
    const card = el("details", undefined, "agent-model-card");
    card.dataset.role = role;
    card.open = expandedAgentModelRoles.has(role);
    card.addEventListener("toggle", () => {
      if (!card.isConnected) return;
      if (card.open) expandedAgentModelRoles.add(role);
      else expandedAgentModelRoles.delete(role);
    });
    const primary = policy?.routes?.[0];
    const primaryKey = primary ? modelRouteKey(primary) : "";
    const choices = enabledRoutes.map((route) => [
      modelRouteKey(route),
      `${route.provider} / ${route.model} · ${route.reasoning_effort} · ${modelRouteLabel(route)}`,
      route.model,
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
    const fallbackRoutes = policy?.routes?.slice(1) || [];
    const summary = el("summary", undefined, "agent-model-summary");
    const roleCopy = el("span", undefined, "agent-model-role");
    roleCopy.append(el("strong", title), settingsHelp(title, description));
    summary.append(
      roleCopy,
      el(
        "span",
        primary
          ? `${primary.model} · ${primary.reasoning_effort || "medium"} · ${modelRouteLabel(primary)}`
          : "当前未配置主模型",
        "agent-model-primary",
      ),
      el(
        "span",
        `${fallbackRoutes.length} 个备用模型`,
        "agent-model-fallback-count",
      ),
      el("span", "", "agent-model-chevron"),
    );
    const detail = el("div", undefined, "agent-model-detail");
    const primaryMeta = primary
      ? el(
          "span",
          `${primary.provider} · ${primary.reasoning_effort || "medium"} · ${modelRouteLabel(primary)}`,
          "agent-primary-meta",
        )
      : null;
    detail.append(settingsField(
      "主模型",
      selector,
      "该 Agent 每次运行首先尝试的模型。",
      primaryMeta,
    ));
    const fallbacks = el("div", undefined, "agent-fallback-settings");
    const fallbackHeading = el("div", undefined, "agent-fallback-heading");
    const fallbackLabel = el("div", undefined, "agent-setting-heading");
    fallbackLabel.append(
      el("strong", "备用模型"),
      settingsHelp("备用模型", "仅在主模型不可用且符合降级规则时，按下列顺序尝试。"),
    );
    fallbackHeading.append(
      fallbackLabel,
      el("span", `${fallbackRoutes.length} 个`, "agent-fallback-count"),
    );
    fallbacks.append(fallbackHeading);
    if (!fallbackRoutes.length)
      fallbacks.append(
        el(
          "p",
          "尚未添加备用模型。",
          "muted agent-fallback-empty",
        ),
      );
    fallbackRoutes.forEach((route, fallbackOffset) => {
      const index = fallbackOffset + 1;
      const row = el("div", undefined, "agent-fallback-row");
      row.dataset.fallbackIndex = String(index);
      const position = el("span", String(index), "agent-fallback-position");
      position.setAttribute("aria-label", `备用 ${index}`);
      const identity = el("span", undefined, "agent-fallback-identity");
      identity.append(
        el("strong", route.model, "agent-fallback-model"),
        el(
          "small",
          `${route.provider} · ${route.reasoning_effort || "medium"} · ${modelRouteLabel(route)}`,
          "agent-fallback-meta",
        ),
      );
      const actions = el("div", undefined, "agent-fallback-actions");
      const moveUp = button("↑", () => {
        moveAgentFallbackModel(role, index, -1);
        render();
      });
      moveUp.setAttribute("aria-label", `上移备用 ${index}`);
      moveUp.title = "上移";
      moveUp.disabled = index === 1;
      const moveDown = button("↓", () => {
        moveAgentFallbackModel(role, index, 1);
        render();
      });
      moveDown.setAttribute("aria-label", `下移备用 ${index}`);
      moveDown.title = "下移";
      moveDown.disabled = index === policy.routes.length - 1;
      const remove = button("×", () => {
        removeAgentFallbackModel(role, index);
        render();
      });
      remove.setAttribute("aria-label", `移除备用 ${index}`);
      remove.title = "移除";
      actions.append(
        moveUp,
        moveDown,
        remove,
      );
      row.append(position, identity, actions);
      fallbacks.append(row);
    });
    const selectedKeys = new Set(
      (policy?.routes || []).map((route) => modelRouteKey(route)),
    );
    const fallbackChoices = enabledRoutes
      .filter((route) => !selectedKeys.has(modelRouteKey(route)))
      .map((route) => [
        modelRouteKey(route),
        `${route.provider} / ${route.model} · ${route.reasoning_effort} · ${modelRouteLabel(route)}`,
      ]);
    const canAddRoute = settingsDraft.model_routes.length < 16;
    if (fallbackChoices.length || canAddRoute) {
      const addFallback = selectInput(
        [
          ["", "＋ 添加备用模型"],
          ...fallbackChoices,
          ...(canAddRoute ? [["__new_route__", "＋ 新增可用模型路由"]] : []),
        ],
        "",
        (value) => {
          if (!value) return;
          if (value === "__new_route__") {
            addModelRoute();
            return;
          }
          addAgentFallbackModel(role, value);
          render();
        },
        `agent-fallback-model-${role}`,
      );
      addFallback.className += " agent-fallback-add";
      fallbacks.append(addFallback);
    }
    if (!fallbackChoices.length)
      fallbacks.append(el(
        "p",
        canAddRoute
          ? "已分配全部启用路由；可以新增路由、完成配置并启用后，再选为备用模型。"
          : "已分配全部启用路由，且模型目录已达 16 条上限。",
        "muted agent-fallback-catalog-note",
      ));
    detail.append(fallbacks);
    card.append(summary, detail);
    assignments.append(card);
  }
  form.append(
    settingsModule(
      "Codex CLI 连接",
      "仅选择 CLIProxyAPI 的路由使用此共享代理；普通 CLI 使用本机 Codex 登录。保存后需应用配置。",
      proxyChildren,
    ),
    settingsModule(
      "可用模型目录",
      "启用只表示可选，不会自动加入任何 Agent 的备用模型。",
      [routeList],
      addRoute,
    ),
    settingsModule(
      "Agent 模型分配",
      "每个 Agent 使用一个主模型；备用模型按顺序在必要时尝试。",
      [assignments],
    ),
  );
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
  return viewBlock(row, `status:${title}`, [title, value, ready]);
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
          `${route.provider} / ${route.model} · ${route.reasoning_effort} · ${recordedModelConnectionLabel(route)}`,
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
    !value.restart_required &&
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
        : value.restart_required
          ? "配置已保存但尚未加载到当前进程，请重启 Web Console。"
          : "请根据下方状态处理尚未就绪的运行依赖。",
      "muted",
    ),
  );
  viewBlock(summary, "status-summary", [ready, value.restart_required]);
  const overview = el("section", undefined, "admin-panel");
  viewGroup(overview, "status-configuration");
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
  viewGroup(runtime, "status-runtime");
  runtime.append(
    el("h2", "运行依赖"),
    statusRow(
      "交付运行时",
      value.delivery_runtime === "READY"
        ? "已就绪"
        : value.restart_required
          ? "已保存 · 待重启"
          : value.database.connection === "NOT_CONFIGURED"
            ? "待配置"
            : "暂不可用",
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
  viewBlock(agentRoutes, "status-agent-routes", [value.agent_model_routes, value.model_routes]);
  const routes = el("section", undefined, "admin-panel");
  viewGroup(routes, "status-model-routes");
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
        `${route.provider} / ${route.model} · ${route.reasoning_effort} · ${recordedModelConnectionLabel(route)}`,
        !route.enabled ? "未启用" : route.ready ? "已就绪" : "缺少运行配置",
        !route.enabled ? null : route.ready,
      ),
    );
  const grid = el("div", undefined, "status-grid");
  viewGroup(grid, "status-grid");
  grid.append(overview, runtime);
  content.append(summary, grid, agentRoutes, routes);
}
function showDetail(kind, id) {
  pausedTaskDetailKey = null;
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
    : request.stage === "WAITING_HUMAN"
      ? request.knowledge_wait_stage
      : request.stage;
  let current = requestStages[effectiveStage] ?? -1;
  const failedStageIndexes = new Set(
    (request.failed_stages || [])
      .map(
        (stage) => requestStages[stage] ?? (stage === "DISPATCHING" ? 2 : undefined),
      )
      .filter((index) => index !== undefined),
  );
  const roleStageIndexes = failedDeliveryRoleStages(request);
  if (roleStageIndexes.size) {
    failedStageIndexes.delete(requestStages.DELIVERING);
    for (const index of roleStageIndexes) failedStageIndexes.add(index);
  }
  const operation = latestOperation(request.id);
  if (
    !failedStageIndexes.size &&
    operation?.status === "FAILED" &&
    deliveryOperationActions.has(operation.intent.action) &&
    !activeOperation(request.id) &&
    requestPresentation(request).group === "blocked" &&
    ["DESIGNING", "PLANNING", "BLOCKED", "FAILED"].includes(request.stage) &&
    current >= 0
  ) failedStageIndexes.add(current);
  const taskStatuses = currentRequestTasks(request).filter(task => !task.terminal).map(task => task.status);
  if (
    request.stage !== "WAITING_HUMAN" &&
    !["VERIFY_QA", "VERIFY_REVIEW"].includes(effectiveStage)
  ) {
    if (taskStatuses.includes("VERIFY_REVIEW") || taskStatuses.includes("REVIEW")) current = 5;
    else if (taskStatuses.includes("VERIFY_QA") || taskStatuses.includes("QA")) current = 4;
    else if (
      taskStatuses.some((status) =>
        ["IMPLEMENTING", "CONTINUE_REQUIRED", "QUEUED"].includes(status),
      )
    )
      current = 3;
  }
  if (terminalBlockedRequestTask(request) && requestPresentation(request).group === "blocked" &&
      !failedStageIndexes.size && requestStages[effectiveStage] !== undefined)
    failedStageIndexes.add(requestStages[effectiveStage]);
  if (failedStageIndexes.size) {
    const firstFailedStage = Math.min(...failedStageIndexes);
    if (requestPresentation(request).group === "blocked" || current < 0 || firstFailedStage < current)
      current = firstFailedStage;
  }
  const flow = el("ol", undefined, "delivery-flow");
  const waitingStages = new Set(currentRequestTasks(request)
    .map(waitingExecutionStep).filter(Boolean)
    .map(step => deliveryRoleStage[step.role]).filter(index => index !== undefined));
  if (waitingStages.size) current = Math.min(...waitingStages);
  else if (["WAITING_HUMAN", "WAITING_DEPENDENCY"].includes(request.stage) && current >= 0)
    waitingStages.add(current);
  const interrupted = interruptedRequestTask(request);
  const interruptedStages = new Set((interrupted?.role_queue || [])
    .filter(interruptedStep)
    .map(step => deliveryRoleStage[step.role]));
  const node = requestNodeExecution(request);
  if (["DONE", "CLOSED"].includes(request.stage)) {
    failedStageIndexes.clear();
    waitingStages.clear();
    interruptedStages.clear();
    current = request.stage === "DONE" ? 6 : -1;
  }
  steps.forEach((title, index) => {
    let state = request.stage === "DONE" || index < current ? "done" : "";
    if (failedStageIndexes.has(index)) state = "blocked";
    if (index === current && !failedStageIndexes.has(index) && request.stage !== "DONE")
      state = node.state === "running" ? "current" : node.state === "blocked" ? "blocked" : "paused";
    if (interruptedStages.has(index)) state = "blocked";
    if (waitingStages.has(index)) state = "blocked";
    if (request.stage === "CLOSED" && index === 6) state = "paused";
    const step = el("li", undefined, state);
    if (state === "blocked") step.setAttribute("title", `${title}：阻塞`);
    if (index === current || (request.stage === "CLOSED" && index === 6)) step.setAttribute("aria-current", "step");
    step.append(el("span", String(index + 1)), el("strong", title));
    if (state === "blocked") step.append(el("small", interruptedStages.has(index) ? "执行中断"
      : ["WAITING_PRODUCT_REPLY", "WAITING_PRODUCT_APPROVAL"].includes(request.stage) ? node.label : "已阻塞", "flow-state"));
    if (state === "current") step.append(el("small", "执行中", "flow-state"));
    if (state === "done") step.append(el("small", "已完成", "flow-state"));
    if (state === "paused") step.append(el("small", node.label, "flow-state"));
    flow.append(step);
  });
  return flow;
}
function managerFlowStatus(request) {
  if (["DONE", "CLOSED"].includes(request.stage)) return null;
  if (["WAITING_PRODUCT_REPLY", "WAITING_PRODUCT_APPROVAL"].includes(request.stage))
    return el("p", `产品确认 · ${requestNodeExecution(request).label}`, "flow-manager blocked");
  if (requestNodeExecution(request).requiresEngineeringCheck)
    return el("p", "工程团队 · 等待工程处理", "flow-manager blocked");
  if (request.execution && !productDiscussionStages.has(request.stage)) {
    const node = requestNodeExecution(request);
    return el("p", `${request.execution.responsibility === "product" ? "产品确认" : "ASE 团队协调"} · ${node.label}`,
      `flow-manager ${node.state === "running" ? "active" : node.state}`);
  }
  const operation = activeOperation(request.id);
  if (operation && deliveryOperationActions.has(operation.intent.action)) {
    const state = operation.status === "QUEUED" ? "等待执行" : "处理中";
    const waiting = waitingRequestTask(request);
    const waitingNote = waiting
      ? (waitingExecutionStep(waiting).wait_reason?.startsWith("KNOWLEDGE_GAP:")
        ? approvedKnowledge(request) ? " · 知识解答已批准，等待角色恢复" : " · 当前角色等待知识确认"
        : " · 当前角色等待前提处理") : "";
    const childBlocker = operationChildBlocker(request, operation);
    return el(
      "p",
      `Manager 协调 · ${state}（${label(operation.intent.action)}）${waitingNote || (interruptedRequestTask(request) ? " · 当前角色执行已中断" : childBlocker ? " · 当前角色已阻塞" : "")}`,
      "flow-manager active",
    );
  }
  if (requestPresentation(request).group !== "blocked") return null;
  if (request.knowledge_gap?.is_current)
    return el("p", approvedKnowledge(request)
      ? "Manager 协调 · 知识解答已批准，等待继续"
      : "Manager 协调 · 等待知识确认", "flow-manager blocked");
  const approval = latestApproval(request.id, request.checkpoint_sha256);
  if (approval)
    return el("p", `Manager 协调 · 等待审批 · ${approval.title}`, "flow-manager blocked");
  if (interruptedRequestTask(request))
    return el("p", "Manager 协调 · 执行中断，等待恢复", "flow-manager blocked");
  if (terminalBlockedRequestTask(request))
    return el("p", "Manager 协调 · 当前角色已阻塞，等待恢复", "flow-manager blocked");
  if (request.coordination)
    return el("p", `Manager 协调 · ${request.coordination.draft.action === "PROPOSE_RECOVERY"
      ? "等待恢复" : "等待处理"} · ${humanizeBlockingText(request.coordination.draft.summary)}`, "flow-manager blocked");
  const latest = latestOperation(request.id);
  if (latest && ["FAILED", "INTERRUPTED"].includes(latest.status) &&
      deliveryOperationActions.has(latest.intent.action))
    return el(
      "p",
      `Manager 协调 · 最近操作${latest.status === "FAILED" ? "失败" : "中断"}`,
      "flow-manager blocked",
    );
  if (["BLOCKED", "FAILED"].includes(request.stage))
    return el(
      "p",
      `Manager 协调 · ${request.failed_stages?.length ? "等待恢复" : "已阻塞"}`,
      "flow-manager blocked",
    );
  if (request.stage === "WAITING_HUMAN")
    return el("p", "Manager 协调 · 等待人工处理", "flow-manager blocked");
  return null;
}
function approvedKnowledge(item) {
  return item.stage === "WAITING_HUMAN" && item.knowledge_gap?.is_current &&
    Boolean(item.knowledge_gap.resolution);
}

function knowledgeGapKey(item) {
  return `${item.project_id}/${item.id}/${item.checkpoint_sha256}/${item.stage}/${item.knowledge_gap?.resolution?.resolution_id || "pending"}/${item.execution?.responsibility || "legacy"}`;
}

function knowledgeGapSection(item) {
  let key = knowledgeGapKey(item);
  if (knowledgeGapSections.has(key)) return knowledgeGapSections.get(key);
  const section = el("section", undefined, "detail-section knowledge-gap-section");
  const heading = el("div", undefined, "knowledge-gap-heading");
  const intro = el("div");
  let approved = approvedKnowledge(item);
  const historyOnly = item.stage !== "WAITING_HUMAN";
  const renderIntro = () => intro.replaceChildren(el("h3", historyOnly ? "知识核对记录" : approved ? "已确认的知识" : "待确认的知识"), el("p", historyOnly
    ? "查看原问题、已保存的解答与确认依据。已确认的历史事项无需重复回答；重新核对本身不代表批准。" : approved
    ? "解答已批准并保存，无需重复填写。点击“继续交付”恢复原需求。"
    : "补充待确认的信息，批准后再继续原需求。", "muted"));
  renderIntro();
  const content = el("div", undefined, "knowledge-gap-content");
  content.id = `knowledge-gap-content-${++actionSerial}`;
  content.hidden = true;
  let loading = false, loaded = false;
  const base = "/api/v1/admin/projects/" + encodeURIComponent(item.project_id) +
    "/requirements/" + encodeURIComponent(item.id);
  const showLabel = () => historyOnly ? "查看知识核对记录" : approved ? "查看已确认的知识" : "查看待确认的知识";
  const toggle = button(showLabel(), async () => {
    if (loading) return;
    if (loaded) {
      content.hidden = !content.hidden;
    } else {
      loading = true;
      toggle.disabled = true;
      content.hidden = false;
      content.replaceChildren(el("p", "正在读取知识详情…", "muted"));
      content.setAttribute("aria-busy", "true");
      try {
        const records = await adminFetch(base + "/knowledge-gaps");
        const unique = [...new Map(records.map(view => [view.gap.gap_id, view])).values()];
        content.replaceChildren(...unique.map((view, index) => knowledgeGapCard(view, index, base, item)));
        if (!unique.length) content.append(el("p", "当前没有已记录的知识缺口。", "muted"));
        loaded = true;
        const current = unique.find(view => view.is_current);
        if (current?.resolution) {
          approved = true;
          renderIntro();
          const request = snapshot?.requests.find(request => request.id === item.id && request.project_id === item.project_id);
          if (request?.stage === "WAITING_HUMAN" && knowledgeGapKey(request) === key &&
              knowledgeGapSections.get(key) === section &&
              (!request.knowledge_gap || request.knowledge_gap.gap.gap_id === current.gap.gap_id)) {
            // Detail reads may observe approval before polling. Keep the open answer
            // under its confirmed cache key instead of recreating a collapsed section.
            knowledgeGapSections.delete(key);
            request.knowledge_gap = current;
            key = knowledgeGapKey(request);
            knowledgeGapSections.set(key, section);
            renderOperationStatus();
            renderDetail();
          }
        }
      } catch (error) {
        content.replaceChildren(el("p", error.message || "无法读取知识缺口，请重试。", "error"));
      } finally {
        loading = false;
        toggle.disabled = false;
        content.setAttribute("aria-busy", "false");
      }
    }
    toggle.textContent = loaded && !content.hidden ? "收起知识详情" : showLabel();
    toggle.setAttribute("aria-expanded", String(!content.hidden));
  }, "secondary");
  toggle.setAttribute("aria-controls", content.id);
  toggle.setAttribute("aria-expanded", "false");
  heading.append(intro, toggle);
  section.append(heading, content);
  knowledgeGapSections.set(key, section);
  // Keep drafts for nearby requirements without an unbounded session cache.
  if (knowledgeGapSections.size > 20) knowledgeGapSections.delete(knowledgeGapSections.keys().next().value);
  return section;
}

function knowledgeGapCard(view, index, base, item) {
  const {gap, resolution, is_current: current} = view;
  const rechecked = item.knowledge_rechecked_gap_ids?.includes(gap.gap_id);
  const card = el(resolution || !current ? "div" : "form", undefined, "knowledge-gap-card");
  const header = el("div", undefined, "knowledge-gap-card-heading");
  header.append(el("h3", `知识事项 ${index + 1}`),
    el("span", resolution ? "已确认的知识" : rechecked ? "已交回设计核对 · 非批准" : current ? "需要你的确认" : "历史记录", "badge"));
  if (resolution || !current) {
    card.append(header, el("p", gap.question, "knowledge-gap-question"));
    if (resolution) {
      card.append(el("h4", "已回答的内容"), el("p", resolution.answer, "knowledge-gap-answer"), el("h4", "事实来源 / 决策依据"));
      for (const source of resolution.sources) card.append(el("p", source.uri));
      card.append(el("p", "确认记录 · " + resolution.resolution_id, "paths"));
      if (resolution.approval_reference) card.append(el("p", "确认依据 · " + resolution.approval_reference, "paths"));
      if (resolution.approved_by) card.append(el("p", "记录的确认身份 · " + resolution.approved_by, "muted"));
      if (current) card.append(el("p", "解答已保存，等待你继续原需求。", "success"));
    } else card.append(el("p", "此项不是当前待处理事项，无需在此重复提交。", "muted"));
    return card;
  }
  const decision = gap.required_decision === "Provide verified facts and approve the exact resolution."
    ? "请提供已核实的信息，并确认将此解答用于当前需求。" : gap.required_decision;
  const answer = el("textarea");
  answer.required = true;
  answer.maxLength = 4096;
  answer.rows = 4;
  answer.placeholder = "填写你的解答或明确的决策…";
  const source = el("input");
  source.required = true;
  source.placeholder = "例如：产品负责人确认，或相关文档链接";
  const feedback = el("div", undefined, "form-feedback");
  feedback.setAttribute("role", "status");
  feedback.setAttribute("aria-live", "polite");
  const submit = el("button", "批准解答", "primary");
  submit.type = "submit";
  const actions = el("div", undefined, "knowledge-gap-actions");
  actions.append(el("span", "批准仅保存解答，不会自动开始交付。", "muted"), submit);
  card.append(header, el("p", gap.question, "knowledge-gap-question"));
  if (decision) card.append(el("p", decision, "knowledge-gap-hint"));
  card.append(field("你的解答", answer), field("事实来源 / 决策依据", source), feedback, actions);
  let submitting = false;
  card.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (submitting) return;
    const content = answer.value.trim(), uri = source.value.trim();
    if (!content || !uri) {
      feedback.replaceChildren(el("p", "请填写解答和事实来源 / 决策依据。", "error"));
      return;
    }
    submitting = true;
    submit.disabled = true;
    feedback.replaceChildren();
    try {
      const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(content));
      const sha256 = Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, "0")).join("");
      const resolution = await adminFetch(base + "/knowledge-resolutions", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({gap_id: gap.gap_id, answer: content,
          sources: [{uri, content, sha256}], approval_reference: "local-console:" + gap.gap_id}),
      });
      const request = snapshot?.requests.find(request => request.id === item.id && request.project_id === item.project_id);
      if (request?.checkpoint_sha256 === item.checkpoint_sha256) {
        request.knowledge_gap = {...view, resolution};
        // Approval changes knowledge facts without advancing the immutable checkpoint.
        renderOperationStatus();
        renderDetail();
      }
    } catch (error) {
      feedback.replaceChildren(el("p", error.message || "解答未被接受。", "error"));
      submitting = false;
      submit.disabled = false;
    }
  });
  return card;
}

function roleExecutionActivity(task) {
  const section = el("div", undefined, "role-execution-activity");
  if (task.terminal) return section;
  const roleStatus = {coder: "IMPLEMENTING", qa: "QA", reviewer: "REVIEW"};
  for (const step of task.role_queue || []) {
    if (step.status !== "RUNNING" || step.lease_liveness !== "LEASE_VALID" ||
        roleStatus[step.role] !== task.status) continue;
    section.append(el("p", `${label(step.role)}正在执行 · 最近心跳 ${time(step.heartbeat_at)}。`));
    section.append(el("p", "执行租约有效；模型请求、工具执行与等待返回的细分进度暂未上报。", "muted"));
  }
  return section;
}

function modelCallDiagnostics(operation) {
  const details = viewBlock(el("details", undefined, "model-call-diagnostics"),
    `model-calls:${operation.operation_id}`, operation);
  details.dataset.key = `model-calls:${operation.operation_id}`;
  details.dataset.operationId = operation.operation_id;
  details.append(el("summary", "查看已完成的阶段调用记录"));
  const content = el("div", undefined, "model-call-list");
  details.append(content, el("div", undefined, "model-call-activity"));
  let loading = false, loaded = false;
  details.addEventListener("toggle", async () => {
    if (!details.open || loading || loaded) return;
    loading = true;
    content.replaceChildren(el("p", "正在读取调用记录…", "muted"));
    try {
      const calls = await adminFetch("/api/v1/operations/" + encodeURIComponent(operation.operation_id) + "/model-calls");
      const phases = {stage_reply: "阶段回复", knowledge_intent: "知识检索意图", knowledge_assessment: "知识充分性评估"};
      content.replaceChildren(...calls.map(call => {
        const card = el("div", undefined, "model-call-card");
        const isCli = call.route_kind === "codex_cli";
        const connection = `${isCli ? "Codex CLI · " : ""}${recordedModelConnectionLabel(call)}`;
        const httpStatus = isCli ? "" : ` · ${call.http_status != null ? `HTTP ${call.http_status}` : "未收到 HTTP 响应"}`;
        card.append(
          el("strong", `${call.route_index === 1 ? "主模型" : `备用 ${call.route_index - 1}`} · ${call.provider} / ${call.model} · ${call.reasoning_effort} · ${connection}`),
          el("p", `${call.role ? label(call.role) + " · " : ""}${phases[call.phase] || call.phase} · ${call.outcome === "SUCCEEDED" ? "成功" : "失败"} · ${(call.duration_ms / 1000).toFixed(2)} 秒${httpStatus}`),
        );
        if (call.error_summary) card.append(el("p", call.error_summary));
        if (!isCli || call.request_id) card.append(el("p", "请求编号：" + (call.request_id || "服务未提供"), "paths"));
        if (call.correlation_id) card.append(el("p", "关联编号：" + call.correlation_id, "paths"));
        return card;
      }));
      if (!calls.length) content.append(el("p", "暂无已完成的阶段调用明细；空列表不表示没有执行模型调用。", "muted"));
      content.append(el("p", "此处只展示已保存的阶段调用诊断。Coder、QA、Reviewer 的完成记录请查看仓库任务。", "muted"));
      refreshDiagnosticActivity(details, operation);
      loaded = !["QUEUED", "RUNNING"].includes(operation.status);
    } catch (error) {
      content.replaceChildren(el("p", error.message || "无法读取调用记录，请收起后重试。", "error"));
    } finally {
      loading = false;
    }
  });
  return details;
}
function refreshDiagnosticActivity(details, operation) {
  const activity = details.querySelector(".model-call-activity");
  if (!activity) return;
  const tasks = () => {
    const request = snapshot?.requests.find(item => item.id === operation.intent?.delivery_id &&
      item.project_id === operation.intent?.project_id);
    return request ? currentRequestTasks(request).filter(task => task.project_id === request.project_id) : [];
  };
  renderView(activity, `activity:${operation.operation_id}`, tasks, target => {
    for (const task of tasks())
      target.append(roleExecutionActivity(task), button("查看角色执行记录", () => showDetail("task", task.id), "secondary"));
  }, true);
}

function executionDetailLine(labelText, value) {
  if (value === null || value === undefined || value === "") return null;
  return el("p", `${labelText} · ${String(value)}`, "execution-detail-line");
}

function appendExecutionArtifactDetails(target, entry) {
  const details = entry.details || {};
  const lineage = [];
  if (Array.isArray(details.parent_artifact_ids) && details.parent_artifact_ids.length)
    lineage.push(`输入产物 ${details.parent_artifact_ids.join("、")}`);
  if (details.supersedes) lineage.push(`替代产物 ${details.supersedes}`);
  const engineering = engineeringDetails("产物工程详情", entry.id);
  if (lineage.length) engineering.append(el("p", lineage.join("；"), "paths"));
  const candidate = details.candidate_revision || details.source_revision;
  const candidateLine = executionDetailLine("候选版本", candidate);
  if (candidateLine) engineering.append(candidateLine);
  if (details.artifact_sha256)
    engineering.append(el("p", "产物 SHA-256 · " + details.artifact_sha256, "paths"));
  if (lineage.length || candidateLine || details.artifact_sha256) target.append(engineering);
  if (details.status || details.verdict) {
    const outcome = details.status || details.verdict;
    target.append(el("p", `结果 · ${outcome}`, outcome === "PASS" || outcome === "APPROVE" ? "success" : "blocker"));
  }
  if (details.summary) target.append(el("p", details.summary, "muted"));
  if (details.environment && typeof details.environment === "object" &&
      !Array.isArray(details.environment) && Object.keys(details.environment).length) {
    const environment = engineeringDetails("QA 验证环境与未完成原因", entry.id + ":environment");
    environment.append(el("pre", JSON.stringify(details.environment, null, 2), "paths"));
    target.append(environment);
  }
  const findings = Array.isArray(details.findings) ? details.findings : [];
  if (findings.length) {
    target.append(el("strong", `发现 · ${findings.length} 项`));
    const list = el("ul", undefined, "execution-findings");
    for (const finding of findings) {
      const item = el("li");
      const identity = [finding.severity, finding.code, finding.finding_id].filter(Boolean).join(" · ");
      if (identity) item.append(el("strong", identity));
      if (finding.message) item.append(el("p", finding.message));
      if (finding.file || finding.line)
        item.append(el("p", `位置 · ${finding.file || "未提供"}${finding.line ? `:${finding.line}` : ""}`, "paths"));
      if (finding.recommendation) item.append(el("p", "建议 · " + finding.recommendation, "muted"));
      if (Array.isArray(finding.evidence_ids) && finding.evidence_ids.length)
        item.append(el("p", "证据 · " + finding.evidence_ids.join("、"), "paths"));
      list.append(item);
    }
    target.append(list);
  } else if (details.kind === "qa-report" || details.kind === "review-report") {
    target.append(el("p", "未提供 finding。", "muted"));
  }
  const tests = Array.isArray(details.tests_run) ? details.tests_run : [];
  if (tests.length) {
    target.append(el("strong", "命令 / 测试"));
    const list = el("ul", undefined, "execution-tests");
    for (const test of tests) {
      const suffix = [test.status, test.evidence_id].filter(Boolean).join(" · ");
      list.append(el("li", `${test.command || "未提供命令"}${suffix ? ` · ${suffix}` : ""}`));
    }
    target.append(list);
  }
  const changed = Array.isArray(details.changed_files) ? details.changed_files : [];
  if (changed.length)
    target.append(el("p", "修改文件 · " + changed.map(item => item.path || "未提供").join("、"), "paths"));
  if (lineage.some(value => value.startsWith("输入产物")) &&
      (details.kind === "implementation-report" || details.kind === "coder-progress"))
    target.append(el("p", "Coder 已接收上轮 QA/Review 反馈作为本轮输入。", "success"));
}

function appendExecutionEntry(target, entry, currentTaskId) {
  const item = viewBlock(el("li", undefined, "execution-history-entry"),
    "execution-entry:" + entry.id, {entry, currentTaskId});
  const current = entry.task_id && entry.task_id === currentTaskId;
  item.append(
    el("div", entry.summary),
    el("span", current ? "当前轮" : "历史轮", "badge"),
    el("div", time(entry.occurred_at), "muted"),
  );
  const engineering = engineeringDetails("记录工程详情", entry.id);
  if (entry.task_id) engineering.append(el("div", "任务 · " + entry.task_id, "paths"));
  engineering.append(el("div", entry.source_uri, "paths"));
  if (entry.source_sha256) engineering.append(el("div", "记录摘要 · " + entry.source_sha256, "paths"));
  if (entry.run_id) engineering.append(el("div", "执行编号 · " + entry.run_id, "paths"));
  item.append(engineering);
  if (entry.kind === "artifact") appendExecutionArtifactDetails(item, entry);
  if (entry.kind === "state_event" && entry.details?.reason)
    engineering.append(el("p", "状态原因 · " + entry.details.reason, "muted"));
  if (entry.kind === "evidence" && entry.details?.operation_id)
    item.append(el("p", "操作 · " + entry.details.operation_id, "paths"));
  appendEngineeringExecutionDetails(item, engineering, entry.details || {});
  target.append(item);
}
function appendEngineeringExecutionDetails(target, technical, details) {
  if (details.kind === "delivery_wait_investigation") {
    const missing = details.missing || [];
    if (missing.length) target.append(el("p", "待核验 · " + missing.map(value =>
      engineeringProofMissingGuidance[value]?.[0] || "平台返回了未识别的检查项，不能据此继续").join("；")));
    const permitted = (details.permitted_resolutions || []).map(value => engineeringResolutionLabels[value]).filter(Boolean);
    if (permitted.length) target.append(el("p", "允许的处理方式 · " + permitted.join("、")));
    target.append(el("p", "调查只记录事实，不改变验收结论。", "muted"));
  } else if (details.kind === "delivery_wait_handling") {
    const status = {
      RESOLVED: "已完成平台处理",
      WAITING_EXECUTION: "等待平台执行",
      NEEDS_AUTHORIZATION: "等待工程决定",
      PLATFORM_ATTENTION: "等待平台维护",
      WAITING_PREREQUISITES: "等待前置条件",
      BUDGET_EXHAUSTED: "执行额度已用完",
    }[details.status] || "平台处理状态未识别";
    target.append(el("p", "当次平台处理 · " + status));
    if (details.summary) target.append(el("p", humanizeBlockingText(details.summary)));
    if (details.user_action) target.append(el("p", "当次用户操作 · " + humanizeBlockingText(details.user_action), "muted"));
    if (details.recheck_when) target.append(el("p", "当次复查时机 · " + humanizeBlockingText(details.recheck_when), "muted"));
    if (details.resolution) appendEngineeringExecutionDetails(target, technical, details.resolution);
  } else if (details.kind === "delivery_wait_resolution") {
    target.append(el("p", "工程决定 · " + (engineeringResolutionLabels[details.resolution_kind] ||
      "平台返回了未识别的继续方案，不能据此执行")));
    if (details.operator_id) target.append(el("p", "实际处理者 · " + details.operator_id, "muted"));
    target.append(el("p", "此记录是工程决定；实际执行和验收结果以之后的角色报告为准。", "muted"));
  } else if (details.kind === "engineering_disposition_record") {
    if (details.next_action) target.append(el("p", "下一步 · " + humanizeBlockingText(details.next_action)));
    technical.append(el("p", "工程原因类型 · " + details.rejection_code, "paths"));
  } else if (details.kind === "verifier_preparation_checkpoint") {
    target.append(el("p", "角色模型调用之前的验证准备 · " + {
      NOT_STARTED: "原生验证尚未执行", FINISHED: "原生验证执行证据已封存",
      UNCERTAIN: "原生验证已开始，执行结果尚未确认",
    }[details.native_execution_state]));
    target.append(el("p", "准备检查不代表 QA 或 Review 通过。", "muted"));
    if (details.failure_reason) technical.append(el("p", "准备原因类型 · " + details.failure_reason, "paths"));
  }
  if (details.authorization_source) technical.append(el("p", "授权来源 · " + {
    engineering_operator_decision: "工程负责人明确决定",
    organization_engineering_policy: "平台按已授权组织工程策略继续（不是人工批准）",
    human_decision: "人工精确批准",
  }[details.authorization_source] || "授权来源未识别", "muted"));
  if (details.work_item_id) technical.append(el("p", "工作项 · " + details.work_item_id, "paths"));
  if (details.proof_sha256) technical.append(el("p", "调查摘要 · " + details.proof_sha256, "paths"));
}
function requestOperationHistory(panel, request) {
  const records = [...operations].filter(operation => operationTarget(operation) === request.id &&
    operation.intent.project_id === request.project_id)
    .sort((a, b) => a.updated_at.localeCompare(b.updated_at) || a.operation_id.localeCompare(b.operation_id));
  if (!records.length) return;
  const fold = viewGroup(el("details", undefined, "request-history-fold"), "operation-history-fold");
  fold.dataset.key = "operation-history:" + request.project_id + "/" + request.id;
  fold.append(el("summary", `操作记录（完整历史） · ${records.length} 条`),
    el("p", `共 ${records.length} 条操作，全部保留。历史原因与当次下一步只描述那一轮；当前阻塞和建议操作以本页上方为准。命令完成不代表需求已交付。`, "muted"));
  const list = viewGroup(el("ol", undefined, "execution-history"), "requirement-operation-history-list");
  for (const record of records) {
    const progress = currentOperationProgress(record, request);
    const outcome = recordedOperationOutcome(record);
    const item = viewBlock(el("li", undefined, "execution-history-entry"), "operation:" + record.operation_id, {record, progress});
    if (progress) {
      item.append(el("strong", progress.title), el("p", "发起操作 · " + operationActionLabel(record), "muted"));
      if (progress.reason) item.append(el("p", "当前原因 · " + progress.reason));
      if (progress.responsibility) item.append(el("p", "处理方 · " + progress.responsibility, "muted"));
      if (progress.nextAction) item.append(el("p", "下一步 · " + progress.nextAction));
    } else if (outcome) {
      item.append(el("strong", outcome.title, outcome.className), el("p", "发起操作 · " + operationActionLabel(record), "muted"),
        el("p", "记录的是当次操作结束时的交付状态；当前进度请查看上方交付流程。", "muted"));
    } else item.append(el("strong", operationActionLabel(record)));
    const purpose = operationPurpose(record);
    if (purpose) item.append(el("p", "操作目的 · " + purpose, "muted"));
    const status = el("p", "操作状态 · ", "muted");
    const commandStatus = badge(record.status);
    if (record.status === "SUCCEEDED") {
      commandStatus.textContent = "命令已完成";
      commandStatus.className = "badge";
    }
    status.append(commandStatus);
    item.append(status, el("p", "操作更新 · " + time(record.updated_at), "muted"));
    if (record.status === "QUEUED") item.append(el("p", record.intent.action === "HANDLE_DELIVERY_WAIT"
      ? "操作已接收，等待平台执行。" : "操作已接收，等待 Manager 处理。", "muted"));
    if (record.error_summary) item.append(el("p", humanizeBlockingText(record.error_summary), "error"));
    if (record.status === "SUCCEEDED" && deliveryOperationActions.has(record.intent.action) && record.result?.diagnostic)
      item.append(el("p", "当次原因 · " + humanizeBlockingText(record.result.diagnostic), "error"));
    if (!progress && record.result?.next_action) item.append(el("p", "当次下一步 · " + humanizeBlockingText(record.result.next_action)));
    const technical = engineeringDetails("排障信息（供工程人员使用）", record.operation_id);
    technical.append(el("p", "这些标识用于工程核验，无需产品负责人填写。", "muted"));
    technical.append(el("p", "操作 · " + record.operation_id, "paths"));
    technical.append(el("p", "原始命令状态 · " + record.status, "paths"));
    if (record.intent.action === "PROPOSE_EXECUTION_BASELINE" && record.intent.purpose === "legacy_workspace_rescue" && record.error_code)
      technical.append(el("p", "平台错误编号 · " + record.error_code, "paths"));
    if (record.intent.expected_checkpoint_sha256)
      technical.append(el("p", "发起操作时的需求版本摘要 · " + record.intent.expected_checkpoint_sha256, "paths"));
    const handling = record.result?.engineering_wait_handling;
    if (handling) {
      item.append(el("p", "当次平台处理 · " + humanizeBlockingText(handling.summary || "未提供处理说明")),
        el("p", "当次用户操作 · " + humanizeBlockingText(handling.user_action || "未提供"), "muted"));
      if (handling.recheck_when) item.append(el("p", "当次复查时机 · " + humanizeBlockingText(handling.recheck_when), "muted"));
      technical.append(el("p", "处理报告摘要 · " + handling.handling_sha256, "paths"));
    }
    const proof = record.result?.engineering_wait_investigation || handling?.investigation;
    if (proof) {
      appendEngineeringInvestigation(item, proof, {historical: true});
      technical.append(el("p", "调查摘要 · " + proof.proof_sha256, "paths"));
    }
    const decision = record.result?.engineering_wait_resolution || handling?.resolution;
    if (decision) appendEngineeringExecutionDetails(item, technical, {
      ...decision, operator_id: decision.operator_principal?.operator_id,
    });
    const rescuePlan = record.result?.execution_baseline_plan;
    const rescuePreparation = record.result?.legacy_rescue_preparation;
    if (rescuePreparation) item.append(el("p", "当次恢复检查 · " + rescuePreparation.summary),
      el("p", "当次处理方 · " + rescuePreparation.responsible_party, "muted"),
      el("p", "当次下一步 · " + rescuePreparation.next_action, "muted"));
    if (rescuePlan?.purpose === "legacy_workspace_rescue") {
      item.append(el("p", "当次恢复方案 · 保留原需求分支的完整合法草稿，旧执行结果仍未知；方案本身不代表恢复执行或交付完成。"));
      technical.append(el("p", "当次恢复计划摘要 · " + rescuePlan.plan_sha256, "paths"));
      const containment = rescuePlan.facts?.legacy_containment;
      if (containment) technical.append(el("p", "原执行开始 · " + time(containment.original_start?.started_at), "muted"),
        el("p", containment.method === "operator_confirmed_local_stop"
          ? "当次本机检查 · " + time(containment.local_execution_survey?.observed_at)
          : "当次整机启动 · " + time(containment.boot?.booted_at), "muted"),
        el("p", "隔离观察摘要 · " + containment.containment_sha256, "paths"));
    }
    item.append(technical);
    list.append(item);
  }
  fold.append(list);
  panel.append(fold);
}
function requestHistoricalDeliveryRecords(panel, request) {
  const history = requestTasks(request).filter(isHistoricalRequestTask)
    .sort((left, right) => left.last_activity.localeCompare(right.last_activity));
  if (!history.length) return;
  const fold = viewGroup(el("details", undefined, "historical-delivery-records"), "historical-delivery-fold");
  fold.dataset.key = "historical-delivery:" + request.project_id + "/" + request.id;
  fold.append(el("summary", `历史仓库交付记录（${history.length} 条）`),
    el("p", "以下记录保留当次执行结果，不代表当前交付状态。", "muted"));
  for (const task of history) {
    const entry = viewBlock(el("div", undefined, "execution-history-entry"), "historical-task:" + task.id, task);
    const phase = deliveryPhase(task), status = label(task.status);
    entry.append(el("p", `${phase === status ? status : phase + " · " + status} · ${time(task.last_activity)}`));
    if (task.blocker) entry.append(el("p", "当次原因 · " + humanizeBlockingText(task.blocker)));
    entry.append(button("查看当次执行记录", () => showDetail("task", task.id), "secondary"));
    fold.append(entry);
  }
  panel.append(fold);
}

function taskDetailScopeKey() {
  return selected?.kind === "task"
    ? JSON.stringify([snapshot?.team_id, page, currentProjectId(), selected.id]) : null;
}
const requestChapters = [
  ["current", "当前进展", "查看当前状态、阻塞原因和下一步操作。"],
  ["outputs", "产物与交付", "查看阶段文档，以及通过验收后的交付结果。"],
  ["history", "完整交付记录", "按记录类型查看全过程；历史结论只描述当次执行。"],
  ["reference", "工程参考", "查看需求身份、工程授权和知识核对信息。"],
];
const taskChapters = [
  ["current", "当前进展", "查看当前执行、处理建议和最近的独立验收反馈。"],
  ["outputs", "产物与报告", "查看已保存的任务产物和报告正文。"],
  ["history", "完整执行记录", "查看全部执行轮次和已完成的模型调用。"],
  ["reference", "工程参考", "查看任务身份、候选版本、角色队列和分配信息。"],
];
function detailChapter(chapters, prefix, key) {
  const index = chapters.findIndex(chapter => chapter[0] === key);
  const [, title, description] = chapters[index];
  const section = viewGroup(el("section", undefined, prefix + "-chapter"), prefix + "-chapter:" + key);
  section.id = prefix + "-chapter-" + key;
  section.setAttribute("aria-labelledby", section.id + "-title");
  const heading = viewBlock(el("div", undefined, prefix + "-chapter-heading"), prefix + "-chapter-heading:" + key, [title, description]);
  const titleNode = el("h2", title);
  titleNode.id = section.id + "-title";
  heading.append(el("span", String(index + 1).padStart(2, "0"), prefix + "-chapter-number"),
    titleNode, el("p", description, "muted"));
  section.append(heading);
  return section;
}
function requestChapter(key) {
  return detailChapter(requestChapters, "request", key);
}
function taskChapter(key) {
  return detailChapter(taskChapters, "task", key);
}
function requestChapterNavigation(request) {
  const nav = viewBlock(el("nav", undefined, "request-chapter-nav"), "request-chapter-nav", [request.project_id, request.id]);
  nav.setAttribute("aria-label", "需求详情章节");
  for (const [key, title] of requestChapters)
    nav.append(button(title, () => document.getElementById("request-chapter-" + key)?.scrollIntoView({block: "start"}), "request-chapter-link"));
  return nav;
}
function syncTaskReadingToolbar(panel) {
  const toolbar = panel.querySelector(".task-reading-toolbar");
  if (!toolbar) return;
  const paused = pausedTaskDetailKey === taskDetailScopeKey();
  const changed = renderedSurfaces.get(panel)?.signature !== JSON.stringify(pollingDetailFacts());
  const status = toolbar.querySelector(".task-reading-status");
  const statusText = paused
    ? changed ? "阅读已暂停 · 有新进展，更新后可查看" : "阅读已暂停 · 当前内容保持不动"
    : "实时更新 · 阅读位置和展开内容会保留";
  if (status.textContent !== statusText) status.textContent = statusText;
  const control = toolbar.querySelector("button");
  const controlText = paused ? "更新并恢复实时" : "暂停详情更新";
  if (control.textContent !== controlText) control.textContent = controlText;
  if (control.getAttribute("aria-pressed") !== String(paused))
    control.setAttribute("aria-pressed", String(paused));
}
function taskReadingToolbar() {
  const toolbar = viewBlock(el("div", undefined, "task-reading-toolbar"), "task-reading-toolbar", taskDetailScopeKey());
  toolbar.append(el("span", "", "task-reading-status"), button("暂停详情更新", () => {
    const key = taskDetailScopeKey();
    pausedTaskDetailKey = pausedTaskDetailKey === key ? null : key;
    if (pausedTaskDetailKey) syncTaskReadingToolbar(document.getElementById("detail"));
    else render({preserveComposer: true, incremental: true});
  }, "secondary"));
  return toolbar;
}
function taskReadingFold(title, key, open = false) {
  const fold = viewGroup(el("details", undefined, "task-detail-section task-reading-fold"), key);
  fold.dataset.key = key + ":" + taskDetailScopeKey();
  // Only set the initial state; reconciliation retains the user's later choice.
  fold.open = open;
  fold.append(viewBlock(el("summary", title), key + ":title", title));
  return fold;
}
function taskFeedbackSection(history, taskId) {
  const reports = ["qa-report", "review-report"].map(kind =>
    [...history].reverse().find(entry => entry.kind === "artifact" && entry.details?.kind === kind)
  ).filter(Boolean);
  if (!reports.length) return null;
  const fold = taskReadingFold("最近 QA / Review 反馈", "task-feedback", true);
  fold.append(viewBlock(el("p", "以下是最近一次已保存的独立验收记录；历史结论不代表当前候选已经通过。", "muted"), "task-feedback-note", []));
  const list = viewGroup(el("div", undefined, "task-feedback-list"), "task-feedback-list");
  for (const entry of reports) {
    const details = entry.details;
    const card = viewBlock(el("article", undefined, "task-feedback-card"), "feedback:" + entry.id, {entry, taskId});
    card.append(el("strong", entry.summary), el("p", `${entry.task_id === taskId ? "当前轮" : "历史轮"} · ${time(entry.occurred_at)}`, "muted"));
    if (details.summary) card.append(el("p", details.summary));
    for (const finding of details.findings || []) {
      if (finding.message) card.append(el("p", finding.message));
      if (finding.recommendation) card.append(el("p", "建议 · " + finding.recommendation));
    }
    list.append(card);
  }
  fold.append(list);
  return fold;
}
function renderDetail({ incremental = false } = {}) {
  const panel = document.getElementById("detail");
  if (!snapshot || selected?.kind !== "task" || pausedTaskDetailKey !== taskDetailScopeKey() ||
      !taskById(selected.id)) pausedTaskDetailKey = null;
  // The Task modal contains only read-side facts and navigation, never approvals.
  // Requirement controls still reconcile against fresh checkpoint/authorization facts.
  if (pausedTaskDetailKey && renderedSurfaces.has(panel)) {
    syncTaskReadingToolbar(panel);
    return;
  }
  const opener = document.activeElement;
  const expanded = new Set([...document.querySelectorAll("details[open]")]
    .filter(node => node.dataset.key).map(node => node.dataset.key));
  renderView(document.getElementById("detail"), `detail:${page}:${currentProjectId()}:${selected?.kind}:${selected?.id}`,
    pollingDetailFacts, buildDetail, incremental);
  rememberModalOpener(document.getElementById("detail"), opener);
  for (const node of document.querySelectorAll("details"))
    if (node.dataset.key && expanded.has(node.dataset.key)) node.open = true;
  syncTaskReadingToolbar(panel);
  syncModalState();
}
function buildDetail(panel = document.getElementById("detail")) {
  panel.className = "";
  panel.hidden =
    !snapshot ||
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
        deliveryButton(
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
        deliveryButton(
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
        deliveryButton(
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
        deliveryButton(
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
      "detail-close-control",
    ),
  );
  top.append(
    el(
      "p",
      selected.kind === "task" ? "任务详情" : "需求详情",
      "detail-panel-heading",
    ),
    topActions,
  );
  if (selected.kind === "request") {
    const presentation = requestPresentation(item);
    const blocking = requestBlockerSection(item);
    panel.className = "request-detail-panel";
    const masthead = viewGroup(el("header", undefined, "request-detail-masthead"), "request-detail-masthead");
    const titleRow = viewGroup(el("div", undefined, "request-title-row"), "request-title-row");
    titleRow.append(viewBlock(el("p", item.title, "request-detail-title"), "request-heading-title", item.title),
      viewBlock(requestNodeBadge(item), "request-heading-status", [deliveryPhase(item), requestNodeExecution(item)]));
    masthead.append(viewBlock(top, "request-heading-actions", [item, pollingControlFacts(), operations]), titleRow);
    panel.append(masthead, requestChapterNavigation(item));
    const current = requestChapter("current");
    const overview = viewBlock(el("div", undefined, "request-detail-overview"), "request-detail-overview",
      [item.execution, presentation, requestNodeExecution(item), deliveryPhase(item), Boolean(blocking)]);
    if (item.execution) overview.append(productExecutionSummary(item, {guidance: !blocking}));
    const identity = engineeringDetails("需求工程详情", item.id);
    identity.append(el("p", item.id, "paths request-detail-id"));
    if (item.execution) identity.append(el("p", "执行事实状态 · " + label(executionPresentationStatus(item.execution)), "muted"));
    if (item.execution?.policy_id) identity.append(el("p", "工程授权 · " + item.execution.policy_id, "paths"));
    if (item.execution?.receipt_uri) identity.append(el("p", "执行事实 · " + item.execution.receipt_uri, "paths"));
    if (item.stage_budget || (item.stage === "DESIGNING" && item.design_budget))
      identity.append(el("p", designBudgetSummary(item), "muted"));
    if (presentation.group !== "blocked" && !item.execution)
      overview.append(
        el(
          "p",
          "下一步 · " + humanizeBlockingText(presentation.nextAction),
          "muted request-detail-next",
        ),
      );
    current.append(overview);
    if (blocking) current.append(blocking);
    const currentKnowledgeVisible = Boolean(item.knowledge_gap?.is_current);
    if (currentKnowledgeVisible)
      current.append(knowledgeGapSection(item));
    // Build the existing discussion/action gates in their original scope, then
    // position current controls ahead of reference material. Rendering never submits.
    const discussionHolder = el("div");
    const discussionSection = requestDialogue(discussionHolder, item);
    const actions = viewGroup(el("section", undefined, "detail-section request-current-actions"), "current-actions");
    actions.append(el("h3", "下一步操作"));
    requestOperation(actions, item, discussionSection);
    if (actions.children.length > 1) current.append(actions);
    if (discussionSection && productDiscussionStages.has(item.stage)) current.append(discussionSection);
    const flow = viewGroup(el("section", undefined, "detail-section"), "delivery-flow");
    flow.append(el("h3", "交付流程"));
    const manager = managerFlowStatus(item);
    if (manager) flow.append(manager);
    flow.append(deliveryFlow(item));
    current.append(flow);
    const scopes = viewGroup(el("section", undefined, "detail-section"), "repository-scopes");
    scopes.append(el("h3", "涉及代码目录"));
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
          button("查看仓库任务 · " + label(taskPresentationStatus(task)), () =>
            showDetail("task", task.id),
          ),
        );
      else scopeCard.append(el("span", "尚未生成交付任务", "badge"));
      scopes.append(scopeCard);
    }
    if (!item.scopes.length) scopes.append(el("p", "此需求没有仓库交付目录。", "muted"));
    current.append(scopes);
    panel.append(current);
    const lastOperation = latestOperation(item.id);
    if (lastOperation?.operation_id && discussionSection)
      discussionSection.append(modelCallDiagnostics(lastOperation));
    const outputs = requestChapter("outputs");
    deliveryResult(outputs, item);
    const artifacts = viewGroup(el("section", undefined, "detail-section stage-artifacts"), "stage-artifacts");
    artifacts.append(el("h3", `阶段产物 · ${item.documents.length} 份`));
    documentList(artifacts, item.documents);
    outputs.append(artifacts);
    panel.append(outputs);
    const history = requestChapter("history");
    if (discussionSection && !productDiscussionStages.has(item.stage)) {
      const fold = viewGroup(el("details", undefined, "request-history-fold"), "discussion-history-fold");
      fold.dataset.key = "discussion-history:" + item.project_id + "/" + item.id;
      fold.append(el("summary", `需求讨论记录（${(item.dialogue || []).length} 轮）`), discussionSection);
      history.append(fold);
    }
    requestOperationHistory(history, item);
    requestHistoricalDeliveryRecords(history, item);
    if (history.children.length === 1) history.append(el("p", "暂无已保存的历史记录。", "muted"));
    panel.append(history);
    const reference = requestChapter("reference");
    const engineering = viewGroup(el("div", undefined, "detail-section request-reference-section"), "request-engineering");
    engineering.append(identity);
    if (!currentKnowledgeVisible) {
      const knowledge = engineeringDetails("知识核对记录", item.id + ":knowledge");
      knowledge.append(knowledgeGapSection(item));
      engineering.append(knowledge);
    }
    reference.append(engineering);
    panel.append(reference);
    return;
  }
  panel.className = "task-detail-modal";
  const dialog = el(
    "section",
    undefined,
    "modal-dialog modal-dialog-wide task-detail-dialog",
  );
  viewGroup(dialog, `task-dialog:${item.id}`);
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.setAttribute("aria-label", "任务详情");
  const header = viewGroup(el("header", undefined, "task-detail-header"), "task-detail-header");
  viewBlock(top, "task-heading", item.id);
  header.append(top, taskReadingToolbar());
  dialog.append(header);
  const masthead = viewGroup(el("div", undefined, "task-detail-masthead"), "task-detail-masthead");
  const taskTitleRow = viewGroup(el("div", undefined, "task-title-row"), "task-title-row");
  taskTitleRow.append(viewBlock(el("p", item.title, "task-detail-title"), "task-title", item.title),
    viewBlock(badge(taskPresentationStatus(item)), "task-heading-status", taskPresentationStatus(item)));
  masthead.append(taskTitleRow);
  dialog.append(masthead);
  const current = taskChapter("current");
  const overview = viewBlock(el("section", undefined, "task-detail-overview"), "task-overview",
    [item.status, taskPresentationStatus(item), item.execution, item.blocker, item.next_action, item.last_activity,
      interruptedExecution(item), waitingExecutionStep(item), item.scope]);
  if (item.execution) overview.append(productExecutionSummary(item));
  else {
    overview.append(el("p", "当前阶段 · " + deliveryPhase(item)));
    if (item.blocker) overview.append(el("p", "当前原因 · " + humanizeBlockingText(item.blocker), "blocker"));
    if (item.next_action) overview.append(el("p", "下一步 · " + humanizeBlockingText(item.next_action)));
  }
  overview.append(el("p", paths(item.scope), "paths"), el("p", "最近活动 · " + time(item.last_activity), "muted"));
  const activity = roleExecutionActivity(item);
  activity.classList.add("task-activity-block");
  viewBlock(activity, "task-activity", [item.status, item.terminal, item.role_queue]);
  current.append(overview, activity);
  const engineering = engineeringDetails("任务工程详情", item.id);
  viewGroup(engineering, "task-engineering");
  const engineeringBody = viewBlock(el("div"), "task-engineering-facts",
    [item.id, item.execution, item.blocker, item.next_action, item.candidate_revision, item.candidate_branch,
      item.role_queue, item.task_id, item.history_task_ids, taskGroup(item), item.assignments, snapshot.agents]);
  const engineeringTarget = engineeringBody;
  engineeringTarget.append(el("p", item.id, "paths"));
  if (item.execution?.policy_id) engineeringTarget.append(el("p", "工程授权 · " + item.execution.policy_id, "paths"));
  if (item.execution?.receipt_uri) engineeringTarget.append(el("p", "执行事实 · " + item.execution.receipt_uri, "paths"));
  if (item.blocker)
    engineeringTarget.append(el("p", "原始阻塞原因 · " + humanizeBlockingText(item.blocker), "blocker"));
  if (taskGroup(item) === "blocked" && item.next_action)
    engineeringTarget.append(el("p", "原始下一步 · " + humanizeBlockingText(item.next_action), "muted"));
  if (interruptedExecution(item) && !item.execution)
    overview.append(el("p", `${interruptedExecutionReason} 当前交付检查点：${label(item.status)}。`));
  if (waitingExecutionStep(item))
    overview.append(el("p", `当前角色已暂停，交付检查点保留在${label(item.status)}。`));
  if (item.candidate_revision)
    engineeringTarget.append(el("p", "候选版本 · " + item.candidate_revision, "paths"));
  if (item.candidate_branch)
    engineeringTarget.append(el("p", "候选分支 · " + item.candidate_branch, "paths"));
  if (item.role_queue?.length) {
    engineeringTarget.append(el("h3", "角色执行队列"));
    for (const step of item.role_queue) {
      const lease = {
        LEASE_VALID: "租约有效",
        LEASE_EXPIRED: "租约已过期",
        UNKNOWN: "无有效租约",
      }[step.lease_liveness];
      const status = step.status === "CLOSED" ? "本次执行已结束"
        : interruptedStep(step)
          ? "执行中断" : label(step.status);
      engineeringTarget.append(el("p", `${label(step.role)} · 第 ${step.attempt} 次 · ${status} · ${lease}`));
      if (step.heartbeat_at)
        engineeringTarget.append(el("p", "最近心跳 · " + time(step.heartbeat_at), "muted"));
      if (step.wait_reason?.startsWith("KNOWLEDGE_GAP:"))
        engineeringTarget.append(el("p", "等待补充知识，详情见需求的阻塞信息。", "muted"));
    }
  }
  engineeringTarget.append(el("h3", "成员与分配模型"));
  for (const a of item.assignments)
    engineeringTarget.append(
      el(
        "p",
        `${snapshot.agents.find((x) => x.id === a.agent_id)?.name || a.agent_id} · ${label(a.role)} · ${a.planned_provider} / ${a.planned_model}${a.current_stage ? " · 当前阶段" : ""}`,
      ),
    );
  const history = item.execution_history?.length ? item.execution_history : item.timeline;
  const feedback = taskFeedbackSection(history, item.task_id || item.id);
  if (feedback) current.append(feedback);
  dialog.append(current);
  const outputs = taskChapter("outputs");
  outputs.append(viewBlock(el("p", `共 ${item.documents.length} 份已保存产物。`, "muted"), "task-document-count", item.documents.length));
  const reports = viewGroup(el("div", undefined, "task-artifact-list"), "task-documents");
  documentList(reports, item.documents);
  outputs.append(reports);
  dialog.append(outputs);
  const executionRecords = taskChapter("history");
  const records = taskReadingFold(`执行记录（完整历史） · ${history.length} 条`, "task-history", true);
  records.append(viewBlock(el("p", `共 ${history.length} 条记录。历史轮次完整保留，不代表当前状态。`, "muted"), "task-history-count", history.length));
  engineeringTarget.append(el("p", "当前 Task · " + (item.task_id || item.id), "paths"));
  if (item.history_task_ids?.length > 1)
    engineeringTarget.append(el("p", "关联 Task · " + item.history_task_ids.join(" → "), "paths"));
  const list = viewGroup(el("ol", undefined, "execution-history"), "task-history-list");
  for (const entry of history) appendExecutionEntry(list, entry, item.task_id || item.id);
  if (!history.length) list.append(el("li", "暂无已保存的执行记录。", "muted"));
  records.append(list);
  executionRecords.append(records);
  const calls = taskReadingFold(`已完成的模型调用 · ${item.runs.length} 次`, "task-model-calls");
  const callList = viewGroup(el("div", undefined, "task-model-call-list"), "task-model-call-list");
  if (!item.runs.length)
    callList.append(
      el("p", "暂无已提交调用记录；进行中的调用完成后才会出现。", "muted"),
    );
  for (const run of item.runs) {
    const card = viewBlock(el("article", undefined, "task-model-call-card"),
      `task-run:${run.run_id}:${run.source_uri}`, run);
    card.append(
      el(
        "p",
        `${label(run.role)} · ${run.provider} / ${run.model} · ${recordedModelConnectionLabel(run)} · 第 ${run.route_index} 路 · ${label(run.outcome)} · ${(run.duration_ms / 1000).toFixed(1)} 秒`,
      ),
    );
    if (run.error_code) card.append(el("div", humanizeBlockingText(run.error_code), "blocker"),
      el("p", "原因代码 · " + run.error_code, "paths"));
    card.append(
      el("div", time(run.completed_at) + " · " + run.source_uri, "paths"),
    );
    callList.append(card);
  }
  calls.append(callList);
  engineering.append(engineeringBody);
  engineering.classList.add("task-detail-section");
  executionRecords.append(calls);
  const reference = taskChapter("reference");
  reference.append(engineering);
  dialog.append(executionRecords, reference);
  panel.append(dialog);
}
function render({ preserveComposer = false, incremental = false } = {}) {
  const focused = document.activeElement;
  const selection = incremental ? globalThis.getSelection?.() : null;
  const selectedText = selection && !selection.isCollapsed
    ? [selection.anchorNode, selection.anchorOffset, selection.focusNode, selection.focusOffset]
    : null;
  const scrollPositions = incremental
    ? [document.scrollingElement, ...document.querySelectorAll("#content *, #detail *, #projects *")]
      .filter(node => node && (node.scrollTop || node.scrollLeft))
      .map(node => [node, node.scrollTop, node.scrollLeft])
    : [];
  const expanded = new Set(
    [...document.querySelectorAll("details[open]")]
      .filter((n) => n.dataset.key)
      .map((n) => n.dataset.key),
  );
  document.getElementById("team").textContent = snapshot?.team_name || "Team 记录暂不可用";
  document.getElementById("main").dataset.page = page;
  const projects = document.getElementById("projects");
  renderView(projects, `projects:${page}:${currentProjectId()}`,
    () => [snapshot?.projects, currentProjectId()],
    target => { if (snapshot) renderProjectPicker(target); }, incremental);
  projects.hidden = !["team", "requests"].includes(page);
  document.getElementById("context-controls").hidden = projects.hidden;
  const projectCreator = document.getElementById("project-creator");
  renderView(projectCreator, `project-creator:${page}`, () => [page, canControlCurrentTeam()],
    target => { if (page === "requests" && canControlCurrentTeam()) renderProjectCreator(target); }, incremental);
  projectCreator.hidden = page !== "requests" || !canControlCurrentTeam();
  document.getElementById("heading").textContent = pageCopy[page][0];
  document.getElementById("explanation").textContent = pageCopy[page][1];
  updatePageContext();
  const content = document.getElementById("content");
  const preserveSettings = page === "settings" && uiCommands.has(content.querySelector?.(".settings-form"));
  if (!preserveSettings) {
    const scope = ["settings", "status"].includes(page) ? snapshot?.team_id : currentProjectId();
    renderView(content, `content:${page}:${scope}`, pollingContentFacts, target => {
      target.className = "";
      if (!snapshot && !["settings", "status"].includes(page))
        target.append(el("div", "团队记录暂时无法读取；设置与平台状态仍可查看。", "operation-error"));
      else if (page === "team") renderTeam(target);
      else if (page === "requests") renderRequests(target);
      else if (page === "knowledge") renderKnowledge(target);
      else if (page === "settings") renderSettings(target);
      else renderStatus(target);
    }, incremental);
  }
  if (!preserveComposer && (!incremental || settingsSaveResult)) renderComposer();
  renderOperationStatus();
  renderNotification();
  renderDetail({incremental});
  for (const details of document.querySelectorAll(".model-call-diagnostics")) {
    const operation = operations.find(item => item.operation_id === details.dataset.operationId);
    if (operation) refreshDiagnosticActivity(details, operation);
  }
  syncDeliveryControls();
  for (const node of document.querySelectorAll("details"))
    if (node.dataset.key && expanded.has(node.dataset.key)) node.open = true;
  // Reattaching an unchanged discussion form preserves its draft but drops browser focus.
  // Restore only that surviving control, never over a new modal or changed checkpoint.
  if (focused?.isConnected && document.activeElement === document.body &&
      document.getElementById("notification").hidden && !hasOpenComposer())
    focused.focus({preventScroll: true});
  if (selectedText && selectedText[0]?.isConnected && selectedText[2]?.isConnected &&
      document.getElementById("notification").hidden && !hasOpenComposer())
    selection.setBaseAndExtent(...selectedText);
  for (const [node, top, left] of scrollPositions) {
    if (!node.isConnected) continue;
    node.scrollTop = top;
    node.scrollLeft = left;
  }
}
function updateNavigation() {
  for (const key of ["team", "requests", "knowledge", "settings", "status"]) {
    const node = document.getElementById("nav-" + key);
    node.classList.toggle("selected", key === page);
    if (key === page) node.setAttribute("aria-current", "page");
    else node.removeAttribute("aria-current");
  }
}
async function navigatePage(target) {
  if (!mayCloseComposer()) return;
  if (uiCommands.has(document.querySelector?.(".settings-form"))) return;
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
  if (["knowledge", "settings"].includes(target)) await loadAdministration();
  if (target === "status") {
    runtimeStatusLoading = true;
    updateNavigation();
    render();
    await loadAdministration();
    if (administrationAvailable) await loadRuntimeStatus();
    runtimeStatusLoading = false;
  }
  // A slow prior navigation must not reset the destination selected afterwards.
  if (page !== target) return;
  updateNavigation();
  render();
}
for (const target of ["team", "requests", "knowledge", "settings", "status"])
  document
    .getElementById("nav-" + target)
    .addEventListener("click", () => navigatePage(target));
async function refreshConsoleInfo(signal) {
  try {
    const response = await fetch("/api/v1/console", { cache: "no-store", signal });
    if (response.status === 404) {
      consoleAvailable = false;
      consoleConnectionFailed = false;
      consoleTeamId = null;
      consoleDeliveryReady = null;
      consoleOperationContractVersion = null;
      consoleSupportedActions = null;
      return;
    }
    if (!response.ok) throw new Error("console unavailable");
    const info = await response.json();
    if (
      info.schema_version !== "v0.2" ||
      typeof info.team_id !== "string" ||
      typeof info.delivery_ready !== "boolean"
    )
      throw new Error("invalid console response");
    consoleAvailable = true;
    consoleConnectionFailed = false;
    consoleTeamId = info.team_id;
    consoleDeliveryReady = info.delivery_ready;
    const actions = info.supported_actions;
    const validManifest = Number.isInteger(info.operation_contract_version) &&
      info.operation_contract_version >= 1 && Array.isArray(actions) && actions.length <= 64 &&
      actions.every(action => typeof action === "string" && /^[A-Z][A-Z0-9_]{0,99}$/.test(action)) &&
      new Set(actions).size === actions.length;
    consoleOperationContractVersion = validManifest ? info.operation_contract_version : null;
    consoleSupportedActions = validManifest ? [...actions] : null;
  } catch {
    consoleAvailable = null;
    consoleConnectionFailed = true;
    consoleTeamId = null;
    consoleDeliveryReady = null;
    consoleOperationContractVersion = null;
    consoleSupportedActions = null;
  }
}
async function refreshOperations(signal) {
  await refreshConsoleInfo(signal);
  try {
    const response = await fetch("/api/v1/operations", { cache: "no-store", signal });
    if (!response.ok) throw new Error("operations unavailable");
    const values = await response.json();
    if (!Array.isArray(values)) throw new Error("invalid operations response");
    operations = values;
    operationsAvailable = true;
  } catch {
    operations = [];
    operationsAvailable = false;
  }
}
async function refreshSettingsSnapshot(signal) {
  try {
    // Refresh saved/process facts without replacing the user's editable draft.
    settingsSnapshot = await adminFetch("/api/v1/admin/settings", { signal });
    if (settingsSnapshot.restart_required && configurationApplyResult?.kind === "success")
      configurationApplyResult = null;
  } catch {
    // Keep the last settings observation during a service restart.
  }
}
async function refresh(projectId, includeRuntimeStatus = false) {
  if (projectId && projectId !== currentProjectId() && !mayCloseComposer()) return;
  if (projectId) {
    requestedProjectId = projectId;
    refreshQueued = projectId !== activeRefreshProject || requestedRuntimeStatus;
  }
  if (includeRuntimeStatus) {
    requestedRuntimeStatus = true;
    refreshQueued = true;
  }
  if (refreshFlight) {
    if (projectId) {
      showRefreshProgress();
      syncDeliveryControls();
    }
    return refreshFlight;
  }
  // Coalesce explicit navigation, but never queue periodic ticks behind a slow poll.
  // Keep shared Console/Operations reads serial: aborting them would revoke readiness.
  refreshFlight = (async () => {
    do {
      refreshQueued = false;
      activeRefreshProject = requestedProjectId || currentProjectId();
      const runtimeStatus = requestedRuntimeStatus;
      requestedRuntimeStatus = false;
      await refreshSnapshot(activeRefreshProject, runtimeStatus);
    } while (refreshQueued);
  })();
  try { await refreshFlight; }
  finally { refreshFlight = null; activeRefreshProject = null; }
}
function showRefreshProgress() {
  const status = document.getElementById("connection");
  status.className = "";
  const name = snapshot?.projects.find(item => item.id === requestedProjectId)?.name
    || requestedProjectId;
  status.textContent = projectSwitchPending()
    ? `正在切换到「${name}」…当前仍显示「${projectName()}」的数据。`
    : "正在刷新团队与交付记录…";
}
async function refreshSnapshot(target, includeRuntimeStatus) {
  refreshing = true;
  document.getElementById("refresh").disabled = true;
  showRefreshProgress();
  syncDeliveryControls();
  const status = document.getElementById("connection");
  const superseded = () => requestedProjectId !== null && requestedProjectId !== target;
  const controller = new AbortController(),
    timeout = setTimeout(() => controller.abort(), 40000);
  const priorConsoleReady = consoleDeliveryReady;
  const priorConsoleTeam = consoleTeamId;
  const priorConsoleCapabilities = JSON.stringify([consoleOperationContractVersion, consoleSupportedActions]);
  const priorSettings = JSON.stringify(settingsSnapshot);
  const priorRuntimeStatus = JSON.stringify(runtimeStatusSnapshot);
  const priorOperations = JSON.stringify(operations);
  const priorOperationsAvailable = operationsAvailable;
  const priorKnowledge = JSON.stringify(pollingKnowledgeFacts());
  const refreshSystemViews = async () => {
    if (configurationApplyInFlight) await refreshConfigurationApply();
    if (["settings", "status"].includes(page) && administrationAvailable)
      await refreshSettingsSnapshot(controller.signal);
    if (
      page === "status" && administrationAvailable &&
      (includeRuntimeStatus || priorConsoleReady !== consoleDeliveryReady ||
        priorSettings !== JSON.stringify(settingsSnapshot) || !runtimeStatusSnapshot)
    )
      await loadRuntimeStatus(controller.signal);
  };
  const systemViewsChanged = () =>
    priorConsoleTeam !== consoleTeamId || priorConsoleReady !== consoleDeliveryReady ||
    priorConsoleCapabilities !== JSON.stringify([consoleOperationContractVersion, consoleSupportedActions]) ||
    priorOperationsAvailable !== operationsAvailable ||
    priorSettings !== JSON.stringify(settingsSnapshot) ||
    priorRuntimeStatus !== JSON.stringify(runtimeStatusSnapshot);
  try {
    const url = target
      ? "/api/v1/team?project_id=" + encodeURIComponent(target)
      : "/api/v1/team";
    const teamRead = fetch(url, {
      cache: "no-store",
      signal: controller.signal,
    });
    const [teamResult, systemResult] = await Promise.allSettled([
      teamRead,
      (async () => {
        await refreshOperations(controller.signal);
        syncDeliveryControls();
        if (priorOperationsAvailable !== operationsAvailable) renderOperationStatus();
        await refreshSystemViews();
      })(),
    ]);
    if (systemResult.status === "rejected") throw systemResult.reason;
    if (teamResult.status === "rejected") throw teamResult.reason;
    const response = teamResult.value;
    if (!response.ok) throw new Error("read failed");
    const next = await response.json();
    if (superseded()) return;
    if (
      next.schema_version !== "v0.2" ||
      (target && next.selected_project_id !== target) ||
      !Array.isArray(next.tasks) ||
      !Array.isArray(next.agents) ||
      !Array.isArray(next.requests)
    )
      throw new Error("invalid snapshot");
    const changed =
      !snapshot ||
      JSON.stringify({ ...snapshot, as_of: null }) !==
        JSON.stringify({ ...next, as_of: null });
    const projectChanged = currentProjectId() !== next.selected_project_id;
    const selectedBeforeRefresh = selected;
    snapshot = next;
    if (requestedProjectId === target) requestedProjectId = null;
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
    if (page === "knowledge") {
      if (projectChanged) {
        // Publish identity and its loading view together; a later navigation may
        // arrive while Knowledge is still loading for this accepted snapshot.
        knowledgeLoading = true;
        render({ preserveComposer: hasOpenComposer() });
      }
      await loadAdministration();
    }
    const modalActive = hasOpenComposer();
    if (
      (!modalActive || (["settings", "status"].includes(page) && systemViewsChanged())) &&
      (changed ||
        priorOperations !== JSON.stringify(operations) ||
        priorKnowledge !== JSON.stringify(pollingKnowledgeFacts()) ||
        systemViewsChanged())
    )
      render({ preserveComposer: Boolean(modalActive && !settingsSaveResult), incremental: true });
    if (superseded()) {
      showRefreshProgress();
      return;
    }
    status.className = "";
    status.textContent = consoleAvailable
      ? (consoleDeliveryReady
          ? "团队与交付控制台已连接"
          : "设置控制台已连接 · 交付运行时尚未就绪") +
        " · 最近读取 " +
        time(snapshot.as_of) +
        " · 每 5 秒刷新"
      : "只读团队记录已连接；交付控制台暂不可用。";
  } catch {
    if (superseded()) return;
    if (systemViewsChanged()) render({preserveComposer: hasOpenComposer(), incremental: true});
    status.className = "error";
    const destination = snapshot?.projects.find(item => item.id === requestedProjectId)?.name
      || requestedProjectId;
    status.textContent = projectSwitchPending()
      ? `切换到「${destination}」失败，仍显示原 Project 数据；刷新将重试该项目。`
      : snapshot
        ? "刷新失败，以下为旧数据 · 上次成功读取 " + time(snapshot.as_of)
        : "暂时无法读取数据。请检查生产配置、MySQL 连接，以及 Team/Project workspace 是否已准备。";
  } finally {
    clearTimeout(timeout);
    refreshing = false;
    document.getElementById("refresh").disabled = false;
    syncDeliveryControls();
    // Notifications follow polling even when editor DOM is deliberately preserved.
    renderOperationStatus();
    renderNotification();
  }
}
document
  .getElementById("refresh")
  .addEventListener("click", () => refresh(undefined, true));
refresh();
setInterval(refresh, 5000);
