"use strict";
let snapshot = null;
let teamReadIssue = null;
let consoleTeamReadContractVersion = null;
// Successful metadata negotiates reading scope; a connection failure revokes
// current control authority without turning the retained read scope into null.
let consoleReadingIdentity = null;
let consoleInfoReadGeneration = 0;
let teamDetailRead = null;
let teamDetailReadGeneration = 0;
let teamDetailRenderRevision = 0;
let teamReadFlight = null;
const teamReadWaiters = new Set();
const teamDetailBusyDelays = [1000, 2000, 4000];
function waitForTeamRead(signal) {
  signal?.throwIfAborted();
  return new Promise((resolve, reject) => {
    const dispose = () => {
      teamReadWaiters.delete(resume);
      signal?.removeEventListener("abort", abort);
    };
    const resume = () => {dispose(); resolve();};
    const abort = () => {dispose(); reject(signal.reason);};
    teamReadWaiters.add(resume);
    signal?.addEventListener("abort", abort, {once:true});
  });
}
async function withTeamRead(read, signal) {
  // This is only browser scheduling. An aborted HTTP request does not prove
  // that the server's synchronous reader stopped; its admission remains intact.
  while (teamReadFlight) await waitForTeamRead(signal);
  signal?.throwIfAborted();
  const flight = {};
  teamReadFlight = flight;
  try {return await read();}
  finally {
    if (teamReadFlight === flight) {
      teamReadFlight = null;
      for (const resume of [...teamReadWaiters]) resume();
    }
  }
}
async function readTeamJson(url, signal, {detail = false, current = () => true, publish = value => value} = {}) {
  return withTeamRead(async () => {
    signal?.throwIfAborted();
    if (!current()) return null;
    const response = await fetch(url, {cache:"no-store", signal});
    if (!response.ok) {
      let code = null;
      try {code = (await response.json())?.error?.code;} catch { /* Fixed codes only. */ }
      throw new TeamReadFailure(code === "TEAM_READ_IN_PROGRESS" ? "busy"
        : detail && response.status === 409 ? "changed" : "unavailable");
    }
    const value = await response.json();
    signal?.throwIfAborted();
    return current() ? publish(value) : null;
  }, signal);
}
async function readCurrentTeamJson(url, signal, options) {
  for (let attempt = 0; ; attempt++) {
    if (!options.current()) return null;
    try {return await readTeamJson(url, signal, options);}
    catch (error) {
      if (!options.current()) return null;
      if (!(error instanceof TeamReadFailure) || error.kind !== "busy" ||
          attempt >= teamDetailBusyDelays.length) throw error;
      await waitForTeamDetailRetry(teamDetailBusyDelays[attempt], signal);
    }
  }
}
function waitForTeamDetailRetry(delay, signal) {
  signal.throwIfAborted();
  return new Promise((resolve, reject) => {
    const dispose = () => {clearTimeout(timer); signal.removeEventListener("abort", abort);};
    const abort = () => {dispose(); reject(signal.reason);};
    const timer = setTimeout(() => {dispose(); resolve();}, delay);
    signal.addEventListener("abort", abort, {once:true});
  });
}
const teamSummaryMode = () => consoleTeamReadContractVersion === "v0.1";
const teamDetailSourceFields = ["team_id", "project_id", "request_id", "resource_kind", "resource_id",
  "requirement_checkpoint_sha256", "resource_checkpoint_sha256", "resource_state_sha256", "work_kind", "task_id",
  "task_revision", "task_intent_sha256", "source_task_id", "verification_plan_sha256"];
const teamBodyFields = kind => kind === "request" ? ["documents", "dialogue"]
  : ["documents", "timeline", "execution_history", "runs"];
const teamDetailSourceKey = source => source && JSON.stringify(teamDetailSourceFields.map(field => source[field] ?? null));
function validTeamDetailSource(source, item, kind, teamId, projectId) {
  const sha = value => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
  if (!source || source.team_id !== teamId || source.project_id !== projectId ||
      source.resource_kind !== kind || source.resource_id !== item.id || item.project_id !== projectId ||
      !sha(source.requirement_checkpoint_sha256) || !sha(source.resource_checkpoint_sha256) ||
      !sha(source.resource_state_sha256)) return false;
  if (kind === "request") return source.request_id === item.id &&
    source.requirement_checkpoint_sha256 === item.checkpoint_sha256 &&
    source.resource_checkpoint_sha256 === item.checkpoint_sha256 &&
    ["work_kind", "task_id", "task_revision", "task_intent_sha256", "source_task_id", "verification_plan_sha256"]
      .every(field => source[field] == null);
  if (source.request_id !== item.request_id || source.work_kind !== item.work_kind ||
      (source.task_id ?? null) !== (item.task_id ?? null) || (source.task_revision ?? null) !== (item.task_revision ?? null) ||
      (source.task_intent_sha256 ?? null) !== (item.task_intent_sha256 ?? null)) return false;
  if (source.work_kind === "candidate_verification") return Boolean(source.task_id && source.source_task_id &&
    source.task_id !== source.source_task_id && source.source_task_id === item.source_task_id &&
    source.verification_plan_sha256 === item.plan_sha256 && sha(source.verification_plan_sha256) &&
    source.resource_id === "verification_" + source.verification_plan_sha256.slice(0, 32) &&
    source.task_revision == null && source.task_intent_sha256 == null);
  const identity = [source.task_id, source.task_revision, source.task_intent_sha256];
  return ["delivery", "remediation"].includes(source.work_kind) &&
    source.source_task_id == null && source.verification_plan_sha256 == null &&
    (identity.every(value => value == null) || typeof source.task_id === "string" &&
      Number.isInteger(source.task_revision) && source.task_revision >= 0 && sha(source.task_intent_sha256));
}
function verifiedTeamSummary(value, target) {
  if (!value || value.schema_version !== "v0.1" || typeof value.team_id !== "string" ||
      value.team_id !== consoleReadingIdentity?.teamId || target && value.selected_project_id !== target ||
      !Array.isArray(value.projects) || !Array.isArray(value.agents) ||
      !Array.isArray(value.requests) || !Array.isArray(value.tasks)) throw new TeamReadFailure("unavailable");
  const requests = new Map();
  for (const item of value.requests) {
    if (requests.has(item.id) || teamBodyFields("request").some(field => Object.hasOwn(item, field)) ||
        !validTeamDetailSource(item.detail_source, item, "request", value.team_id, value.selected_project_id))
      throw new TeamReadFailure("unavailable");
    requests.set(item.id, item);
  }
  const tasks = new Set();
  for (const item of value.tasks) {
    const owner = requests.get(item.request_id);
    if (tasks.has(item.id) || !owner || teamBodyFields("task").some(field => Object.hasOwn(item, field)) ||
        !validTeamDetailSource(item.detail_source, item, "task", value.team_id, value.selected_project_id) ||
        item.detail_source.requirement_checkpoint_sha256 !== owner.checkpoint_sha256)
      throw new TeamReadFailure("unavailable");
    tasks.add(item.id);
  }
  return value;
}
function clearTeamDetailRead() {
  teamDetailReadGeneration++;
  teamDetailRead?.controller?.abort();
  teamDetailRead = null;
  teamDetailRenderRevision++;
}
function selectedTeamDetailTarget() {
  if (!teamSummaryMode() || !selected || !snapshot || snapshot.team_id !== consoleReadingIdentity?.teamId || projectSwitchPending()) return null;
  const item = selected.kind === "task" ? taskById(selected.id) : requestById(selected.id);
  if (!item || !validTeamDetailSource(item.detail_source, item, selected.kind, snapshot.team_id, currentProjectId())) return null;
  return {source: item.detail_source, key: teamDetailSourceKey(item.detail_source),
    owner: JSON.stringify([page, snapshot.team_id, currentProjectId(), selected.kind, selected.id, selectionIntentRevision])};
}
function teamDetailQuery(source) {
  const query = new URLSearchParams({team_id:source.team_id, project_id:source.project_id,
    request_id:source.request_id, kind:source.resource_kind, id:source.resource_id,
    expected_requirement_checkpoint_sha256:source.requirement_checkpoint_sha256,
    expected_resource_checkpoint_sha256:source.resource_checkpoint_sha256,
    expected_resource_state_sha256:source.resource_state_sha256});
  for (const field of ["work_kind", "task_id", "task_revision", "task_intent_sha256", "source_task_id", "verification_plan_sha256"])
    if (source[field] != null) query.set("expected_" + field, String(source[field]));
  return "/api/v1/team-details?" + query;
}
function verifiedTeamDetail(value, source) {
  const item = value?.resource, kind = source.resource_kind;
  if (!value || value.schema_version !== "v0.1" || value.kind !== kind ||
      teamDetailSourceKey(value.scope) !== teamDetailSourceKey(source) ||
      !Number.isFinite(Date.parse(value.as_of)) || !item || item.id !== source.resource_id ||
      item.project_id !== source.project_id ||
      kind === "request" && item.checkpoint_sha256 !== source.resource_checkpoint_sha256 ||
      kind === "task" && (item.request_id !== source.request_id || item.work_kind !== source.work_kind ||
        (item.task_id ?? null) !== (source.task_id ?? null) || (item.task_revision ?? null) !== (source.task_revision ?? null) ||
        (item.task_intent_sha256 ?? null) !== (source.task_intent_sha256 ?? null) ||
        source.work_kind === "candidate_verification" && (item.source_task_id !== source.source_task_id ||
          item.plan_sha256 !== source.verification_plan_sha256)) ||
      teamBodyFields(kind).some(field => !Array.isArray(item[field]))) throw new Error("invalid detail");
  return value;
}
async function readSelectedTeamDetail({force = false} = {}) {
  const target = selectedTeamDetailTarget();
  if (!target) { if (teamDetailRead) clearTeamDetailRead(); return; }
  if (!force && teamDetailRead?.owner === target.owner && teamDetailRead.key === target.key) return teamDetailRead.promise;
  const previous = teamDetailRead;
  const retain = previous?.source.team_id === target.source.team_id &&
    previous.source.project_id === target.source.project_id && previous.source.resource_kind === target.source.resource_kind &&
    previous.source.resource_id === target.source.resource_id && previous.owner === target.owner;
  clearTeamDetailRead();
  const generation = teamDetailReadGeneration, controller = new AbortController();
  // Copy the small locator so an in-place current-fact mutation cannot alter a frozen read.
  const source = {...target.source};
  const state = {owner:target.owner, key:target.key, source, controller, status:"loading", issue:null,
    value:retain ? previous.value : null, loadedKey:retain ? previous.loadedKey : null};
  teamDetailRead = state;
  const current = () => teamDetailRead === state && generation === teamDetailReadGeneration &&
    selectedTeamDetailTarget()?.owner === target.owner && selectedTeamDetailTarget()?.key === target.key;
  const timeout = setTimeout(() => controller.abort(), 40000);
  state.promise = (async () => {
    try {
      for (let attempt = 0; ; attempt++) {
        try {
          // Recheck the selected owner after waiting for the page's other Team
          // read, before issuing any request for a no-longer-selected source.
          const value = await readTeamJson(teamDetailQuery(source), controller.signal, {detail:true, current});
          if (!current()) return;
          state.value = verifiedTeamDetail(value, source);
          state.loadedKey = target.key;
          state.issue = null;
          state.status = "ready";
          break;
        } catch (error) {
          if (!current()) return;
          if (!(error instanceof TeamReadFailure) || error.kind !== "busy" ||
              attempt >= teamDetailBusyDelays.length) throw error;
          state.issue = "busy";
          state.status = "waiting";
          teamDetailRenderRevision++;
          render({preserveComposer:true, incremental:true});
          await waitForTeamDetailRetry(teamDetailBusyDelays[attempt], controller.signal);
          if (!current()) return;
        }
      }
    } catch (error) {
      if (!current()) return;
      state.issue = controller.signal.aborted ? "timeout"
        : error instanceof TeamReadFailure ? error.kind : "unavailable";
      state.status = "error";
    } finally {
      clearTimeout(timeout);
      state.promise = null;
      state.controller = null;
      if (current()) {
        teamDetailRenderRevision++;
        render({preserveComposer:true, incremental:true});
      } else {
        state.value = null;
        if (teamDetailRead === state) clearTeamDetailRead();
      }
    }
  })();
  return state.promise;
}
function detailReadingItem(item) {
  if (!teamSummaryMode()) return item;
  const source = teamDetailRead?.value?.scope;
  if (!source || source.team_id !== snapshot?.team_id || source.project_id !== currentProjectId() ||
      source.resource_id !== item.id || source.resource_kind !== selected?.kind) return item;
  return {...item, ...Object.fromEntries(teamBodyFields(source.resource_kind)
    .map(field => [field, teamDetailRead.value.resource[field]]))};
}
function productApprovalReadReady(request) {
  if (!teamSummaryMode()) return true;
  const target = selectedTeamDetailTarget(), state = teamDetailRead, spec = request.product_spec_source;
  if (selected?.kind !== "request" || selected.id !== request.id || request.stage !== "WAITING_PRODUCT_APPROVAL" ||
      !target || state?.status !== "ready" || state.loadedKey !== target.key || state.owner !== target.owner ||
      request.checkpoint_sha256 !== requestById(request.id)?.checkpoint_sha256 || !spec ||
      !/^[a-f0-9]{64}$/.test(spec.sha256 || "") ||
      spec.source_uri !== (spec.spec_id != null ? "ProductSpec://" + spec.spec_id : "request://" + request.id + "/ProductSpec")) return false;
  return state.value.resource.documents.some(doc => {
    if (doc.source_uri !== spec.source_uri || doc.sha256 !== spec.sha256 || !doc.content) return false;
    try {
      const body = JSON.parse(doc.content);
      return spec.spec_id != null ? spec.version == null && body.id === spec.spec_id
        : Number.isInteger(spec.version) && spec.version >= 1 && body.version === spec.version &&
          body.product != null && typeof body.product === "object" && !Array.isArray(body.product);
    } catch { return false; }
  });
}
function productApprovalReadBinding(request) {
  return teamSummaryMode() ? JSON.stringify([teamDetailSourceKey(request?.detail_source), request?.product_spec_source]) : null;
}
function requireProductApprovalRead(intent, expectedBinding) {
  if (intent.action !== "PRODUCT_APPROVAL" || !teamSummaryMode()) return;
  const request = requestById(intent.delivery_id);
  if (!request || request.project_id !== intent.project_id || request.checkpoint_sha256 !== intent.expected_checkpoint_sha256 ||
      !productApprovalReadReady(request) || productApprovalReadBinding(request) !== expectedBinding)
    throw new Error("请先读取并审阅当前完整 ProductSpec；旧版本或尚未读取的正文不能用于批准。");
}
function teamDetailReadNotice() {
  const state = teamDetailRead, target = selectedTeamDetailTarget();
  if (state?.status === "ready" && state.loadedKey === target?.key) return null;
  const box = viewBlock(el("div", undefined, "detail-body-read-status admin-notice"), "detail-body-read-status",
    [state?.status, state?.issue, state?.loadedKey, target?.key, state?.value?.as_of]);
  box.setAttribute("role", "status");
  const saved = state?.value ? "下方保留上次读取的正文，仅供阅读；当前状态和操作以上方最新记录为准。" : "正文尚未读取，不能据此判断没有产物或历史。";
  const reason = state?.status === "error" ? state.issue === "changed"
    ? "记录已有更新，请刷新当前状态后重新读取正文。"
    : state.issue === "timeout" ? "完整正文读取超时，可以稍后重新读取。"
      : state.issue === "busy" ? "团队读取仍然繁忙，已完成本次自动重试；可以稍后重新读取完整正文。"
        : "完整正文暂时无法读取，可以稍后重新读取。"
    : state?.issue === "busy" ? "团队信息正在读取，完整正文会稍后自动重试…"
      : "正在读取所选记录的完整正文与历史…";
  box.append(el("p", reason), el("p", saved, "muted"));
  if (state?.status === "error") box.append(button(state.issue === "changed" ? "刷新当前状态并重新读取" : "重新读取完整正文",
    retrySelectedTeamDetail, "secondary"));
  return box;
}
async function retrySelectedTeamDetail() {
  const target = selectedTeamDetailTarget(), state = teamDetailRead;
  if (!target || !state || ["loading", "waiting"].includes(state.status)) return state?.promise;
  if (state.issue === "changed") {
    await refresh();
    const current = selectedTeamDetailTarget();
    if (current?.owner !== target.owner || teamReadIssue) return;
    // A successful summary may already have started the changed-version body.
    // Join it rather than canceling and duplicating the exact new read.
    if (current.key !== target.key) return readSelectedTeamDetail();
  }
  return readSelectedTeamDetail({force:true});
}
class TeamReadFailure extends Error {
  constructor(kind) { super("Team read failed"); this.kind = kind; }
}
function unavailableTeamName() {
  return teamReadIssue === "busy" ? "Team 数据读取中" : "Team 记录暂不可用";
}
function unavailableTeamMessage() {
  if (teamReadIssue === "busy")
    return "团队数据正在读取中；上一轮读取尚未完成，页面会自动重试。设置与平台状态仍可查看。";
  if (teamReadIssue === "timeout")
    return "团队数据读取超时；后台读取可能仍在进行，页面会自动重试。设置与平台状态仍可查看。";
  return "团队记录暂时无法读取；设置与平台状态仍可查看。";
}
let page = "team";
let selected = null;
let selectionIntentRevision = 0;
let pausedTaskDetailKey = null;
let refreshing = false;
let refreshFlight = null;
let teamRefreshTimer = null;
let teamRefreshDelay = 5000;
let requestedProjectId = null;
let activeRefreshProject = null;
let refreshQueued = false;
let requestedRuntimeStatus = false;
let operations = [];
let operationsAvailable = false;
let consoleOperationSummaryContractVersion = null;
const operationSummaryPages = new Map();
const operationDetailCache = new Map();
const operationHistoryPages = new Map();
let operationSummaryReadRevision = 0;
let operationReadOwnerGeneration = 0;
let operationHistoryRevision = 0;
let operationDetailReadyScope = null;
let operationDetailReadyInventory = null;
let currentOperationSources = [];
let operationDetailReadFlight = null;
const operationDetailMaximumBytes = 32 * 1024 * 1024;
const operationDetailMaximumCount = 8;
const operationSummaryMode = () => consoleOperationSummaryContractVersion === "v0.1";
const operationProject = value => value?.intent
  ? value.intent.project_id ?? (value.intent.action === "CREATE_PROJECT" ? value.result?.project_id : null) ?? null
  : value?.project_id ?? null;
const operationAction = value => value?.intent?.action ?? value?.action ?? null;
function operationResultScopeRelation(value) {
  if (!value?.intent) return value?.result_scope_relation ?? null;
  const result = value.result;
  if (!result) return "NO_RESULT";
  const action = operationAction(value), project = operationProject(value);
  if (result.project_id != null && project != null && result.project_id !== project) return "UNVERIFIED_RESOURCE";
  if (action === "CREATE_PROJECT" && value.intent.project_id == null) return "CREATED_RESOURCE";
  if (action === "CREATE_REQUIREMENT") return result.delivery_id ? "CREATED_RESOURCE" : "UNVERIFIED_RESOURCE";
  if ((value.intent.delivery_id ?? null) === (result.delivery_id ?? null)) return "SAME_RESOURCE";
  return action === "DELETE_REQUIREMENT" && result.delivery_id == null ? "NO_RESOURCE" : "UNVERIFIED_RESOURCE";
}
function operationResult(value) {
  return ["SAME_RESOURCE", "CREATED_RESOURCE"].includes(operationResultScopeRelation(value)) ? value.result : null;
}
function operationResultStage(value) {
  if (value?.intent) return operationResult(value)?.stage ?? null;
  // Older summary servers have no relation locator. Full hydration independently
  // checks scope before any current approval/handling fact can be consumed.
  return value?.result_scope_relation == null || ["SAME_RESOURCE", "CREATED_RESOURCE"].includes(value.result_scope_relation)
    ? value?.result_stage ?? null : null;
}
function appendIndependentOperationResult(target, record) {
  const relation = operationResultScopeRelation(record);
  if (!["NO_RESOURCE", "UNVERIFIED_RESOURCE"].includes(relation)) return;
  target.append(el("p", relation === "NO_RESOURCE"
    ? "本次是已完成的删除命令，未返回需求资源；命令结果不代表交付阶段。"
    : "本次命令返回了独立结果对象，与原需求的关系尚未核验；不能作为当前需求的阶段、审批或下一步。", "muted"));
  const raw = record.intent ? record.result : null;
  const project = raw?.project_id ?? record.result_project_id;
  const delivery = raw?.delivery_id ?? record.result_delivery_id;
  if (project) target.append(el("p", "结果所属项目 · " + project, "paths"));
  if (delivery) target.append(el("p", "独立结果对象 · " + delivery, "paths"));
  if (!raw) return;
  const audit = el("details", undefined, "request-history-fold");
  audit.append(el("summary", "独立命令结果（仅供历史审计）"),
    el("p", "以下是原结果对象的历史事实，不是当前需求的操作建议。", "muted"));
  if (raw.stage) audit.append(el("p", "原结果阶段 · " + label(raw.stage)));
  if (raw.diagnostic) audit.append(el("p", "原结果原因 · " + humanizeBlockingText(raw.diagnostic)));
  if (raw.next_action) audit.append(el("p", "原结果记录的下一步 · " + humanizeBlockingText(raw.next_action), "muted"));
  if (raw.checkpoint_sha256) audit.append(el("p", "原结果版本摘要 · " + raw.checkpoint_sha256, "paths"));
  const handling = raw.engineering_wait_handling;
  if (handling?.summary) audit.append(el("p", "原结果处理说明 · " + humanizeBlockingText(handling.summary)));
  if (handling?.user_action) audit.append(el("p", "原结果记录的用户操作 · " + humanizeBlockingText(handling.user_action), "muted"));
  if (raw.approval) {
    audit.append(el("p", "原结果历史方案 · " + raw.approval.title));
    for (const fact of [...(raw.approval.facts || []), ...(raw.approval.technical_facts || [])]) audit.append(el("p", fact));
  }
  target.append(audit);
}
function validOperationResultScopeMetadata(item) {
  const relation = item.result_scope_relation;
  if (relation == null) return true;
  if (!["NO_RESULT", "SAME_RESOURCE", "CREATED_RESOURCE", "NO_RESOURCE", "UNVERIFIED_RESOURCE"].includes(relation)) return false;
  if (relation === "NO_RESULT") {
    if (item.result_project_id != null || item.result_delivery_id != null) return false;
  } else if (item.result_project_id !== item.project_id) return false;
  if (relation === "SAME_RESOURCE" && (item.result_delivery_id ?? null) !== (item.delivery_id ?? null)) return false;
  if (relation === "CREATED_RESOURCE" && !["CREATE_PROJECT", "CREATE_REQUIREMENT"].includes(item.action)) return false;
  if (relation === "NO_RESOURCE" && (item.action !== "DELETE_REQUIREMENT" || item.result_delivery_id != null)) return false;
  return ["SAME_RESOURCE", "CREATED_RESOURCE"].includes(relation) ||
    ["result_stage", "result_checkpoint_sha256", "approval_kind", "approval_plan_sha256", "baseline_plan_sha256",
      "baseline_purpose", "summary", "next_step"].every(field => item[field] == null) && !item.has_baseline_binding;
}
function editedRequirementReplacement(operation, originalRequest, originalTeamId) {
  const result = operation?.result;
  if (!originalRequest || originalTeamId !== snapshot?.team_id || operation?.team_id !== originalTeamId ||
      operation.status !== "SUCCEEDED" || operationAction(operation) !== "UPDATE_REQUIREMENT" ||
      operationProject(operation) !== originalRequest.project_id || originalRequest.project_id !== currentProjectId() ||
      operation.intent?.delivery_id !== originalRequest.id ||
      operation.intent.expected_checkpoint_sha256 !== originalRequest.checkpoint_sha256 ||
      requestById(originalRequest.id) || result?.project_id !== originalRequest.project_id ||
      !result.delivery_id || result.delivery_id === originalRequest.id ||
      !/^[a-f0-9]{64}$/.test(result.checkpoint_sha256 || "")) return null;
  const replacement = requestById(result.delivery_id);
  return replacement?.project_id === result.project_id && replacement.checkpoint_sha256 === result.checkpoint_sha256
    ? replacement : null;
}
async function readEditedRequirementReplacement(originalRequest, originalTeamId, signal) {
  if (!operationSummaryMode() || !operationsAvailable || !originalRequest ||
      originalTeamId !== snapshot?.team_id || originalRequest.project_id !== currentProjectId() ||
      requestById(originalRequest.id)) return;
  const page = await readOperationSummaryPage(originalRequest.project_id, originalRequest.id, {signal});
  const source = page.items.find(item => item.status === "SUCCEEDED" && item.action === "UPDATE_REQUIREMENT" &&
    item.team_id === originalTeamId && item.project_id === originalRequest.project_id &&
    item.delivery_id === originalRequest.id && item.intent_checkpoint_sha256 === originalRequest.checkpoint_sha256);
  if (source) await readFullOperation(source, {signal, fresh:true});
}
const operationSummaryScopeKey = (projectId, deliveryId) => JSON.stringify([consoleTeamId, projectId, deliveryId]);
const operationReadOwnerSignature = () => JSON.stringify([operationReadOwnerGeneration,
  snapshot?.team_id, consoleTeamId, currentProjectId(), selectionIntentRevision]);
const operationWriteOwnerSignature = () => JSON.stringify([operationReadOwnerSignature(),
  consoleAvailable, consoleDeliveryReady, consoleMode, consoleOperationContractVersion, consoleSupportedActions,
  consoleOperationSummaryContractVersion]);
function operationReadingRecords() {
  if (!operationSummaryMode()) return operations;
  const records = new Map();
  for (const state of operationSummaryPages.values()) {
    if (state.page.team_id !== consoleTeamId || consoleTeamId !== snapshot?.team_id) continue;
    for (const item of [...state.page.items, ...state.page.active]) records.set(item.operation_id, item);
  }
  for (const item of currentOperationSources) if (item.team_id === consoleTeamId && !records.has(item.operation_id)) records.set(item.operation_id, item);
  // Loaded details can enhance reading only while their current summary matches.
  return [...records.values()].filter(item => !operationProject(item) || operationProject(item) === currentProjectId())
    .map(item => operations.find(value =>
    value.operation_id === item.operation_id && value.operation_sha256 === item.operation_sha256) || item);
}
function clearOperationReadScope() {
  operationReadOwnerGeneration++;
  operationSummaryReadRevision++;
  operationDetailReadyScope = null;
  operationDetailReadyInventory = null;
  currentOperationSources = [];
  operationDetailCache.clear();
  operationSummaryPages.clear();
  operationHistoryPages.clear();
  operations = [];
  operationsAvailable = false;
}
function selectedOperationScope() {
  const request = selectedPreparationRequest();
  return request && request.project_id === currentProjectId()
    ? {projectId: request.project_id, deliveryId: request.id, checkpoint: request.checkpoint_sha256} : null;
}
const selectedOperationScopeKey = scope => scope && JSON.stringify([snapshot?.team_id, scope.projectId,
  scope.deliveryId, scope.checkpoint, selectionIntentRevision]);
async function loadCurrentOperationDetails(signal) {
  const scope = selectedOperationScope();
  if (!operationSummaryMode() || !scope) return;
  const key = selectedOperationScopeKey(scope);
  if (operationDetailReadFlight?.key === key) return operationDetailReadFlight.promise;
  const revision = ++operationSummaryReadRevision;
  const currentScope = () => revision === operationSummaryReadRevision && selectedOperationScopeKey(selectedOperationScope()) === key;
  const promise = (async () => {
    const priorScope = operationDetailReadyScope;
    // An unchanged poll is a freshness read, not a new authorization. Keep the
    // already verified scope until an actual inventory/cache change revokes it.
    if (priorScope !== key || !currentOperationSources.every(item =>
        operationDetailCache.get(item.operation_id)?.value.operation_sha256 === item.operation_sha256))
      operationDetailReadyScope = null;
    const current = await readOperationSummaryPage(scope.projectId, scope.deliveryId, {signal});
    if (!currentScope()) throw new Error("所选需求已变化，请核对当前页面。");
    if (priorScope === key && operationDetailReadyInventory === current.inventory_sha256 &&
        currentOperationSources.every(item => operationDetailCache.get(item.operation_id)?.value.operation_sha256 === item.operation_sha256)) {
      operationDetailReadyScope = key;
      return;
    }
    operationDetailReadyScope = null;
    currentOperationSources = [];
    operationDetailCache.clear();
    operations = [];
    const latest = new Map(), taskIds = new Set(currentRequestTasks(requestById(scope.deliveryId))
      .flatMap(task => [task.task_id, task.id]));
    const observe = items => {
      for (const item of items) {
        const currentCheckpoint = item.result_checkpoint_sha256 === scope.checkpoint || item.intent_checkpoint_sha256 === scope.checkpoint;
        if (item.task_id && !taskIds.has(item.task_id)) continue;
        if (!currentCheckpoint && !["QUEUED", "RUNNING"].includes(item.status) && !item.task_id) continue;
        if (!latest.has(item.action)) latest.set(item.action, item);
        if (item.approval_kind && currentCheckpoint && !latest.has("current-approval")) latest.set("current-approval", item);
      }
    };
    observe([...current.active, ...current.items]);
    let cursor = current.next_cursor, seen = new Set();
    while (cursor) {
      if (seen.has(cursor)) throw new Error("历史操作分页无法完整核验。");
      seen.add(cursor);
      const older = await readOperationSummaryPage(scope.projectId, scope.deliveryId, {signal, cursor, publish: false});
      if (!currentScope()) throw new Error("所选需求已变化，请核对当前页面。");
      if (older.inventory_sha256 !== current.inventory_sha256) throw new Error("操作记录已有更新，请重新核对。");
      observe(older.items);
      cursor = older.next_cursor;
    }
    const sources = [...new Map([...latest.values()].map(item => [item.operation_id, item])).values()];
    if (sources.length > operationDetailMaximumCount) throw new Error("当前待核对的完整操作较多，请由平台核对记录关联。");
    currentOperationSources = sources;
    for (const item of sources) {
      await readFullOperation(item, {signal, fresh: true});
      if (!currentScope()) throw new Error("所选需求已变化，请核对当前页面。");
    }
    if (revision !== operationSummaryReadRevision || selectedOperationScopeKey(selectedOperationScope()) !== key)
      throw new Error("所选需求已变化，请核对当前页面。");
    if (!sources.every(item => operationDetailCache.get(item.operation_id)?.value.operation_sha256 === item.operation_sha256))
      throw new Error("当前完整方案超过页面读取预算，请由平台拆分核对入口。");
    operationDetailReadyScope = key;
    operationDetailReadyInventory = current.inventory_sha256;
  })();
  operationDetailReadFlight = {key, promise};
  try { await promise; }
  catch (error) {
    if (currentScope()) operationDetailReadyScope = null;
    throw error;
  }
  finally { if (operationDetailReadFlight?.promise === promise) operationDetailReadFlight = null; }
}
function verifiedOperationSummaryPage(value, projectId, deliveryId) {
  const sha = field => typeof field === "string" && /^[a-f0-9]{64}$/.test(field);
  const nullableText = (field, maximum) => field == null || typeof field === "string" && field.length <= maximum;
  const check = item => item && /^operation_[a-f0-9]{32}$/.test(item.operation_id || "") &&
    item.team_id === consoleTeamId && nullableText(item.project_id, 128) &&
    nullableText(item.delivery_id, 128) && nullableText(item.result_project_id, 128) &&
    nullableText(item.result_delivery_id, 128) && validOperationResultScopeMetadata(item) &&
    (!projectId || item.project_id === projectId) &&
    (!deliveryId || item.delivery_id === deliveryId) &&
    typeof item.action === "string" && /^[A-Z][A-Z0-9_]{0,99}$/.test(item.action) &&
    ["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "INTERRUPTED"].includes(item.status) &&
    Number.isInteger(item.sequence) && item.sequence > 0 && sha(item.operation_sha256) &&
    typeof item.requested_at === "string" && Number.isFinite(Date.parse(item.requested_at)) &&
    typeof item.updated_at === "string" && Number.isFinite(Date.parse(item.updated_at)) &&
    item.has_details === true && ["intent", "result", "patch", "approval", "execution_baseline_plan"]
      .every(field => !Object.hasOwn(item, field)) &&
    ["error_summary", "summary", "next_step"].every(field => nullableText(item[field], 512)) &&
    ["error_code", "approval_kind", "baseline_purpose"].every(field => nullableText(item[field], 64)) &&
    ["result_stage", "task_id", "work_item_id"].every(field => nullableText(item[field], 128)) &&
    (item.has_baseline_binding == null || typeof item.has_baseline_binding === "boolean") &&
    (item.submitted_approval_kind == null || ["plan", "scope", "repair"].includes(item.submitted_approval_kind)) &&
    ["result_checkpoint_sha256", "intent_checkpoint_sha256", "approval_plan_sha256", "baseline_plan_sha256",
      "submitted_approval_sha256", "intent_plan_sha256"].every(field => item[field] == null || sha(item[field]));
  if (!value || value.schema_version !== "v0.1" || value.team_id !== consoleTeamId ||
      (value.scope?.project_id ?? null) !== projectId || (value.scope?.delivery_id ?? null) !== deliveryId ||
      !sha(value.inventory_sha256) || !Array.isArray(value.items) || value.items.length > 50 ||
      !Array.isArray(value.active) || value.active.length > 64 || value.active_complete !== true ||
      !Number.isInteger(value.total_count) || value.total_count < value.items.length ||
      !nullableText(value.next_cursor, 4096) || value.next_cursor != null && !/^[A-Za-z0-9_-]+$/.test(value.next_cursor) ||
      ![...value.items, ...value.active].every(check) ||
      !value.active.every(item => ["QUEUED", "RUNNING"].includes(item.status)) ||
      new Set(value.items.map(item => item.operation_id)).size !== value.items.length ||
      new Set(value.active.map(item => item.operation_id)).size !== value.active.length ||
      new TextEncoder().encode(JSON.stringify(value)).byteLength > 256 * 1024)
    throw new Error("交付操作摘要无法完整核验，请重新读取。");
  return value;
}
async function readOperationSummaryPage(projectId, deliveryId, {signal, cursor = null, publish = true} = {}) {
  const owner = operationReadOwnerSignature();
  const assertOwner = () => {
    if (owner !== operationReadOwnerSignature())
      throw new Error("当前团队或页面已变化，请重新读取当前操作记录。");
  };
  const key = operationSummaryScopeKey(projectId, deliveryId);
  const previous = operationSummaryPages.get(key);
  const query = new URLSearchParams({page_size: "25"});
  if (projectId) query.set("project_id", projectId);
  if (deliveryId) query.set("delivery_id", deliveryId);
  if (cursor) query.set("cursor", cursor);
  const response = await fetch("/api/v1/operation-summaries?" + query, {cache: "no-store", signal,
    headers: !cursor && previous?.etag ? {"If-None-Match": previous.etag} : {}});
  assertOwner();
  if (response.status === 304) {
    if (cursor || !previous || operationSummaryPages.get(key) !== previous)
      throw new Error("交付操作摘要尚未读取，不能复用旧确认。");
    return verifiedOperationSummaryPage(previous.page, projectId, deliveryId);
  }
  if (response.status === 409) throw new Error("历史记录已有更新，请重新读取后继续翻页。");
  if (!response.ok) throw new Error("交付操作摘要暂时无法读取。");
  const body = await response.json();
  assertOwner();
  const value = verifiedOperationSummaryPage(body, projectId, deliveryId);
  if (publish) {
    if (previous && previous.page.inventory_sha256 !== value.inventory_sha256)
      operationDetailReadyScope = null;
    operationSummaryPages.set(key, {page: value, etag: response.headers?.get("ETag") || null});
    while (operationSummaryPages.size > 3) operationSummaryPages.delete(operationSummaryPages.keys().next().value);
    const history = operationHistoryPages.get(key);
    if (history && !history.inventory) {
      history.items = value.items;
      history.inventory = value.inventory_sha256;
      history.next = value.next_cursor || null;
      history.total = value.total_count;
    } else if (history && history.inventory !== value.inventory_sha256) {
      history.changed = true;
      history.next = null;
    }
  }
  return value;
}
function cacheFullOperation(value) {
  const bytes = new TextEncoder().encode(JSON.stringify(value)).byteLength;
  if (bytes > 16 * 1024 * 1024) throw new Error("完整操作记录超出读取预算。");
  operationDetailCache.delete(value.operation_id);
  operationDetailCache.set(value.operation_id, {value, bytes});
  let retained = [...operationDetailCache.values()].reduce((total, item) => total + item.bytes, 0);
  while (operationDetailCache.size > operationDetailMaximumCount || retained > operationDetailMaximumBytes) {
    const oldest = operationDetailCache.keys().next().value;
    retained -= operationDetailCache.get(oldest).bytes;
    operationDetailCache.delete(oldest);
  }
  operations = [...operationDetailCache.values()].map(item => item.value)
    .filter(item => currentOperationSources.some(source => source.operation_id === item.operation_id));
  if (operationSummaryMode() && !currentOperationSources.every(item =>
      operationDetailCache.get(item.operation_id)?.value.operation_sha256 === item.operation_sha256))
    operationDetailReadyScope = null;
  return value;
}
async function readFullOperation(source, {signal, fresh = false} = {}) {
  const owner = operationReadOwnerSignature();
  const assertOwner = () => {
    if (owner !== operationReadOwnerSignature()) throw new Error("当前团队或页面已变化，本次完整记录不再使用。");
  };
  const cached = operationDetailCache.get(source.operation_id)?.value;
  if (!fresh && cached?.operation_sha256 === source.operation_sha256) return cached;
  const response = await fetch("/api/v1/operations/" + encodeURIComponent(source.operation_id), {cache: "no-store", signal});
  assertOwner();
  if (!response.ok) throw invalidateOperationAuthority("完整操作记录暂时无法读取，请重新核对。");
  const value = await response.json();
  assertOwner();
  if (!value || value.operation_id !== source.operation_id || value.team_id !== source.team_id ||
      operationSummaryMode() && source.team_id !== consoleTeamId ||
      value.operation_sha256 !== source.operation_sha256 || operationProject(value) !== operationProject(source) ||
      operationTarget(value) !== operationTarget(source) || operationAction(value) !== operationAction(source) ||
      value.status !== source.status || value.sequence !== source.sequence || !value.intent ||
      value.result?.project_id != null && value.result.project_id !== operationProject(value) ||
      source.result_scope_relation != null && (operationResultScopeRelation(value) !== source.result_scope_relation ||
        (value.result?.project_id ?? null) !== (source.result_project_id ?? null) ||
        (value.result?.delivery_id ?? null) !== (source.result_delivery_id ?? null)) ||
      operationSummaryMode() && ![...operationReadingRecords(), ...[...operationHistoryPages.values()].flatMap(item => item.items)]
        .some(item => item.operation_id === source.operation_id && item.operation_sha256 === source.operation_sha256))
    throw invalidateOperationAuthority("操作记录已有变化，请重新读取并核对当前方案。");
  return cacheFullOperation(value);
}
function invalidateOperationAuthority(message) {
  operationsAvailable = false;
  operationDetailReadyScope = null;
  nativeRuleReviews.clear();
  nativeRuleReviewsRevision++;
  if (typeof document.getElementById === "function") {
    syncDeliveryControls();
    render({preserveComposer: true, incremental: true});
  }
  return new Error(message);
}
function operationHistoryPage(projectId, deliveryId) {
  const key = operationSummaryScopeKey(projectId, deliveryId);
  let state = operationHistoryPages.get(key);
  if (!state) {
    const current = operationSummaryPages.get(key)?.page;
    state = {items: current?.items || [], inventory: current?.inventory_sha256 || null,
      next: current?.next_cursor || null, total: current?.total_count || 0, changed: false, loading: false,
      back: [], pageNumber: 1};
    operationHistoryPages.set(key, state);
    while (operationHistoryPages.size > 2) operationHistoryPages.delete(operationHistoryPages.keys().next().value);
  }
  return state;
}
async function loadMoreOperationHistory(projectId, deliveryId, signal) {
  const state = operationHistoryPage(projectId, deliveryId);
  if (state.loading || state.changed || !state.next) return state;
  state.loading = true;
  try {
    const value = await readOperationSummaryPage(projectId, deliveryId, {signal, cursor: state.next, publish: false});
    if (state.inventory !== value.inventory_sha256) throw new Error("历史记录已有更新，请重新读取。");
    state.back.push({items: state.items, next: state.next, pageNumber: state.pageNumber});
    if (state.back.length > 4) state.back.shift();
    state.items = value.items;
    state.pageNumber++;
    state.next = value.next_cursor || null;
    state.total = value.total_count;
    return state;
  } catch (error) {
    state.changed = true;
    throw error;
  } finally { state.loading = false; }
}
function operationWriteResourceSignature(intent, request) {
  const tasks = request ? currentRequestTasks(request) : [];
  if (!["PROPOSE_EXECUTION_BASELINE", "EXECUTE_EXECUTION_BASELINE", "RESUME_EXECUTION_BASELINE"].includes(intent.action))
    return JSON.stringify([request || null, tasks]);
  const readingFields = new Set(["title", "documents", "dialogue", "detail_source", "last_activity",
    "execution_liveness", "timeline", "execution_history", "runs"]);
  // Keep all current and future authority fields. Only explicitly read-side
  // content/locators and an idle wait's heartbeat timestamp are excluded.
  const resource = value => value && Object.fromEntries(Object.entries(value)
    .filter(([field]) => !readingFields.has(field)));
  return JSON.stringify([resource(request) || null, tasks.map(task => ({...resource(task),
    role_queue: (task.role_queue || []).map(step => {
      if (!["WAITING_HUMAN", "WAITING_DEPENDENCY"].includes(step.status) || step.lease_liveness === "LEASE_VALID") return step;
      const {heartbeat_at: _heartbeat, ...authority} = step;
      return authority;
    }),
  }))]);
}
async function recheckOperationWriteFacts(intent) {
  if (!operationSummaryMode()) return;
  const owner = operationWriteOwnerSignature();
  const projectId = currentProjectId(), revision = selectionIntentRevision;
  const request = intent.delivery_id && requestById(intent.delivery_id);
  const resourceSignature = operationWriteResourceSignature(intent, request);
  const sources = [...currentOperationSources];
  const sourceSignature = JSON.stringify(sources.map(item => [item.operation_id, item.operation_sha256]));
  const assertCurrent = () => {
    const current = intent.delivery_id && requestById(intent.delivery_id);
    if (owner !== operationWriteOwnerSignature() || revision !== selectionIntentRevision || projectId !== currentProjectId() ||
        resourceSignature !== operationWriteResourceSignature(intent, current) ||
        sourceSignature !== JSON.stringify(currentOperationSources.map(item => [item.operation_id, item.operation_sha256])) ||
        !canControlCurrentTeam()) throw new Error("当前团队、需求或完整方案已有变化，请重新核对并确认。");
  };
  const settleCurrent = async () => {
    const flight = operationDetailReadFlight;
    if (flight?.key === selectedOperationScopeKey(selectedOperationScope())) await flight.promise;
    assertCurrent();
  };
  const summary = await readOperationSummaryPage(intent.project_id || projectId, intent.delivery_id || null);
  await settleCurrent();
  if (intent.delivery_id && summary.active.some(item => operationTarget(item) === intent.delivery_id))
    throw new Error("已有操作正在处理，请等待当前结果；本次确认没有提交。");
  for (const source of sources) {
    await readFullOperation(source, {fresh: true});
    await settleCurrent();
  }
  assertCurrent();
}
let recoveryPreparationObservation = null;
let recoveryPreparationFlight = null;
let recoveryPreparationTargetKey = null;
let recoveryPreparationTargetRevision = null;
const preparationScopeFields = ["operation_id", "team_id", "project_id", "delivery_id",
  "expected_checkpoint_sha256", "approved_plan_sha256"];
const preparationKinds = ["AUTHORIZATION_RECORDED", "TASK_SEALED", "DISPATCH_COMMITTED", "SEED_VERIFIED", "EXECUTION_CLAIMED"];
let consoleAvailable = null;
let consoleConnectionFailed = false;
let consoleTeamId = null;
let consoleDeliveryReady = null;
let consoleMode = null;
let maintenanceCompletionGuide = null;
const inspectionSummary = "平台处于维护仅查看模式：可以查看已保存的需求和执行记录；交付与修改操作已暂停。";
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
let operationNoticeObservation = null;
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
function consoleSupportsPausedBaseline() {
  return consoleOperationContractVersion >= 4 && consoleSupportsLegacyRescue() &&
    consoleSupportsOperation("RESUME_EXECUTION_BASELINE");
}
function consoleSupportsCompletedOutputRescue(rejected = false) {
  return consoleOperationContractVersion >= (rejected ? 7 : 5) && consoleSupportsPausedBaseline();
}
function consoleSupportsStoppedProviderRetry() {
  return consoleOperationContractVersion >= 6 && consoleSupportsPausedBaseline();
}
function consoleSupportsContextCapacityResume() {
  return consoleOperationContractVersion >= 8 && consoleSupportsPausedBaseline();
}
function consoleSupportsStoppedExecutionRescue() {
  return consoleOperationContractVersion >= 9 && consoleSupportsPausedBaseline();
}
function consoleSupportsStoppedFailureRetry() {
  return consoleOperationContractVersion >= 10 && consoleSupportsPausedBaseline();
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
const nativeRuleReviews = new Map();
let nativeRuleReviewsRevision = 0;
// Signatures stay in memory; draft values and credentials must never become DOM attributes.
const renderedSurfaces = new WeakMap();
const renderedBlocks = new WeakMap();
const detailReadSources = new WeakMap();
function operationRenderFact(operation) {
  // The backend seals the complete Operation, including its result. This key
  // only invalidates rendered DOM; execution and approval use the full facts.
  if (typeof operation?.operation_id === "string" && /^operation_[a-f0-9]{32}$/.test(operation.operation_id) &&
      typeof operation.operation_sha256 === "string" && /^[a-f0-9]{64}$/.test(operation.operation_sha256))
    return [operation.operation_id, operation.operation_sha256];
  return operation;
}
function operationRenderFacts(values = operationReadingRecords()) {
  return values.map(operationRenderFact);
}
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
  return [consoleAvailable, consoleTeamId, consoleDeliveryReady, consoleMode, consoleOperationContractVersion,
    consoleSupportedActions, consoleOperationSummaryContractVersion, operationsAvailable, operationDetailReadyScope, teamReadIssue,
    snapshot?.team_id, currentProjectId(), projectSwitchPending(), consoleTeamReadContractVersion];
}
function pollingContentFacts() {
  const common = [page, pollingControlFacts(), administrationNotice, !snapshot && teamReadIssue, operationHistoryRevision];
  if (page === "settings") return [...common, administrationAvailable, settingsSnapshot,
    settingsSection, configurationApplyInFlight, configurationApplyResult];
  if (page === "status") return [...common, administrationAvailable, runtimeStatusSnapshot,
    runtimeStatusLoading, runtimeStatusError];
  if (page === "knowledge") return [...common, snapshot?.team_name, snapshot?.projects,
    knowledgeScope, knowledgeMode, knowledgeDocuments, knowledgeIndexStatus, specDocuments,
    learningProposals, knowledgeLoading, knowledgeError];
  return [...common, snapshot?.team_name, snapshot?.projects, snapshot?.agents, snapshot?.tasks,
    snapshot?.requests, operationRenderFacts(), selected, selectedAgentId, requestFilter, recoveryPreparationDisplayFacts()];
}
function pollingKnowledgeFacts() {
  return [knowledgeDocuments, knowledgeIndexStatus, specDocuments, learningProposals,
    knowledgeLoading, knowledgeError];
}
function pollingDetailFacts() {
  const item = selected?.kind === "task" ? taskById(selected.id)
    : selected ? requestById(selected.id) : null;
  const parent = selected?.kind === "task" && item ? taskParentRequest(item) : null;
  const request = selected?.kind === "request" ? item : parent;
  const tasks = request ? requestTasks(request) : [];
  return [page, selected, item, parent, tasks, snapshot?.agents, pollingControlFacts(), operationHistoryRevision,
    operationRenderFacts(item ? operations.filter(operation => operationTarget(operation) === item.id ||
      (parent && operationTarget(operation) === parent.id && operationProject(operation) === parent.project_id)) : []),
    page === "requests" && Boolean(snapshot?.requests.length), nativeRuleReviewsRevision, recoveryPreparationDisplayFacts(),
    teamDetailRenderRevision];
}
function recoveryPreparationDisplayFacts() {
  const facts = recoveryPreparationObservation;
  return facts && {...facts, readAt: facts.issue || !operationsAvailable ? facts.readAt : null};
}
function selectedPreparationRequest() {
  const item = selected?.kind === "task" ? taskById(selected.id)
    : selected?.kind === "request" ? requestById(selected.id) : null;
  return selected?.kind === "task" && item ? taskParentRequest(item) : item;
}
function currentRecoveryPreparationScope() {
  const request = selectedPreparationRequest();
  if (!request || projectSwitchPending() || request.project_id !== currentProjectId()) return null;
  // Saved Operation facts may still be read during an outage; they cannot authorize a command.
  const operation = operations.find(value => operationTarget(value) === request.id &&
    operationProject(value) === request.project_id && ["QUEUED", "RUNNING"].includes(value.status));
  if (!operation || operation.status !== "RUNNING" || operation.team_id !== snapshot?.team_id ||
      operationAction(operation) !== "CONTINUE_DELIVERY" ||
      !/^[a-f0-9]{64}$/.test(operation.intent?.approved_plan_sha256 || "") ||
      !/^[a-f0-9]{64}$/.test(operation.intent?.expected_checkpoint_sha256 || "")) return null;
  return {operation_id: operation.operation_id, team_id: operation.team_id, project_id: request.project_id,
    delivery_id: request.id, expected_checkpoint_sha256: operation.intent?.expected_checkpoint_sha256,
    approved_plan_sha256: operation.intent?.approved_plan_sha256};
}
const preparationScopeKey = scope => scope && JSON.stringify(preparationScopeFields.map(field => scope[field]));
const samePreparationScope = (left, right) => Boolean(left && right &&
  preparationScopeFields.every(field => left[field] === right[field]));
function recoveryPreparationFacts(request) {
  const scope = currentRecoveryPreparationScope();
  return request && request.id === scope?.delivery_id && request.project_id === scope.project_id &&
    samePreparationScope(scope, recoveryPreparationObservation?.scope) ? recoveryPreparationObservation : null;
}
function verifiedPreparationRecords(value, scope) {
  if (!value || value.schema_version !== "v0.1" || !samePreparationScope(value.scope, scope) ||
      !Array.isArray(value.records) || value.records.length > 5) throw new Error("invalid preparation records");
  const seen = new Set(), taskId = "task_recovery_" + scope.approved_plan_sha256.slice(0, 32);
  return value.records.map(record => {
    if (!record || !preparationKinds.includes(record.kind) || seen.has(record.kind) ||
        !samePreparationScope(record.scope, scope) || typeof record.observed_at !== "string" ||
        !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(record.observed_at) ||
        !Number.isFinite(Date.parse(record.observed_at)) || typeof record.record_sha256 !== "string" ||
        !/^[a-f0-9]{64}$/.test(record.record_sha256) ||
        !record.evidence || typeof record.evidence !== "object") throw new Error("invalid preparation record");
    seen.add(record.kind);
    const evidence = record.evidence;
    const fields = {
      AUTHORIZATION_RECORDED: ["authorization_sha256"],
      TASK_SEALED: ["task_id", "task_record_sha256", "source_revision"],
      DISPATCH_COMMITTED: ["task_id", "dispatch_id", "dispatch_sha256", "task_record_sha256"],
      SEED_VERIFIED: ["task_id", "seed_record_sha256", "dispatch_sha256", "input_mode"],
      EXECUTION_CLAIMED: ["task_id", "work_item_id", "lease_id", "assignment_id", "claim_sha256", "dispatch_sha256", "source_revision", "role", "attempt"],
    }[record.kind];
    if (Object.keys(evidence).some(field => !fields.includes(field)) ||
        fields.some(field => evidence[field] === undefined) ||
        fields.filter(field => field.endsWith("_sha256")).some(field => typeof evidence[field] !== "string" || !/^[a-f0-9]{64}$/.test(evidence[field])) ||
        (fields.includes("task_id") && evidence.task_id !== taskId) ||
        (fields.includes("source_revision") && (typeof evidence.source_revision !== "string" || !/^(?:[a-f0-9]{40}|[a-f0-9]{64})$/.test(evidence.source_revision))) ||
        (record.kind === "DISPATCH_COMMITTED" && evidence.dispatch_id !== "dispatch_commit_" + scope.approved_plan_sha256) ||
        (record.kind === "SEED_VERIFIED" && !["preserve_draft", "coder_reapply"].includes(evidence.input_mode)) ||
        (record.kind === "EXECUTION_CLAIMED" && (evidence.role !== "coder" || evidence.attempt !== 1 ||
          ["work_item_id", "lease_id", "assignment_id"].some(field => typeof evidence[field] !== "string") ||
          !/^work_[a-z0-9][a-z0-9_-]{2,95}$/.test(evidence.work_item_id) ||
          !/^lease_[a-z0-9][a-z0-9_-]{2,63}$/.test(evidence.lease_id) ||
          !/^assignment_[a-z0-9][a-z0-9_-]{2,63}$/.test(evidence.assignment_id))))
      throw new Error("invalid preparation evidence");
    return {kind: record.kind, scope: {...scope}, observed_at: record.observed_at, record_sha256: record.record_sha256,
      evidence: Object.fromEntries(fields.map(field => [field, evidence[field]]))};
  }).sort((left, right) => preparationKinds.indexOf(left.kind) - preparationKinds.indexOf(right.kind));
}
function syncRecoveryPreparationTarget() {
  const scope = currentRecoveryPreparationScope(), key = preparationScopeKey(scope);
  if (key === recoveryPreparationTargetKey && selectionIntentRevision === recoveryPreparationTargetRevision) return;
  recoveryPreparationTargetKey = key;
  recoveryPreparationTargetRevision = selectionIntentRevision;
  if (!samePreparationScope(scope, recoveryPreparationObservation?.scope))
    recoveryPreparationObservation = scope ? {scope, records: [], issue: "loading", readAt: null} : null;
  if (recoveryPreparationFlight) recoveryPreparationFlight.controller.abort();
  else if (scope) void refreshRecoveryPreparationProgress();
}
async function refreshRecoveryPreparationProgress() {
  const scope = currentRecoveryPreparationScope(), revision = selectionIntentRevision;
  if (!scope) {syncRecoveryPreparationTarget(); return;}
  if (recoveryPreparationFlight) return recoveryPreparationFlight.promise;
  recoveryPreparationTargetKey = preparationScopeKey(scope);
  recoveryPreparationTargetRevision = revision;
  if (!samePreparationScope(scope, recoveryPreparationObservation?.scope))
    recoveryPreparationObservation = {scope, records: [], issue: "loading", readAt: null};
  const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 8000);
  const flight = {scope, revision, controller, promise: null};
  recoveryPreparationFlight = flight;
  const current = () => selectionIntentRevision === revision && samePreparationScope(scope, currentRecoveryPreparationScope());
  flight.promise = (async () => {
    try {
      const response = await fetch("/api/v1/operations/" + encodeURIComponent(scope.operation_id) + "/preparation-progress",
        {cache: "no-store", signal: controller.signal});
      if (!response.ok) throw new Error(response.status === 404 ? "unsupported" : "unavailable");
      const records = verifiedPreparationRecords(await response.json(), scope);
      if (!current()) return;
      if (controller.signal.aborted) throw new Error("unavailable");
      if (recoveryPreparationObservation.records.some(saved =>
        !records.some(record => record.kind === saved.kind && record.record_sha256 === saved.record_sha256)))
        throw new Error("preparation records changed");
      recoveryPreparationObservation = {scope, records, issue: null, readAt: new Date().toISOString()};
    } catch (error) {
      if (!current()) return;
      recoveryPreparationObservation = {...recoveryPreparationObservation,
        issue: error?.message === "unsupported" ? "unsupported" : "unavailable"};
    } finally {
      clearTimeout(timeout);
      recoveryPreparationFlight = null;
      if (current()) render({preserveComposer: true, incremental: true});
      else if (currentRecoveryPreparationScope()) void refreshRecoveryPreparationProgress();
    }
  })();
  return flight.promise;
}
function preparationRecordLabel(record) {
  return {AUTHORIZATION_RECORDED: "恢复授权已核验", TASK_SEALED: "恢复任务输入已封存",
    DISPATCH_COMMITTED: "派发记录已保存", EXECUTION_CLAIMED: "开发执行已领取（历史记录）"}[record.kind] ||
    (record.evidence.input_mode === "coder_reapply" ? "恢复输入已核验，旧进度交由开发继续适配" : "保留改动已载入并核验");
}
function preparationReadMessage(facts) {
  if (facts.issue === "unsupported") return "当前服务不提供恢复准备明细；请以交付流程和执行记录为准。";
  if (facts.issue === "unavailable") return "恢复准备明细暂不可读取，将自动重试；这不能说明交付已停止。";
  if (facts.issue === "loading") return "正在读取已保存的恢复准备明细。";
  if (!facts.records.length) return "本次操作没有已保存的准备明细。当前执行状态仍以交付流程和执行记录为准。";
  return null;
}
function recoveryPreparationSection(request) {
  const facts = recoveryPreparationFacts(request);
  if (!facts) return null;
  const section = viewGroup(el("section", undefined, "detail-section recovery-preparation"),
    "recovery-preparation:" + preparationScopeKey(facts.scope));
  section.setAttribute("aria-label", "恢复准备明细");
  const title = selected?.kind === "task" ? "当前需求的恢复准备明细" : "恢复准备明细";
  section.append(viewBlock(el("h3", title), "preparation-heading", title),
    viewBlock(el("p", "以下是平台已保存的准备事实；不代表当前执行状态或验收结论。", "muted"), "preparation-note", []));
  const message = preparationReadMessage(facts);
  if (message) section.append(viewBlock(el("p", message, "muted preparation-read-notice"), "preparation-read-notice", message));
  if (facts.records.length) {
    const list = viewGroup(el("ol", undefined, "preparation-milestones"), "preparation-milestones");
    for (const record of facts.records) {
      const row = viewBlock(el("li"), "preparation-record:" + record.kind, record);
      const timestamp = el("time", time(record.observed_at), "muted");
      timestamp.setAttribute("datetime", record.observed_at);
      row.append(el("span", preparationRecordLabel(record)), timestamp);
      list.append(row);
    }
    section.append(list);
  }
  if (facts.readAt && (facts.issue || !operationsAvailable))
    section.append(viewBlock(el("p", "保留上次读取的明细 · " + time(facts.readAt), "muted preparation-read-notice"),
      "preparation-saved-read", facts.readAt));
  return section;
}
function preparationLatestSummary(request) {
  const facts = recoveryPreparationFacts(request);
  if (!facts) return null;
  const latest = [...facts.records].sort((a, b) => Date.parse(b.observed_at) - Date.parse(a.observed_at))[0];
  return latest ? "最近准备记录 · " + preparationRecordLabel(latest) + " · " + time(latest.observed_at) +
    (facts.issue || !operationsAvailable ? "（上次读取）" : "") : preparationReadMessage(facts);
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
  CONTEXT_CAPACITY: "上下文容量不足",
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
  RESUME_EXECUTION_BASELINE: "继续保留进度的原需求",
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
  "RESUME_EXECUTION_BASELINE",
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
    team: ["Team 级", snapshot?.team_name || unavailableTeamName(), "工作负载筛选"],
    requests: ["Project 级", projectName(), "当前 Project"],
    knowledge:
      knowledgeScope === "team"
        ? ["Team 知识", snapshot?.team_name || unavailableTeamName(), ""]
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
    const unavailable = deliveryControlUnavailableReason();
    operationNotice = {kind: "error", title: "交付操作暂不可用",
      message: unavailable.reason + " " + unavailable.next_action};
    renderNotification();
    return null;
  }, className);
  control.setAttribute("data-delivery-control", "true");
  return control;
};
const suspendedDeliveryControls = new WeakMap();
const knowledgeApprovalControls = new WeakMap();
function setDeliveryControlDisabled(control, disabled) {
  const ready = canControlCurrentTeam() && !knowledgeApprovalControls.get(control)?.unavailable();
  if (ready) suspendedDeliveryControls.delete(control);
  else suspendedDeliveryControls.set(control, Boolean(disabled));
  control.disabled = Boolean(disabled) || !ready;
}
function syncDeliveryControls() {
  const ready = canControlCurrentTeam();
  document.getElementById("project-creator").hidden = page !== "requests" || !ready;
  for (const control of document.querySelectorAll('[data-delivery-control="true"]')) {
    const knowledge = knowledgeApprovalControls.get(control);
    const unavailable = knowledge?.unavailable();
    if (knowledge) {
      const message = unavailable ? unavailable.reason + " " + unavailable.next_action : "";
      if (knowledge.status.textContent !== message) knowledge.status.textContent = message;
      knowledge.status.hidden = !unavailable;
    }
    if (!ready || unavailable) {
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
  operation.intent?.delivery_id || operation.delivery_id ||
    (operationAction(operation) === "CREATE_REQUIREMENT" ? operationResult(operation)?.delivery_id : null) || null;
const operationRequest = (operation) => {
  const target = operationTarget(operation);
  return target && snapshot?.requests.find(request => request.id === target &&
    request.project_id === operationProject(operation)) || null;
};
const currentProjectId = () => snapshot?.selected_project_id || null;
const projectSwitchPending = () =>
  requestedProjectId !== null && requestedProjectId !== currentProjectId();
const activeOperation = (deliveryId, projectId = null) =>
  operationsAvailable ? operationReadingRecords().find(
    (operation) =>
      operationTarget(operation) === deliveryId &&
      (!projectId || operationProject(operation) === projectId) &&
      ["QUEUED", "RUNNING"].includes(operation.status),
  ) : undefined;
const latestOperation = (deliveryId) =>
  [...operationReadingRecords()]
    .filter((operation) => operationTarget(operation) === deliveryId)
    .sort((left, right) => right.updated_at.localeCompare(left.updated_at))[0] ||
  null;
const operationNeedsHumanAttention = (operation) =>
  operation?.status === "SUCCEEDED" &&
  (["WAITING_HUMAN", "BLOCKED", "FAILED"].includes(operationResultStage(operation)) ||
    ["NEEDS_AUTHORIZATION", "PLATFORM_ATTENTION", "WAITING_PREREQUISITES", "BUDGET_EXHAUSTED"]
      .includes(operationResult(operation)?.engineering_wait_handling?.status)) &&
  !operationResult(operation)?.approval && !operation.approval_kind;
const isSourceRevisionDrift = (operation) =>
  operation?.status === "FAILED" &&
  (operation.error_code === "SOURCE_REVISION_DRIFT" ||
    /source revision (?:drift|changed after Requirement preparation)/i.test(
      operation.error_summary || "",
    ));
const latestApproval = (deliveryId, checkpoint, projectId = null) => {
  if (!operationsAvailable) return null;
  const operation = (
    [...operations]
      .sort((left, right) => right.updated_at.localeCompare(left.updated_at))
      .find(
        (operation) => {
          const approval = operationResult(operation)?.approval;
          if (
            operationTarget(operation) !== deliveryId ||
            (projectId !== null && operationProject(operation) !== projectId) ||
            operation.status !== "SUCCEEDED" ||
            !approval ||
            operationResult(operation).delivery_id !== deliveryId ||
            operationResult(operation).checkpoint_sha256 !== checkpoint
          )
            return false;
          return !operationReadingRecords().some((candidate) => {
            const submittedApproval =
              candidate.intent?.approved_plan_sha256 ||
              candidate.intent?.approved_scope_sha256 ||
              candidate.intent?.approved_repair_sha256 || candidate.submitted_approval_sha256;
            return (
              operationTarget(candidate) === deliveryId &&
              (projectId === null || operationProject(candidate) === projectId) &&
              operationAction(candidate) === "CONTINUE_DELIVERY" &&
              submittedApproval === approval.plan_sha256 &&
              candidate.updated_at.localeCompare(operation.updated_at) > 0
            );
          });
        },
      )
  );
  return operationResult(operation)?.approval || null;
};
const operationKey = () => `browser-${Date.now()}-${++actionSerial}`;
function deliveryControlUnavailableReason() {
  if (consoleMode === "inspection") return {
    title: "维护中 · 仅查看",
    reason: inspectionSummary,
    next_action: "需求线保持暂停。待平台维护完成并明确恢复交付后，再继续原需求。",
  };
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
  if (operationSummaryMode() && selectedOperationScope() &&
      operationDetailReadyScope !== selectedOperationScopeKey(selectedOperationScope())) return {
    title: "正在核对当前操作记录",
    reason: "平台正在读取当前需求的完整处理方案，暂不能使用此前的确认。",
    next_action: "请等待完整方案读取完成，再核对所列内容；原需求和开发进度保留。",
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
  if (teamReadIssue) return {
    title: teamReadIssue === "busy" ? "团队数据正在读取"
      : teamReadIssue === "timeout" ? "团队数据读取超时" : "团队数据读取失败",
    reason: (teamReadIssue === "busy" ? "上一轮团队数据读取尚未完成。"
      : teamReadIssue === "timeout" ? "本次团队数据读取超时，后台读取可能仍在进行。" : "本次团队数据暂时无法读取。") +
      "暂时无法核对最新的团队数据，当前操作已暂停；仍可阅读上次保存的需求和历史。",
    next_action: "页面会自动重试；成功读取后将重新核对当前项目、需求和审批，再恢复可用操作。原需求与已保存进度保留。",
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
  RETRY_REJECTED_CODER_OUTPUT: "保留进度并重新提交开发报告",
  REPLAY_RECORDED_RESULT: "使用已保存结果继续",
  RESUME_UNINVOKED: "继续未开始的工作",
  REVERIFY_CANDIDATE: "重新测试当前候选",
  RETRY_VERIFIER_PREPARATION: "重试验证准备",
  RETRY_KNOWLEDGE_PREPARATION: "扩大知识准备窗口并继续",
  RETRY_REJECTED_KNOWLEDGE_PREPARATION: "重新进行知识准备并继续",
  RETRY_REJECTED_WORKSPACE_ADMISSION: "修复工作区准入后继续原开发",
};
const engineeringAuthorizationLabels = {
  engineering_operator_decision: "工程负责人明确决定",
  organization_engineering_policy: "平台按已授权组织工程策略继续（不是人工批准）",
  human_decision: "人工精确批准",
};
function knowledgePreparationWindowLines(evidence) {
  if (!evidence || !["coder", "qa", "reviewer"].includes(evidence.role) ||
      !["intent", "assessment"].includes(evidence.phase) || evidence.budget_source !== "frozen_work_attempt" ||
      ![1, 2].includes(evidence.expansion_number) ||
      !["initial_timeout_seconds", "current_timeout_seconds", "next_timeout_seconds", "maximum_timeout_seconds"]
        .every(key => Number.isSafeInteger(evidence[key]) && evidence[key] >= 1 && evidence[key] <= 86400)) return [];
  const maximum = Math.min(evidence.initial_timeout_seconds * 4, 86400);
  const current = Math.min(evidence.initial_timeout_seconds * 2 ** (evidence.expansion_number - 1), maximum);
  if (evidence.maximum_timeout_seconds !== maximum || evidence.current_timeout_seconds !== current ||
      evidence.next_timeout_seconds !== Math.min(current * 2, maximum) || evidence.next_timeout_seconds <= current) return [];
  const role = {coder: "Coder", qa: "QA", reviewer: "Reviewer"}[evidence.role];
  const phase = {intent: "检索意图准备", assessment: "充分性评估"}[evidence.phase];
  return [
    `${role} 知识${phase}：本次窗口 ${current} 秒 → 下一次窗口 ${evidence.next_timeout_seconds} 秒。`,
    `冻结上限 ${maximum} 秒；本次扩窗 ${evidence.expansion_number}/2。`,
    "执行额度：使用 1 次原任务剩余的冻结工作额度，不重置已用额度。",
    "原需求、代码分支和已有开发进度保留；后续仍需独立 QA 和 Review，处理决定不代表验收通过。",
  ];
}
function matchingKnowledgePreparationEvidence(request, step, proof) {
  const evidence = proof?.knowledge_preparation;
  const facts = step.wait_disposition?.facts;
  if (!facts || facts.classification !== "KNOWLEDGE_PREPARATION_LIMIT" ||
      !knowledgePreparationWindowLines(evidence).length ||
      evidence.scope?.team_id !== snapshot?.team_id || evidence.scope?.project_id !== request.project_id ||
      (evidence.delivery_requirement_id ?? evidence.requirement_id) !== request.id || evidence.task_id !== proof.task_id ||
      evidence.work_item_id !== step.work_item_id || evidence.role !== step.role ||
      evidence.source_revision !== proof.source_revision || evidence.checkpoint_sequence !== proof.checkpoint_sequence) return null;
  const task = currentRequestTasks(request).find(item => item.task_id === proof.task_id);
  if (task?.scope?.root && evidence.scope.repository_root !== task.scope.root) return null;
  return evidence;
}
function rejectedKnowledgePreparationLines(evidence) {
  if (!evidence || evidence.role !== "coder" ||
      evidence.budget_source !== "frozen_work_attempt") return [];
  const role = {coder: "Coder", qa: "QA", reviewer: "Reviewer"}[evidence.role];
  return [
    `${role} 本轮知识评估未通过校验，主角色尚未开始。`,
    "继续使用 1 次原任务剩余的冻结工作额度，重新进行知识准备；执行时限保持。",
    "原需求、分支、开发进度、原知识结果和历史保留；后续仍需独立 QA 和 Review。",
  ];
}
function matchingRejectedKnowledgePreparationEvidence(request, step, proof) {
  const evidence = proof?.rejected_knowledge;
  const facts = step.wait_disposition?.facts;
  const task = currentRequestTasks(request).find(item => item.task_id === proof?.task_id);
  const requirementMatches = evidence?.requirement_id === request.id || task &&
    evidence?.requirement_id === task.id && request.scopes?.some(scope => scope.delivery_id === task.id);
  const carries = evidence?.carry_history_sha256s || [];
  if (!task || !facts || facts.classification !== "INVALID_OUTPUT" ||
      !rejectedKnowledgePreparationLines(evidence).length || !requirementMatches ||
      evidence.scope?.team_id !== snapshot?.team_id || evidence.scope?.project_id !== request.project_id ||
      evidence.task_id !== proof.task_id || evidence.work_item_id !== step.work_item_id ||
      evidence.role !== step.role || evidence.role !== facts.role ||
      evidence.source_revision !== proof.source_revision || evidence.checkpoint_sequence !== proof.checkpoint_sequence ||
      evidence.previous_run_id !== proof.original_run_id ||
      evidence.workspace_inventory_sha256 !== proof.workspace_inventory_sha256 ||
      !/^run_[a-z0-9][a-z0-9_-]{2,63}$/.test(evidence.previous_run_id || "") ||
      !/^ctx_[a-f0-9]{64}$/.test(evidence.previous_context_manifest_id || "") ||
      !["original_lease_id", "current_lease_id"].every(key => typeof evidence[key] === "string" && evidence[key].trim()) ||
      !Number.isSafeInteger(evidence.original_attempt) || evidence.original_attempt < 1 ||
      !["checkpoint_sequence", "original_dispatch_sequence", "current_dispatch_sequence"].every(key =>
        Number.isSafeInteger(evidence[key]) && evidence[key] >= 0) ||
      evidence.current_dispatch_sequence < evidence.original_dispatch_sequence ||
      !["original_claim_sha256", "observation_sha256", "context_sha256", "workspace_inventory_sha256",
        "workspace_capture_sha256", "current_claim_sha256"].every(key => /^[a-f0-9]{64}$/.test(evidence[key] || "")) ||
      (evidence.carry_refusal_sha256 != null && !/^[a-f0-9]{64}$/.test(evidence.carry_refusal_sha256)) ||
      !Array.isArray(carries) || carries.length > 511 || new Set(carries).size !== carries.length ||
      carries.some(value => !/^[a-f0-9]{64}$/.test(value)) ||
      (evidence.carry_refusal_sha256 && carries.at(-1) !== evidence.carry_refusal_sha256) ||
      (evidence.current_lease_id === evidence.original_lease_id && carries.length) ||
      ((evidence.current_lease_id !== evidence.original_lease_id ||
        evidence.current_claim_sha256 !== evidence.original_claim_sha256 ||
        evidence.current_dispatch_sequence !== evidence.original_dispatch_sequence) && !evidence.carry_refusal_sha256) ||
      facts.evidence_ids?.length !== 1 ||
      facts.evidence_ids[0] !== "knowledge-assessment-rejection://" + evidence.observation_sha256 ||
      proof.retry_cause != null || proof.invocation_start_sha256 != null || proof.invocation_outcome_sha256 != null) return null;
  if (task.scope?.root && evidence.scope.repository_root !== task.scope.root) return null;
  if (task.repository_id && evidence.scope.repository_id !== task.repository_id) return null;
  return evidence;
}
function rejectedWorkspaceAdmissionLines(evidence) {
  if (!evidence || evidence.role !== "coder" || evidence.reason !== "PRESERVED_PROGRESS_CAPTURE_MISMATCH" ||
      evidence.budget_source !== "frozen_work_attempt") return [];
  return [
    "平台在模型启动前拒绝了已批准的保留草稿与开发进度组合；修复后的完整准入已重新核验。",
    "继续使用 1 次原任务剩余的冻结工作额度，重新领取开发执行；执行时限保持。",
    "原需求、分支、全部草稿、已接纳进度和原失败历史保留；后续仍需独立 QA 和 Review。",
  ];
}
function matchingRejectedWorkspaceAdmissionEvidence(request, step, proof) {
  const evidence = proof?.rejected_workspace_admission;
  const facts = step.wait_disposition?.facts;
  const task = currentRequestTasks(request).find(item => item.task_id === proof?.task_id);
  const requirementMatches = evidence?.requirement_id === request.id || task &&
    evidence?.requirement_id === task.id && request.scopes?.some(scope => scope.delivery_id === task.id);
  if (!task || task.status !== "IMPLEMENTING" || task.terminal || !facts || !["NONTRANSIENT_INFRA", "PLATFORM_BUG", "INVALID_OUTPUT"].includes(facts.classification) ||
      !rejectedWorkspaceAdmissionLines(evidence).length || !requirementMatches ||
      evidence.scope?.team_id !== snapshot?.team_id || evidence.scope?.project_id !== request.project_id ||
      evidence.task_id !== proof.task_id || evidence.work_item_id !== step.work_item_id ||
      evidence.role !== step.role || evidence.role !== facts.role ||
      evidence.source_revision !== proof.source_revision || evidence.checkpoint_sequence !== proof.checkpoint_sequence ||
      evidence.run_id !== proof.original_run_id || evidence.invocation_start_sha256 !== proof.invocation_start_sha256 ||
      evidence.invocation_outcome_sha256 !== proof.invocation_outcome_sha256 ||
      evidence.workspace_inventory_sha256 !== proof.workspace_inventory_sha256 ||
      !/^run_[a-z0-9][a-z0-9_-]{2,63}$/.test(evidence.run_id || "") ||
      !/^ctx_[a-f0-9]{64}$/.test(evidence.context_manifest_id || "") ||
      !/^art_[a-z0-9][a-z0-9_-]{2,63}$/.test(evidence.progress_artifact_id || "") ||
      typeof evidence.lease_id !== "string" || !evidence.lease_id.trim() ||
      !Number.isSafeInteger(evidence.attempt) || evidence.attempt < 1 ||
      !["checkpoint_sequence", "dispatch_sequence"].every(key => Number.isSafeInteger(evidence[key]) && evidence[key] >= 0) ||
      !["claim_sha256", "invocation_start_sha256", "invocation_outcome_sha256", "route_attempt_sha256", "context_sha256",
        "baseline_binding_sha256", "baseline_plan_sha256", "progress_sha256", "workspace_inventory_sha256",
        "workspace_capture_sha256", "adapter_contract_sha256", "observation_sha256"].every(key => /^[a-f0-9]{64}$/.test(evidence[key] || "")) ||
      proof.retry_cause != null || proof.interruption_receipt_sha256 != null || proof.process_stop_sha256 != null) return null;
  if (task.scope?.root && evidence.scope.repository_root !== task.scope.root) return null;
  if (task.repository_id && evidence.scope.repository_id !== task.repository_id) return null;
  return evidence;
}
function rejectedCoderOutputLines(evidence) {
  if (!evidence || evidence.rejection_code !== "PROGRESS_SEQUENCE_MISMATCH" ||
      evidence.budget_source !== "frozen_work_attempt" ||
      !["requirement_id", "work_item_id", "original_lease_id", "source_revision"].every(key =>
        typeof evidence[key] === "string" && evidence[key].trim().length > 0) ||
      !/^task_[a-z0-9][a-z0-9_-]{2,63}$/.test(evidence.task_id || "") ||
      !/^run_[a-z0-9][a-z0-9_-]{2,63}$/.test(evidence.previous_run_id || "") ||
      !/^art_[a-z0-9][a-z0-9_-]{2,63}$/.test(evidence.rejected_artifact_id || "") ||
      !/^ctx_[a-f0-9]{64}$/.test(evidence.previous_context_manifest_id || "") ||
      !Number.isSafeInteger(evidence.original_dispatch_sequence) || evidence.original_dispatch_sequence < 0 ||
      !["original_attempt", "checkpoint_sequence", "expected_sequence", "reported_sequence"].every(key =>
        Number.isSafeInteger(evidence[key]) && evidence[key] >= 1) ||
      evidence.expected_sequence !== evidence.original_attempt || evidence.reported_sequence === evidence.expected_sequence ||
      !["original_claim_sha256", "invocation_start_sha256", "invocation_outcome_sha256", "rejected_artifact_sha256",
        "process_stop_sha256", "capture_sha256", "workspace_inventory_sha256", "checkpoint_sha256"]
        .every(key => /^[a-f0-9]{64}$/.test(evidence[key] || ""))) return [];
  return [
    "本轮开发报告的进度序号不符合执行约定，报告未被接纳。",
    "已核验原执行结束，并封存完整开发文件；继续使用原任务、分支和工作区。",
    "继续将消耗 1 次剩余开发额度，由 Coder 重新整理并提交报告；原错误报告和处理记录保留。",
    "这次处理不表示开发完成；后续仍需独立 QA 和 Review。",
  ];
}
function matchingRejectedCoderOutputEvidence(request, step, proof) {
  const evidence = proof?.rejected_output;
  const facts = step.wait_disposition?.facts;
  const task = currentRequestTasks(request).find(item => item.task_id === proof?.task_id);
  const requirementMatches = evidence?.requirement_id === request.id || task &&
    evidence?.requirement_id === task.id && request.scopes?.some(scope => scope.delivery_id === task.id);
  if (!task || !facts || step.role !== "coder" || facts.role !== "coder" ||
      !["PLATFORM_BUG", "INVALID_OUTPUT"].includes(facts.classification) ||
      !rejectedCoderOutputLines(evidence).length || !requirementMatches ||
      evidence.scope?.team_id !== snapshot?.team_id || evidence.scope?.project_id !== request.project_id ||
      evidence.task_id !== proof.task_id || evidence.work_item_id !== step.work_item_id ||
      evidence.source_revision !== proof.source_revision || evidence.checkpoint_sequence !== proof.checkpoint_sequence ||
      evidence.previous_run_id !== proof.original_run_id ||
      evidence.invocation_start_sha256 !== proof.invocation_start_sha256 ||
      evidence.invocation_outcome_sha256 !== proof.invocation_outcome_sha256 ||
      evidence.process_stop_sha256 !== proof.process_stop_sha256 ||
      evidence.workspace_inventory_sha256 !== proof.workspace_inventory_sha256 ||
      proof.retry_cause != null || proof.interruption_receipt_sha256 != null) return null;
  if (task.scope?.root && evidence.scope.repository_root !== task.scope.root) return null;
  if (task.repository_id && evidence.scope.repository_id !== task.repository_id) return null;
  return evidence;
}
function engineeringWaitHandlingLabel(step) {
  const classification = step.wait_disposition?.facts.classification;
  if (classification === "INVALID_OUTPUT" && step.wait_disposition?.facts.evidence_ids?.some(value =>
    /^knowledge-assessment-rejection:\/\/[a-f0-9]{64}$/.test(value))) return "让平台处理知识准备";
  if (classification === "KNOWLEDGE_PREPARATION_LIMIT") return "让平台处理知识准备";
  if (["PLATFORM_BUG", "INVALID_OUTPUT"].includes(classification)) return "让平台处理产出校验";
  return "让平台处理中断";
}
function knowledgePreparationWaitExhausted(step, proof) {
  return step.wait_disposition?.facts.classification === "KNOWLEDGE_PREPARATION_LIMIT" &&
    proof?.missing?.some(item => ["KNOWLEDGE_WINDOW_EXHAUSTED", "BUDGET_EXHAUSTED"].includes(item));
}
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
  KNOWLEDGE_PREPARATION_UNAVAILABLE: ["知识准备的执行记录不完整或未通过校验", "ASE 平台维护者", "核对原知识调用、实际结束记录和领取身份，修复记录关联或读取问题；保留原需求、代码进度和知识记录，不能靠重复执行绕过校验。", "平台修复知识准备记录后，再重新处理。"],
  KNOWLEDGE_WINDOW_EXHAUSTED: ["知识准备已达到冻结扩窗上限", "工程负责人", "检查知识输入或执行器耗时，修复后重新评估；原需求和全部历史保留，不会继续放大时限或重复必败执行。", "工程负责人完成知识输入或执行器耗时的原因修复，并重新评估资源方案后，再重新检查状态；本页没有追加窗口授权入口，重复检查不增加窗口。"],
};
const engineeringHandlingStatuses = new Set(["RESOLVED", "WAITING_EXECUTION", "NEEDS_AUTHORIZATION",
  "PLATFORM_ATTENTION", "WAITING_PREREQUISITES", "BUDGET_EXHAUSTED"]);
const engineeringCollectionFailureNotice = "部分执行事实已核验，但收集校验失败，当前不能继续。平台需处理校验问题后重新检查。";
function engineeringCaptureRefusal(proof, handling) {
  return handling?.collection_failed === true && handling.collection_failure === "WORKSPACE_CAPTURE_REJECTED" &&
    /^[a-f0-9]{64}$/.test(proof?.process_stop_sha256 || "") &&
    !proof?.missing?.includes("STOP_UNRECORDED") &&
    proof?.missing?.includes("CHECKPOINT_UNAVAILABLE") && !proof?.permitted_resolutions?.length;
}
function engineeringCollectionNotice(proof, handling) {
  return engineeringCaptureRefusal(proof, handling)
    ? "已核验原执行停止，但进度封存校验未通过。平台维护者修复后需要重新处理，当前不能直接继续。"
    : engineeringCollectionFailureNotice;
}
function engineeringMissingGuidance(item, captureRefused = false) {
  if (captureRefused && item === "OUTCOME_UNKNOWN") return [
    "原执行没有已接纳的完成结果", "ASE 平台", "原执行停止已核验，平台需在完整保留进度后接续开发。", "进度封存问题修复后重新处理。",
  ];
  if (captureRefused && item === "CHECKPOINT_UNAVAILABLE") return [
    "保留进度的完整封存未通过校验", "ASE 平台维护者", "修复完整进度封存校验问题；保留现有文件和停止记录，不能直接清空或重建需求。",
    consoleSupportsOperation("HANDLE_DELIVERY_WAIT") ? "平台修复后，点击“平台修复后重新处理”。" : "服务支持处理中断操作后，重新处理保留的进度。",
  ];
  return engineeringProofMissingGuidance[item] || [
    "平台返回了未识别的检查项", "平台维护者", "平台需要修复这项检查结果；当前不能安全继续。", "平台修复检查结果后再检查。",
  ];
}
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
function engineeringPendingBaselineSteps(request) {
  if (["DONE", "CLOSED"].includes(request.stage)) return [];
  return currentRequestTasks(request).filter(task => !task.terminal && task.status === "IMPLEMENTING").flatMap(task =>
    (task.role_queue || []).filter(step => {
      const authority = step.pending_baseline_continuation;
      return step.status === "READY" && step.role === "coder" && authority &&
        authority.scope?.team_id === snapshot?.team_id && authority.scope?.project_id === request.project_id &&
        (!task.scope?.root || authority.scope.repository_root === task.scope.root) &&
        authority.task_id === task.task_id && authority.task_revision === task.task_revision &&
        authority.task_intent_sha256 === task.task_intent_sha256 && authority.work_item_id === step.work_item_id &&
        authority.checkpoint_sequence === authority.task_revision &&
        /^[a-f0-9]{40}$/.test(authority.expected_source_revision || "") &&
        [authority.authorization_sha256, authority.execution_baseline_sha256, authority.expected_disposition_sha256]
          .every(value => /^[a-f0-9]{64}$/.test(value || "")) &&
        typeof authority.reference === "string" && authority.reference.length > 0;
    }).map(step => ({task, step})));
}
function engineeringAuthorizedContinuationIntent(request, step) {
  const authority = step.pending_baseline_continuation;
  return {action: "RESUME_EXECUTION_BASELINE", project_id: request.project_id, delivery_id: request.id,
    expected_checkpoint_sha256: request.checkpoint_sha256, task_id: authority.task_id,
    expected_task_intent_sha256: authority.task_intent_sha256, expected_task_revision: authority.task_revision,
    expected_work_item_id: authority.work_item_id, expected_source_revision: authority.expected_source_revision,
    expected_execution_baseline_sha256: authority.execution_baseline_sha256,
    expected_disposition_sha256: authority.expected_disposition_sha256, reference: authority.reference};
}
async function submitEngineeringAuthorizedContinuation(bound, authorizationSha256) {
  const request = requestById(bound.delivery_id);
  const {expected_checkpoint_sha256: _previousCheckpoint, ...authorizedInput} = bound;
  const current = request && engineeringPendingBaselineSteps(request).find(({step}) =>
    step.work_item_id === bound.expected_work_item_id &&
    step.pending_baseline_continuation.authorization_sha256 === authorizationSha256 &&
    sameEngineeringWaitIntent(engineeringAuthorizedContinuationIntent(request, step), authorizedInput));
  if (!current || !canControlCurrentTeam() || !consoleSupportsPausedBaseline() || activeOperation(request.id, request.project_id)) {
    operationNotice = {kind: "error", title: "已授权执行的状态已变化",
      message: "请查看当前需求；原继续决定只能接续同一份尚未启动的已授权执行。"};
    renderDetail(); renderNotification(); return null;
  }
  return submitOperation(engineeringAuthorizedContinuationIntent(request, current.step));
}
function engineeringAuthorizedContinuationBox(request, task, step) {
  const authority = step.pending_baseline_continuation;
  const bound = engineeringAuthorizedContinuationIntent(request, step);
  const preparing = matchingEngineeringResumeOperation(request, bound);
  const panel = viewGroup(el("section", undefined, "engineering-wait-panel engineering-baseline-continuation-pending"),
    "engineering-pending-continuation:" + step.work_item_id);
  panel.dataset.key = "engineering:" + step.work_item_id + ":pending-continuation";
  panel.append(viewBlock(el("h3", preparing ? "平台正在准备继续原需求" : "已授权执行等待接续"), "pending-continuation-title", Boolean(preparing)),
    viewBlock(el("p", preparing ? "继续决定已保存，平台正在准备继续；本轮主执行尚未开始。原需求和完整开发进度均保留，请等待执行记录更新，无需再次批准。" :
      "之前的继续决定已经保存，但平台尚未启动这份执行。保留进度和原需求均保持；点击下面按钮接续已授权执行，无需再次批准代码、规范或恢复方案。"),
      "pending-continuation-description", Boolean(preparing)));
  const active = activeOperation(request.id, request.project_id);
  const unavailable = deliveryControlUnavailableReason();
  if (unavailable) panel.append(deliveryControlUnavailableNotice(unavailable));
  else if (!consoleSupportsPausedBaseline()) panel.append(el("p", "当前服务不支持此接续入口。请在服务空闲时更新并重启，再刷新原需求。", "muted"));
  else if (active) panel.append(engineeringActiveOperationBox(request, active));
  else if (canControlCurrentTeam()) panel.append(deliveryButton("继续已授权执行", () =>
    submitEngineeringAuthorizedContinuation(bound, authority.authorization_sha256), "primary"));
  const detail = engineeringDetails("已保存的继续决定", step.work_item_id + ":pending-continuation");
  detail.append(el("p", "原任务 · " + task.task_id, "paths"),
    el("p", "原工作项 · " + step.work_item_id, "paths"),
    el("p", "继续决定 · " + authority.authorization_sha256, "paths"),
    el("p", "当前执行版本 · " + authority.expected_source_revision, "paths"));
  panel.append(detail);
  return panel;
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
    .find(item => actions.includes(operationAction(item)) &&
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
  const handling = operation?.status === "SUCCEEDED" && operationAction(operation) === "HANDLE_DELIVERY_WAIT"
    ? operationResult(operation)?.engineering_wait_handling : null;
  const proof = handling && matchingEngineeringWaitProof(handling.investigation, request, step);
  if (!handling || !proof || operationResult(operation).checkpoint_sha256 !== request.checkpoint_sha256 ||
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
  if (operation?.status !== "SUCCEEDED" || operationResult(operation)?.checkpoint_sha256 !== request.checkpoint_sha256) return null;
  return operationAction(operation) === "HANDLE_DELIVERY_WAIT" ? engineeringWaitHandlingFromOperation(operation, request, step)?.investigation || null
    : matchingEngineeringWaitProof(operationResult(operation)?.engineering_wait_investigation, request, step);
}
function engineeringWaitDecision(request, step, proof) {
  if (!proof) return null;
  const bound = engineeringWaitIntent(request, step);
  const handling = engineeringWaitHandling(request, step);
  const matchesKnowledge = decision => decision?.resolution_kind !== "RETRY_KNOWLEDGE_PREPARATION" ||
    matchingKnowledgePreparationEvidence(request, step, proof) &&
    sameEngineeringWaitProofFacts({knowledge_preparation: decision.knowledge_preparation},
      {knowledge_preparation: proof.knowledge_preparation});
  const matchesRejected = decision => decision?.resolution_kind !== "RETRY_REJECTED_CODER_OUTPUT" ||
    matchingRejectedCoderOutputEvidence(request, step, proof) &&
    sameEngineeringWaitProofFacts({rejected_output: decision.rejected_output}, {rejected_output: proof.rejected_output});
  const matchesRejectedKnowledge = decision => decision?.resolution_kind !== "RETRY_REJECTED_KNOWLEDGE_PREPARATION" ||
    matchingRejectedKnowledgePreparationEvidence(request, step, proof) &&
    sameEngineeringWaitProofFacts({rejected_knowledge: decision.rejected_knowledge},
      {rejected_knowledge: proof.rejected_knowledge});
  const matchesWorkspace = decision => decision?.resolution_kind !== "RETRY_REJECTED_WORKSPACE_ADMISSION" ||
    matchingRejectedWorkspaceAdmissionEvidence(request, step, proof) &&
    sameEngineeringWaitProofFacts({rejected_workspace_admission: decision.rejected_workspace_admission},
      {rejected_workspace_admission: proof.rejected_workspace_admission});
  if (handling?.status === "RESOLVED" && handling.resolution?.proof_sha256 === handling.investigation.proof_sha256 &&
      engineeringResolutionLabels[handling.resolution.resolution_kind] && matchesKnowledge(handling.resolution) &&
      matchesRejected(handling.resolution) && matchesRejectedKnowledge(handling.resolution) && matchesWorkspace(handling.resolution)) return handling.resolution;
  const operation = operations.find(item => item.status === "SUCCEEDED" &&
    operationAction(item) === "RESOLVE_DELIVERY_WAIT" && sameEngineeringWaitIntent(item.intent, bound) &&
    operationResult(item)?.engineering_wait_resolution?.proof_sha256 === proof.proof_sha256 &&
    matchesKnowledge(operationResult(item).engineering_wait_resolution) &&
    matchesRejected(operationResult(item).engineering_wait_resolution) &&
    matchesRejectedKnowledge(operationResult(item).engineering_wait_resolution) &&
    matchesWorkspace(operationResult(item).engineering_wait_resolution));
  return operationResult(operation)?.engineering_wait_resolution || null;
}
function engineeringWaitCanResolve(request, step, proof) {
  const handling = engineeringWaitHandling(request, step);
  const bound = engineeringWaitIntent(request, step);
  const lastHandling = [...operations].sort((a, b) => b.updated_at.localeCompare(a.updated_at))
    .find(item => operationAction(item) === "HANDLE_DELIVERY_WAIT" && sameEngineeringWaitIntent(item.intent, bound));
  const permission = !lastHandling || engineeringWaitHandlingFromOperation(lastHandling, request, step)?.manual_resolution_allowed === true;
  return proof && !proof.missing?.length && !engineeringWaitDecision(request, step, proof) &&
    permission &&
    (!handling || handling.status === "NEEDS_AUTHORIZATION" && handling.manual_resolution_allowed === true) &&
    (proof.permitted_resolutions || []).length > 0 &&
    proof.permitted_resolutions.every(kind => Boolean(engineeringResolutionLabels[kind]) &&
      (kind !== "RETRY_KNOWLEDGE_PREPARATION" || matchingKnowledgePreparationEvidence(request, step, proof)) &&
      (kind !== "RETRY_REJECTED_KNOWLEDGE_PREPARATION" || matchingRejectedKnowledgePreparationEvidence(request, step, proof)) &&
      (kind !== "RETRY_REJECTED_WORKSPACE_ADMISSION" || matchingRejectedWorkspaceAdmissionEvidence(request, step, proof)) &&
      (kind !== "RETRY_REJECTED_CODER_OUTPUT" || matchingRejectedCoderOutputEvidence(request, step, proof)));
}
async function submitEngineeringWaitOperation(intent) {
  const request = requestById(intent.delivery_id);
  const current = request && engineeringWaitSteps(request).find(({step}) =>
    sameEngineeringWaitIntent(intent, engineeringWaitIntent(request, step)));
  const proof = current && engineeringWaitProof(request, current.step);
  const completedPlan = current && engineeringCurrentCompletedPlan(request, current.task, current.step);
  if (!current || !canControlCurrentTeam() || !consoleSupportsOperation(intent.action) ||
      activeOperation(request.id, request.project_id) ||
      !["INSPECT_DELIVERY_WAIT", "HANDLE_DELIVERY_WAIT", "RESOLVE_DELIVERY_WAIT"].includes(intent.action) ||
      (intent.action !== "INSPECT_DELIVERY_WAIT" && completedPlan) ||
      (intent.action === "HANDLE_DELIVERY_WAIT" && knowledgePreparationWaitExhausted(current.step, proof)) ||
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
    const points = Array.isArray(description) ? description : description.split(/(?<=[。；])\s*|\n+/u);
    for (const point of points) {
      if (point.trim()) list.append(el("li", point.trim()));
    }
  }
  return list;
}
function engineeringActiveOperationBox(request, operation) {
  const queued = operation.status === "QUEUED";
  const progress = currentOperationProgress(operation, request);
  const panel = viewBlock(el("div", undefined, "engineering-operation-progress"),
    "engineering-active-operation", [operation, progress]);
  panel.setAttribute("role", "status");
  panel.setAttribute("aria-live", "polite");
  const heading = el("div", undefined, "engineering-operation-heading");
  heading.append(el("strong", queued ? "操作已排队" : "操作执行中"),
    el("span", queued ? "等待执行" : "执行中", "engineering-operation-state"));
  panel.append(heading, el("p", "当前操作 · " + operationActionLabel(operation), "engineering-operation-action"),
    el("p", queued ? "操作已接收，等待平台开始处理。"
      : progress?.title || "平台正在处理当前操作，完成后会更新检查结果与可用操作。", "muted"));
  return panel;
}
function appendEngineeringInvestigation(target, proof, {historical = false, collectionFailed = false, handling = null, legacyRescue = false, rescueFailure = null, controlUnavailable = null, rejectedOutputValid = false, rejectedKnowledgeValid = false, workspaceAdmissionValid = false} = {}) {
  const knowledgeWindow = !(proof.missing || []).length && proof.permitted_resolutions?.includes("RETRY_KNOWLEDGE_PREPARATION")
    ? knowledgePreparationWindowLines(proof.knowledge_preparation) : [];
  const rejectedKnowledge = !(proof.missing || []).length && proof.permitted_resolutions?.includes("RETRY_REJECTED_KNOWLEDGE_PREPARATION")
    ? rejectedKnowledgePreparationLines(proof.rejected_knowledge) : [];
  const workspaceLines = !(proof.missing || []).length && proof.permitted_resolutions?.includes("RETRY_REJECTED_WORKSPACE_ADMISSION")
    ? rejectedWorkspaceAdmissionLines(proof.rejected_workspace_admission) : [];
  if (historical) {
    for (const line of workspaceLines) target.append(el("p", "当次工作区准入方案 · " + line));
    target.append(el("p", "当次调查 · " + humanizeBlockingText(proof.next_action || "调查结果未提供处理建议。")),
      el("p", "这是该次调查保存的结果；当前原因与操作以页面上方为准。", "muted"));
    if (proof.missing?.length) target.append(el("p", "当次未完成项 · " + proof.missing.map(item =>
      engineeringProofMissingGuidance[item]?.[0] || "平台返回了未识别的检查项，不能据此继续").join("；")));
    for (const line of knowledgeWindow) target.append(el("p", "当次知识准备方案 · " + line));
    for (const line of rejectedKnowledge) target.append(el("p", "当次知识准备方案 · " + line));
    if (!(proof.missing || []).length && proof.permitted_resolutions?.includes("RETRY_REJECTED_CODER_OUTPUT"))
      for (const line of rejectedCoderOutputLines(proof.rejected_output)) target.append(el("p", "当次保留进度方案 · " + line));
    return;
  }
  const missing = proof.missing || [];
  if (collectionFailed) target.append(el("p", engineeringCollectionNotice(proof, handling), "error"));
  else if (/^[a-f0-9]{64}$/.test(proof.process_stop_sha256 || "") && !missing.includes("STOP_UNRECORDED"))
    target.append(el("p", "已核验原执行停止；结果与完整进度是否可复用，请查看下面的检查项。", "muted"));
  if (legacyRescue) {
    target.append(engineeringGuidanceList("旧执行没有留下完整结果、结束和现场记录，不能把它当作已完成，也不能靠重复调查补齐。",
      controlUnavailable ? "当前恢复操作不可用，具体原因和下一步见下方；操作恢复后须重新读取并核对方案，不能使用旧页面的审批。"
        : rescueFailure ? "本次恢复方案准备尚未完成，具体失败和平台处理下一步见下方；当前没有可批准的恢复方案。"
        : "可使用下方“保留进度的恢复方案”：平台检查当前本机执行并封存完整合法草稿，展示所需工程确认；授权后才可继续同一需求。"));
    return;
  }
  if (proof.provider_failure_code === "AUTHENTICATION_ERROR") {
    target.append(engineeringGuidanceList("原模型调用记录为认证失败，没有可接纳的开发报告；停止和完整进度仍由平台核验。",
      "请使用下方“准备保留进度的续跑方案”。方案准备后，先修复或核验原认证与执行器配置前提，再明确确认；原失败历史保留，不能通过重复调查改成成功或临时故障。"));
    return;
  }
  if (missing.length) {
    target.append(el("strong", "当前尚未解决的事项"));
    const list = el("ul", undefined, "engineering-wait-issues");
    for (const item of missing) {
      const [title, owner, action, recheck] = engineeringMissingGuidance(item, engineeringCaptureRefusal(proof, handling));
      const entry = el("li", undefined, "engineering-wait-issue");
      entry.append(el("strong", title), el("p", "处理方 · " + owner, "muted"), el("p", action),
        el("p", "何时复查 · " + recheck, "muted"));
      list.append(entry);
    }
    target.append(list);
  } else if (!collectionFailed) {
    const permitted = (proof.permitted_resolutions || []).map(item => engineeringResolutionLabels[item]).filter(Boolean);
    const known = permitted.length === proof.permitted_resolutions?.length &&
      (!proof.permitted_resolutions?.includes("RETRY_REJECTED_CODER_OUTPUT") || rejectedOutputValid) &&
      (!proof.permitted_resolutions?.includes("RETRY_REJECTED_KNOWLEDGE_PREPARATION") || rejectedKnowledgeValid) &&
      (!proof.permitted_resolutions?.includes("RETRY_REJECTED_WORKSPACE_ADMISSION") || workspaceAdmissionValid);
    target.append(el("p", permitted.length && known ? "检查已通过，可按以下方案继续 · " + permitted.join("、")
      : "当前没有可安全执行的继续方案，需平台维护者处理。"));
    for (const line of knowledgeWindow) target.append(el("p", line));
    if (known) for (const line of workspaceLines) target.append(el("p", line));
    if (known) for (const line of rejectedKnowledge) target.append(el("p", line));
    if (known && proof.permitted_resolutions?.includes("RETRY_REJECTED_CODER_OUTPUT"))
      for (const line of rejectedCoderOutputLines(proof.rejected_output)) target.append(el("p", line));
  }
}
function engineeringWaitCurrentFacts(request, step, proof, handling, decision, active) {
  const bound = engineeringWaitIntent(request, step);
  const activeHandling = operationAction(active) === "HANDLE_DELIVERY_WAIT" && sameEngineeringWaitIntent(active.intent, bound);
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
    user: `你可以点击“${engineeringWaitHandlingLabel(step)}”。如果需要额外授权，页面会明确列出待决定的方案。`,
  };
  const ownerTask = currentRequestTasks(request).find(item => item.task_id === step.wait_disposition.facts.task_id);
  const completedPlan = ownerTask && engineeringCurrentCompletedPlan(request, ownerTask, step);
  if (completedPlan) {
    facts.happened = completedOutputReportExplanation(completedPlan);
    facts.preservation = "完整合法草稿已封存，原任务、分支和工作区保留。" +
      (completedPlan.purpose === "source_rebind" ? "目标代码与项目规范变更须按本方案明确批准。" : "代码基线保持。");
    facts.platform = "可在精确工程批准后保存进度并预留新的开发执行，仍需独立 QA 和 Review。";
    facts.user = "查看下方恢复方案；批准后保持暂停，再明确继续原需求。";
  }
  const knowledge = matchingKnowledgePreparationEvidence(request, step, proof);
  const rejectedKnowledge = matchingRejectedKnowledgePreparationEvidence(request, step, proof);
  const rejected = matchingRejectedCoderOutputEvidence(request, step, proof);
  if (rejected) {
    facts.happened = "本轮开发报告的进度序号不符合执行约定，报告未被接纳。";
    facts.preservation = "原执行已结束，完整开发文件已封存；原任务、分支和工作区保留。";
    facts.platform = "可以使用 1 次剩余开发额度，让 Coder 在保留进度上重新提交报告；后续仍需独立 QA 和 Review。";
    facts.user = "查看下方保留进度方案；需要工程授权时，确认后继续。";
  }
  if (knowledge) {
    const role = {coder: "Coder", qa: "QA", reviewer: "Reviewer"}[knowledge.role];
    facts.happened = `${role} 知识准备达到本次执行时限，原执行已核验结束，主执行尚未开始。`;
    facts.preservation = "原需求、代码分支、已有开发进度和知识记录保留；不会清空工作区或重建需求。";
    if (!missing.length)
      facts.platform = `可使用 1 次原任务剩余的冻结工作额度，将下一次知识准备窗口扩大到 ${knowledge.next_timeout_seconds} 秒，再领取原任务继续。`;
  }
  if (rejectedKnowledge) {
    facts.happened = rejectedKnowledgePreparationLines(rejectedKnowledge)[0];
    facts.preservation = "原需求、分支、开发进度、原知识结果和历史保留。";
    facts.platform = "可使用 1 次原任务剩余的冻结工作额度，重新进行知识准备；执行时限保持。";
    facts.user = "查看知识准备方案；需要工程授权时，确认后继续，后续仍需独立 QA 和 Review。";
  }
  if (!completedPlan && /^[a-f0-9]{64}$/.test(proof?.process_stop_sha256 || "") &&
      !missing.includes("STOP_UNRECORDED") && missing.includes("CHECKPOINT_UNAVAILABLE")) {
    facts.happened = proof.retry_cause === "local_execution_limit"
      ? "本轮 Coder 达到本地执行时限后已停止，尚无可接纳的完成结果。"
      : "原执行停止已核验，完整结果与保留进度仍需平台核对。";
    facts.preservation = "原开发文件和停止记录已保留，尚未形成可安全复用的完整进度记录。平台不会自动清空原工作区。";
  }
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
    if (handling.status === "PLATFORM_ATTENTION" && !facts.user.includes("平台修复后重新处理"))
      facts.user += " 平台问题修复后，点击“平台修复后重新处理”，由平台重新核验并尝试继续原需求。";
  } else if (proof?.missing?.length) {
    facts.user = "你无需判断内部执行记录。可以让平台尝试处理；若平台仍无法继续，会说明处理方和具体事项。";
  } else if (engineeringWaitCanResolve(request, step, proof)) {
    facts.platform = "已检查原执行和保留进度，现有规则要求工程授权者确认所列方案后继续。";
    facts.user = "需要工程授权者确认按页面所列方案继续；不需要手工核验内部记录。";
  }
  if (missing.includes("KNOWLEDGE_WINDOW_EXHAUSTED") && !active && !decision) {
    facts.platform = "知识准备已达到冻结扩窗上限，当前不能继续扩大窗口或重复执行。";
    facts.user = engineeringProofMissingGuidance.KNOWLEDGE_WINDOW_EXHAUSTED[2];
  } else if (knowledgePreparationWaitExhausted(step, proof) && !active && !decision) {
    facts.platform = "本任务冻结的工作额度已用完，当前不能继续知识准备。";
    facts.user = "工程负责人需评估执行资源或结束交付；新的精确授权生效后再检查，重复处理不会重置额度。";
  }
  const task = engineeringWaitSteps(request).find(item => item.step.work_item_id === step.work_item_id)?.task;
  if (!completedPlan && !active && !decision && task && engineeringLegacyRescueFacts(request, task, step, proof, handling)) {
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
  if (completedPlan && !active && !decision) {
    facts.platform = "完整合法进度的恢复方案已准备，精确批准后保持暂停；仍需独立 QA 和 Review。";
    facts.user = consoleSupportsCompletedOutputRescue(completedOutputRejected(completedPlan))
      ? completedPlan.purpose === "source_rebind"
        ? "审阅下方目标代码和每项完整项目规范变更，批准更新基线并保持暂停；之后再明确继续原需求。"
        : "查看下方方案，点击“批准保留进度，保持暂停”，之后再明确继续原需求。"
      : "当前服务不支持此恢复审批入口。请在服务空闲时更新并重启，再查看原方案。";
  }
  const providerPlan = ownerTask && engineeringCurrentProviderPlan(request, ownerTask, step);
  if (ownerTask && engineeringStoppedProviderRetryFacts(request, ownerTask, step) && !active && !decision) {
    facts.happened = "原模型调用记录为认证失败，没有可接纳的开发报告。原失败历史保留。";
    facts.preservation = providerPlan ? providerPlan.purpose === "source_rebind"
      ? "平台已核验停止，并完整封存合法开发进度；原任务和分支保留，目标代码与项目规范待精确确认。"
      : "平台已核验停止，并完整封存合法开发进度；原任务、分支和代码基线保留。"
      : "原开发文件保留；平台还需核验原执行停止和完整进度，不会清空工作区。";
    facts.platform = providerPlan ? "可在确认原执行前提已修复后保留进度并预留新的开发执行，仍需独立 QA 和 Review。"
      : "可检查原执行和完整开发进度，准备保留进度的续跑方案；检查不启动 Coder。";
    facts.user = !consoleSupportsStoppedProviderRetry() ? "当前服务不支持此前提修复后的续跑入口，请在服务空闲时更新并重启。"
      : providerPlan ? engineeringProviderPlanNextAction(providerPlan)
      : "点击下方“准备保留进度的续跑方案”，查看平台核验结果；之后再确认前提已修复。";
  }
  if (ownerTask && engineeringStoppedExecutionRescueFacts(request, ownerTask, step) && !active && !decision) {
    const stoppedPlan = engineeringBaselinePlan(request, ownerTask, step, "stopped_execution_rescue");
    facts.happened = "原执行已保存真实停止记录，原调用结果仍未封存，不能据此判定开发完成或提供方故障。";
    facts.preservation = stoppedPlan ? "完整合法草稿已封存，原需求、任务、分支和代码基线保留。"
      : "原开发文件保留，平台需核验完整进度及真实停止证明。";
    facts.platform = stoppedPlan ? "已准备精确工程恢复方案，批准后消耗一次普通工作额度并保持暂停。"
      : "可以核验停止证明、完整开发文件及剩余额度，准备同一需求的恢复方案。";
    facts.user = !consoleSupportsStoppedExecutionRescue() ? "请在服务空闲时更新并刷新原需求。"
      : stoppedPlan ? "查看下方方案，批准保留进度并保持暂停；之后再明确继续原需求。"
      : "点击下方“检查停止后的保留进度”，查看平台核验结果。";
  }
  if (ownerTask && engineeringStoppedFailureRetryFacts(request, ownerTask, step) && !active && !decision) {
    const failurePlan = engineeringBaselinePlan(request, ownerTask, step, "stopped_failure_retry");
    facts.happened = "原模型调用失败，原因仍未知，没有可接纳的开发报告；原失败记录保留。";
    facts.preservation = failurePlan ? "平台已核验真实停止证明并完整封存合法草稿，原需求、任务、分支和代码基线保留。"
      : "原开发文件保留；平台仍需核验真实停止和完整合法进度。";
    facts.platform = failurePlan ? "精确工程方案已准备，批准后消耗一次普通工作额度并保持暂停；原失败原因仍未知。"
      : "可检查原执行停止、完整开发进度和剩余普通工作额度；检查不启动 Coder。";
    facts.user = !consoleSupportsStoppedFailureRetry() ? "请在服务空闲时更新并刷新原需求。"
      : failurePlan ? "查看下方方案，确认接受未知原因和一次普通工作额度，批准保持暂停后再独立明确继续。"
      : "点击下方“检查失败后的保留进度”，先查看平台核验结果。";
  }
  if (consoleAvailable === true && !consoleSupportsOperation("HANDLE_DELIVERY_WAIT")) {
    if (!active && !decision) {
      if (!handling) facts.platform = "当前页面的处理操作未获当前服务支持，请先更新运行中的服务。";
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
  const failureCurrent = engineeringWaitSteps(request).find(({task, step}) => task.task_id === handling.task_id &&
    step.work_item_id === handling.work_item_id && engineeringStoppedFailureRetryFacts(request, task, step));
  if (failureCurrent) {
    const {task, step} = failureCurrent;
    const plan = engineeringBaselinePlan(request, task, step, "stopped_failure_retry");
    const facts = engineeringWaitCurrentFacts(request, step, engineeringWaitProof(request, step), handling, null,
      activeOperation(request.id, request.project_id));
    const report = ["ASE 交付处理报告", "需求 · " + request.title, "当前原因 · " + facts.happened,
      "开发进度 · " + facts.preservation, "平台可以做什么 · " + facts.platform, "用户操作 · " + facts.user,
      ...(plan ? ["当前恢复方案 · " + plan.plan_sha256,
        "额度 · 批准消耗 1 次普通工作额度，不退还原执行额度；保持暂停后再独立继续，仍需独立 QA 和 Review。"] : []),
      "原处理结果 · " + humanizeBlockingText(handling.summary || "未提供"),
      "原执行 · " + (proof.original_run_id || "未核验"), "处理报告摘要 · " + handling.handling_sha256].join("\n");
    try {
      await navigator.clipboard.writeText(report);
      operationNotice = {kind: "info", title: "处理报告已复制", message: "报告包含当前方案、未知失败原因及原处理历史。"};
    } catch {
      operationNotice = {kind: "error", title: "无法复制处理报告", message: "请展开排障信息，选择处理说明和报告摘要复制。"};
    }
    renderNotification(); return;
  }
  const stoppedCurrent = engineeringWaitSteps(request).find(({task, step}) => task.task_id === handling.task_id &&
    step.work_item_id === handling.work_item_id && engineeringStoppedExecutionRescueFacts(request, task, step));
  if (stoppedCurrent) {
    const {task, step} = stoppedCurrent;
    const plan = engineeringBaselinePlan(request, task, step, "stopped_execution_rescue");
    const facts = engineeringWaitCurrentFacts(request, step, engineeringWaitProof(request, step), handling, null,
      activeOperation(request.id, request.project_id));
    const report = ["ASE 交付处理报告", "需求 · " + request.title, "当前原因 · " + facts.happened,
      "开发进度 · " + facts.preservation, "平台可以做什么 · " + facts.platform, "用户操作 · " + facts.user,
      ...(plan ? ["当前恢复方案 · " + plan.plan_sha256] : []),
      "原处理结果 · " + humanizeBlockingText(handling.summary || "未提供"),
      "原执行 · " + proof.original_run_id, "处理报告摘要 · " + handling.handling_sha256].join("\n");
    try {
      await navigator.clipboard.writeText(report);
      operationNotice = {kind: "info", title: "处理报告已复制", message: "报告包含当前恢复方案及原处理历史。"};
    } catch {
      operationNotice = {kind: "error", title: "无法复制处理报告", message: "请展开排障信息，选择处理说明和报告摘要复制。"};
    }
    renderNotification(); return;
  }
  const providerCurrent = engineeringWaitSteps(request).find(({task, step}) => task.task_id === handling.task_id &&
    step.work_item_id === handling.work_item_id && engineeringStoppedProviderRetryFacts(request, task, step));
  const providerPlan = providerCurrent && engineeringCurrentProviderPlan(request, providerCurrent.task, providerCurrent.step);
  const completedPlan = engineeringWaitSteps(request).filter(({task, step}) =>
    task.task_id === handling.task_id && step.work_item_id === handling.work_item_id)
    .map(({task, step}) => engineeringCurrentCompletedPlan(request, task, step)).find(Boolean);
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
    const [title, owner, action, recheck] = engineeringMissingGuidance(item, engineeringCaptureRefusal(proof, handling));
    return [(completedPlan || providerPlan ? "原调查记录事项 · " : "待处理事项 · ") + title, "处理方 · " + (failure ? "ASE 平台维护者" : rescue ? "ASE 平台与工程授权者" : owner),
      "具体处理 · " + (providerPlan ? "这是原调查保存的记录；当前续跑方案已核验停止并封存完整合法进度，原认证失败保持。先确认执行前提已修复，再按当前方案决定。"
        : completedPlan ? "这是原调查保存的缺项，当前精确恢复方案已补齐停止和进度核验；开发报告内容仍未知，按当前方案决定。"
        : controlUnavailable ? controlUnavailable.next_action
        : failure ? "先处理本次恢复方案准备失败；旧执行的缺失事实仍保留，不能通过重复调查补造。"
        : rescue ? "使用需求详情中的“准备保留进度的恢复方案”，由平台检查当前本机执行并封存合法草稿；查看检查结果后再决定，不补造原执行记录。" : action),
      "何时复查 · " + (completedPlan || providerPlan ? "当前恢复方案已准备，无需为了历史缺项重复调查。"
        : failure ? "平台修复本次失败后，再重新检查恢复前提。"
        : rescue ? "按恢复前提检查所列下一步处理后再检查；重复检查不会补出旧执行结果。" : recheck)].join("\n");
  });
  const report = ["ASE 交付处理报告", "需求 · " + request.title,
    ...(providerCurrent ? ["当前原因 · 原模型调用记录为认证失败，没有可接纳的开发报告，原失败历史保留。",
      "当前进度 · " + (providerPlan ? providerPlan.purpose === "source_rebind"
        ? "平台已核验停止并封存完整合法进度，原需求、任务和分支保留；目标代码与项目规范待精确确认。"
        : "平台已核验停止并封存完整合法进度，原需求、任务、分支和基线保留。" : "原开发文件保留，停止与完整进度仍需平台核验。"),
      ...(providerPlan ? ["当前续跑方案 · " + providerPlan.plan_sha256,
        ...(providerPlan.purpose === "source_rebind" ? ["目标代码版本 · " + providerPlan.target_base_ref] : []),
        "额度 · 批准后消耗 1 次普通开发额度，不退还原执行额度；保持暂停后再明确继续，仍需独立 QA 和 Review。"] : [])] : []),
    ...(completedPlan ? ["当前恢复结论 · " + completedOutputReportExplanation(completedPlan) + "完整合法草稿已封存。",
      "当前恢复方案 · " + completedPlan.plan_sha256, "额度 · 批准后预留 1 次普通开发执行，原执行不退款；批准后保持暂停，之后再明确继续。"] : []),
    ...(controlUnavailable ? ["操作可用性 · " + controlUnavailable.title + "；" + controlUnavailable.reason] : []),
    ...(handling.collection_failed === true ? [(completedPlan || providerPlan ? "原处理结果 · " : "当前结果 · ") + engineeringCollectionNotice(proof, handling)] : []),
    (completedPlan || providerPlan ? "原平台处理 · " : "本次处理 · ") + (failure ? `恢复方案准备${failure.status === "INTERRUPTED" ? "被中断" : "失败"}：${failure.summary}`
      : preparation?.summary || humanizeBlockingText(handling.summary || "未提供处理说明")),
    "用户操作 · " + (controlUnavailable ? controlUnavailable.next_action
      : providerCurrent ? activeOperation(request.id, request.project_id) ? "当前平台操作尚未结束，请等待结果。"
        : !consoleSupportsStoppedProviderRetry() ? "当前服务不支持此前提修复后的续跑入口，请在服务空闲时更新并重启。"
        : providerPlan ? engineeringProviderPlanNextAction(providerPlan)
        : "在当前需求点击“准备保留进度的续跑方案”，先查看平台核验结果；准备不启动开发。"
      : completedPlan ? activeOperation(request.id, request.project_id) ? "当前平台操作尚未结束，请等待结果更新；原进度和精确方案保留。"
        : consoleSupportsCompletedOutputRescue(completedOutputRejected(completedPlan)) ?
          completedPlan.purpose === "source_rebind" ? "审阅目标代码和每项完整项目规范变更，批准更新基线并保持暂停；之后再明确继续原需求。"
          : "查看当前需求中的精确恢复方案，点击“批准保留进度，保持暂停”；之后再明确继续原需求。"
        : "当前服务不支持此恢复审批入口，请在服务空闲时更新并重启，再查看原方案。"
      : handling.status === "PLATFORM_ATTENTION" && !consoleSupportsOperation("HANDLE_DELIVERY_WAIT") ? consoleOperationVersionMismatchMessage
      : failure ? failure.next_action
      : preparation?.next_action || (rescue ? "在当前需求详情点击“准备保留进度的恢复方案”；先看平台检查结果，方案准备完成后由工程授权者明确确认所列实际停止前提，再批准继续原需求。" : humanizeBlockingText(handling.user_action || "无"))),
    "复查时机 · " + (providerCurrent ? providerPlan ? "当前续跑方案已准备；先修复或核验原执行前提并确认，无需重复调查。" : "原执行停止和开发现场核验完成后查看方案；重复调查不能修复认证或配置。"
      : completedPlan ? "当前完整恢复方案已准备，无需重复调查；先核对当前方案和操作状态。"
      : failure ? "平台修复本次失败后，再重新检查恢复前提；重复调查不能修复内部异常。"
      : rescue ? "按恢复前提检查所列下一步处理后重新检查；旧执行结果仍保持未知。" : humanizeBlockingText(handling.recheck_when || "处理记录或执行前提更新后")),
    ...(!(proof?.missing || []).length && proof?.permitted_resolutions?.includes("RETRY_KNOWLEDGE_PREPARATION")
      ? knowledgePreparationWindowLines(proof.knowledge_preparation).map(line => "知识准备方案 · " + line) : []),
    ...(!(proof?.missing || []).length && proof?.permitted_resolutions?.includes("RETRY_REJECTED_KNOWLEDGE_PREPARATION")
      ? rejectedKnowledgePreparationLines(proof.rejected_knowledge).map(line => "知识准备方案 · " + line) : []),
    ...(!(proof?.missing || []).length && proof?.permitted_resolutions?.includes("RETRY_REJECTED_WORKSPACE_ADMISSION")
      ? rejectedWorkspaceAdmissionLines(proof.rejected_workspace_admission).map(line => "工作区准入方案 · " + line) : []),
    ...(!(proof?.missing || []).length && proof?.permitted_resolutions?.includes("RETRY_REJECTED_CODER_OUTPUT")
      ? rejectedCoderOutputLines(proof.rejected_output).map(line => "保留进度方案 · " + line) : []),
    ...(handling.resolution ? ["工程决定 · " + (engineeringResolutionLabels[handling.resolution.resolution_kind] || "当前继续方案未识别")] : []),
    ...(handling.resolution?.authorization_source ? ["授权来源 · " +
      (engineeringAuthorizationLabels[handling.resolution.authorization_source] || "授权来源未识别")] : []),
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
  if (step.wait_disposition?.facts.classification === "EXECUTION_BASELINE_PAUSED")
    return engineeringBaselinePauseBox(request, task, step);
  if (step.role === "coder" && step.wait_disposition?.facts.classification === "CONTEXT_CAPACITY")
    return engineeringContextCapacityBox(request, task, step);
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
  const completedPlan = engineeringCurrentCompletedPlan(request, task, step);
  const providerPlan = engineeringCurrentProviderPlan(request, task, step);
  const stoppedPlan = engineeringBaselinePlan(request, task, step, "stopped_execution_rescue");
  const failurePlan = engineeringBaselinePlan(request, task, step, "stopped_failure_retry");
  const stoppedFailureRetry = engineeringStoppedFailureRetryFacts(request, task, step);
  const providerRetry = engineeringStoppedProviderRetryFacts(request, task, step);
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
    const rejectedOutputValid = Boolean(matchingRejectedCoderOutputEvidence(request, step, proof));
    const rejectedKnowledgeValid = Boolean(matchingRejectedKnowledgePreparationEvidence(request, step, proof));
    const workspaceAdmissionValid = Boolean(matchingRejectedWorkspaceAdmissionEvidence(request, step, proof));
    const result = viewBlock(el("div", undefined, "engineering-investigation-result"), "engineering-wait-proof",
      [proof, collectionFailed, handling?.collection_failure || null, consoleSupportsOperation("HANDLE_DELIVERY_WAIT"), Boolean(rescue), rescueFailure, controlUnavailable, rejectedOutputValid, rejectedKnowledgeValid, workspaceAdmissionValid, completedPlan?.plan_sha256 || providerPlan?.plan_sha256 || stoppedPlan?.plan_sha256 || failurePlan?.plan_sha256 || null]);
    appendEngineeringInvestigation(result, proof, {historical: Boolean(completedPlan || providerPlan || stoppedPlan || failurePlan), collectionFailed, handling, legacyRescue: Boolean(rescue), rescueFailure, controlUnavailable, rejectedOutputValid, rejectedKnowledgeValid, workspaceAdmissionValid});
    management.append(result);
  }
  if (controlUnavailable) management.append(deliveryControlUnavailableNotice(controlUnavailable));
  const actionRow = viewGroup(el("div", undefined, "engineering-wait-action-row"), "engineering-wait-action-row");
  if (decision) {
    management.append(el("p", "继续决定已记录；实际进度与验收以新的执行记录为准。", "muted"));
  } else if (canControlCurrentTeam() && !running) {
    const canResolve = engineeringWaitCanResolve(request, step, proof);
    const actions = viewBlock(el("div", undefined, "engineering-wait-actions"), "engineering-wait-actions",
      [bound, proof, handling, Boolean(rescue), canResolve, canControlCurrentTeam(), consoleOperationContractVersion, consoleSupportedActions, completedPlan?.plan_sha256 || providerPlan?.plan_sha256 || failurePlan?.plan_sha256 || null, Boolean(providerRetry), Boolean(stoppedFailureRetry)]);
    if (!completedPlan && !providerRetry && !stoppedFailureRetry && consoleSupportsOperation("HANDLE_DELIVERY_WAIT") && !canResolve && !knowledgePreparationWaitExhausted(step, proof) &&
      !["NEEDS_AUTHORIZATION", "PLATFORM_ATTENTION", "BUDGET_EXHAUSTED", "WAITING_PREREQUISITES"].includes(handling?.status))
      actions.append(deliveryButton(engineeringWaitHandlingLabel(step), () => submitEngineeringWaitOperation({
        ...bound, action: "HANDLE_DELIVERY_WAIT",
      }), "primary"));
    if (!completedPlan && !providerRetry && !stoppedFailureRetry && consoleSupportsOperation("HANDLE_DELIVERY_WAIT") && !canResolve && !knowledgePreparationWaitExhausted(step, proof) && handling?.status === "PLATFORM_ATTENTION")
      actions.append(deliveryButton("平台修复后重新处理", () => submitEngineeringWaitOperation({
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
    actionRow.append(actions);
  } else if (running) {
    management.append(el("p", "操作尚未结束；原等待只有在新的执行事实成立后才解除。", "muted"));
  }
  if (handling?.status === "PLATFORM_ATTENTION") actionRow.append(viewBlock(button("复制处理报告", () =>
    copyEngineeringWaitReport(request, handling), "secondary engineering-wait-report"), "engineering-wait-report", [request.title, handling]));
  if (actionRow.children.length) management.append(actionRow);
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
  appendEngineeringCompletedOutputRescue(management, request, task, step);
  appendEngineeringStoppedExecutionRescue(management, request, task, step);
  appendEngineeringStoppedProviderRetry(management, request, task, step);
  appendEngineeringStoppedFailureRetry(management, request, task, step);
  if (!completedPlan) appendEngineeringLegacyRescue(management, request, task, step, proof, handling);
  management.append(technical);
  return management;
}
function engineeringBaselinePauseFacts(request, task, step) {
  const baseline = engineeringBaselineFacts(request, task, step);
  const facts = step.wait_disposition?.facts;
  if (!baseline || step.status !== "WAITING_HUMAN" ||
      facts.classification !== "EXECUTION_BASELINE_PAUSED" ||
      step.wait_disposition.action !== "RESUME_EXECUTION_BASELINE" ||
      !/^[a-f0-9]{64}$/.test(facts.execution_baseline_sha256 || "") ||
      !/^[a-f0-9]{64}$/.test(step.wait_disposition_sha256 || "")) return null;
  return {...baseline, expected_execution_baseline_sha256: facts.execution_baseline_sha256,
    expected_disposition_sha256: step.wait_disposition_sha256};
}
async function submitEngineeringBaselineContinuation(bound) {
  const request = requestById(bound.delivery_id);
  const current = request && engineeringWaitSteps(request).find(({task, step}) =>
    sameEngineeringWaitIntent(engineeringBaselinePauseFacts(request, task, step), bound));
  if (!current || request.project_id !== snapshot?.selected_project_id || !canControlCurrentTeam() || !consoleSupportsPausedBaseline() ||
      activeOperation(request.id, request.project_id)) {
    operationNotice = {kind: "error", title: "保留进度的暂停已变化",
      message: "请查看当前需求和精确执行基线；旧的继续入口不能启动执行。"};
    renderDetail(); renderNotification(); return null;
  }
  return submitOperation({...bound, action: "RESUME_EXECUTION_BASELINE",
    reference: "工程授权者明确继续当前已保存的完整进度和已批准代码及项目规范基线"});
}
function engineeringBaselinePauseBox(request, task, step) {
  const bound = engineeringBaselinePauseFacts(request, task, step);
  const preparing = bound && matchingEngineeringResumeOperation(request, bound);
  const panel = viewGroup(el("section", undefined, "engineering-wait-panel engineering-baseline-pause"),
    "engineering-pause:" + step.work_item_id);
  panel.dataset.key = "engineering:" + step.work_item_id + ":pause";
  panel.append(viewBlock(el("h3", preparing ? "平台正在准备继续原需求" : "进度已保留 · 交付暂停"), "pause-title", Boolean(preparing)),
    viewBlock(engineeringGuidanceList(preparing ? [
      "继续操作已接纳，平台正在准备继续；本轮主执行尚未开始。",
      "完整开发进度和原执行历史已保留，请等待执行记录更新，无需再次点击继续。",
    ] : [
      "完整开发进度和原执行历史已保留，没有启动新的 Coder。",
      "如需纳入最新代码与规范，先在下面准备并批准基线更新；更新后仍保持暂停。",
      "确认当前执行基线后，点击“继续原需求”，使用已经预留的执行身份接续开发，再进行独立 QA 和 Review。",
    ]),
    "pause-description", Boolean(preparing)));
  if (!bound) {
    panel.append(el("p", "当前暂停记录缺少完整绑定。请刷新页面；仍缺失时由平台维护者核验，不能直接继续。", "error"));
    return panel;
  }
  const active = activeOperation(request.id, request.project_id);
  const unavailable = deliveryControlUnavailableReason();
  if (unavailable) panel.append(deliveryControlUnavailableNotice(unavailable));
  else if (!consoleSupportsPausedBaseline()) panel.append(el("p",
    "当前服务不支持保留进度后暂停并单独继续。请在服务空闲时更新并重启，再刷新原需求。", "muted"));
  const savedSource = viewBlock(el("div", undefined, "engineering-paused-source"), "pause-saved-source", [bound, Boolean(preparing)]);
  savedSource.append(el("strong", "继续使用的代码版本"),
    el("p", bound.expected_source_revision, "paths"),
    el("p", preparing ? "平台正在按此已批准版本和保留的开发进度准备执行，实际角色启动以新的执行记录为准。" :
      "这是当前已保存的执行输入。点击“继续原需求”将使用此版本和保留的开发进度；更新代码需要先确认新的方案。", "muted"));
  panel.append(savedSource);
  appendEngineeringBaseline(panel, request, task, step);
  const continuation = viewBlock(el("div", undefined, "engineering-baseline-actions"), "pause-continue",
    [bound, active, active && currentOperationProgress(active, request), canControlCurrentTeam(), consoleOperationContractVersion, consoleSupportedActions]);
  if (active) continuation.append(engineeringActiveOperationBox(request, active));
  else if (canControlCurrentTeam() && consoleSupportsPausedBaseline()) continuation.append(
    deliveryButton("继续原需求", () => submitEngineeringBaselineContinuation(bound), "primary"));
  panel.append(continuation);
  return panel;
}
function matchingEngineeringResumeOperation(request, bound) {
  const operation = activeOperation(request.id, request.project_id);
  if (!operation || operationAction(operation) !== "RESUME_EXECUTION_BASELINE" || !bound) return null;
  // The requirement journal can advance after acceptance; Task/work/baseline and
  // disposition identities must remain exact. An unrelated operation proves nothing.
  const {expected_checkpoint_sha256: _checkpoint, ...identity} = bound;
  return sameEngineeringWaitIntent(operation.intent, identity) ? operation : null;
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
function engineeringContextCapacityFacts(request, task, step) {
  const baseline = engineeringBaselineFacts(request, task, step);
  const facts = step.wait_disposition?.facts;
  const evidence = facts?.evidence_ids;
  if (!baseline || facts.classification !== "CONTEXT_CAPACITY" || facts.role !== "coder" ||
      !["WAITING_HUMAN", "WAITING_DEPENDENCY"].includes(step.status) ||
      step.wait_disposition.responsibility !== "engineering" ||
      task.project_id !== request.project_id || task.request_id !== request.id ||
      ["DONE", "CLOSED"].includes(request.stage) ||
      !/^[a-f0-9]{64}$/.test(request.checkpoint_sha256 || "") ||
      !/^[a-f0-9]{64}$/.test(step.wait_disposition_sha256 || "") ||
      !Array.isArray(evidence) || evidence.length !== 1 ||
      !/^context-capacity:\/\/[a-f0-9]{64}$/.test(evidence[0])) return null;
  return {baseline, receipt_sha256: evidence[0].slice("context-capacity://".length),
    disposition_sha256: step.wait_disposition_sha256};
}
function matchingContextCapacityPlan(plan, bound, operation) {
  const facts = plan.facts;
  const base = plan.previous_binding?.execution_base_ref || facts.task.base_ref;
  return !Object.hasOwn(operation.intent, "target_base_ref") &&
    plan.input_mode === "preserve_draft" && !plan.conflicted &&
    plan.target_base_ref === base && plan.prepared_source_revision === bound.baseline.expected_source_revision &&
    facts.context_capacity_receipt_sha256 === bound.receipt_sha256 &&
    !facts.native_rule_change && !facts.legacy_containment && !facts.completed_output && !facts.stopped_provider_failure && !facts.stopped_failure;
}
async function submitEngineeringContextCapacityOperation(intent, original) {
  const request = requestById(intent.delivery_id);
  const current = request && engineeringWaitSteps(request).find(({task, step}) => {
    const facts = engineeringContextCapacityFacts(request, task, step);
    return facts && sameEngineeringWaitIntent(facts.baseline, original.baseline) &&
      facts.receipt_sha256 === original.receipt_sha256 && facts.disposition_sha256 === original.disposition_sha256;
  });
  if (!consoleSupportsContextCapacityResume()) {
    operationNotice = {kind: "error", title: "当前服务不支持保留原代码版本的容量恢复",
      message: "请在当前操作和角色执行结束、服务空闲时更新服务，再刷新原需求。原进度和历史保留。"};
    renderDetail(); renderNotification(); return null;
  }
  const plan = current && engineeringBaselinePlan(request, current.task, current.step, "context_capacity_resume");
  const propose = intent.action === "PROPOSE_EXECUTION_BASELINE";
  const execute = intent.action === "EXECUTE_EXECUTION_BASELINE";
  if (!current || intent.project_id !== original.baseline.project_id ||
      request.project_id !== snapshot?.selected_project_id || !canControlCurrentTeam() ||
      activeOperation(request.id, request.project_id) ||
      ["approved_native_rule_change_sha256", "confirm_provider_prerequisites_repaired", "confirm_local_execution_stopped",
        "confirm_legacy_containment", "target_base_ref"].some(key => Object.hasOwn(intent, key)) ||
      propose && (!sameEngineeringWaitIntent(intent, original.baseline) ||
        intent.purpose !== "context_capacity_resume" || intent.input_mode !== "preserve_draft") ||
      execute && (!plan || plan.plan_sha256 !== intent.expected_plan_sha256 || intent.continuation_mode !== "pause" ||
        intent.expected_checkpoint_sha256 !== request.checkpoint_sha256 || intent.task_id !== current.task.task_id) || !propose && !execute) {
    operationNotice = {kind: "error", title: "容量恢复事实已变化",
      message: "请查看当前需求并重新核对恢复方案。旧页面不能批准或继续新的执行现场。"};
    renderDetail(); renderNotification(); return null;
  }
  return submitOperation(intent);
}
function engineeringContextCapacityBox(request, task, step) {
  const bound = engineeringContextCapacityFacts(request, task, step);
  const plan = bound && engineeringBaselinePlan(request, task, step, "context_capacity_resume");
  const operation = bound && engineeringBaselineProposalOperation(bound.baseline, "context_capacity_resume");
  const active = activeOperation(request.id, request.project_id);
  const unavailable = deliveryControlUnavailableReason();
  const panel = viewGroup(el("section", undefined, "engineering-wait-panel engineering-capacity-resume"),
    "engineering-capacity:" + step.work_item_id);
  panel.dataset.key = "engineering:" + step.work_item_id + ":capacity";
  const phase = !bound ? "incomplete" : plan ? "ready" : "waiting";
  panel.append(viewBlock(el("h3", !bound ? "容量等待记录不完整 · 交付暂停" :
    plan ? "恢复方案已准备 · 等待确认" : "输入超过模型容量 · 交付暂停"), "capacity-title", phase),
    viewBlock(engineeringGuidanceList(!bound ? [
      "平台还不能核对当前容量等待与原开发现场。原需求和进度保留，完整记录恢复后再准备方案。",
    ] : plan ? [
      "平台已核验本次容量等待，完整合法开发进度已封存。原需求、分支、工作区和代码版本保持。",
      "批准只保存本次精确恢复决定，交付保持暂停；之后再点击“继续原需求”，平台重新检查输入并接续开发。",
      "本轮主开发调用尚未开始，后续仍需独立测试与评审。原容量记录和完整执行历史保留。",
    ] : [
      "本次模型输入超过容量，本轮主开发调用尚未开始。由 ASE 平台修复模型输入准备或执行配置后再检查。",
      "原需求、分支、已有开发文件和执行历史保留。准备方案会重新核验完整现场，不要求填写代码版本。",
      "平台修复后，点击“准备保留进度的恢复方案”；查看结果并批准保持暂停，之后再明确继续原需求。",
    ]), "capacity-description", phase));
  if (!bound) {
    panel.append(viewBlock(el("p", "当前容量等待缺少完整记录。请刷新原需求；仍缺失时由平台修复记录读取，不能直接批准或继续。", "error"),
      "capacity-incomplete", true));
    return panel;
  }
  if (plan) {
    const summary = viewBlock(el("div"), "capacity-summary", [plan, bound.receipt_sha256]);
    summary.append(el("p", "原需求分支 · " + plan.facts.task.branch_name, "paths"));
    const detail = engineeringDetails("恢复方案核对信息", step.work_item_id + ":capacity-plan");
    detail.append(el("p", "代码版本保持 · " + plan.target_base_ref, "paths"),
      el("p", "精确方案 · " + plan.plan_sha256, "paths"),
      el("p", "容量记录 · " + bound.receipt_sha256, "paths"));
    summary.append(detail);
    panel.append(summary);
  } else if (["FAILED", "INTERRUPTED"].includes(operation?.status)) {
    panel.append(viewBlock(el("p", "恢复方案尚未准备完成 · " + humanizeBlockingText(operation.error_summary || "平台未能完成本次核验。") +
      " 原需求和文件保留；处理本次原因后再重新准备。", "error"), "capacity-failure", operationRenderFact(operation)));
  }
  if (unavailable) panel.append(viewBlock(deliveryControlUnavailableNotice(unavailable), "capacity-control-unavailable", unavailable));
  else if (!consoleSupportsContextCapacityResume()) panel.append(viewBlock(el("p",
    "当前服务不支持保留原代码版本的容量恢复。请在当前操作和角色执行结束、服务空闲时更新服务，再刷新原需求；无需新建需求或填写代码版本。", "muted"),
    "capacity-unsupported", [consoleOperationContractVersion, consoleSupportedActions]));
  else if (active) panel.append(engineeringActiveOperationBox(request, active));
  else if (canControlCurrentTeam()) {
    const actions = viewBlock(el("div", undefined, "engineering-baseline-actions"), "capacity-actions",
      [bound, plan, Boolean(operation), pollingControlFacts()]);
    if (plan) {
      const planSha256 = plan.plan_sha256;
      actions.append(deliveryButton("批准保留进度，保持暂停", () => submitEngineeringContextCapacityOperation({
        action: "EXECUTE_EXECUTION_BASELINE", project_id: request.project_id, delivery_id: request.id,
        expected_checkpoint_sha256: bound.baseline.expected_checkpoint_sha256, task_id: task.task_id,
        expected_plan_sha256: planSha256, continuation_mode: "pause",
        reference: "批准保留完整开发进度，代码版本保持，交付保持暂停；之后另行明确继续原需求",
      }, bound), "primary"));
    }
    actions.append(deliveryButton(operation ? "重新准备保留进度的恢复方案" : "准备保留进度的恢复方案", () =>
      submitEngineeringContextCapacityOperation({...bound.baseline, action: "PROPOSE_EXECUTION_BASELINE",
        purpose: "context_capacity_resume", input_mode: "preserve_draft"}, bound), plan ? "secondary" : "primary"));
    panel.append(actions);
  }
  appendEngineeringBaseline(panel, request, task, step);
  return panel;
}
function engineeringBaselinePlan(request, task, step, purpose = "source_rebind") {
  const bound = engineeringBaselineFacts(request, task, step);
  if (!bound) return null;
  const operation = engineeringBaselineProposalOperation(bound, purpose);
  const plan = operation?.status === "SUCCEEDED" ? operationResult(operation)?.execution_baseline_plan : null;
  if (!plan || operationResult(operation).checkpoint_sha256 !== request.checkpoint_sha256 ||
      (plan.purpose || "source_rebind") !== purpose ||
      !/^[a-f0-9]{64}$/.test(plan.plan_sha256 || "") ||
      plan.facts?.task?.id !== bound.task_id || plan.facts.task_revision !== bound.expected_task_revision ||
      plan.facts.work_item_id !== bound.expected_work_item_id ||
      plan.dirty_capture?.source_revision !== bound.expected_source_revision ||
      (!["completed_output_rescue", "stopped_provider_retry", "context_capacity_resume", "stopped_execution_rescue", "stopped_failure_retry"].includes(purpose) && plan.target_base_ref !== operation.intent?.target_base_ref) ||
      plan.input_mode !== operation.intent?.input_mode ||
      !["preserve_draft", "coder_reapply"].includes(plan.input_mode)) return null;
  if (purpose === "completed_output_rescue" && !matchingCompletedOutputRescuePlan(plan, bound, operation)) return null;
  if (purpose === "stopped_provider_retry" && !matchingStoppedProviderRetryPlan(plan, bound, operation)) return null;
  if (purpose === "stopped_failure_retry" && (!matchingStoppedFailureRetryPlan(plan, bound, operation) ||
      engineeringWaitProof(request, step)?.original_run_id &&
      plan.facts.stopped_failure.outcome.start.request.run_id !== engineeringWaitProof(request, step).original_run_id)) return null;
  if (purpose === "stopped_execution_rescue" && (!matchingStoppedExecutionRescuePlan(plan, bound, operation) ||
      plan.facts.stopped_execution.invocation_start.request.run_id !== engineeringWaitProof(request, step)?.original_run_id)) return null;
  if (purpose === "context_capacity_resume") {
    const capacity = engineeringContextCapacityFacts(request, task, step);
    if (!capacity || !matchingContextCapacityPlan(plan, capacity, operation)) return null;
  }
  if (purpose === "source_rebind" && plan.facts.stopped_provider_failure &&
      !matchingStoppedProviderRetryPlan(plan, bound, operation, false)) return null;
  if (purpose === "source_rebind" && plan.facts.completed_output &&
      !matchingCompletedOutputRescuePlan(plan, bound, operation, false)) return null;
  if (purpose !== "stopped_failure_retry" && plan.facts.stopped_failure) return null;
  return plan;
}
function engineeringCurrentProviderPlan(request, task, step) {
  const bound = engineeringBaselineFacts(request, task, step);
  if (!bound) return null;
  // Both purposes retain their own strict matcher and submission contract.
  // Only their already validated plan and Operation are combined for display.
  const candidates = ["stopped_provider_retry", "source_rebind"].flatMap(purpose => {
    const plan = engineeringBaselinePlan(request, task, step, purpose);
    const operation = engineeringBaselineProposalOperation(bound, purpose);
    return plan?.facts.stopped_provider_failure ? [{plan, operation}] : [];
  });
  candidates.sort((a, b) => b.operation.updated_at.localeCompare(a.operation.updated_at) ||
    b.operation.operation_id.localeCompare(a.operation.operation_id));
  return candidates[0]?.plan || null;
}
function engineeringProviderPlanNextAction(plan) {
  if (plan.purpose === "source_rebind") return plan.conflicted
    ? "查看当前基线方案的冲突，点击“提出 Coder 适配完整旧补丁的计划”，再审阅新方案并确认原认证与执行器配置前提。"
    : "先修复或核验原认证与执行器配置前提，并审阅目标代码与每项完整项目规范变更；分别勾选所需确认后，点击“批准更新基线，保持暂停”；之后明确继续原需求。";
  return "先修复或核验原认证与执行器配置前提，再在当前需求勾选确认并点击“确认前提已修复，保留进度”；批准后保持暂停，之后明确继续原需求。";
}
function matchingStoppedProviderRetryPlan(plan, bound, operation, sameSource = true) {
  const proof = plan.facts.stopped_provider_failure;
  const start = proof?.outcome?.start;
  const request = start?.request;
  const result = proof?.outcome?.result;
  const capture = proof?.capture_start;
  const stop = proof?.capture_stop;
  const reservation = plan.facts.continuation;
  const base = plan.previous_binding?.execution_base_ref || plan.facts.task.base_ref;
  return proof?.kind === "stopped_provider_failure" && /^[a-f0-9]{64}$/.test(proof.proof_sha256 || "") &&
    request?.task_id === bound.task_id && request.role === "coder" && request.source_revision === bound.expected_source_revision &&
    start.work_item_id === bound.expected_work_item_id && start.checkpoint_sequence === bound.expected_task_revision &&
    typeof request.run_id === "string" && request.run_id.length > 0 && result?.status === "FAILED" &&
    result.artifact == null && result.error?.code === "AUTHENTICATION_ERROR" && result.error.transient === false &&
    capture?.request?.run_id === request.run_id && capture.request.task_id === bound.task_id &&
    capture.request.source_revision === bound.expected_source_revision && capture.task_revision === bound.expected_task_revision &&
    capture.worktree_path === plan.dirty_capture.worktree_path && stop?.task_id === bound.task_id && stop.run_id === request.run_id &&
    stop.capture_start_sha256 === capture.start_sha256 && stop.process_stop?.kind === "failed" &&
    Number.isInteger(stop.process_stop.returncode) && stop.process_stop.returncode !== 0 && stop.output_present === false &&
    !stop.cause && [null, undefined, "AUTHENTICATION_ERROR"].includes(stop.original_error_code) && reservation?.retry_cause === "provider_prerequisite_repaired" &&
    reservation.stopped_provider_failure_sha256 === proof.proof_sha256 && !plan.facts.completed_output &&
    !plan.facts.legacy_containment && !plan.facts.stopped_failure && !plan.facts.implementation_artifact_id &&
    (!sameSource || !plan.facts.native_rule_change && plan.target_base_ref === base &&
      plan.prepared_source_revision === bound.expected_source_revision && operation.intent?.target_base_ref == null) &&
    (!sameSource || plan.input_mode === "preserve_draft" && !plan.conflicted);
}
function engineeringStoppedProviderRetryFacts(request, task, step) {
  const bound = engineeringBaselineFacts(request, task, step);
  const proof = engineeringWaitProof(request, step);
  const plan = engineeringCurrentProviderPlan(request, task, step);
  if (!bound || step.wait_disposition.facts.classification === "EXECUTION_BASELINE_PAUSED" ||
      !["TRANSIENT_INFRA", "NONTRANSIENT_INFRA", "PLATFORM_BUG", "EXECUTION_UNCERTAIN"].includes(step.wait_disposition.facts.classification) ||
      proof?.knowledge_preparation || proof?.rejected_knowledge || proof?.rejected_workspace_admission || proof?.rejected_output || proof?.interruption_receipt_sha256 ||
      proof?.permitted_resolutions?.length || proof?.missing?.includes("BUDGET_EXHAUSTED") ||
      !plan && (proof?.provider_failure_code !== "AUTHENTICATION_ERROR" ||
        !/^[a-f0-9]{64}$/.test(proof.invocation_outcome_sha256 || ""))) return null;
  return bound;
}
async function submitEngineeringStoppedProviderRetry(intent, originalBound) {
  const request = requestById(intent.delivery_id);
  const current = request && engineeringWaitSteps(request).find(({task, step}) =>
    sameEngineeringWaitIntent(engineeringStoppedProviderRetryFacts(request, task, step), originalBound));
  const plan = current && engineeringBaselinePlan(request, current.task, current.step, "stopped_provider_retry");
  const providerPlan = current && engineeringCurrentProviderPlan(request, current.task, current.step);
  const propose = intent.action === "PROPOSE_EXECUTION_BASELINE";
  const execute = intent.action === "EXECUTE_EXECUTION_BASELINE";
  if (!current || request.project_id !== snapshot?.selected_project_id || !canControlCurrentTeam() || !consoleSupportsStoppedProviderRetry() ||
      activeOperation(request.id, request.project_id) || providerPlan?.purpose === "source_rebind" || !propose && !execute ||
      propose && (intent.purpose !== "stopped_provider_retry" || intent.target_base_ref != null || intent.input_mode !== "preserve_draft") ||
      execute && (!plan || plan.plan_sha256 !== intent.expected_plan_sha256 || intent.continuation_mode !== "pause" ||
        intent.confirm_provider_prerequisites_repaired !== true)) {
    operationNotice = {kind: "error", title: "续跑前提或方案已变化", message: "请查看当前需求的检查结果；必须确认已修复所列前提，并核对当前方案后才能保留进度。"};
    renderDetail(); renderNotification(); return null;
  }
  return submitOperation(intent);
}
function appendEngineeringStoppedProviderRetry(target, request, task, step) {
  const bound = engineeringStoppedProviderRetryFacts(request, task, step);
  if (!bound || engineeringCurrentProviderPlan(request, task, step)?.purpose === "source_rebind") return;
  const plan = engineeringBaselinePlan(request, task, step, "stopped_provider_retry");
  const operation = engineeringBaselineProposalOperation(bound, "stopped_provider_retry");
  const active = activeOperation(request.id, request.project_id);
  const panel = viewGroup(el("section", undefined, "engineering-baseline-panel engineering-baseline-pending"), "stopped-provider-retry:" + step.work_item_id);
  panel.append(viewBlock(el("h4", "修复执行前提后，保留进度继续"), "provider-title", true));
  const explanation = viewBlock(el("div"), "provider-explanation", plan || bound);
  if (plan) {
    explanation.append(engineeringGuidanceList([
      "平台已核验原执行已停止；原记录为认证失败，没有可接纳的开发报告。原失败记录保持，不会改成临时故障。",
      "完整合法开发进度已封存，原需求、任务、分支和代码基线保留。",
      "请先修复原模型调用的认证或执行器配置问题。确认前提已修复是你的工程决定，平台检查没有证明模型通道现在一定可用。",
      "批准后保持暂停，预留新的开发执行，消耗 1 次剩余开发额度；不退还原执行额度。随后点击“继续原需求”，仍需独立 QA 和 Review。",
    ]));
    const details = engineeringDetails("当前续跑方案的技术信息", step.work_item_id + ":provider-plan");
    details.append(el("p", "原执行 · " + plan.facts.stopped_provider_failure.outcome.start.request.run_id, "paths"),
      el("p", "原需求分支 · " + plan.facts.task.branch_name, "paths"), el("p", "保留代码版本 · " + plan.target_base_ref, "paths"),
      el("p", "方案摘要 · " + plan.plan_sha256, "paths"));
    explanation.append(details);
  } else explanation.append(el("p", "原调用记录为认证失败。平台将核验原执行是否真正停止、是否没有可接纳的报告，并保存完整合法开发进度。准备方案不启动 Coder，也不会替你确认认证或配置问题已修复。", "muted"));
  panel.append(explanation);
  const unavailable = deliveryControlUnavailableReason();
  if (unavailable) panel.append(deliveryControlUnavailableNotice(unavailable));
  else if (!consoleSupportsStoppedProviderRetry()) panel.append(el("p", "当前服务尚不支持此前提修复后的续跑入口。请在服务空闲时更新并重启，再刷新原需求。", "muted"));
  else if (active) panel.append(engineeringActiveOperationBox(request, active));
  else if (canControlCurrentTeam()) {
    const controls = viewBlock(el("div", undefined, "engineering-baseline-form"), "provider-controls",
      [bound, plan, operation?.status, consoleOperationContractVersion, consoleSupportedActions, canControlCurrentTeam()]);
    if (!plan && ["FAILED", "INTERRUPTED"].includes(operation?.status)) panel.append(el("p", "本次方案未准备成功 · " +
      humanizeBlockingText(operation.error_summary || "恢复前提未核验完整。") + " 原进度和失败记录保留；按说明处理后再检查。", "error"));
    if (plan) {
      const confirmation = el("input"); confirmation.type = "checkbox"; confirmation.checked = false;
      confirmation.setAttribute("aria-label", "确认原模型认证或执行器配置前提已修复");
      const field = el("label", undefined, "settings-checkbox-control");
      field.append(confirmation, el("span", "我已修复或核验原模型认证和执行器配置前提，认可本方案保留进度、消耗一次开发额度并保持暂停。"));
      const approve = deliveryButton("确认前提已修复，保留进度", () => submitEngineeringStoppedProviderRetry({
        action: "EXECUTE_EXECUTION_BASELINE", project_id: request.project_id, delivery_id: request.id,
        expected_checkpoint_sha256: request.checkpoint_sha256, task_id: task.task_id, expected_plan_sha256: plan.plan_sha256,
        continuation_mode: "pause", confirm_provider_prerequisites_repaired: confirmation.checked === true,
        reference: "工程授权者确认已修复或核验原模型认证与执行器配置前提，批准精确方案保留完整合法进度及原失败历史，消耗普通开发额度并保持暂停",
      }, bound), "primary");
      approve.disabled = true; confirmation.addEventListener("change", () => {approve.disabled = confirmation.checked !== true;});
      controls.append(field, approve);
    } else controls.append(deliveryButton("准备保留进度的续跑方案", () => submitEngineeringStoppedProviderRetry({
      ...bound, action: "PROPOSE_EXECUTION_BASELINE", purpose: "stopped_provider_retry", input_mode: "preserve_draft",
    }, bound), "primary"));
    panel.append(controls);
  }
  target.append(panel);
}
function matchingStoppedFailureRetryPlan(plan, bound, operation) {
  const proof = plan.facts.stopped_failure;
  const start = proof?.outcome?.start;
  const request = start?.request;
  const result = proof?.outcome?.result;
  const capture = proof?.capture_start;
  const stop = proof?.capture_stop;
  const reservation = plan.facts.continuation;
  const base = plan.previous_binding?.execution_base_ref || plan.facts.task.base_ref;
  return proof?.kind === "stopped_failure" && /^[a-f0-9]{64}$/.test(proof.proof_sha256 || "") &&
    request?.task_id === bound.task_id && request.role === "coder" && request.source_revision === bound.expected_source_revision &&
    start.work_item_id === bound.expected_work_item_id && start.checkpoint_sequence === bound.expected_task_revision &&
    typeof request.run_id === "string" && request.run_id.length > 0 && result?.status === "FAILED" &&
    result.artifact == null && result.error?.code === "PROVIDER_UNAVAILABLE" && result.error.transient === false &&
    capture?.request?.run_id === request.run_id && capture.request.task_id === bound.task_id &&
    capture.request.source_revision === bound.expected_source_revision && capture.task_revision === bound.expected_task_revision &&
    capture.worktree_path === plan.dirty_capture.worktree_path && stop?.task_id === bound.task_id && stop.run_id === request.run_id &&
    stop.capture_start_sha256 === capture.start_sha256 && stop.process_stop?.kind === "failed" &&
    Number.isInteger(stop.process_stop.returncode) && stop.process_stop.returncode !== 0 &&
    stop.process_stop.session_proof?.proof_scope === "owned_session_empty" &&
    /^[a-f0-9]{64}$/.test(stop.process_stop.session_proof.proof_sha256 || "") && stop.output_present === false &&
    !stop.cause && [null, undefined, "PROVIDER_UNAVAILABLE"].includes(stop.original_error_code) &&
    reservation?.retry_cause === "stopped_failure_retry" && reservation.stopped_failure_sha256 === proof.proof_sha256 &&
    !plan.facts.stopped_provider_failure && !plan.facts.stopped_execution && !plan.facts.completed_output &&
    !plan.facts.legacy_containment && !plan.facts.context_capacity_receipt_sha256 && !plan.facts.implementation_artifact_id &&
    !plan.facts.native_rule_change && plan.target_base_ref === base && plan.prepared_source_revision === bound.expected_source_revision &&
    operation.intent?.target_base_ref == null && plan.input_mode === "preserve_draft" && !plan.conflicted;
}
function engineeringStoppedFailureRetryFacts(request, task, step) {
  const bound = engineeringBaselineFacts(request, task, step);
  const proof = engineeringWaitProof(request, step);
  if (!bound || task.project_id !== request.project_id || task.request_id !== request.id ||
      ["DONE", "CLOSED"].includes(request.stage) || step.wait_disposition?.facts.classification !== "NONTRANSIENT_INFRA" ||
      proof?.knowledge_preparation || proof?.rejected_knowledge || proof?.rejected_workspace_admission || proof?.rejected_output || proof?.interruption_receipt_sha256 ||
      proof?.permitted_resolutions?.length || proof?.missing?.includes("BUDGET_EXHAUSTED") ||
      proof?.provider_failure_code && proof.provider_failure_code !== "PROVIDER_UNAVAILABLE" ||
      proof?.retry_cause || engineeringCurrentCompletedPlan(request, task, step) ||
      engineeringCurrentProviderPlan(request, task, step) || engineeringWaitDecision(request, step, proof)) return null;
  return bound;
}
async function submitEngineeringStoppedFailureRetry(intent, originalBound) {
  const request = requestById(intent.delivery_id);
  const current = request && engineeringWaitSteps(request).find(({task, step}) =>
    sameEngineeringWaitIntent(engineeringStoppedFailureRetryFacts(request, task, step), originalBound));
  const plan = current && engineeringBaselinePlan(request, current.task, current.step, "stopped_failure_retry");
  const propose = intent.action === "PROPOSE_EXECUTION_BASELINE";
  const execute = intent.action === "EXECUTE_EXECUTION_BASELINE";
  if (!current || request.project_id !== snapshot?.selected_project_id || !canControlCurrentTeam() ||
      !consoleSupportsStoppedFailureRetry() || activeOperation(request.id, request.project_id) ||
      intent.project_id !== originalBound.project_id || intent.expected_checkpoint_sha256 !== originalBound.expected_checkpoint_sha256 ||
      intent.task_id !== originalBound.task_id || intent.confirm_provider_prerequisites_repaired === true || !propose && !execute ||
      propose && (intent.purpose !== "stopped_failure_retry" || intent.target_base_ref != null || intent.input_mode !== "preserve_draft") ||
      execute && (!plan || plan.plan_sha256 !== intent.expected_plan_sha256 || intent.continuation_mode !== "pause" ||
        intent.confirm_stopped_failure_retry !== true)) {
    operationNotice = {kind: "error", title: "失败后的恢复方案已变化",
      message: "请重新查看当前需求与精确方案，明确接受未知原因和一次普通工作额度后再批准。"};
    renderDetail(); renderNotification(); return null;
  }
  return submitOperation(intent);
}
function appendEngineeringStoppedFailureRetry(target, request, task, step) {
  const bound = engineeringStoppedFailureRetryFacts(request, task, step);
  if (!bound) return;
  const plan = engineeringBaselinePlan(request, task, step, "stopped_failure_retry");
  const planSha256 = plan?.plan_sha256;
  const operation = engineeringBaselineProposalOperation(bound, "stopped_failure_retry");
  const active = activeOperation(request.id, request.project_id);
  const panel = viewGroup(el("section", undefined, "engineering-baseline-panel engineering-baseline-pending"), "stopped-failure-retry:" + step.work_item_id);
  panel.append(viewBlock(el("h4", "原调用失败 · 保留进度继续"), "failure-title", true));
  const explanation = viewBlock(el("div"), "failure-explanation", plan || bound);
  explanation.append(engineeringGuidanceList(plan ? [
    "平台已核验原执行已停止，没有可接纳的开发报告；原因仍未知，原失败记录保留。",
    "完整合法开发进度已封存，原需求、任务、分支和代码基线保留。此决定不声称原故障原因已查明或修复。",
    "批准后消耗 1 次剩余开发额度并保持暂停，不退还原执行额度；之后单独点击“继续原需求”，仍需独立 QA 和 Review。",
  ] : ["原调用失败，原因仍未知。平台将核验真实停止、完整合法开发文件和剩余额度，检查本身不启动 Coder，也不证明故障已修复。"]));
  if (plan) {
    const details = engineeringDetails("失败记录与保留进度方案", step.work_item_id + ":stopped-failure-plan");
    details.append(el("p", "原执行 · " + plan.facts.stopped_failure.outcome.start.request.run_id, "paths"),
      el("p", "保留代码基线 · " + plan.target_base_ref, "paths"), el("p", "方案摘要 · " + planSha256, "paths"));
    explanation.append(details);
  }
  panel.append(explanation);
  const unavailable = deliveryControlUnavailableReason();
  if (unavailable) panel.append(deliveryControlUnavailableNotice(unavailable));
  else if (!consoleSupportsStoppedFailureRetry()) panel.append(el("p", "当前服务尚不支持此失败后的工程恢复入口，请在服务空闲时更新并刷新原需求。", "muted"));
  else if (active) panel.append(engineeringActiveOperationBox(request, active));
  else if (canControlCurrentTeam()) {
    const controls = viewBlock(el("div", undefined, "engineering-baseline-form"), "failure-controls",
      [bound, plan, operation?.status, consoleOperationContractVersion, consoleSupportedActions, canControlCurrentTeam()]);
    if (!plan && ["FAILED", "INTERRUPTED"].includes(operation?.status)) controls.append(el("p", "本次检查未完成 · " +
      humanizeBlockingText(operation.error_summary || "恢复前提未核验完整。") + " 原现场和失败记录保留，请先处理所列原因。", "error"));
    if (plan) {
      const confirmation = el("input"); confirmation.type = "checkbox"; confirmation.checked = false;
      confirmation.setAttribute("aria-label", "接受原失败原因未知，并消耗一次普通工作额度");
      const field = el("label", undefined, "settings-checkbox-control");
      field.append(confirmation, el("span", "我接受原失败原因仍未知，批准精确方案保留完整合法进度，消耗一次普通工作额度并保持暂停。"));
      const approve = deliveryButton("批准保留进度，保持暂停", () => submitEngineeringStoppedFailureRetry({
        action: "EXECUTE_EXECUTION_BASELINE", project_id: bound.project_id, delivery_id: bound.delivery_id,
        expected_checkpoint_sha256: bound.expected_checkpoint_sha256, task_id: bound.task_id, expected_plan_sha256: planSha256,
        continuation_mode: "pause", confirm_stopped_failure_retry: confirmation.checked === true,
        reference: "工程授权者接受原失败原因仍未知，批准精确方案保留完整合法进度和原失败历史，消耗一次普通工作额度并保持暂停，之后另行明确继续",
      }, bound), "primary");
      approve.disabled = true; confirmation.addEventListener("change", () => {approve.disabled = confirmation.checked !== true;});
      controls.append(field, approve);
    } else controls.append(deliveryButton("检查失败后的保留进度", () => submitEngineeringStoppedFailureRetry({
      ...bound, action: "PROPOSE_EXECUTION_BASELINE", purpose: "stopped_failure_retry", input_mode: "preserve_draft",
    }, bound), "primary"));
    panel.append(controls);
  }
  target.append(panel);
}
function completedOutputRejected(plan) {
  return plan?.facts.completed_output?.outcome?.result?.error?.code === "INVALID_OUTPUT";
}
function engineeringCurrentCompletedPlan(request, task, step) {
  const bound = engineeringBaselineFacts(request, task, step);
  if (!bound) return null;
  const candidates = ["completed_output_rescue", "source_rebind"].flatMap(purpose => {
    const plan = engineeringBaselinePlan(request, task, step, purpose);
    const operation = engineeringBaselineProposalOperation(bound, purpose);
    return plan?.facts.completed_output ? [{plan, operation}] : [];
  });
  candidates.sort((a, b) => b.operation.updated_at.localeCompare(a.operation.updated_at) ||
    b.operation.operation_id.localeCompare(a.operation.operation_id));
  return candidates[0]?.plan || null;
}
function completedOutputReportExplanation(plan) {
  if (!completedOutputRejected(plan))
    return "原执行已核验结束，但开发报告未被接纳，报告内容仍未知；不能据此认为开发已经完成。";
  const diagnostic = coderOutputDiagnostic(plan.facts.completed_output.outcome.result.error.message || "");
  return "原执行已核验结束，开发报告被拒；" +
    (diagnostic ? diagnostic + "。" : "具体旧校验子因未保存。") +
    "报告内容仍未知，不能据此认为开发已经完成。";
}
function engineeringRejectedOutputWait(step) {
  return step.wait_disposition?.facts.classification === "INVALID_OUTPUT";
}
function matchingCompletedOutputRescuePlan(plan, bound, operation, sameSource = true) {
  const proof = plan.facts.completed_output;
  const start = proof?.outcome?.start;
  const request = start?.request;
  const result = proof?.outcome?.result;
  const capture = proof?.capture_start;
  const stop = proof?.capture_stop;
  const reservation = plan.facts.continuation;
  const base = plan.previous_binding?.execution_base_ref || plan.facts.task.base_ref;
  return proof?.kind === "completed_coder_output_unavailable" && proof.output_content_status === "unknown" &&
    /^[a-f0-9]{64}$/.test(proof.proof_sha256 || "") && request?.task_id === bound.task_id &&
    request.role === "coder" && request.source_revision === bound.expected_source_revision &&
    start.work_item_id === bound.expected_work_item_id && start.checkpoint_sequence === bound.expected_task_revision &&
    typeof request.run_id === "string" && request.run_id.length > 0 &&
    result?.status === "FAILED" && result.artifact == null && ["WORK_INTERRUPTED", "INVALID_OUTPUT"].includes(result.error?.code) &&
    result.error.transient === false && capture?.request?.run_id === request.run_id &&
    capture.request.task_id === bound.task_id && capture.request.source_revision === bound.expected_source_revision &&
    capture.task_revision === bound.expected_task_revision && capture.worktree_path === plan.dirty_capture.worktree_path &&
    stop?.task_id === bound.task_id && stop.run_id === request.run_id &&
    stop.capture_start_sha256 === capture.start_sha256 && stop.process_stop?.kind === "completed" &&
    stop.process_stop.returncode === 0 && stop.output_present === true && !stop.cause && !stop.original_error_code &&
    reservation?.retry_cause === (result.error.code === "INVALID_OUTPUT" ? "completed_output_rejected" : "completed_output_unavailable") &&
    reservation.completed_output_sha256 === proof.proof_sha256 &&
    !plan.facts.legacy_containment && !plan.facts.stopped_provider_failure && !plan.facts.stopped_failure && !plan.facts.implementation_artifact_id &&
    (!sameSource || !plan.facts.native_rule_change && plan.target_base_ref === base &&
      plan.prepared_source_revision === bound.expected_source_revision &&
      plan.input_mode === "preserve_draft" && !plan.conflicted && operation.intent?.target_base_ref == null);
}
function engineeringCompletedOutputRescueFacts(request, task, step) {
  const bound = engineeringBaselineFacts(request, task, step);
  const proof = engineeringWaitProof(request, step);
  const plan = engineeringBaselinePlan(request, task, step, "completed_output_rescue");
  if (!bound || engineeringStoppedExecutionRescueFacts(request, task, step) || engineeringStoppedFailureRetryFacts(request, task, step) ||
      step.wait_disposition?.facts.classification === "EXECUTION_BASELINE_PAUSED" ||
      engineeringCurrentCompletedPlan(request, task, step)?.purpose === "source_rebind" ||
      proof?.provider_failure_code === "AUTHENTICATION_ERROR" ||
      engineeringBaselinePlan(request, task, step, "stopped_provider_retry") ||
      !["TRANSIENT_INFRA", "NONTRANSIENT_INFRA", "PLATFORM_BUG", "EXECUTION_UNCERTAIN", "INVALID_OUTPUT"].includes(step.wait_disposition?.facts.classification) ||
      proof?.knowledge_preparation || proof?.rejected_knowledge || proof?.rejected_workspace_admission || proof?.rejected_output || proof?.interruption_receipt_sha256 ||
      proof?.permitted_resolutions?.length || proof?.retry_cause && proof.retry_cause !==
        (engineeringRejectedOutputWait(step) ? "completed_output_rejected" : "completed_output_unavailable") ||
      proof?.missing?.includes("BUDGET_EXHAUSTED") || !plan && engineeringLegacyRescueFacts(request, task, step, proof)) return null;
  return bound;
}
async function submitEngineeringCompletedOutputRescue(intent, originalBound) {
  const request = requestById(intent.delivery_id);
  const current = request && engineeringWaitSteps(request).find(({task, step}) =>
    sameEngineeringWaitIntent(engineeringCompletedOutputRescueFacts(request, task, step), originalBound));
  const plan = current && engineeringBaselinePlan(request, current.task, current.step, "completed_output_rescue");
  if (!current || request.project_id !== snapshot?.selected_project_id || !canControlCurrentTeam() ||
      !consoleSupportsCompletedOutputRescue(engineeringRejectedOutputWait(current.step) || completedOutputRejected(plan)) ||
      activeOperation(request.id, request.project_id) ||
      !["PROPOSE_EXECUTION_BASELINE", "EXECUTE_EXECUTION_BASELINE"].includes(intent.action) ||
      intent.action === "PROPOSE_EXECUTION_BASELINE" && (intent.purpose !== "completed_output_rescue" ||
        intent.input_mode !== "preserve_draft" || intent.target_base_ref != null) ||
      intent.action === "EXECUTE_EXECUTION_BASELINE" && (!plan || plan.plan_sha256 !== intent.expected_plan_sha256 || intent.continuation_mode !== "pause")) {
    operationNotice = {kind: "error", title: "保留进度的恢复前提已变化",
      message: "请查看当前需求和平台检查结果；旧方案不能用于不同执行或工作现场。"};
    renderDetail(); renderNotification(); return null;
  }
  return submitOperation(intent);
}
function appendEngineeringCompletedOutputRescue(target, request, task, step) {
  const bound = engineeringCompletedOutputRescueFacts(request, task, step);
  if (!bound) return;
  const plan = engineeringBaselinePlan(request, task, step, "completed_output_rescue");
  const operation = engineeringBaselineProposalOperation(bound, "completed_output_rescue");
  const active = activeOperation(request.id, request.project_id);
  const panel = viewGroup(el("section", undefined, "engineering-baseline-panel engineering-baseline-pending"), "completed-output-rescue:" + step.work_item_id);
  panel.append(el("h4", "保留进度，继续同一需求"));
  if (plan) {
    panel.append(engineeringGuidanceList([
      completedOutputRejected(plan) ? completedOutputReportExplanation(plan) :
        "平台已核验原执行已结束，但开发报告未被接纳，报告内容仍未知；不能据此认为开发已经完成。",
      "完整合法草稿已封存，原任务、需求分支、代码基线和执行历史保持。",
      "批准后保持暂停，并预留一次新的开发执行；消耗 1 次剩余开发额度，不退还原执行额度。",
      "之后明确继续原需求，由 Coder 使用保留的进度重新产出报告，仍需独立 QA 和 Review。",
    ]));
    const details = engineeringDetails("已核验的恢复方案", step.work_item_id + ":completed-output-plan");
    details.append(el("p", "原需求分支 · " + plan.facts.task.branch_name, "paths"),
      el("p", "保留代码基线 · " + plan.target_base_ref, "paths"), el("p", "原执行 · " + plan.facts.completed_output.outcome.start.request.run_id, "paths"),
      el("p", "方案摘要 · " + plan.plan_sha256, "paths"));
    panel.append(details);
  } else panel.append(el("p", (engineeringRejectedOutputWait(step) ? "本轮开发报告被拒，尚未形成可接纳的完成结果。" : "") +
    "平台将核验原执行是否已结束、报告是否未接纳，以及现有开发进度是否完整合法。检查通过后才会准备可批准的恢复方案；检查本身不启动 Coder，也不保证当前执行符合恢复前提。", "muted"));
  const issue = deliveryControlUnavailableReason();
  if (issue) panel.append(deliveryControlUnavailableNotice(issue));
  else if (!consoleSupportsCompletedOutputRescue(engineeringRejectedOutputWait(step) || completedOutputRejected(plan))) panel.append(el("p", "当前服务不支持此恢复入口。请在服务空闲时更新并重启，再刷新原需求；开发进度和原历史保留。", "muted"));
  else if (active) panel.append(el("p", "当前平台操作尚未结束，请等待检查结果；尚未启动新的开发执行。", "muted"));
  else if (canControlCurrentTeam()) {
    if (!plan && ["FAILED", "INTERRUPTED"].includes(operation?.status)) panel.append(el("p",
      "本次方案未准备成功 · " + humanizeBlockingText(operation.error_summary || "平台尚未核验完整恢复前提。") + " 原状态和现场保留；请先处理所列原因，再重新准备。", "error"));
    panel.append(plan ? deliveryButton("批准保留进度，保持暂停", () => submitEngineeringCompletedOutputRescue({
      action: "EXECUTE_EXECUTION_BASELINE", project_id: request.project_id, delivery_id: request.id,
      expected_checkpoint_sha256: request.checkpoint_sha256, task_id: task.task_id, expected_plan_sha256: plan.plan_sha256,
      continuation_mode: "pause", reference: "批准精确已结束执行恢复方案，保留完整合法进度、原分支与原基线，保持暂停",
    }, bound), "primary") : deliveryButton("准备保留进度的恢复方案", () => submitEngineeringCompletedOutputRescue({
      ...bound, action: "PROPOSE_EXECUTION_BASELINE", purpose: "completed_output_rescue", input_mode: "preserve_draft",
    }, bound), "primary"));
  }
  target.append(panel);
}
function matchingStoppedExecutionRescuePlan(plan, bound, operation) {
  const proof = plan.facts.stopped_execution;
  const start = proof?.invocation_start;
  const request = start?.request;
  const capture = proof?.capture_start;
  const stop = proof?.capture_stop;
  const reservation = plan.facts.continuation;
  const base = plan.previous_binding?.execution_base_ref || plan.facts.task.base_ref;
  return proof?.kind === "stopped_coder_execution_without_outcome" &&
    /^[a-f0-9]{64}$/.test(proof.proof_sha256 || "") && request?.task_id === bound.task_id &&
    request.role === "coder" && request.source_revision === bound.expected_source_revision &&
    start.work_item_id === bound.expected_work_item_id && start.checkpoint_sequence === bound.expected_task_revision &&
    typeof request.run_id === "string" && request.run_id.length > 0 &&
    capture?.request?.run_id === request.run_id && capture.request.task_id === bound.task_id &&
    capture.request.source_revision === bound.expected_source_revision && capture.task_revision === bound.expected_task_revision &&
    capture.worktree_path === plan.dirty_capture.worktree_path &&
    stop?.task_id === bound.task_id && stop.run_id === request.run_id && stop.capture_start_sha256 === capture.start_sha256 &&
    stop.process_stop?.kind === "failed" && Number.isInteger(stop.process_stop.returncode) && stop.process_stop.returncode !== 0 &&
    stop.process_stop.session_proof?.proof_scope === "owned_session_empty" &&
    /^[a-f0-9]{64}$/.test(stop.process_stop.session_proof.proof_sha256 || "") &&
    stop.output_present === false && !stop.cause &&
    reservation?.retry_cause === "stopped_execution_unknown" && reservation.stopped_execution_sha256 === proof.proof_sha256 &&
    !plan.facts.legacy_containment && !plan.facts.completed_output && !plan.facts.stopped_provider_failure && !plan.facts.stopped_failure &&
    !plan.facts.implementation_artifact_id && !plan.facts.native_rule_change &&
    plan.target_base_ref === base && plan.prepared_source_revision === bound.expected_source_revision &&
    plan.input_mode === "preserve_draft" && !plan.conflicted && operation.intent?.target_base_ref == null;
}
function engineeringStoppedExecutionRescueFacts(request, task, step) {
  const bound = engineeringBaselineFacts(request, task, step);
  const proof = engineeringWaitProof(request, step);
  const missing = proof?.missing || [];
  if (!bound || task.project_id !== request.project_id || task.request_id !== request.id ||
      ["DONE", "CLOSED"].includes(request.stage) || step.wait_disposition?.facts.classification !== "EXECUTION_UNCERTAIN" ||
      !/^run_[a-z0-9_]+$/.test(proof?.original_run_id || "") ||
      !/^[a-f0-9]{64}$/.test(proof?.process_stop_sha256 || "") ||
      missing.length !== 2 || !missing.includes("OUTCOME_UNKNOWN") || !missing.includes("CHECKPOINT_UNAVAILABLE") ||
      proof.permitted_resolutions?.length || proof.interruption_receipt_sha256 || proof.retry_cause ||
      proof.knowledge_preparation || proof.rejected_knowledge || proof.rejected_workspace_admission || proof.rejected_output || proof.provider_failure_code ||
      engineeringWaitDecision(request, step, proof)) return null;
  return bound;
}
async function submitEngineeringStoppedExecutionRescue(intent, originalBound) {
  const request = requestById(intent.delivery_id);
  const current = request && engineeringWaitSteps(request).find(({task, step}) =>
    sameEngineeringWaitIntent(engineeringStoppedExecutionRescueFacts(request, task, step), originalBound));
  const plan = current && engineeringBaselinePlan(request, current.task, current.step, "stopped_execution_rescue");
  if (!current || request.project_id !== snapshot?.selected_project_id || !canControlCurrentTeam() ||
      !consoleSupportsStoppedExecutionRescue() || activeOperation(request.id, request.project_id) ||
      !["PROPOSE_EXECUTION_BASELINE", "EXECUTE_EXECUTION_BASELINE"].includes(intent.action) ||
      intent.action === "PROPOSE_EXECUTION_BASELINE" && (intent.purpose !== "stopped_execution_rescue" ||
        intent.input_mode !== "preserve_draft" || intent.target_base_ref != null) ||
      intent.action === "EXECUTE_EXECUTION_BASELINE" && (!plan || plan.plan_sha256 !== intent.expected_plan_sha256 ||
        intent.continuation_mode !== "pause")) {
    operationNotice = {kind: "error", title: "停止后的恢复前提已变化", message: "请重新核对当前执行和完整进度；旧方案不能批准。"};
    renderDetail(); renderNotification(); return null;
  }
  return submitOperation(intent);
}
function appendEngineeringStoppedExecutionRescue(target, request, task, step) {
  const bound = engineeringStoppedExecutionRescueFacts(request, task, step);
  if (!bound) return;
  const plan = engineeringBaselinePlan(request, task, step, "stopped_execution_rescue");
  const operation = engineeringBaselineProposalOperation(bound, "stopped_execution_rescue");
  const active = activeOperation(request.id, request.project_id);
  const panel = viewGroup(el("section", undefined, "engineering-baseline-panel engineering-baseline-pending"), "stopped-execution-rescue:" + step.work_item_id);
  panel.append(el("h4", "原执行已停止 · 保留进度恢复"));
  panel.append(engineeringGuidanceList(plan ? [
    "平台已核验真实停止证明，原调用结果仍未封存；原执行原因和历史保持，不视为开发完成。",
    "完整合法草稿已封存，原需求、分支和代码基线保留。",
    "批准后消耗 1 次剩余开发额度并保持暂停；之后明确继续原需求，仍需独立 QA 和 Review。",
  ] : ["已有真实停止记录，但原调用结果仍未封存。平台将检查原执行、完整开发文件和剩余额度，检查本身不启动新的 Coder。"]));
  if (plan) {
    const details = engineeringDetails("停止证明与恢复方案", step.work_item_id + ":stopped-execution-plan");
    details.append(el("p", "保留代码基线 · " + plan.target_base_ref, "paths"),
      el("p", "原执行 · " + plan.facts.stopped_execution.invocation_start.request.run_id, "paths"),
      el("p", "方案摘要 · " + plan.plan_sha256, "paths"));
    panel.append(details);
  }
  const unavailable = deliveryControlUnavailableReason();
  if (unavailable) panel.append(deliveryControlUnavailableNotice(unavailable));
  else if (!consoleSupportsStoppedExecutionRescue()) panel.append(el("p", "当前服务尚不支持此停止后的恢复入口，请在服务空闲时更新并刷新原需求。", "muted"));
  else if (active) panel.append(engineeringActiveOperationBox(request, active));
  else if (canControlCurrentTeam()) {
    if (!plan && ["FAILED", "INTERRUPTED"].includes(operation?.status)) panel.append(el("p", "本次检查未完成 · " +
      humanizeBlockingText(operation.error_summary || "恢复前提未核验完整。") + " 请先处理所列原因，再检查保留进度。", "error"));
    panel.append(plan ? deliveryButton("批准保留进度，保持暂停", () => submitEngineeringStoppedExecutionRescue({
      action: "EXECUTE_EXECUTION_BASELINE", project_id: request.project_id, delivery_id: request.id,
      expected_checkpoint_sha256: request.checkpoint_sha256, task_id: task.task_id, expected_plan_sha256: plan.plan_sha256,
      continuation_mode: "pause", reference: "批准精确停止证明与完整进度方案，保留未知原结果，消耗普通工作额度并保持暂停",
    }, bound), "primary") : deliveryButton("检查停止后的保留进度", () => submitEngineeringStoppedExecutionRescue({
      ...bound, action: "PROPOSE_EXECUTION_BASELINE", purpose: "stopped_execution_rescue", input_mode: "preserve_draft",
    }, bound), "primary"));
  }
  target.append(panel);
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
  const preparation = operation?.status === "SUCCEEDED" ? operationResult(operation)?.legacy_rescue_preparation : null;
  if (!preparation || operationResult(operation).checkpoint_sha256 !== request.checkpoint_sha256 ||
      preparation.task_id !== task.task_id || preparation.work_item_id !== step.work_item_id ||
      preparation.source_revision !== rescue.baseline.expected_source_revision ||
      !["READY", "WAITING"].includes(preparation.status) || typeof preparation.summary !== "string" ||
      !preparation.summary || typeof preparation.next_action !== "string" || !preparation.next_action ||
      !["平台执行服务", "工程授权者"].includes(preparation.responsible_party)) return null;
  return preparation;
}
function engineeringBaselineProposalOperation(bound, purpose = "source_rebind") {
  if (!operationsAvailable || !bound) return null;
  return [...operations].sort((a, b) => b.updated_at.localeCompare(a.updated_at))
    .find(item => item.intent?.action === "PROPOSE_EXECUTION_BASELINE" &&
      (item.intent?.purpose || "source_rebind") === purpose && sameEngineeringWaitIntent(item.intent, bound) &&
      (purpose !== "legacy_workspace_rescue" || item.intent?.target_base_ref === bound.expected_source_revision &&
        item.intent?.input_mode === "preserve_draft"));
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
    operationAction(item) === "EXECUTE_EXECUTION_BASELINE" && operationProject(item) === request.project_id &&
    item.intent?.delivery_id === request.id && item.intent?.task_id === task.task_id &&
    item.intent?.expected_plan_sha256 === plan.plan_sha256);
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
  if (!current || engineeringBaselinePlan(request, current.task, current.step, "completed_output_rescue") || activeOperation(request.id, request.project_id) ||
      (!propose && !execute) || propose && (intent.purpose !== "legacy_workspace_rescue" ||
        intent.target_base_ref !== rescue.baseline.expected_source_revision || intent.input_mode !== "preserve_draft") ||
      execute && (!plan || plan.plan_sha256 !== intent.expected_plan_sha256 ||
        !consoleSupportsPausedBaseline() || intent.continuation_mode !== "pause" ||
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
    panel.append(viewBlock(el("p", active.intent?.purpose === "legacy_workspace_rescue"
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
  } else if (!controlUnavailable && (!supported || local && !consoleSupportsLocalRescue() ||
      plan && !consoleSupportsPausedBaseline())) {
    panel.append(viewBlock(el("p", "当前服务尚不支持此恢复路径。请在服务空闲时更新并重启 Web Console，再刷新页面；原需求和草稿保留。", "muted"),
      "rescue-unavailable", [consoleOperationContractVersion, consoleSupportedActions]));
  } else if (canControlCurrentTeam()) {
    const controls = viewBlock(el("div", undefined, "engineering-baseline-form"), "rescue-controls",
      [rescue, plan, preparation, canControlCurrentTeam(), consoleOperationContractVersion, consoleSupportedActions]);
    if (plan) {
      const field = el(local ? "div" : "label", undefined,
        local ? "engineering-rescue-confirmation" : "settings-checkbox-control");
      const confirmation = local ? null : el("input");
      if (local) {
        field.append(el("p", "点击“批准保留进度，保持暂停”即表示你以工程授权者身份确认：原调用一直在当前同一电脑、同一账户本地执行，未迁移或远程执行；原调用及全部派生工具已结束，不会再修改保留的现场。你接受旧结果仍为未知，并批准保存完整进度及预留下一次执行身份。批准后不会启动 Coder；可以先更新代码和项目规范基线，再明确继续。此确认是独立人工工程授权，不是平台补出的旧停止记录。"));
      } else {
        confirmation.type = "checkbox";
        confirmation.checked = false;
        confirmation.setAttribute("aria-label", "确认原执行在同一电脑且已整机重启");
        field.append(confirmation, el("span", "我以工程授权者身份确认：原执行一直在当前同一电脑本地运行，未迁移或远程执行；原执行之后已重启整台电脑，并认可平台显示的时间依据。"));
      }
      const approve = deliveryButton("批准保留进度，保持暂停", () => submitEngineeringLegacyRescueOperation({
        action: "EXECUTE_EXECUTION_BASELINE", project_id: request.project_id, delivery_id: request.id,
        expected_checkpoint_sha256: request.checkpoint_sha256, task_id: task.task_id,
        expected_plan_sha256: planSha256,
        continuation_mode: "pause",
        ...(local ? {confirm_local_execution_stopped: true}
          : {confirm_legacy_containment: confirmation.checked === true}),
        reference: local
          ? "工程授权者确认原调用始终同机同账户本地未迁移或远程、原调用及全部派生工具已结束且不会再修改现场；接受旧结果未知，批准保留完整合法草稿并保持暂停"
          : "工程授权者确认原执行同机本地且已整机重启，批准保留完整合法草稿并保持暂停",
      }, rescue), "primary");
      approve.disabled = !local;
      if (confirmation) confirmation.addEventListener("change", () => {approve.disabled = confirmation.checked !== true;});
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
  if (!current || request.project_id !== snapshot?.selected_project_id || !canControlCurrentTeam() || !consoleSupportsPausedBaseline() ||
      (engineeringRejectedOutputWait(current.step) || completedOutputRejected(plan)) && !consoleSupportsCompletedOutputRescue(true) ||
      activeOperation(request.id, request.project_id) || (intent.action === "EXECUTE_EXECUTION_BASELINE" &&
      (!plan || plan.plan_sha256 !== intent.expected_plan_sha256 || plan.conflicted ||
       intent.continuation_mode !== "pause" ||
       plan.facts.stopped_failure ||
       plan.facts.stopped_provider_failure && (!consoleSupportsStoppedProviderRetry() || intent.confirm_provider_prerequisites_repaired !== true) ||
       plan.facts.stopped_provider_failure && engineeringCurrentProviderPlan(request, current.task, current.step)?.plan_sha256 !== plan.plan_sha256 ||
       plan.facts.completed_output && engineeringCurrentCompletedPlan(request, current.task, current.step)?.plan_sha256 !== plan.plan_sha256 ||
       (intent.approved_native_rule_change_sha256 || null) !== (plan.facts.native_rule_change?.change_sha256 || null) ||
       plan.facts.native_rule_change && !nativeRulePlanReviewed(plan)))) {
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
function nativeRuleReviewPlanKey(plan) {
  return JSON.stringify([plan.facts.task.id, plan.facts.work_item_id, plan.plan_sha256]);
}
function nativeRuleReview(plan, path) {
  return nativeRuleReviews.get(nativeRuleReviewPlanKey(plan))?.get(path);
}
function saveNativeRuleReview(plan, path, review) {
  const key = nativeRuleReviewPlanKey(plan);
  if (!nativeRuleReviews.has(key)) nativeRuleReviews.set(key, new Map());
  nativeRuleReviews.get(key).set(path, review);
  nativeRuleReviewsRevision += 1;
}
function pruneNativeRuleReviews() {
  const request = snapshot && selected?.kind === "request" ? requestById(selected.id) : null;
  const retained = new Set((request ? engineeringWaitSteps(request) : [])
    .map(({task, step}) => engineeringBaselinePlan(request, task, step))
    .filter(plan => plan?.facts.native_rule_change).map(nativeRuleReviewPlanKey));
  for (const key of nativeRuleReviews.keys())
    if (!retained.has(key)) {
      nativeRuleReviews.delete(key);
      nativeRuleReviewsRevision += 1;
    }
}
function nativeRulePlanReviewed(plan) {
  return (plan.facts.native_rule_change?.changes || []).every(delta =>
    nativeRuleReview(plan, delta.path)?.status === "READY");
}
async function loadEngineeringNativeRuleReview(request, task, step, plan, delta) {
  const original = engineeringBaselineFacts(request, task, step);
  const operation = engineeringBaselineProposalOperation(original);
  if (!operation || !canControlCurrentTeam() || !consoleSupportsPausedBaseline() ||
      engineeringBaselinePlan(request, task, step)?.plan_sha256 !== plan.plan_sha256) return;
  saveNativeRuleReview(plan, delta.path, {status: "LOADING"});
  renderDetail({incremental: true});
  try {
    const response = await fetch("/api/v1/operations/" + encodeURIComponent(operation.operation_id) +
      "/native-rules?path=" + encodeURIComponent(delta.path));
    if (!response.ok) throw new Error("项目规范变更暂不可读取，请重新准备当前基线方案。");
    const inspection = await response.json();
    const latestRequest = requestById(request.id);
    const current = latestRequest && engineeringWaitSteps(latestRequest).find(({task, step}) =>
      sameEngineeringWaitIntent(engineeringBaselineFacts(latestRequest, task, step), original));
    if (!current || engineeringBaselinePlan(latestRequest, current.task, current.step)?.plan_sha256 !== plan.plan_sha256)
      return;
    if (JSON.stringify(inspection.delta) !== JSON.stringify(delta) || typeof inspection.unified_diff !== "string" ||
        JSON.stringify(inspection.epoch) !== JSON.stringify(plan.facts.native_rule_change.target))
      throw new Error("项目规范审阅与精确方案不一致，请重新准备方案。");
    saveNativeRuleReview(plan, delta.path, {status: "READY", inspection});
  } catch (error) {
    saveNativeRuleReview(plan, delta.path, {status: "FAILED", message: error.message});
  }
  renderDetail({incremental: true});
}
function appendEngineeringBaseline(target, request, task, step) {
  const bound = engineeringBaselineFacts(request, task, step);
  if (engineeringStoppedExecutionRescueFacts(request, task, step) || engineeringStoppedFailureRetryFacts(request, task, step)) return;
  if (!bound) return;
  const sourcePlan = engineeringBaselinePlan(request, task, step);
  const plan = sourcePlan?.facts.stopped_provider_failure &&
    engineeringCurrentProviderPlan(request, task, step)?.plan_sha256 !== sourcePlan.plan_sha256 ||
    sourcePlan?.facts.completed_output &&
    engineeringCurrentCompletedPlan(request, task, step)?.plan_sha256 !== sourcePlan.plan_sha256 ? null : sourcePlan;
  const planSha256 = plan?.plan_sha256;
  const targetBaseRef = plan?.target_base_ref;
  const inputMode = plan?.input_mode;
  const paused = step.wait_disposition?.facts.classification === "EXECUTION_BASELINE_PAUSED";
  const active = activeOperation(request.id, request.project_id);
  const executed = plan && operations.some(item => item.status === "SUCCEEDED" &&
    operationAction(item) === "EXECUTE_EXECUTION_BASELINE" && item.intent?.task_id === task.task_id &&
    operationProject(item) === request.project_id &&
    item.intent?.delivery_id === request.id && item.intent?.expected_plan_sha256 === plan.plan_sha256);
  const fold = viewGroup(paused || plan && !executed
    ? el("section", undefined, "engineering-baseline-panel engineering-baseline-pending")
    : engineeringDetails("可选工程操作 · 更新原分支基线", step.work_item_id + ":baseline"),
    "engineering-baseline:" + step.work_item_id);
  fold.classList.add("engineering-baseline-panel");
  if (paused || plan && !executed) {
    fold.setAttribute("data-key", "engineering:" + step.work_item_id + ":baseline");
    fold.append(el("h4", "更新原分支的代码与项目规范", "engineering-baseline-title"));
  }
  fold.append(viewBlock(el("p",
    "目标仓库有新代码时，可以在原需求分支更新基线。准备方案先保存完整草稿，展示代码冲突和项目规范变化；批准更新后仍保持暂停，独立测试和评审在明确继续后执行。",
    "muted engineering-baseline-description"), "engineering-baseline-description", Boolean(plan)));
  if (plan) {
    if (plan.facts.stopped_provider_failure) fold.append(viewBlock(engineeringGuidanceList([
      "原调用的认证失败和真实停止已核验，完整合法开发进度已封存，原失败记录保留。",
      "确认原认证与执行器配置前提已修复是你的工程决定，平台并未证明模型通道现在一定可用。",
      "批准精确目标和项目规范后保持暂停，消耗 1 次普通开发额度，不退还原执行额度；之后明确继续原需求，仍需独立 QA 和 Review。",
    ]), "provider-source-explanation", plan));
    if (plan.facts.completed_output) fold.append(viewBlock(engineeringGuidanceList([
      completedOutputReportExplanation(plan),
      "完整合法开发草稿已封存。此方案更新原分支的执行输入，不改变原需求范围或失败历史。",
      "批准精确目标和项目规范后保持暂停，消耗 1 次普通开发额度，不退还原执行额度；之后明确继续原需求，仍需独立 QA 和 Review。",
    ]), "completed-source-explanation", plan));
    fold.append(el("p", plan.conflicted ? "原草稿与目标代码存在冲突，原现场保留。需明确提出让 Coder 读取完整旧补丁后适配的新计划。" :
      plan.input_mode === "coder_reapply" ? "当前计划从目标代码建立干净执行输入，由 Coder 读取完整旧补丁并适配。" :
      "当前计划在原需求分支保留草稿并更新执行基线。"),
      el("p", "原需求分支 · " + (plan.facts.task.branch_name || "未提供"), "paths"),
      el("p", "目标代码版本 · " + plan.target_base_ref, "paths"));
    const technical = engineeringDetails("执行基线计划绑定", step.work_item_id + ":baseline-plan");
    technical.append(el("p", "计划摘要 · " + plan.plan_sha256, "paths"),
      el("p", "当前执行输入 · " + bound.expected_source_revision, "paths"));
    fold.append(technical);
    const rules = plan.facts.native_rule_change;
    if (rules) {
      const changes = viewBlock(el("div", undefined, "engineering-native-rule-changes"),
        "native-rule-changes", [rules, rules.changes.map(delta => nativeRuleReview(plan, delta.path)),
          canControlCurrentTeam(), consoleOperationContractVersion, consoleSupportedActions]);
      changes.append(el("strong", "目标版本包含项目规范变更"),
        el("p", "这些规范将用于后续 Coder、QA 和 Reviewer；原需求范围与产品批准保持。请审阅所列变更后明确确认。"));
      const list = el("ul");
      for (const delta of rules.changes || []) {
        const item = el("li");
        item.append(el("p", ({added: "新增", modified: "修改", deleted: "删除"}[delta.change] || "变更") + " · " + delta.path, "paths"));
        const review = nativeRuleReview(plan, delta.path);
        if (review?.status === "READY") {
          const detail = engineeringDetails("完整规范变更 · " + delta.path, "native-rule:" + plan.plan_sha256 + ":" + delta.path);
          detail.append(el("pre", review.inspection.unified_diff, "paths"));
          item.append(detail);
        } else if (canControlCurrentTeam() && consoleSupportsPausedBaseline()) {
          const inspect = button(review?.status === "LOADING" ? "正在读取规范变更" : "查看规范变更 · " + delta.path,
            () => loadEngineeringNativeRuleReview(request, task, step, plan, delta), "secondary");
          inspect.disabled = review?.status === "LOADING";
          item.append(inspect);
          if (review?.status === "FAILED") item.append(el("p", review.message, "error"));
        }
        list.append(item);
      }
      changes.append(list);
      fold.append(changes);
    }
  }
  if (executed) {
    fold.append(el("p", "此精确计划已执行，后续进度和验收以新的执行记录为准。", "muted"));
  } else if (canControlCurrentTeam() && (engineeringRejectedOutputWait(step) || completedOutputRejected(plan)) &&
      !consoleSupportsCompletedOutputRescue(true)) {
    fold.append(el("p", "当前服务不支持报告被拒后的基线恢复。请在服务空闲时更新并重启，再刷新原需求。", "muted"));
  } else if (canControlCurrentTeam() && consoleSupportsPausedBaseline() && !active) {
    const form = viewBlock(el("div", undefined, "engineering-baseline-form"), "engineering-baseline-controls",
      [bound, plan, canControlCurrentTeam(), consoleOperationContractVersion, consoleSupportedActions,
        plan?.facts.native_rule_change?.changes.map(delta => nativeRuleReview(plan, delta.path)?.status)]);
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
    if (plan && !plan.conflicted) {
      const rules = plan.facts.native_rule_change;
      const providerFailure = plan.facts.stopped_provider_failure;
      const providerConfirmation = providerFailure ? el("input") : null;
      if (providerConfirmation) {
        providerConfirmation.type = "checkbox"; providerConfirmation.checked = false;
        providerConfirmation.setAttribute("aria-label", "确认原模型认证或执行器配置前提已修复");
        const providerField = el("label", undefined, "settings-checkbox-control");
        providerField.append(providerConfirmation, el("span", "原调用的认证失败记录保留。我已修复或核验原认证与执行器配置前提，认可保留完整进度、消耗一次开发额度并保持暂停。"));
        form.append(providerField);
      }
      const confirmation = rules ? el("input") : null;
      if (confirmation) {
        confirmation.type = "checkbox";
        confirmation.checked = false;
        confirmation.setAttribute("aria-label", "确认目标版本的项目规范变更");
        confirmation.disabled = !nativeRulePlanReviewed(plan);
        const label = el("label", undefined, "settings-checkbox-control");
        label.append(confirmation, el("span", "我已审阅并确认此目标版本的项目规范变更，用于后续独立开发、测试和评审。"));
        if (confirmation.disabled) label.append(el("small", "请先查看上面每项完整规范变更，再确认。", "muted"));
        form.append(label);
      }
      const approve = deliveryButton("批准更新基线，保持暂停", () =>
        submitEngineeringBaselineOperation({action: "EXECUTE_EXECUTION_BASELINE", project_id: request.project_id,
        delivery_id: request.id, expected_checkpoint_sha256: request.checkpoint_sha256, task_id: task.task_id,
        expected_plan_sha256: planSha256,
        continuation_mode: "pause",
        ...(providerFailure ? {confirm_provider_prerequisites_repaired: providerConfirmation.checked === true} : {}),
        ...(rules && confirmation.checked === true ? {approved_native_rule_change_sha256: rules.change_sha256} : {}),
        reference: inputMode === "coder_reapply" ? "批准 Coder 从精确目标版本适配完整旧补丁" :
          "批准在原需求分支保留草稿并更新到精确目标版本和明确确认的项目规范，保持交付暂停"}, bound), "primary");
      const updateApproval = () => {approve.disabled = Boolean(rules && confirmation.checked !== true ||
        providerFailure && (!consoleSupportsStoppedProviderRetry() || providerConfirmation.checked !== true));};
      updateApproval();
      if (confirmation) confirmation.addEventListener("change", updateApproval);
      if (providerConfirmation) providerConfirmation.addEventListener("change", updateApproval);
      actions.append(approve);
    }
    form.append(field, actions);
    fold.append(form);
  } else if (active) {
    fold.append(el("p", "工程基线操作正在处理，交付进度以之后的角色事实为准。", "muted"));
  }
  target.append(fold);
}
function deliveryPhase(item, node = null) {
  if (node?.currentApproval) return "恢复待确认";
  if (node?.platformProcessing) return "恢复准备";
  const task = item.request_id ? item : currentRequestTasks(item)
    .filter(task => !task.terminal).sort((a, b) => b.last_activity.localeCompare(a.last_activity))[0];
  const status = task?.status || item.knowledge_wait_stage || item.stage || item.status;
  return {IMPLEMENTING: "实现", QA: "测试", REVIEW: "评审", CONTINUE_REQUIRED: "实现",
    QUEUED: "实现", DELIVERING: "实现", VERIFY_QA: "候选测试", VERIFY_REVIEW: "候选评审", INTEGRATING: "联合验收"}[status] || label(status);
}
function coderOutputDiagnostic(detail) {
  detail = detail.replace(/^coder run run_[0-9a-z]+ failed: /, "");
  if (!detail.startsWith("Codex CLI returned invalid structured output;")) return null;
  if (/(?:^|;\s*)cause=GIT_CONTRACT(?:;|$)/.test(detail))
    return "开发报告未通过代码与工作区校验，具体旧校验子因未保存，不能据此认定开发完成";
  if (!/(?:^|;\s*)cause=WORK_SLICE(?:;|$)/.test(detail)) return null;
  const rule = detail.match(/(?:^|;\s*)validation_rule=([A-Z_]+)(?:;|$)/);
  const reasons = {
    PARTIAL_CANDIDATE: "本轮仍有后续步骤，只能保存开发进度，完整候选未接纳",
    UNSELECTED_COMPLETION: "本轮报告把未选定的后续步骤记为完成，平台未接纳报告",
    DEFERRED_STEPS: "开发进度遗漏了后续待完成步骤，平台未接纳报告",
    STEP_PARTITION: "开发进度未完整列出已完成和待完成步骤，平台未接纳报告",
    PRIOR_COMPLETION: "开发进度撤回了此前已完成的步骤，平台未接纳报告",
    SOURCE_REVISION: "开发报告未绑定当前代码基线，平台未接纳报告",
    TASK_BINDING: "开发报告不属于当前任务切片，平台未接纳报告",
    OUTPUT_KIND: "本轮报告类型不符合开发切片约定，平台未接纳报告",
    INPUT_CONTRACT: "当前开发切片不满足执行前提，平台未接纳报告",
  };
  return reasons[rule?.[1]] || "开发报告不符合本轮步骤约定，平台未接纳报告";
}
function operationBaselinePurpose(operation) {
  const result = operationResult(operation);
  const purpose = operation.intent?.purpose || operation.baseline_purpose ||
    result?.execution_baseline_plan?.purpose || result?.execution_baseline_binding?.purpose;
  if (purpose) return purpose;
  const planSha256 = operation.intent?.expected_plan_sha256;
  if (!planSha256) return null;
  const proposal = operations.find(item => operationAction(item) === "PROPOSE_EXECUTION_BASELINE" &&
    item.status === "SUCCEEDED" && operationProject(item) === operationProject(operation) &&
    item.intent?.delivery_id === operation.intent?.delivery_id && item.intent?.task_id === operation.intent?.task_id &&
    operationResult(item)?.execution_baseline_plan?.plan_sha256 === planSha256);
  return proposal && operationResult(proposal).execution_baseline_plan.purpose;
}
function operationPurpose(operation) {
  if (["PROPOSE_EXECUTION_BASELINE", "EXECUTE_EXECUTION_BASELINE"].includes(operationAction(operation)) &&
      operationBaselinePurpose(operation) === "context_capacity_resume")
    return operationAction(operation) === "EXECUTE_EXECUTION_BASELINE"
      ? "保存精确恢复决定及完整开发进度，代码版本保持，交付保持暂停；之后需要另行继续原需求。"
      : "检查容量等待与完整开发现场，准备保留原需求、分支、代码版本和进度的恢复方案；准备不启动开发。";
  if (operationAction(operation) === "EXECUTE_EXECUTION_BASELINE" && operation.intent?.continuation_mode === "pause")
    return "保存精确工程决定及完整开发进度，更新所批准的代码和规范输入，交付保持暂停；此操作不启动 Coder。";
  if ((operation.intent?.purpose || operation.baseline_purpose) === "legacy_workspace_rescue")
    return "检查本机执行与恢复前提，封存同一需求的完整合法草稿，准备工程恢复方案。";
  if (operationAction(operation) === "EXECUTE_EXECUTION_BASELINE" &&
      (operation.intent?.confirm_legacy_containment === true || operation.intent?.confirm_local_execution_stopped === true))
    return "按精确工程决定保留进度继续同一需求，保留旧执行未知结果和完整历史。";
  return {
    PRODUCT_REPLY: "记录产品回复并继续梳理需求。",
    PRODUCT_APPROVAL: "确认本版产品规格并推进后续交付。",
    CONTINUE_DELIVERY: "接续已保存的交付进度。",
    RESUME_EXECUTION_BASELINE: "按明确继续决定释放当前保留进度的暂停，使用已预留身份接续原需求。",
    RECOVER_DESIGN: "处理本次技术设计恢复。",
    RECHECK_DESIGN: "核对保留的设计问题与产品需求。",
  }[operationAction(operation)] || null;
}
function operationActionLabel(operation) {
  if (["PROPOSE_EXECUTION_BASELINE", "EXECUTE_EXECUTION_BASELINE"].includes(operationAction(operation)) &&
      operationBaselinePurpose(operation) === "context_capacity_resume")
    return operationAction(operation) === "EXECUTE_EXECUTION_BASELINE"
      ? "批准保留进度，保持暂停" : "准备保留进度的恢复方案";
  if (operationAction(operation) === "EXECUTE_EXECUTION_BASELINE" && operation.intent?.continuation_mode === "pause")
    return operation.intent?.confirm_legacy_containment || operation.intent?.confirm_local_execution_stopped
      ? "批准保留进度，保持暂停" : "批准更新基线，保持暂停";
  if ((operation.intent?.purpose || operation.baseline_purpose) === "legacy_workspace_rescue") return "准备保留进度的恢复方案";
  if (operationAction(operation) === "EXECUTE_EXECUTION_BASELINE" &&
      (operation.intent?.confirm_legacy_containment === true || operation.intent?.confirm_local_execution_stopped === true))
    return "批准保留进度并继续原需求";
  return label(operationAction(operation));
}
function currentEngineeringRescueAdvice(operation, request) {
  const handling = operationResult(operation)?.engineering_wait_handling;
  if (!request || request.project_id !== operationProject(operation) || !handling) return null;
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
  if (operation.status !== "SUCCEEDED" || !deliveryOperationActions.has(operationAction(operation))) return null;
  const stage = operationResultStage(operation);
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
  if (!request || operation.status !== "RUNNING" || !deliveryOperationActions.has(operationAction(operation)) ||
      operationTarget(operation) !== request.id || operationProject(operation) !== request.project_id ||
      activeOperation(request.id, request.project_id)?.operation_id !== operation.operation_id) return null;
  const node = requestNodeExecution(request);
  const execution = request.execution;
  const responsibility = node.responsibility || (node.requiresEngineeringCheck ? "engineering"
    : ["WAITING_PRODUCT_REPLY", "WAITING_PRODUCT_APPROVAL"].includes(request.stage) ? "product" : execution?.responsibility);
  return {
    title: `当前阶段 · ${deliveryPhase(request, node)} · ${node.label}`,
    reason: node.upstreamProcessing ? "当前节点正在执行，请等待本阶段处理完成。"
      : humanizeBlockingText(node.reason || execution?.reason || request.blocker),
    responsibility: {product: "产品负责人", team: "ASE 团队", engineering: "工程团队"}[responsibility] || null,
    nextAction: node.upstreamProcessing ? "请等待本轮处理完成。"
      : humanizeBlockingText(node.nextAction || execution?.next_action || request.next_action),
    preparation: preparationLatestSummary(request),
  };
}
function productExecutionSummary(item, {guidance = true} = {}) {
  if (!item.execution) return null;
  const execution = item.execution;
  const node = item.stage ? requestNodeExecution(item) : taskExecutionPresentation(item);
  const section = el("div", undefined, "product-execution-summary");
  section.append(
    el("p", "交付阶段 · " + deliveryPhase(item, node), "execution-phase"),
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
  if (status === "RUNNING") return runningRolePresentation(task.execution);
  if (status === "READY") return queuedRolePresentation();
  if (status === "RETRY_SCHEDULED") return {state: "paused", label: "待重试", status, responsibility: "team",
    reason: "模型执行重试已排队。", nextAction: "请等待计划重试，平台将按记录的时间继续。"};
  if (status === "PREPARING_EXECUTION") return {state: "paused", label: "准备执行", status, responsibility: "team",
    reason: "平台正在准备已批准的执行计划。", nextAction: "请等待本轮准备完成。"};
  return {label: label(status), status};
}
function runningRolePresentation(execution) {
  const phase = execution?.state === "RUNNING" ? {
    ROLE_KNOWLEDGE_PREPARATION: "准备知识", ROLE_FINALIZING: "保存结果",
  }[execution.reason_code] : null;
  return {state: "running", label: phase ? "执行中 · " + phase : "执行中", status: "RUNNING", responsibility: "team",
    reason: execution?.state === "RUNNING" && execution.reason
      ? execution.reason : "当前角色已领取工作，细分执行进度暂未上报。",
    nextAction: execution?.state === "RUNNING" && execution.next_action
      ? execution.next_action : "请等待当前工作处理；主执行是否开始尚无细分记录。"};
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
  return Boolean(operation?.status === "RUNNING" && operationProject(operation) === request.project_id &&
    deliveryOperationActions.has(operationAction(operation)));
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
function canCloseRequirement(request) {
  if (request.stage === "BLOCKED" || productDiscussionStages.has(request.stage)) return true;
  if (request.stage !== "DELIVERING") return false;
  const tasks = requestTasks(request);
  if (!tasks.length) return false;
  let waiting = false;
  for (const task of tasks) {
    const steps = (task.role_queue || []).filter(step => step.status !== "CLOSED");
    if (!task.terminal && !steps.length) return false;
    for (const step of steps) {
      const facts = step.wait_disposition?.facts;
      const expectedRole = {IMPLEMENTING: "coder", QA: "qa", REVIEW: "reviewer"}[task.status];
      if (task.terminal || !["WAITING_HUMAN", "WAITING_DEPENDENCY"].includes(step.status) ||
          step.lease_liveness === "LEASE_VALID" || step.wait_disposition?.responsibility !== "engineering" ||
          !facts || facts.task_id !== task.task_id || facts.work_item_id !== step.work_item_id ||
          step.role !== expectedRole || facts.role !== step.role ||
          facts.task_intent_sha256 !== task.task_intent_sha256 ||
          !Number.isInteger(task.task_revision) || task.task_revision !== facts.checkpoint_sequence ||
          !/^[a-f0-9]{40}$/.test(facts.source_revision || "")) return false;
      waiting = true;
    }
  }
  // The command still rechecks complete history, process locks and current leases.
  return waiting || tasks.every(task => task.terminal &&
    (task.role_queue || []).every(step => step.status === "CLOSED"));
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
function taskParentRequest(task) {
  return snapshot.requests.find(item => item.id === task.request_id && item.project_id === task.project_id) || null;
}
function isHistoricalRequestTask(task) {
  const request = taskParentRequest(task);
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
function recoveryApprovalNextAction(approval) {
  return {
    coder_scope: "请工程授权者核对下方精确文件范围，点击“批准文件范围”。批准只准备恢复计划，不会启动 Agent；准备后还需审批恢复计划。",
    coder_recovery: "请工程授权者核对下方恢复方案，点击“批准并继续”。平台将保留开发进度并安排 Coder 继续开发；实现完成后仍须独立 QA 和 Reviewer 验收。",
    coder_interruption: "请工程授权者核对下方保留进度的继续方案，点击“批准并继续”。平台按精确方案继续原需求，不表示实现已经完成。",
    pre_execution_restart: "请工程授权者核对下方执行重启方案，点击“批准并继续”。平台按精确方案安排新执行，原记录保留。",
    candidate_verification: "请工程授权者核对下方独立验证方案，点击“批准并继续”。平台仅按方案继续 QA 或 Reviewer，不表示验收已经通过。",
    joint_integration: "请工程授权者核对下方联合验收方案，点击“批准并继续”。平台按批准范围开展联合验收，不表示需求已经交付。",
    prerequisite_repair: "请工程授权者核对下方工程前提修复方案，点击“批准并继续”。平台按精确范围安排修复和独立验收，不表示需求已经完成。",
  }[approval.kind] || "请工程授权者核对下方具体方案，点击“批准并继续”。批准只授权本次精确方案，当前尚未继续执行。";
}
function requestRecoveryDecision(request) {
  if (["DONE", "CLOSED", "WAITING_PRODUCT_REPLY", "WAITING_PRODUCT_APPROVAL",
      "WAITING_DELIVERY_FINALIZATION"].includes(request.stage) || approvedKnowledge(request) || !canControlCurrentTeam() ||
      currentProjectId() !== request.project_id || !consoleSupportsOperation("CONTINUE_DELIVERY") ||
      activeOperation(request.id, request.project_id)) return null;
  // A prepared decision cannot replace actual current dispatch or role execution.
  if (currentRequestTasks(request).some(task => !task.terminal &&
      (["QUEUED", "CONTINUE_REQUIRED"].includes(task.status) || task.role_queue?.some(step =>
        ["READY", "LEASED", "RUNNING", "RETRY_SCHEDULED"].includes(step.status) &&
        !(step.status === "RETRY_SCHEDULED" && interruptedStep(step)))))) return null;
  const approval = latestApproval(request.id, request.checkpoint_sha256, request.project_id);
  const reason = approval?.kind === "coder_scope"
    ? approval.coder_scope_request
      ? "Coder 申请补充文件范围，尚未修改所申请的文件；本次方案尚未批准执行。"
      : "Coder 的文件改动超出原任务授权范围，原执行现场保留；本次方案尚未批准执行。"
    : approval?.title + "；本次方案尚未批准执行。";
  return approval ? {state: "blocked", label: "待工程确认", status: "WAITING_ENGINEERING",
    currentApproval: true, approval, responsibility: "engineering",
    reason,
    nextAction: recoveryApprovalNextAction(approval)} : null;
}
function requestRoleDispatch(tasks) {
  const entries = tasks.filter(task => !task.terminal && !task.blocker &&
    !waitingExecutionStep(task) && !interruptedExecution(task) &&
    !["WAITING", "STOPPED", "INTERRUPTED"].includes(task.execution?.state)).flatMap(task =>
    (task.role_queue || []).filter(step => step.role === roleForTaskStatus[task.status] && !interruptedStep(step))
      .map(step => ({task, step})));
  const running = entries.find(({step}) => step.status === "RUNNING" && step.lease_liveness === "LEASE_VALID");
  if (running) return {...runningRolePresentation(running.task.execution), currentRoleDispatch: true};
  const steps = entries.map(({step}) => step);
  if (steps.some(step => ["READY", "LEASED"].includes(step.status)))
    return {...queuedRolePresentation(), label: "已排队", currentRoleDispatch: true};
  if (steps.some(step => step.status === "RETRY_SCHEDULED"))
    return {state: "paused", label: "待重试", status: "RETRY_SCHEDULED", responsibility: "team",
      reason: "模型执行重试已排队。", nextAction: "请等待计划重试，平台将按记录的时间继续。",
      currentRoleDispatch: true};
  return null;
}
function consistentCurrentOperationSummary(source, projectId) {
  if (!operationSummaryMode()) return true;
  const observations = [...operationSummaryPages.values()]
    .filter(state => state.page.team_id === snapshot?.team_id)
    .flatMap(state => [...state.page.items, ...state.page.active])
    .filter(item => item.operation_id === source.operation_id);
  // Independent scope polls may disagree temporarily. An older page cannot
  // erase an already observed new result, independently of control readiness.
  return observations.length > 0 && observations.every(item => item.team_id === source.team_id &&
    item.project_id === projectId && operationProject(source) === projectId && item.status === source.status &&
    item.sequence === source.sequence && item.operation_sha256 === source.operation_sha256);
}
function observedApprovedRecoveryOperation(request, operation) {
  if (!operationsAvailable || projectSwitchPending() ||
      currentProjectId() !== request.project_id || !snapshot?.team_id ||
      consoleTeamId !== snapshot.team_id || operation?.team_id !== snapshot.team_id ||
      operation.status !== "RUNNING" || operationAction(operation) !== "CONTINUE_DELIVERY" ||
      operationProject(operation) !== request.project_id || operationTarget(operation) !== request.id ||
      activeOperation(request.id, request.project_id)?.operation_id !== operation.operation_id ||
      operation.intent?.expected_checkpoint_sha256 !== request.checkpoint_sha256 ||
      !/^[a-f0-9]{64}$/.test(operation.intent?.approved_plan_sha256 || "")) return false;
  if (!consistentCurrentOperationSummary(operation, request.project_id)) return false;
  // Observe only the currently accepted exact request; this never restores control authority.
  return operationReadingRecords().some(source => source.team_id === operation.team_id && source.status === "SUCCEEDED" &&
    consistentCurrentOperationSummary(source, request.project_id) &&
    operationProject(source) === request.project_id && operationTarget(source) === request.id &&
    operationResult(source)?.approval?.plan_sha256 === operation.intent?.approved_plan_sha256 &&
    operationResult(source).delivery_id === request.id &&
    operationResult(source).checkpoint_sha256 === operation.intent?.expected_checkpoint_sha256);
}
function requestNodeExecution(request) {
  if (request.stage === "DONE") return {state: "done", label: "已完成", status: "DONE"};
  if (request.stage === "CLOSED") return {state: "closed", label: "已关闭", status: "CLOSED"};
  const execution = request.execution;
  const tasks = currentRequestTasks(request);
  const active = activeOperation(request.id, request.project_id);
  const operation = active && operationProject(active) === request.project_id &&
    deliveryOperationActions.has(operationAction(active)) ? active : null;
  const waiting = tasks.find(task => waitingExecutionStep(task));
  const expired = tasks.find(task => !task.terminal &&
    (interruptedExecution(task) || task.role_queue?.some(interruptedStep)));
  const childBlocker = operationChildBlocker(request, operation) ||
    (!operation ? terminalBlockedRequestTask(request) : null);
  const roleDispatch = requestRoleDispatch(tasks);
  if (["WAITING_PRODUCT_REPLY", "WAITING_PRODUCT_APPROVAL"].includes(request.stage))
    return {state: "blocked", label: request.stage === "WAITING_PRODUCT_REPLY" ? "需确认" : "待审批", status: request.stage};
  if (request.stage === "WAITING_DELIVERY_FINALIZATION")
    return {state: "blocked", label: "待确认", status: request.stage, reason: request.blocker};
  if (approvedKnowledge(request))
    return {state: "blocked", label: "已确认的知识 · 待继续", status: "KNOWLEDGE_APPROVED"};
  const decision = requestRecoveryDecision(request);
  if (decision) return decision;
  if (operation?.status === "RUNNING" && operationAction(operation) === "CONTINUE_DELIVERY" &&
      consistentCurrentOperationSummary(operation, request.project_id) &&
      (canControlCurrentTeam() || observedApprovedRecoveryOperation(request, operation)) &&
      currentProjectId() === request.project_id &&
      !childBlocker && !waiting && !expired && !tasks.some(task => !task.terminal) &&
      (execution?.state === "STOPPED" || tasks.some(task => task.terminal && taskGroup(task) === "blocked")))
    return {state: "paused", label: "平台正在处理恢复", status: "PREPARING_EXECUTION",
      platformProcessing: true, responsibility: "team",
      reason: "本次恢复请求的处理记录尚未结束；当前尚未取得新的可核验角色执行记录。",
      nextAction: "请等待平台检查并返回结果；不要重复准备或批准。"};
  // A current bound role queue supersedes the retained original STOPPED summary.
  // New waits, failures and expired claims still require their own handling.
  if (execution?.state === "STOPPED" && roleDispatch && !waiting && !expired && !childBlocker &&
      !["WAITING_HUMAN", "WAITING_DEPENDENCY"].includes(request.stage) &&
      execution.reason_code !== "EXECUTION_CLAIM_EXPIRED") return roleDispatch;
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
    return roleDispatch?.status === "RETRY_SCHEDULED" ? roleDispatch : {state: "paused", label: "待重试", status: "RETRY_SCHEDULED", responsibility: "team",
      reason: "模型执行重试已排队。", nextAction: "请等待计划重试，平台将按记录的时间继续。"};
  const roleSteps = tasks.filter(task => !task.terminal).flatMap(task =>
    (task.role_queue || []).filter(step => step.role === roleForTaskStatus[task.status]));
  const hasNativeStage = tasks.some(task => !task.terminal && roleForTaskStatus[task.status]);
  if (operation?.status === "QUEUED" || execution?.state === "QUEUED" ||
      roleSteps.some(step => ["READY", "LEASED"].includes(step.status)))
    return roleDispatch?.status === "READY" ? roleDispatch : {...queuedRolePresentation(), label: "已排队"};
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
    return roleDispatch || runningRolePresentation();
  if (!operation && request.design_recovery_available && request.stage_budget?.exhausted !== "capacity")
    return {state: "blocked", label: "设计待恢复", status: "DESIGN_RECOVERY_REQUIRED", reason: request.blocker};
  if (!operation && designBudgetExhausted(request))
    return {state: "blocked", label: request.stage === "DESIGNING" ? "设计预算已用尽" : "执行预算已用尽",
      status: request.stage === "DESIGNING" ? "DESIGN_BUDGET_EXHAUSTED" : "RETRY_BUDGET_EXHAUSTED", reason: designBudgetSummary(request)};
  if (!operation && request.design_recheck_pending)
    return {state: "blocked", label: "待继续核对设计", status: "DESIGNING", reason: request.next_action};
  if (tasks.some(task => !task.terminal))
    return engineeringExecutionCheck();
  const failed = latestOperation(request.id);
  if (!operation && ["FAILED", "INTERRUPTED"].includes(failed?.status) && deliveryOperationActions.has(operationAction(failed)) &&
      (!operationProject(failed) || operationProject(failed) === request.project_id))
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
  const text = node.currentApproval || node.platformProcessing
    ? node.label : `${deliveryPhase(request)} · ${node.label}`;
  return el("span", text, `badge request-node-badge ${node.state}`);
}
function requestPresentation(request) {
  const currentNode = requestNodeExecution(request);
  if (currentNode.currentApproval) return {group: "blocked", status: currentNode.status,
    blocker: currentNode.reason, nextAction: currentNode.nextAction};
  if (currentNode.platformProcessing) return {group: "active", status: currentNode.status,
    blocker: null, nextAction: currentNode.nextAction};
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
  const latestResult = operationResult(latestOperation(request.id));
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
    running && deliveryOperationActions.has(operationAction(running))
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
      operationAction(deliveryOperation) === "PRODUCT_REPLY"
        ? "PRODUCT_DISCOVERY"
        : operationAction(deliveryOperation) === "PRODUCT_APPROVAL"
          ? "DESIGNING"
          : ["RECOVER_DESIGN", "RECHECK_DESIGN"].includes(operationAction(deliveryOperation))
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
      operationAction(failedDesignOperation),
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
  if (engineeringWaitSteps(request).length || engineeringPendingBaselineSteps(request).length) return false;
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
  if ((operationProject(operation) && operationProject(operation) !== request.project_id) ||
      !deliveryOperationActions.has(operationAction(operation)) || isSourceRevisionDrift(operation)) return false;
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
    (!operationProject(operation) || operationProject(operation) === request.project_id) &&
    operationTarget(operation) === request.id &&
    ["PRODUCT_APPROVAL", "CONTINUE_DELIVERY", "RECOVER_DESIGN"].includes(operationAction(operation)) &&
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

function knowledgePreparationTimeoutRole(value) {
  const match = String(value || "").trim().match(
    /^(?:TRANSIENT_INFRA:\s*)?(coder|qa|reviewer) knowledge preparation reached local time limit$/i,
  );
  return match ? {coder: "Coder", qa: "QA", reviewer: "Reviewer"}[match[1].toLowerCase()] : null;
}
function isStoppedCoderKnowledgeTimeout(request, node = requestNodeExecution(request)) {
  return request.stage === "BLOCKED" && node.state === "blocked" && !node.requiresEngineeringCheck &&
    !node.currentApproval && request.execution?.state === "STOPPED" &&
    knowledgePreparationTimeoutRole(node.reason) === "Coder";
}
function requestBlockingSummary(request) {
  if (requestPresentation(request).group !== "blocked") return null;
  const node = requestNodeExecution(request);
  const approval = node.currentApproval ? node.approval : null;
  if (node.currentApproval) {
    const historyReason = terminalBlockedRequestTask(request)?.blocker || request.blocker || request.execution?.reason;
    return {reasons: historyReason ? [{reason: historyReason, scopes: []}] : [], operationReason: null,
      approval, currentApproval: true, currentReason: node.reason, suggestedAction: node.nextAction,
      approvedKnowledge: false, responsibility: "engineering"};
  }
  if (isStoppedCoderKnowledgeTimeout(request, node)) {
    const unavailable = deliveryControlUnavailableReason();
    const active = activeOperation(request.id, request.project_id);
    return {reasons: [{reason: node.reason, scopes: []}], operationReason: null, approval: null,
      suggestedAction: unavailable ? unavailable.reason + " " + unavailable.next_action
        : active ? active.status === "QUEUED"
          ? "本次继续请求已排队，请等待平台检查并返回结果，不要重复提交。"
          : "平台正在处理本次继续请求，请等待操作结果，不要重复提交。"
        : !consoleSupportsOperation("CONTINUE_DELIVERY")
          ? "当前服务不支持继续交付。请在服务空闲时加载支持此操作的版本，再刷新原需求。"
          : "点击本页“继续交付”，由平台检查并准备保留进度的恢复方案；方案准备好后再核对并批准继续。",
      approvedKnowledge: false, responsibility: "engineering"};
  }
  if (node.requiresEngineeringCheck)
    return {reasons: [{reason: node.reason, scopes: []}], operationReason: null,
      approval, suggestedAction: node.nextAction,
      approvedKnowledge: false, responsibility: "engineering"};
  if (request.execution && request.execution.responsibility !== "product") {
    return {
      reasons: [{reason: node.reason || request.execution.reason, scopes: []}],
      operationReason: null,
      approval,
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
  const operationReason =
    operation?.status === "FAILED"
      ? operation.error_summary
      : operationNeedsHumanAttention(operation)
        ? operationResult(operation)?.next_action
        : null;
  const nextActions = blockedTasks.map((task) => task.next_action).filter(
    (value, index, values) =>
      value &&
      !reasons.has(value) &&
      value !== operationReason &&
      values.indexOf(value) === index,
  );
  let suggestedAction = "处理上述原因后，再点击“继续交付”。";
  if (approval)
    suggestedAction = recoveryApprovalNextAction(approval);
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
function nativeProviderFailureDetail(detail) {
  const marker = "; main_error=";
  const index = detail.indexOf(marker);
  const metadata = index < 0 ? detail : detail.slice(0, index);
  if (index < 0 || !/^(?:(?:coder|qa|reviewer) run run_[0-9a-z]+ failed: )?Codex CLI provider execution failed; cause=[A-Z0-9_]+; returncode=-?\d+; stdout_sha256=[0-9a-f]{64}; stderr_sha256=[0-9a-f]{64}$/.test(metadata))
    return {detail, summary: null};
  // Published summaries are redacted by the adapter. Decode only their first
  // JSON string, keep them out of reason/metadata selection and render as text.
  const token = detail.slice(index + marker.length).match(/^"(?:[^"\\]|\\.)*"/);
  if (!token) return {detail: metadata, summary: null};
  try {
    const decoded = JSON.parse(token[0]);
    const characters = Array.from(decoded.replace(/[\u0000-\u001f\u007f-\u009f]/g, " ").replace(/\s+/g, " ").trim());
    const summary = characters.length > 500 ? characters.slice(0, 499).join("") + "…" : characters.join("");
    return {detail: metadata, summary: summary || null};
  } catch {
    return {detail: metadata, summary: null};
  }
}
function isLocalizedNativeProviderFailure(text) {
  // The reader may prefix its already-localized detail with a static wait
  // reason. Preserve that complete display value without re-reading summary
  // prose as another blocker. The fixed native reason and both hashes must fit.
  return /(?:^| )(?:Coder|QA|Reviewer) 第 \d+ 次执行失败：(?:Codex CLI 模型服务执行失败|模型服务认证失败，当前阶段未完成|模型服务触发限流，当前阶段未完成|模型服务或执行器超时，当前阶段未完成)；主错误摘要：[^\r\n]+；(?:执行记录 run_[0-9a-z]+；)?证据摘要 [0-9a-f]{64}；证据摘要 [0-9a-f]{64}。$/.test(text);
}
function humanizeBlockingText(value) {
  const text = String(value || "").trim();
  if (!text) return "暂未记录具体原因。";
  const exact = {
    "coder-progress checkpoint_sequence must equal the run attempt": "本轮开发报告的进度序号与执行约定不一致，报告未被接纳。开发文件和原执行记录保留，请让平台核验现场并准备保留进度的续跑方案。",
    "Coder progress checkpoint_sequence must equal the exact request attempt": "本轮开发报告的进度序号与执行约定不一致，报告未被接纳。开发文件和原执行记录保留，请让平台核验现场并准备保留进度的续跑方案。",
    "new progress does not match the bound execution source": "平台在基线更新后选取开发进度失败，本次未能继续原需求，已保存的进度和现场仍保留。请加载修复版本并刷新原需求，再点击“继续原需求”；无需新建需求。",
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
    "Required context exceeds the configured input budget; no automatic retry.": "所需上下文超过平台输入容量，交付已暂停。请由平台调整输入装配后，为原需求准备保留完整开发进度的恢复方案。",
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
  if (isLocalizedNativeProviderFailure(text)) return text;
  const roleFailure = text.match(
    /^(?:(?:TRANSIENT_INFRA|NONTRANSIENT_INFRA|POLICY_VIOLATION|INVALID_OUTPUT|VERIFICATION_INCONCLUSIVE|WORK_INTERRUPTED):\s*)?(Coder|QA|Reviewer) failed at attempt (\d+): (.*)$/,
  );
  const nativeFailure = roleFailure ? nativeProviderFailureDetail(roleFailure[3]) : null;
  const classificationText = nativeFailure && nativeFailure.detail !== roleFailure[3] ? nativeFailure.detail : text;
  if (
    classificationText.includes("Coder requested continuation after the configured run budget")
  )
    return "Coder 已用完本轮连续执行次数，但实现尚未完成，需要创建恢复任务后继续。";
  if (
    classificationText.includes(
      "QA verification could not complete in the current environment",
    )
  )
    return "QA 未能在当前环境完成验证；候选代码已保留，继续交付时只会重新执行 QA/Review。";
  if (
    classificationText.includes(
      "failed Coder identity is missing, unsafe or ambiguous",
    ) ||
    classificationText.includes(
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
  if (roleFailure) {
    const detail = nativeFailure.detail;
    const reason = coderOutputDiagnostic(detail) || (detail.startsWith("工程执行已中断。草稿已保留。")
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
        : "执行失败，原始诊断已封存");
    const run = detail.match(/\brun_[0-9a-z]+\b/);
    const digests = [...detail.matchAll(/\b[0-9a-f]{64}\b/g)].slice(0, 2).map((item) => item[0]);
    const facts = [nativeFailure.summary ? `主错误摘要：${nativeFailure.summary}` : "", run?.[0] ? `执行记录 ${run[0]}` : "", ...digests.map((digest) => `证据摘要 ${digest}`)]
      .filter(Boolean);
    return `${roleFailure[1]} 第 ${roleFailure[2]} 次执行失败：${reason}${facts.length ? `；${facts.join("；")}` : ""}。`;
  }
  const localKnowledgeTimeout = knowledgePreparationTimeoutRole(text);
  if (localKnowledgeTimeout)
    return `${localKnowledgeTimeout} 知识准备达到本次执行时限，本轮尚未开始该角色的代码执行或验证；已有交付进度与历史保留。`;
  const knowledgeFailure = text.match(
    /^(?:(?:TRANSIENT_INFRA|NONTRANSIENT_INFRA|BUDGET_EXHAUSTED|POLICY_VIOLATION):\s*)?(Coder|QA|Reviewer) knowledge (preparation|assessment|intent) failed:\s*([A-Z0-9_:-]+)$/i,
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
  if (text.startsWith("CONTEXT_BUDGET_EXHAUSTED:") || text.startsWith("CONTEXT_CAPACITY:"))
    return "执行上下文超过平台输入容量，模型尚未调用；本次未消耗自动重试额度。请由平台调整上下文装配或执行能力后，再为原需求准备新的精确恢复方案。";
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
  if (summary.currentApproval) {
    section.append(el("h3", "待工程确认"), el("p", summary.currentReason),
      el("p", "下一步 · " + summary.suggestedAction, "request-blocking-next"),
      recoveryApprovalBox(request, summary.approval));
    if (summary.reasons.length) {
      const history = viewBlock(engineeringDetails("原执行历史", request.id + ":recovery-source-history"),
        "recovery-original-execution", summary.reasons);
      history.append(el("p", "以下为原执行停止时的记录。当前恢复方案已经准备，后续操作以本页待确认方案为准。", "muted"));
      for (const item of summary.reasons) history.append(el("p", humanizeBlockingText(item.reason), "muted"));
      section.append(history);
    }
    return section;
  }
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
          ? summary.approval.coder_scope_request
            ? "Coder 申请补充文件范围，尚未修改所申请的文件；平台保留已有进度，等待本次精确范围审批。"
            : "Coder 的文件改动超出原任务授权范围，平台已保留工作现场并进入文件范围审批。"
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
  for (const {task, step} of engineeringPendingBaselineSteps(request))
    section.append(engineeringAuthorizedContinuationBox(request, task, step));
  return section;
}

function recoveryApprovalCapabilityIssue() {
  return consoleSupportsOperation("CONTINUE_DELIVERY") ? null : {
    kind: "error", title: "当前服务不支持恢复审批",
    message: "当前服务未提供继续交付和恢复审批能力。" + consoleOperationVersionMismatchMessage,
  };
}
async function submitRecoveryApprovalOperation(intent, approvalSignature) {
  const request = requestById(intent.delivery_id);
  const current = request && latestApproval(request.id, request.checkpoint_sha256, request.project_id);
  if (!request || request.project_id !== intent.project_id || currentProjectId() !== intent.project_id ||
      ["DONE", "CLOSED"].includes(request.stage) ||
      request.checkpoint_sha256 !== intent.expected_checkpoint_sha256 ||
      JSON.stringify(current) !== approvalSignature || !canControlCurrentTeam() ||
      activeOperation(request.id, request.project_id)) {
    operationNotice = {kind: "error", title: "当前审批方案已变化",
      message: "请查看当前需求并重新核对所列方案；已失效的审批不能用于继续交付。"};
    renderDetail(); renderNotification(); return null;
  }
  const capabilityIssue = recoveryApprovalCapabilityIssue();
  if (capabilityIssue) {
    operationNotice = capabilityIssue;
    renderDetail(); renderNotification(); return null;
  }
  const decision = requestRecoveryDecision(request);
  if (!decision || JSON.stringify(decision.approval) !== approvalSignature) {
    operationNotice = {kind: "error", title: "当前审批方案已变化",
      message: "当前工作已有新的执行或确认步骤。请查看当前需求，不能使用先前保留的恢复审批。"};
    renderDetail(); renderNotification(); return null;
  }
  return submitOperation(intent);
}
function recoveryApprovalBox(request, approval) {
  const capabilityIssue = recoveryApprovalCapabilityIssue();
  const intent = {
    action: "CONTINUE_DELIVERY", project_id: request.project_id, delivery_id: request.id,
    expected_checkpoint_sha256: request.checkpoint_sha256,
    ...(approval.kind === "coder_scope"
      ? { approved_scope_sha256: approval.plan_sha256,
          ...(approval.coder_scope_request ? { coder_scope_request: approval.coder_scope_request } : {}) }
      : approval.kind === "prerequisite_repair"
        ? { approved_repair_sha256: approval.plan_sha256 }
        : { approved_plan_sha256: approval.plan_sha256 }),
  };
  const approvalSignature = JSON.stringify(approval);
  const management = viewBlock(el("section", undefined, "engineering-current-decision"),
    "current-recovery-decision", [intent, approvalSignature, canControlCurrentTeam(),
      capabilityIssue]);
  management.append(el("p", "当前需要工程授权者确认。请阅读下方具体方案后决定；平台会核验工程权限并记录实际批准者。", "muted"));
  const box = el("div", undefined, "approval-box request-blocking-approval");
  box.append(el("h3", approval.title));
  for (const fact of approval.facts) box.append(el("p", fact));
  if (Array.isArray(approval.technical_facts) && approval.technical_facts.length) {
    const details = engineeringDetails("技术核对信息", "current-recovery-technical-facts");
    for (const fact of approval.technical_facts) details.append(el("p", fact, "paths"));
    box.append(details);
  }
  if (capabilityIssue) box.append(el("strong", capabilityIssue.title), el("p", capabilityIssue.message, "muted"));
  const approve = deliveryButton(
    approval.kind === "coder_scope" ? "批准文件范围" : "批准并继续",
    () => submitRecoveryApprovalOperation(intent, approvalSignature),
    "primary",
  );
  setDeliveryControlDisabled(approve, Boolean(capabilityIssue));
  box.append(
    el(
      "p",
      approval.kind === "coder_scope"
        ? "批准后平台按上方精确范围准备恢复计划，不会启动 Agent；执行前仍需审批恢复计划。"
        : "批准只对当前方案有效；方案变化后需要重新确认。",
      "muted",
    ),
    approve,
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
function currentOperationNoticeObservation() {
  const teamId = snapshot?.team_id;
  if (!teamId || consoleTeamId !== teamId) return null;
  if (operationNoticeObservation?.teamId !== teamId)
    operationNoticeObservation = {teamId, initialized: false, knownIds: new Set(), observedIds: new Set()};
  return operationNoticeObservation;
}
function observeOperationNotices() {
  if (!operationsAvailable) return;
  const observation = currentOperationNoticeObservation();
  if (!observation) return;
  const currentIds = new Set();
  for (const operation of operationReadingRecords()) {
    if (operation.team_id && operation.team_id !== observation.teamId) continue;
    currentIds.add(operation.operation_id);
    if (["QUEUED", "RUNNING"].includes(operation.status) ||
        (observation.initialized && !observation.knownIds.has(operation.operation_id)))
      observation.observedIds.add(operation.operation_id);
  }
  // Bound this ephemeral catalog to the records still supplied by this Team.
  observation.observedIds = new Set([...observation.observedIds].filter(id => currentIds.has(id)));
  observation.knownIds = currentIds;
  observation.initialized = true;
}
function observeSubmittedOperation(operation, teamId) {
  const observation = currentOperationNoticeObservation();
  if (observation?.teamId === teamId && (!operation.team_id || operation.team_id === teamId))
    observation.observedIds.add(operation.operation_id);
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
  if (!operation.intent) {
    const target = operationRequest(operation);
    const active = ["QUEUED", "RUNNING"].includes(operation.status);
    const attention = operationNeedsHumanAttention(operation);
    if (!active && !attention && !["FAILED", "INTERRUPTED"].includes(operation.status)) return null;
    return {key: operationNoticeKey(operation), operationId: operation.operation_id,
      state: active ? "ACTIVE" : attention ? "ACTION_REQUIRED" : operation.status,
      kind: active ? "info" : attention ? "warning" : "error",
      title: `${operationProject(operation) ? projectName() : "团队"} · ${operationActionLabel(operation)} · ${label(operation.status)}`,
      message: humanizeBlockingText(operation.error_summary || operation.summary ||
        (active ? "平台正在处理已接收的操作，执行结果以需求详情为准。" : "请打开需求查看完整处理说明。")),
      target: target?.id || null, jumpLabel: target ? "打开需求工作区" : null};
  }
  const context = operationProject(operation)
    ? projectName() : "团队";
  const targetId = operationTarget(operation);
  const request = operationRequest(operation);
  const target = request ? targetId : null;
  const progress = currentOperationProgress(operation, request);
  const needsHumanAttention = operationNeedsHumanAttention(operation);
  const knowledgeApproved =
    needsHumanAttention &&
    operationResult(operation)?.stage === "WAITING_HUMAN" &&
    request &&
    operationResult(operation).checkpoint_sha256 === request.checkpoint_sha256 &&
    approvedKnowledge(request);
  const rescueFailure = operationAction(operation) === "PROPOSE_EXECUTION_BASELINE" && operation.intent?.purpose === "legacy_workspace_rescue"
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
          ? operationAction(operation) === "HANDLE_DELIVERY_WAIT"
            ? "处理中断的操作已接收，等待平台执行。关闭弹窗不会改变当前等待。"
            : "操作已安全接收，正在等待 Manager 执行。关闭弹窗不会中断任务。"
          : progress
            ? [progress.title, progress.reason, progress.responsibility && "处理方 · " + progress.responsibility,
              progress.nextAction && "下一步 · " + progress.nextAction, "关闭弹窗不会改变交付状态。"].filter(Boolean).join("\n")
          : operationAction(operation) === "HANDLE_DELIVERY_WAIT"
            ? "平台正在处理中断。只有已核实、且现有授权允许的路径才会继续；当前等待与验收结果不会由提示覆盖。"
          : operationAction(operation) === "INSPECT_DELIVERY_WAIT"
            ? "工程团队正在核验原执行与现场。调查期间保留原等待状态，调查不会产生验收结论。"
          : operationAction(operation) === "RESOLVE_DELIVERY_WAIT"
            ? "工程团队正在记录精确处理决定并继续原交付。是否恢复及验收通过以新的执行记录为准。"
          : operationAction(operation) === "PROPOSE_EXECUTION_BASELINE"
            ? operation.intent?.purpose === "legacy_workspace_rescue"
              ? "平台正在检查本机执行与恢复前提并封存完整合法草稿；尚未启动下一轮，也未改变旧执行的未知结果。"
              : "工程团队正在核验原分支、完整草稿和目标代码版本，尚未改变交付或验收结论。"
          : operationAction(operation) === "EXECUTE_EXECUTION_BASELINE"
            ? operation.intent?.continuation_mode === "pause"
              ? "平台正在保存精确工程决定和完整开发进度；本次处理完成后仍保持暂停，不会启动 Coder。"
            : operation.intent?.confirm_legacy_containment === true || operation.intent?.confirm_local_execution_stopped === true
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
        : operationResult(operation)?.engineering_wait_handling
          ? currentEngineeringRescueAdvice(operation, request) || [operationResult(operation).engineering_wait_handling.summary, operationResult(operation).engineering_wait_handling.user_action]
            .filter(Boolean).map(humanizeBlockingText).join("\n")
        : operationResult(operation)?.diagnostic
          ? humanizeBlockingText(operationResult(operation).diagnostic)
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
  if (consoleAvailable === true && consoleDeliveryReady === false && consoleMode !== "inspection")
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
      notice.kind === "error" ? "!" : notice.kind === "success" ? "✓" : "i",
      `settings-result-icon ${["error", "warning", "success"].includes(notice.kind) ? notice.kind : "info"}`,
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
  const ownerTeamId = snapshot?.team_id;
  const owner = operationWriteOwnerSignature();
  const productReadBinding = intent.action === "PRODUCT_APPROVAL"
    ? productApprovalReadBinding(snapshot?.requests.find(item => item.id === intent.delivery_id)) : null;
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
    if ((intent.continuation_mode === "pause" || intent.action === "RESUME_EXECUTION_BASELINE") &&
        !consoleSupportsPausedBaseline())
      throw new Error("本次保留进度暂停或继续请求未被受理，不是原需求新增的阻塞。" + consoleOperationVersionMismatchMessage);
    requireProductApprovalRead(intent, productReadBinding);
    await recheckOperationWriteFacts(intent);
    if (owner !== operationWriteOwnerSignature() || !canControlCurrentTeam() ||
        !consoleSupportsOperation(intent.action) || activeOperation(intent.delivery_id, intent.project_id))
      throw new Error("当前操作或控制资格已变化，请重新核对后再提交。");
    requireProductApprovalRead(intent, productReadBinding);
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
    if (operationSummaryMode()) {
      cacheFullOperation(payload);
      operationDetailReadyScope = null;
      // The newly accepted exact full record denies duplicate work immediately;
      // next summary read replaces this temporary reading projection.
      currentOperationSources = [...currentOperationSources.filter(item => item.operation_id !== payload.operation_id), {
        operation_id: payload.operation_id, team_id: payload.team_id, project_id: operationProject(payload),
        delivery_id: operationTarget(payload), action: operationAction(payload), status: payload.status,
        operation_sha256: payload.operation_sha256, sequence: payload.sequence,
        requested_at: payload.requested_at, updated_at: payload.updated_at, has_details: true,
      }].slice(-operationDetailMaximumCount);
      operations = [...operationDetailCache.values()].map(item => item.value)
        .filter(item => currentOperationSources.some(source => source.operation_id === item.operation_id));
    } else operations = [...operations.filter(item => item.operation_id !== payload.operation_id), payload];
    observeSubmittedOperation(payload, ownerTeamId);
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
  observeOperationNotices();
  const visible = [...operationReadingRecords()]
    .filter((operation) => {
      if (operation.team_id && operation.team_id !== snapshot?.team_id) return false;
      if (operationProject(operation) && operationProject(operation) !== currentProjectId()) return false;
      if (
        operation.status === "SUCCEEDED" &&
        !operationNeedsHumanAttention(operation)
      )
        return false;
      if (!operationNeedsHumanAttention(operation) &&
          !["FAILED", "INTERRUPTED"].includes(operation.status)) return true;
      if (operationProject(operation) && !operationRequest(operation) &&
          !(operationNoticeObservation?.teamId === snapshot?.team_id &&
            operationNoticeObservation.observedIds.has(operation.operation_id))) return false;
      const target = operationTarget(operation);
      return !operationReadingRecords().some(
        (candidate) =>
          (!candidate.team_id || candidate.team_id === snapshot?.team_id) &&
          (target !== null || operationAction(candidate) === operationAction(operation)) &&
          operationProject(candidate) === operationProject(operation) &&
          operationTarget(candidate) === target &&
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
  const isProductDiscussion = productDiscussionStages.has(request.stage);
  // Product discussion is a read/write draft surface, not an authority surface. Keep
  // the exact draft visible while Team facts are unavailable; its submit path below
  // still rechecks the live control gate before every network write. Other operations
  // retain the original top-level gate and are not rendered while control is stale.
  if (!canControlCurrentTeam() && !isProductDiscussion) return;
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
  const sourceRevisionDrift = isSourceRevisionDrift(
    latestOperation(request.id),
  );
  const discussionKeyFor = candidate => JSON.stringify([
    snapshot?.team_id, candidate.project_id, candidate.id, candidate.checkpoint_sha256, candidate.stage,
    activeOperation(candidate.id, candidate.project_id)?.operation_id || null,
    isSourceRevisionDrift(latestOperation(candidate.id)), candidate.stage_budget,
  ]);
  const discussionKey = discussionKeyFor(request);
  const identity = JSON.stringify([snapshot?.team_id, request.project_id, request.id]);
  let discussionFormCache = discussionFormCaches.get(identity);
  if (discussionFormCache && discussionFormCache.key !== discussionKey) {
    discussionFormCache.dispose();
    discussionFormCaches.delete(identity);
    discussionFormCache = null;
  }
  const approvingProduct = operationAction(running) === "PRODUCT_APPROVAL";
  // A terminal browser operation may leave an admitted QA/Reviewer item visible until
  // Manager creates its successor plan. Only a live Console operation suppresses the
  // recovery action; the durable task projection alone must not strand the operator.
  if (running && !isProductDiscussion) return;
  if (!running && designBudgetExhausted(request) && !canRecoverDesign(request) &&
      !requestRecoveryDecision(request)) return;
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
  const approval = requestRecoveryDecision(request)?.approval;
  if (approval && !running) {
    if (requestPresentation(request).group !== "blocked")
      appendOperation(recoveryApprovalBox(request, approval), true);
    return;
  }
  if (request.stage === "WAITING_PRODUCT_APPROVAL" && !running) {
    const approval = el("div", undefined, "approval-box");
    const readBinding = productApprovalReadBinding(request);
    const approve = deliveryButton("批准 ProductSpec 并开始交付", () => {
      const current = requestById(request.id);
      if (teamSummaryMode() && (!current || !productApprovalReadReady(current) ||
          readBinding !== productApprovalReadBinding(current))) return null;
      return submitOperation({action:"PRODUCT_APPROVAL", project_id:request.project_id,
        delivery_id:request.id, expected_checkpoint_sha256:request.checkpoint_sha256});
    }, "primary");
    setDeliveryControlDisabled(approve, !productApprovalReadReady(request));
    approval.append(
      el("h3", "产品文档已准备好"),
      el(
        "p",
        "请先阅读下方 ProductSpec。确认内容准确后批准；如果仍需调整，可在下方继续和 Product Agent 讨论。",
        "muted",
      ),
      ...(productApprovalReadReady(request) ? [] : [el("p", "当前完整 ProductSpec 尚未读取并核对，读取完成后才可批准。", "muted")]),
      approve,
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
      discussionFormCache.syncAvailability();
      appendDiscussionContent(discussionFormCache.form);
      return;
    }
    const boundDiscussion = {
      team_id: snapshot?.team_id || null,
      project_id: request.project_id,
      delivery_id: request.id,
      checkpoint_sha256: request.checkpoint_sha256,
      stage: request.stage,
    };
    const discussionFactsCurrent = (form = null) => {
      const current = snapshot?.requests?.find(item => item.id === boundDiscussion.delivery_id);
      return Boolean(
        form?.isConnected &&
        discussionFormCaches.get(identity)?.form === form &&
        discussionFormCaches.get(identity)?.key === discussionKey &&
        canControlCurrentTeam() &&
        snapshot?.team_id === boundDiscussion.team_id &&
        currentProjectId() === boundDiscussion.project_id &&
        current && current.project_id === boundDiscussion.project_id &&
        current.checkpoint_sha256 === boundDiscussion.checkpoint_sha256 &&
        current.stage === boundDiscussion.stage &&
        discussionKeyFor(current) === discussionKey &&
        !designBudgetExhausted(current) &&
        !activeOperation(boundDiscussion.delivery_id, boundDiscussion.project_id),
      );
    };
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
    const availability = el("p", undefined, "discussion-availability muted");
    availability.setAttribute("role", "status");
    const syncAvailability = () => {
      const unavailable = deliveryControlUnavailableReason();
      availability.hidden = !unavailable;
      availability.textContent = unavailable
        ? "暂时暂停发送。当前交付状态暂时无法核对；草稿仍可编辑、复制和整理。页面重新核对成功后恢复提交。"
        : "";
    };
    syncAvailability();
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
      availability,
      screenshotSection,
      feedback,
      submit,
    );
    if (request.stage === "PRODUCT_DISCOVERY" && !running) {
      submit.addEventListener("click", () => runUiAction(form, () => {
        if (!discussionFactsCurrent(form)) return;
        return submitOperation({
          action: "CONTINUE_DELIVERY",
          project_id: boundDiscussion.project_id,
          delivery_id: boundDiscussion.delivery_id,
          expected_checkpoint_sha256: boundDiscussion.checkpoint_sha256,
        });
      }));
    }
    onFormSubmit(form, async (event) => {
      event.preventDefault();
      if (!replyEnabled || !discussionFactsCurrent(form)) {
        feedback.className = "form-feedback error";
        feedback.textContent = "当前团队数据暂不可核对，草稿仍保留；恢复读取后请重新核对并提交。";
        return;
      }
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
          if (!discussionFactsCurrent(form))
            throw new Error("当前需求事实已变化，截图未继续提交；请重新核对后再发送。");
          const attachment = await adminFetch(
            "/api/v1/admin/projects/" +
              encodeURIComponent(boundDiscussion.project_id) +
              "/requirements/" +
              encodeURIComponent(boundDiscussion.delivery_id) +
              "/screenshots?filename=" +
              encodeURIComponent(item.name) +
              "&checkpoint=" +
              encodeURIComponent(boundDiscussion.checkpoint_sha256),
            {
              method: "POST",
              headers: { "Content-Type": "application/octet-stream" },
              body: item.file,
            },
          );
          uploaded.push(attachment.id);
        }
        if (!discussionFactsCurrent(form))
          throw new Error("当前需求事实已变化，回复未提交；草稿仍保留，请重新核对后再发送。");
        feedback.textContent = "已提交，等待 Product Agent…";
        const accepted = await submitOperation({
          action: "PRODUCT_REPLY",
          project_id: boundDiscussion.project_id,
          delivery_id: boundDiscussion.delivery_id,
          expected_checkpoint_sha256: boundDiscussion.checkpoint_sha256,
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
      key: discussionKey, form, dispose: revokeScreenshotPreviews, syncAvailability,
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
    appendOperation(action, isStoppedCoderKnowledgeTimeout(request));
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
function renderSummaryOperationHistory(panel, projectId, deliveryId) {
  if (!projectId) return;
  const state = operationHistoryPage(projectId, deliveryId);
  const request = deliveryId ? requestById(deliveryId) : null;
  const current = deliveryId ? activeOperation(deliveryId, projectId) : null;
  const fold = viewGroup(el("details", undefined, "request-history-fold"), "summary-operation-history");
  fold.dataset.key = "operation-history:" + projectId + "/" + (deliveryId || "project");
  fold.append(el("summary", `操作记录 · 共 ${state.total} 条`),
    el("p", `第 ${state.pageNumber} 页 · 当前 ${state.items.length} 条。所有历史均可翻页查看；展开单条读取完整处理原因和当次下一步。命令完成不代表需求已交付。`, "muted"));
  if (!operationsAvailable || state.changed) fold.append(el("p", state.changed
    ? "记录已有更新，当前页保留供阅读。请返回最新记录再翻页，不能把新旧记录合成当前事实。"
    : "以下是上次读取的记录，当前操作暂不可用；页面正在重新读取。", "error"));
  const list = viewGroup(el("ol", undefined, "execution-history"), "summary-history-list");
  for (const source of state.items) {
    const progress = !state.changed && current?.operation_id === source.operation_id &&
      current.operation_sha256 === source.operation_sha256 && request?.project_id === projectId
      ? currentOperationProgress(source, request) : null;
    const outcome = recordedOperationOutcome(source);
    const item = viewBlock(el("li", undefined, "execution-history-entry"), "summary-history:" + source.operation_id,
      {record: operationRenderFact(source), progress});
    if (progress) {
      item.append(el("strong", progress.title), el("p", "发起操作 · " + operationActionLabel(source), "muted"));
      if (progress.reason) item.append(el("p", "当前原因 · " + progress.reason));
      if (progress.responsibility) item.append(el("p", "处理方 · " + progress.responsibility, "muted"));
      if (progress.nextAction) item.append(el("p", "下一步 · " + progress.nextAction));
      if (progress.preparation) item.append(el("p", progress.preparation, "muted"));
    } else if (outcome) {
      item.append(el("strong", outcome.title, outcome.className), el("p", "发起操作 · " + operationActionLabel(source), "muted"),
        el("p", "记录的是当次操作结束时的交付状态；当前进度请查看上方交付流程。", "muted"));
    } else item.append(el("strong", operationActionLabel(source)));
    const status = el("p", "操作状态 · ", "muted");
    const commandStatus = badge(source.status);
    if (source.status === "SUCCEEDED") {
      commandStatus.textContent = "命令已完成";
      commandStatus.className = "badge";
    }
    status.append(commandStatus);
    item.append(status,
      el("p", "操作更新 · " + time(source.updated_at), "muted"));
    if (source.error_summary || source.summary) item.append(el("p", humanizeBlockingText(source.error_summary || source.summary),
      source.error_summary ? "error" : ""));
    if (source.next_step) item.append(el("p", "当次下一步（摘要） · " + humanizeBlockingText(source.next_step), "muted"));
    appendIndependentOperationResult(item, source);
    const details = el("details", undefined, "request-history-fold");
    details.append(el("summary", "查看完整处理记录"));
    const body = el("div");
    details.append(body);
    let reading = false;
    const releaseClosedDetail = () => {
      body.replaceChildren();
      const cached = operationDetailCache.get(source.operation_id)?.value;
      if (cached?.team_id === source.team_id && cached.operation_sha256 === source.operation_sha256 &&
          !currentOperationSources.some(value => value.operation_id === source.operation_id))
        operationDetailCache.delete(source.operation_id);
    };
    details.addEventListener("toggle", async () => {
      if (!details.open) {
        releaseClosedDetail();
        return;
      }
      if (reading) return;
      reading = true;
      const teamId = snapshot?.team_id, revision = selectionIntentRevision;
      const currentView = () => details.open && details.isConnected !== false && revision === selectionIntentRevision &&
        teamId === snapshot?.team_id && projectId === currentProjectId();
      body.replaceChildren(el("p", "正在读取完整记录…", "muted"));
      try {
        const record = await readFullOperation(source, {fresh: true});
        if (!currentView()) return;
        body.replaceChildren();
        appendIndependentOperationResult(body, record);
        const handling = operationResult(record)?.engineering_wait_handling;
        if (record.error_summary) body.append(el("p", humanizeBlockingText(record.error_summary), "error"));
        if (operationResult(record)?.diagnostic) body.append(el("p", "当次原因 · " + humanizeBlockingText(operationResult(record).diagnostic)));
        if (handling) {
          body.append(el("p", "当次平台处理 · " + humanizeBlockingText(handling.summary)),
            el("p", "当次用户操作 · " + humanizeBlockingText(handling.user_action), "muted"));
          if (handling.recheck_when) body.append(el("p", "当次复查时机 · " + humanizeBlockingText(handling.recheck_when), "muted"));
        }
        const proof = operationResult(record)?.engineering_wait_investigation || handling?.investigation;
        if (proof) appendEngineeringInvestigation(body, proof, {historical: true});
        if (operationResult(record)?.next_action) body.append(el("p", "当次下一步 · " + humanizeBlockingText(operationResult(record).next_action)));
        const approval = operationResult(record)?.approval;
        if (approval) {
          body.append(el("p", "当次待确认方案 · " + approval.title));
          for (const fact of [...(approval.facts || []), ...(approval.technical_facts || [])]) body.append(el("p", fact));
          body.append(el("p", "历史方案仅供阅读；需要审批时，请使用本页上方的当前完整方案。", "muted"));
        }
        const technical = engineeringDetails("排障信息（供工程人员使用）", record.operation_id);
        technical.append(el("p", "操作 · " + record.operation_id, "paths"),
          el("p", "记录摘要 · " + record.operation_sha256, "paths"));
        body.append(technical, modelCallDiagnostics(record));
      } catch (error) {
        if (currentView()) body.replaceChildren(el("p", error.message || "完整记录暂时无法读取，请重新展开。", "error"));
      } finally {
        reading = false;
        if (!currentView()) releaseClosedDetail();
      }
    });
    item.append(details);
    list.append(item);
  }
  const controls = el("div", undefined, "detail-actions");
  const redraw = () => { operationHistoryRevision++; render({preserveComposer: true, incremental: true}); };
  const prior = button("上一页", () => {
    const previous = state.back.pop();
    if (previous) Object.assign(state, previous);
    redraw();
  }, "secondary");
  prior.disabled = !state.back.length || state.loading;
  const next = button("下一页（更早记录）", async () => {
    try { await loadMoreOperationHistory(projectId, deliveryId); }
    catch { /* Fixed changed-history message is rendered from state. */ }
    redraw();
  }, "secondary");
  next.disabled = !state.next || state.loading || state.changed;
  const latest = button("返回最新记录", async () => {
    try {
      await readOperationSummaryPage(projectId, deliveryId);
      operationHistoryPages.delete(operationSummaryScopeKey(projectId, deliveryId));
    } catch { state.changed = true; }
    redraw();
  }, "secondary");
  controls.append(prior, next, latest);
  fold.append(list, controls);
  panel.append(fold);
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
        selectionIntentRevision++;
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
async function withReadDeadline(signal, read) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) abort();
  else signal?.addEventListener("abort", abort, {once: true});
  const timeout = setTimeout(abort, 40000);
  try { return await read(controller.signal); }
  finally {
    clearTimeout(timeout);
    signal?.removeEventListener("abort", abort);
  }
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
async function refreshConfigurationApply(signal) {
  if (!configurationApplyInFlight) return;
  if (
    configurationApplyStartedAt !== null &&
    Date.now() - configurationApplyStartedAt >= configurationApplyTimeoutMs
  ) {
    expireConfigurationApply();
    return;
  }
  try {
    const state = await adminFetch("/api/v1/admin/settings/apply", {signal});
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
      const saved = await adminFetch("/api/v1/admin/settings", {signal});
      settingsSnapshot = saved;
      if (saved.restart_required) {
        configurationApplyInFlight = false;
        configurationApplyResult = null;
        persistConfigurationApplyPending(null);
        render();
        return;
      }
      await refreshConsoleInfo(signal);
      runtimeStatusSnapshot = null;
      if (page === "status") await loadRuntimeStatus(signal);
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
async function resumeConfigurationApply(signal) {
  if (!configurationApplyPending) {
    try {
      const state = await adminFetch("/api/v1/admin/settings/apply", {signal});
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
  if (configurationApplyPending) await refreshConfigurationApply(signal);
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
async function loadKnowledge(signal) {
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
      [documents, index] = await withReadDeadline(signal, readSignal => Promise.all([
        adminFetch(owner + resource, {signal: readSignal}),
        mode === "background" ? adminFetch(owner + "/knowledge/index", {signal: readSignal}) : null,
      ]));
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
    knowledgeError = signal?.aborted || error?.name === "AbortError"
      ? "知识读取等待超时或连接已中断，请刷新重试；已保存的知识与需求保持不变。"
      : error instanceof Error ? error.message : "知识读取失败，请重试。";
    return true;
  } finally {
    if (isCurrent()) knowledgeLoading = false;
  }
}
function settingsHaveDraft() {
  return settingsDraft && (JSON.stringify(settingsDraft) !== settingsDraftBaseline ||
    Object.keys(runtimeVariablesDraft).length > 0);
}
async function loadAdministration(signal, {refreshConsole = true} = {}) {
  if (!administrationLoadPromise) administrationLoadPromise = withReadDeadline(signal, async readSignal => {
    try {
      const settings = await adminFetch("/api/v1/admin/settings", {signal: readSignal});
      settingsSnapshot = settings;
      if (!settingsHaveDraft()) {
        settingsDraft = structuredClone(settings.config);
        normalizeModelConnectionModes(settingsDraft);
        normalizeAgentModelRoutes(settingsDraft);
        settingsDraftBaseline = JSON.stringify(settingsDraft);
      }
      administrationAvailable = true;
      if (refreshConsole) await refreshConsoleInfo(readSignal);
      await resumeConfigurationApply(readSignal);
      let projects;
      try { projects = await adminFetch("/api/v1/admin/projects", {signal: readSignal}); }
      catch { projects = []; }
      administrationProjects = projects;
    } catch {
      administrationAvailable = false;
      // A read outage must never erase unsaved configuration or write-only secrets.
    }
  });
  const pending = administrationLoadPromise;
  try { await pending; }
  finally {
    if (administrationLoadPromise === pending) administrationLoadPromise = null;
  }
  // Share only Team administration facts. Knowledge reads belong to the current
  // scope, so an old Project request must never hold up a new Project navigation.
  if (page === "knowledge" && administrationAvailable) await loadKnowledge(signal);
}
async function loadRuntimeStatus(signal) {
  try {
    runtimeStatusSnapshot = await withReadDeadline(signal,
      readSignal => adminFetch("/api/v1/admin/status", {signal: readSignal}));
    runtimeStatusError = null;
  } catch (error) {
    runtimeStatusSnapshot = null;
    runtimeStatusError =
      error?.name === "AbortError" ? "平台状态读取等待超时或连接已中断，请重新打开状态页或刷新重试。"
        : error instanceof Error ? error.message : "平台状态暂时无法读取。";
  }
}
function administrationUnavailable(content) {
  content.append(
    el(
      "div",
      consoleMode === "inspection"
        ? "维护仅查看模式暂不开放设置和知识管理；需求、任务与执行历史仍可查看，交付保持暂停。"
        : "当前服务没有启用管理能力。请使用 ase-console 启动本地 Web Console。",
      consoleMode === "inspection" ? "admin-notice" : "operation-error",
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
  if (consoleDeliveryReady === false && consoleMode !== "inspection")
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
  selectionIntentRevision++;
  clearTeamDetailRead();
  pausedTaskDetailKey = null;
  selected = { kind, id };
  if (operationSummaryMode()) {
    operationDetailReadyScope = null;
    operationDetailReadyInventory = null;
    currentOperationSources = [];
    operationDetailCache.clear();
    operations = [];
    const revision = selectionIntentRevision;
    loadCurrentOperationDetails().then(() => {
      if (revision === selectionIntentRevision) render({preserveComposer: true, incremental: true});
    }).catch(() => {
      if (revision !== selectionIntentRevision) return;
      operationsAvailable = false;
      render({preserveComposer: true, incremental: true});
    });
  }
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
    deliveryOperationActions.has(operationAction(operation)) &&
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
  if (node.currentApproval || node.platformProcessing || node.currentRoleDispatch) failedStageIndexes.clear();
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
      : node.currentApproval || ["WAITING_PRODUCT_REPLY", "WAITING_PRODUCT_APPROVAL"].includes(request.stage) ? node.label : "已阻塞", "flow-state"));
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
  if (operation && deliveryOperationActions.has(operationAction(operation))) {
    const state = operation.status === "QUEUED" ? "等待执行" : "处理中";
    const waiting = waitingRequestTask(request);
    const waitingNote = waiting
      ? (waitingExecutionStep(waiting).wait_reason?.startsWith("KNOWLEDGE_GAP:")
        ? approvedKnowledge(request) ? " · 知识解答已批准，等待角色恢复" : " · 当前角色等待知识确认"
        : " · 当前角色等待前提处理") : "";
    const childBlocker = operationChildBlocker(request, operation);
    return el(
      "p",
      `Manager 协调 · ${state}（${label(operationAction(operation))}）${waitingNote || (interruptedRequestTask(request) ? " · 当前角色执行已中断" : childBlocker ? " · 当前角色已阻塞" : "")}`,
      "flow-manager active",
    );
  }
  if (requestPresentation(request).group !== "blocked") return null;
  if (request.knowledge_gap?.is_current)
    return el("p", approvedKnowledge(request)
      ? "Manager 协调 · 知识解答已批准，等待继续"
      : "Manager 协调 · 等待知识确认", "flow-manager blocked");
  const approval = requestRecoveryDecision(request)?.approval;
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
      deliveryOperationActions.has(operationAction(latest)))
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
  return `${item.project_id}/${item.id}/${item.checkpoint_sha256}/${item.stage}/${item.knowledge_gap?.gap?.gap_id || "unread"}/${item.knowledge_gap?.resolution?.resolution_id || "pending"}/${item.execution?.responsibility || "legacy"}`;
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
  const boundItem = {id: item.id, project_id: item.project_id, checkpoint_sha256: item.checkpoint_sha256,
    knowledge_rechecked_gap_ids: [...(item.knowledge_rechecked_gap_ids || [])]};
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
        content.replaceChildren(...unique.map((view, index) => knowledgeGapCard(view, index, base, boundItem)));
        if (!unique.length) content.append(el("p", "当前没有已记录的知识缺口。", "muted"));
        loaded = true;
        const current = unique.find(view => view.is_current);
        if (current) {
          if (current.resolution) {approved = true; renderIntro();}
          const request = snapshot?.requests.find(request => request.id === boundItem.id && request.project_id === boundItem.project_id);
          if (request?.stage === "WAITING_HUMAN" && request.checkpoint_sha256 === boundItem.checkpoint_sha256 &&
              currentProjectId() === boundItem.project_id && knowledgeGapKey(request) === key &&
              knowledgeGapSections.get(key) === section &&
              (!request.knowledge_gap || request.knowledge_gap.gap.gap_id === current.gap.gap_id)) {
            // Bind the verified current question as well as a possible saved approval.
            // Keep its open body and draft under the exact gap cache key.
            knowledgeGapSections.delete(key);
            request.knowledge_gap = current;
            key = knowledgeGapKey(request);
            knowledgeGapSections.set(key, section);
            renderOperationStatus();
            renderDetail();
            syncDeliveryControls();
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

function knowledgeApprovalUnavailableReason(bound) {
  const unavailable = deliveryControlUnavailableReason();
  if (unavailable) return unavailable;
  const request = snapshot?.requests.find(item => item.id === bound.id && item.project_id === bound.project_id);
  if (currentProjectId() !== bound.project_id || request?.stage !== "WAITING_HUMAN" ||
      request.checkpoint_sha256 !== bound.checkpoint_sha256 || !request.knowledge_gap?.is_current ||
      request.knowledge_gap.resolution || JSON.stringify(request.knowledge_gap.gap) !== bound.gap_signature)
    return {title: "知识事项已变化", reason: "当前项目、需求或待确认的知识事项已变化，旧解答不能用于批准。",
      next_action: "请重新查看当前需求的知识事项，再核对问题和解答；现有草稿保留供参考。"};
  return null;
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
  submit.setAttribute("data-delivery-control", "true");
  const bound = {id: item.id, project_id: item.project_id, checkpoint_sha256: item.checkpoint_sha256,
    gap_signature: JSON.stringify(gap)};
  const controlStatus = el("p", "", "form-feedback");
  controlStatus.setAttribute("role", "status");
  controlStatus.setAttribute("aria-live", "polite");
  const unavailable = () => knowledgeApprovalUnavailableReason(bound);
  knowledgeApprovalControls.set(submit, {unavailable, status: controlStatus});
  setDeliveryControlDisabled(submit, false);
  const actions = el("div", undefined, "knowledge-gap-actions");
  actions.append(el("span", "批准仅保存解答，不会自动开始交付。", "muted"), submit);
  card.append(header, el("p", gap.question, "knowledge-gap-question"));
  if (decision) card.append(el("p", decision, "knowledge-gap-hint"));
  card.append(field("你的解答", answer), field("事实来源 / 决策依据", source), controlStatus, feedback, actions);
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
    setDeliveryControlDisabled(submit, true);
    feedback.replaceChildren();
    try {
      const beforeHash = unavailable();
      if (beforeHash) throw new Error(beforeHash.reason + " " + beforeHash.next_action);
      const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(content));
      const sha256 = Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, "0")).join("");
      const beforePost = unavailable();
      if (beforePost) throw new Error(beforePost.reason + " " + beforePost.next_action);
      const resolution = await adminFetch(base + "/knowledge-resolutions", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({gap_id: gap.gap_id, answer: content,
          sources: [{uri, content, sha256}], approval_reference: "local-console:" + gap.gap_id}),
      });
      const request = snapshot?.requests.find(request => request.id === bound.id && request.project_id === bound.project_id);
      if (request?.stage === "WAITING_HUMAN" && request.checkpoint_sha256 === bound.checkpoint_sha256 &&
          request.knowledge_gap?.is_current && !request.knowledge_gap.resolution &&
          JSON.stringify(request.knowledge_gap.gap) === bound.gap_signature) {
        request.knowledge_gap = {...view, resolution};
        // Approval changes knowledge facts without advancing the immutable checkpoint.
        renderOperationStatus();
        renderDetail();
      }
    } catch (error) {
      feedback.replaceChildren(el("p", error.message || "解答未被接受。", "error"));
      submitting = false;
      setDeliveryControlDisabled(submit, false);
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
    const execution = runningRolePresentation(task.execution);
    section.append(el("p", `${label(step.role)} · ${execution.label} · 最近心跳 ${time(step.heartbeat_at)}。`));
    section.append(el("p", execution.reason, "muted"));
  }
  return section;
}

function modelCallDiagnostics(operation) {
  const details = viewBlock(el("details", undefined, "model-call-diagnostics"),
    `model-calls:${operation.operation_id}`, operationRenderFact(operation));
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
  if (Array.isArray(details.parent_artifact_ids) && details.parent_artifact_ids.length &&
      (details.kind === "implementation-report" || details.kind === "coder-progress")) {
    // Only the selected Task's verified lineage can establish parent types.
    const tasks = (snapshot?.tasks || []).filter(task => selected?.kind === "task" &&
      task.id === selected.id && task.project_id === currentProjectId());
    const sourceTask = tasks.length === 1 ? tasks[0] : null;
    const reading = selectedTeamDetailTarget();
    const currentBody = !teamSummaryMode() || teamDetailRead?.status === "ready" &&
      teamDetailRead.owner === reading?.owner && teamDetailRead.loadedKey === reading?.key;
    const task = sourceTask && currentBody ? detailReadingItem(sourceTask) : null;
    const history = task?.execution_history?.length ? task.execution_history : task?.timeline || [];
    const taskIds = new Set([task?.task_id, ...(task?.history_task_ids || [])].filter(Boolean));
    const verified = item => item?.kind === "artifact" && taskIds.has(item.task_id) &&
      item.source_uri === "artifact://" + item.id && typeof item.source_sha256 === "string" &&
      /^[a-f0-9]{64}$/.test(item.source_sha256) &&
      item.details?.artifact_sha256 === item.source_sha256;
    const current = history.filter(item => item.id === entry.id);
    const parents = details.parent_artifact_ids.map(id => {
      const matches = history.filter(item => item.id === id);
      return matches.length === 1 && verified(matches[0]) ? matches[0] : null;
    });
    const complete = current.length === 1 && current[0] === entry && verified(entry) &&
      new Set(details.parent_artifact_ids).size === details.parent_artifact_ids.length && parents.every(Boolean);
    const feedback = complete && parents.some(parent =>
      ["qa-report", "review-report"].includes(parent.details.kind));
    target.append(el("p", feedback
      ? "Coder 已接收上轮 QA/Review 反馈作为本轮输入。是否解决相关问题仍须后续独立 QA/Review 验收。"
      : complete ? "Coder 的本轮输入产物已记录。"
      : "Coder 的本轮输入产物已记录；当前历史不足以确认是否包含 QA/Review 反馈。", "muted"));
  }
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
    if (!missing.length && details.permitted_resolutions?.includes("RETRY_KNOWLEDGE_PREPARATION"))
      for (const line of knowledgePreparationWindowLines(details.knowledge_preparation)) target.append(el("p", line));
    if (!missing.length && details.permitted_resolutions?.includes("RETRY_REJECTED_KNOWLEDGE_PREPARATION"))
      for (const line of rejectedKnowledgePreparationLines(details.rejected_knowledge)) target.append(el("p", line));
    if (!missing.length && details.permitted_resolutions?.includes("RETRY_REJECTED_WORKSPACE_ADMISSION"))
      for (const line of rejectedWorkspaceAdmissionLines(details.rejected_workspace_admission)) target.append(el("p", line));
    if (!missing.length && details.permitted_resolutions?.includes("RETRY_REJECTED_CODER_OUTPUT"))
      for (const line of rejectedCoderOutputLines(details.rejected_output)) target.append(el("p", line));
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
    else if (["RESOLVED", "NEEDS_AUTHORIZATION"].includes(details.status)) {
      for (const line of knowledgePreparationWindowLines(details.knowledge_preparation)) target.append(el("p", line));
      for (const line of rejectedKnowledgePreparationLines(details.rejected_knowledge)) target.append(el("p", line));
      for (const line of rejectedWorkspaceAdmissionLines(details.rejected_workspace_admission)) target.append(el("p", line));
    }
  } else if (details.kind === "delivery_wait_resolution") {
    target.append(el("p", "工程决定 · " + (engineeringResolutionLabels[details.resolution_kind] ||
      "平台返回了未识别的继续方案，不能据此执行")));
    if (details.operator_id) target.append(el("p", "实际处理者 · " + details.operator_id, "muted"));
    if (details.resolution_kind === "RETRY_KNOWLEDGE_PREPARATION")
      for (const line of knowledgePreparationWindowLines(details.knowledge_preparation)) target.append(el("p", line));
    if (details.resolution_kind === "RETRY_REJECTED_WORKSPACE_ADMISSION")
      for (const line of rejectedWorkspaceAdmissionLines(details.rejected_workspace_admission)) target.append(el("p", line));
    if (details.resolution_kind === "RETRY_REJECTED_KNOWLEDGE_PREPARATION")
      for (const line of rejectedKnowledgePreparationLines(details.rejected_knowledge)) target.append(el("p", line));
    if (details.resolution_kind === "RETRY_REJECTED_CODER_OUTPUT")
      for (const line of rejectedCoderOutputLines(details.rejected_output)) target.append(el("p", line));
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
  if (details.authorization_source) technical.append(el("p", "授权来源 · " +
    (engineeringAuthorizationLabels[details.authorization_source] || "授权来源未识别"), "muted"));
  if (details.work_item_id) technical.append(el("p", "工作项 · " + details.work_item_id, "paths"));
  if (details.proof_sha256) technical.append(el("p", "调查摘要 · " + details.proof_sha256, "paths"));
}
function requestOperationHistory(panel, request) {
  if (operationSummaryMode()) {
    renderSummaryOperationHistory(panel, request.project_id, request.id);
    return;
  }
  const records = [...operations].filter(operation => operationTarget(operation) === request.id &&
    operationProject(operation) === request.project_id)
    .sort((a, b) => a.updated_at.localeCompare(b.updated_at) || a.operation_id.localeCompare(b.operation_id));
  if (!records.length) return;
  const fold = viewGroup(el("details", undefined, "request-history-fold"), "operation-history-fold");
  fold.dataset.key = "operation-history:" + request.project_id + "/" + request.id;
  fold.append(el("summary", `操作记录（完整历史） · ${records.length} 条`),
    el("p", `共 ${records.length} 条操作，全部保留。历史原因与当次下一步只描述那一轮；当前阻塞和建议操作以本页上方为准。命令完成不代表需求已交付。`, "muted"));
  if (!operationsAvailable)
    fold.append(el("p", "交付操作记录读取失败。以下保留上次成功读取的完整历史，不能代表当前执行状态；恢复读取后再核对和操作。", "error"));
  const list = viewGroup(el("ol", undefined, "execution-history"), "requirement-operation-history-list");
  for (const record of records) {
    const progress = currentOperationProgress(record, request);
    const outcome = recordedOperationOutcome(record);
    const item = viewBlock(el("li", undefined, "execution-history-entry"), "operation:" + record.operation_id,
      {record: operationRenderFact(record), progress});
    if (progress) {
      item.append(el("strong", progress.title), el("p", "发起操作 · " + operationActionLabel(record), "muted"));
      if (progress.reason) item.append(el("p", "当前原因 · " + progress.reason));
      if (progress.responsibility) item.append(el("p", "处理方 · " + progress.responsibility, "muted"));
      if (progress.nextAction) item.append(el("p", "下一步 · " + progress.nextAction));
      if (progress.preparation) item.append(el("p", progress.preparation, "muted"));
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
    if (record.status === "QUEUED") item.append(el("p", operationAction(record) === "HANDLE_DELIVERY_WAIT"
      ? "操作已接收，等待平台执行。" : "操作已接收，等待 Manager 处理。", "muted"));
    appendIndependentOperationResult(item, record);
    if (record.error_summary) item.append(el("p", humanizeBlockingText(record.error_summary), "error"));
    if (record.status === "SUCCEEDED" && deliveryOperationActions.has(operationAction(record)) && operationResult(record)?.diagnostic)
      item.append(el("p", "当次原因 · " + humanizeBlockingText(operationResult(record).diagnostic), "error"));
    if (!progress && operationResult(record)?.next_action) item.append(el("p", "当次下一步 · " + humanizeBlockingText(operationResult(record).next_action)));
    const technical = engineeringDetails("排障信息（供工程人员使用）", record.operation_id);
    technical.append(el("p", "这些标识用于工程核验，无需产品负责人填写。", "muted"));
    technical.append(el("p", "操作 · " + record.operation_id, "paths"));
    technical.append(el("p", "原始命令状态 · " + record.status, "paths"));
    if (operationAction(record) === "PROPOSE_EXECUTION_BASELINE" && record.intent?.purpose === "legacy_workspace_rescue" && record.error_code)
      technical.append(el("p", "平台错误编号 · " + record.error_code, "paths"));
    if (record.intent?.expected_checkpoint_sha256)
      technical.append(el("p", "发起操作时的需求版本摘要 · " + record.intent?.expected_checkpoint_sha256, "paths"));
    const handling = operationResult(record)?.engineering_wait_handling;
    if (handling) {
      item.append(el("p", "当次平台处理 · " + humanizeBlockingText(handling.summary || "未提供处理说明")),
        el("p", "当次用户操作 · " + humanizeBlockingText(handling.user_action || "未提供"), "muted"));
      if (handling.recheck_when) item.append(el("p", "当次复查时机 · " + humanizeBlockingText(handling.recheck_when), "muted"));
      technical.append(el("p", "处理报告摘要 · " + handling.handling_sha256, "paths"));
    }
    const proof = operationResult(record)?.engineering_wait_investigation || handling?.investigation;
    if (proof) {
      appendEngineeringInvestigation(item, proof, {historical: true});
      technical.append(el("p", "调查摘要 · " + proof.proof_sha256, "paths"));
    }
    const decision = operationResult(record)?.engineering_wait_resolution || handling?.resolution;
    if (decision) appendEngineeringExecutionDetails(item, technical, {
      ...decision, operator_id: decision.operator_principal?.operator_id,
    });
    const rescuePlan = operationResult(record)?.execution_baseline_plan;
    const rescuePreparation = operationResult(record)?.legacy_rescue_preparation;
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
function taskChapter(key, {historical = false} = {}) {
  const chapters = historical ? taskChapters.map(chapter => chapter[0] === "current"
    ? ["current", "当次执行结果", "查看当次保存的状态、处理建议和独立验收反馈；这些记录不代表当前需求。"]
    : chapter) : taskChapters;
  return detailChapter(chapters, "task", key);
}
function historicalTaskContext(task, parent) {
  const scopeKey = taskDetailScopeKey();
  const bound = {taskId: task.id, parentId: parent.id, projectId: parent.project_id};
  const phase = deliveryPhase(parent), node = requestNodeExecution(parent);
  const context = viewBlock(el("section", undefined, "product-execution-summary task-historical-context"),
    "task-historical-context", [scopeKey, bound, parent.title, phase, node, projectSwitchPending()]);
  context.setAttribute("aria-label", "历史执行与当前需求");
  context.append(el("strong", "历史执行记录"),
    el("p", "此处保留当次执行结果和处理建议，不代表当前需求的状态或可用操作。", "muted"));
  const current = el("div", undefined, "row");
  current.append(el("p", "当前需求 · " + parent.title), requestNodeBadge(parent));
  const open = button("查看当前需求", () => {
    const task = taskById(bound.taskId);
    const parent = task && taskParentRequest(task);
    if (open.isConnected === false || taskDetailScopeKey() !== scopeKey || projectSwitchPending() ||
        currentProjectId() !== bound.projectId || !parent || parent.id !== bound.parentId ||
        parent.project_id !== bound.projectId || !isHistoricalRequestTask(task)) return;
    showDetail("request", parent.id);
  }, "secondary");
  open.disabled = projectSwitchPending() || currentProjectId() !== bound.projectId;
  context.append(current, open);
  return context;
}
function historicalTaskExecutionSummary(task) {
  const execution = task.execution;
  const section = el("div", undefined, "product-execution-summary");
  section.append(el("p", "当次交付阶段 · " + deliveryPhase(task), "execution-phase"),
    el("p", "当次执行 · " + label(task.terminal || !execution ? task.status : executionPresentationStatus(execution)), "execution-state"));
  if (execution?.responsibility)
    section.append(el("p", "当次处理方 · " + {product: "产品负责人", team: "ASE 团队", engineering: "工程团队"}[execution.responsibility], "muted"));
  const reason = execution?.reason || task.blocker;
  const advice = execution?.next_action || task.next_action;
  if (reason) section.append(el("p", "当次原因 · " + humanizeBlockingText(reason)));
  if (advice) section.append(el("p", "当次处理建议 · " + humanizeBlockingText(advice), "muted"),
    el("p", "以上建议仅保留当次记录；当前可用操作请查看当前需求。", "muted"));
  if (execution?.available_at)
    section.append(el("p", "当次计划重试时间 · " + time(execution.available_at), "muted"));
  return section;
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
function detailReadFreshnessSlot() {
  const source = {teamId: snapshot?.team_id, projectId: currentProjectId(),
    kind: selected?.kind, id: selected?.id, asOf: snapshot?.as_of};
  const slot = viewBlock(el("div", undefined, "detail-read-freshness-slot"), "detail-read-freshness-slot", source);
  slot.hidden = true;
  detailReadSources.set(slot, source);
  return slot;
}
function syncDetailReadFreshness(panel) {
  const slot = panel.querySelector(".detail-read-freshness-slot");
  const source = slot && detailReadSources.get(slot);
  if (!source) return;
  const visible = Boolean(teamReadIssue && source.teamId === snapshot?.team_id &&
    source.projectId === currentProjectId() && source.kind === selected?.kind && source.id === selected?.id);
  const facts = [source, teamReadIssue, visible];
  renderView(slot, "detail-read-freshness:" + JSON.stringify(source), () => facts, target => {
    target.className = "detail-read-freshness-slot";
    target.hidden = !visible;
    if (!visible) return;
    const observedAt = Number.isFinite(Date.parse(source.asOf)) ? time(source.asOf) : "读取时间未记录";
    const notice = viewBlock(el("p", `当前展示上次读取结果 · ${observedAt}。页面会自动重新读取，暂无法确认最新执行状态。`,
      "detail-read-freshness"), "detail-read-freshness", facts);
    notice.setAttribute("role", "status");
    target.append(notice);
  }, true);
}
function renderDetail({ incremental = false } = {}) {
  // This starts at most one read per exact selection/version. The read response
  // only updates a separate body owner, never the current snapshot or controls.
  void readSelectedTeamDetail();
  syncRecoveryPreparationTarget();
  // Retain every repository plan visible in this requirement; prune once for the
  // complete detail, never while rendering an individual repository's controls.
  pruneNativeRuleReviews();
  const panel = document.getElementById("detail");
  if (!snapshot || selected?.kind !== "task" || pausedTaskDetailKey !== taskDetailScopeKey() ||
      !taskById(selected.id)) pausedTaskDetailKey = null;
  // The Task modal contains only read-side facts and navigation, never approvals.
  // Requirement controls still reconcile against fresh checkpoint/authorization facts.
  if (pausedTaskDetailKey && renderedSurfaces.has(panel)) {
    // Freshness remains visible while the Task body keeps its original read source.
    syncDetailReadFreshness(panel);
    syncTaskReadingToolbar(panel);
    return;
  }
  const opener = document.activeElement;
  const expanded = new Set([...document.querySelectorAll("details[open]")]
    .filter(node => node.dataset.key).map(node => node.dataset.key));
  renderView(document.getElementById("detail"), `detail:${page}:${currentProjectId()}:${selected?.kind}:${selected?.id}`,
    pollingDetailFacts, buildDetail, incremental);
  syncDetailReadFreshness(panel);
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
  const currentItem =
    selected.kind === "task" ? taskById(selected.id) : requestById(selected.id);
  if (!currentItem) {
    panel.append(el("p", "当前快照中找不到这条记录。"));
    return;
  }
  const item = detailReadingItem(currentItem);
  const historicalTask = selected.kind === "task" && isHistoricalRequestTask(item);
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
    if (canCloseRequirement(item))
      topActions.append(
        deliveryButton(
          "关闭需求",
          () =>
            confirmMutation(
              "关闭需求",
              item.stage === "DELIVERING"
                ? `确认关闭“${item.title}”吗？平台会核验工程执行已停止，再取消等待中的交付；需求与历史仍会保留。如需重新交付，请新建需求。`
                : `确认关闭“${item.title}”吗？平台会核验执行已停止、保存成果并释放临时工作区，需求与交付历史仍会保留。`,
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
    if (
      productDiscussionStages.has(item.stage) ||
      ["BLOCKED", "CLOSED", "DONE"].includes(item.stage)
    )
      topActions.append(
        deliveryButton(
          "删除需求",
          () =>
            confirmMutation(
              "删除需求",
              `确认从当前 Project 删除“${item.title}”吗？需求资料、操作记录和临时资源将永久删除，已合入代码仓库的成果保留。此操作无法撤销。`,
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
        selectionIntentRevision++;
        selected = null;
        clearTeamDetailRead();
        render();
      },
      "detail-close-control",
    ),
  );
  const detailName = selected.kind === "task" ? historicalTask ? "历史任务详情" : "任务详情" : "需求详情";
  const detailHeading = el("p", detailName, "detail-panel-heading");
  if (selected.kind === "task") detailHeading.id = "task-detail-dialog-heading";
  if (selected.kind === "task") {
    const owner = requestById(item.request_id);
    if (owner && owner.project_id === item.project_id) topActions.append(button("打开所属需求", () => showDetail("request", owner.id), "secondary"));
  }
  top.append(detailHeading, topActions);
  if (selected.kind === "request") {
    const presentation = requestPresentation(item);
    const blocking = requestBlockerSection(item);
    panel.className = "request-detail-panel";
    const masthead = viewGroup(el("header", undefined, "request-detail-masthead"), "request-detail-masthead");
    const titleRow = viewGroup(el("div", undefined, "request-title-row"), "request-title-row");
    titleRow.append(viewBlock(el("p", item.title, "request-detail-title"), "request-heading-title", item.title),
      viewBlock(requestNodeBadge(item), "request-heading-status", [deliveryPhase(item), requestNodeExecution(item)]));
    masthead.append(viewBlock(top, "request-heading-actions", [currentItem, pollingControlFacts(), operationRenderFacts()]), titleRow,
      detailReadFreshnessSlot());
    if (teamSummaryMode()) {
      const notice = teamDetailReadNotice();
      if (notice) masthead.append(notice);
    }
    panel.append(masthead, requestChapterNavigation(item));
    const current = requestChapter("current");
    const processingControlIssue = requestNodeExecution(item).platformProcessing
      ? deliveryControlUnavailableReason() : null;
    const overview = viewBlock(el("div", undefined, "request-detail-overview"), "request-detail-overview",
      [item.execution, presentation, requestNodeExecution(item), deliveryPhase(item), Boolean(blocking), processingControlIssue]);
    if (item.execution) overview.append(productExecutionSummary(item, {guidance: !blocking}));
    if (processingControlIssue) overview.append(deliveryControlUnavailableNotice({...processingControlIssue,
      reason: processingControlIssue.reason.replace("当前操作已暂停", "新操作暂不可提交")}));
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
    const preparation = recoveryPreparationSection(item);
    if (preparation) current.append(preparation);
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
    artifacts.append(el("h3", Array.isArray(item.documents) ? `阶段产物 · ${item.documents.length} 份` : "阶段产物"));
    if (Array.isArray(item.documents)) documentList(artifacts, item.documents);
    else artifacts.append(el("p", "完整产物正文尚未读取，请查看上方读取提示。", "muted"));
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
    if (teamSummaryMode() && !Array.isArray(item.dialogue)) history.append(el("p", "需求讨论正文尚未读取；交付操作记录独立展示。", "muted"));
    else if (history.children.length === 1) history.append(el("p", "暂无已保存的历史记录。", "muted"));
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
  // The heading changes with current/historical identity; groups retain DOM attributes.
  dialog.setAttribute("aria-labelledby", "task-detail-dialog-heading");
  const header = viewGroup(el("header", undefined, "task-detail-header"), "task-detail-header");
  viewBlock(top, "task-heading", [item.id, historicalTask]);
  header.append(top, taskReadingToolbar(), detailReadFreshnessSlot());
  if (teamSummaryMode()) {
    const notice = teamDetailReadNotice();
    if (notice) header.append(notice);
  }
  dialog.append(header);
  const masthead = viewGroup(el("div", undefined, "task-detail-masthead"), "task-detail-masthead");
  const taskTitleRow = viewGroup(el("div", undefined, "task-title-row"), "task-title-row");
  const status = historicalTask ? el("span", "当次 · " + label(item.status), "badge") : badge(taskPresentationStatus(item));
  taskTitleRow.append(viewBlock(el("p", item.title, "task-detail-title"), "task-title", item.title),
    viewBlock(status, "task-heading-status", [historicalTask, historicalTask ? item.status : taskPresentationStatus(item)]));
  masthead.append(taskTitleRow);
  if (historicalTask) masthead.append(historicalTaskContext(item, taskParentRequest(item)));
  dialog.append(masthead);
  const current = taskChapter("current", {historical: historicalTask});
  const overview = viewBlock(el("section", undefined, "task-detail-overview"), "task-overview",
    [item.status, taskPresentationStatus(item), item.execution, item.blocker, item.next_action, item.last_activity,
      interruptedExecution(item), waitingExecutionStep(item), item.scope, historicalTask]);
  if (historicalTask) overview.append(historicalTaskExecutionSummary(item));
  else if (item.execution) overview.append(productExecutionSummary(item));
  else {
    overview.append(el("p", "当前阶段 · " + deliveryPhase(item)));
    if (item.blocker) overview.append(el("p", "当前原因 · " + humanizeBlockingText(item.blocker), "blocker"));
    if (item.next_action) overview.append(el("p", "下一步 · " + humanizeBlockingText(item.next_action)));
  }
  overview.append(el("p", paths(item.scope), "paths"), el("p", (historicalTask ? "当次记录更新 · " : "最近交付记录 · ") + time(item.last_activity), "muted"));
  const activity = historicalTask ? el("div", undefined, "role-execution-activity") : roleExecutionActivity(item);
  activity.classList.add("task-activity-block");
  viewBlock(activity, "task-activity", [item.status, item.terminal, item.role_queue, item.execution, historicalTask]);
  current.append(overview, activity);
  const preparation = recoveryPreparationSection(taskParentRequest(item));
  if (preparation) current.append(preparation);
  const engineering = engineeringDetails("任务工程详情", item.id);
  viewGroup(engineering, "task-engineering");
  const engineeringBody = viewBlock(el("div"), "task-engineering-facts",
    [item.id, item.execution, item.blocker, item.next_action, item.candidate_revision, item.candidate_branch,
      item.role_queue, item.task_id, item.history_task_ids, taskGroup(item), item.assignments, snapshot.agents, historicalTask]);
  const engineeringTarget = engineeringBody;
  engineeringTarget.append(el("p", item.id, "paths"));
  if (item.execution?.policy_id) engineeringTarget.append(el("p", "工程授权 · " + item.execution.policy_id, "paths"));
  if (item.execution?.receipt_uri) engineeringTarget.append(el("p", "执行事实 · " + item.execution.receipt_uri, "paths"));
  if (item.blocker)
    engineeringTarget.append(el("p", "原始阻塞原因 · " + humanizeBlockingText(item.blocker), "blocker"));
  if (taskGroup(item) === "blocked" && item.next_action)
    engineeringTarget.append(el("p", (historicalTask ? "当次原始处理建议 · " : "原始下一步 · ") + humanizeBlockingText(item.next_action), "muted"));
  if (!historicalTask && interruptedExecution(item) && !item.execution)
    overview.append(el("p", `${interruptedExecutionReason} 当前交付检查点：${label(item.status)}。`));
  if (!historicalTask && waitingExecutionStep(item))
    overview.append(el("p", `当前角色已暂停，交付检查点保留在${label(item.status)}。`));
  if (item.candidate_revision)
    engineeringTarget.append(el("p", "候选版本 · " + item.candidate_revision, "paths"));
  if (item.candidate_branch)
    engineeringTarget.append(el("p", "候选分支 · " + item.candidate_branch, "paths"));
  if (item.role_queue?.length) {
    engineeringTarget.append(el("h3", historicalTask ? "当次角色执行队列" : "角色执行队列"));
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
  engineeringTarget.append(el("h3", historicalTask ? "当次成员与分配模型" : "成员与分配模型"));
  for (const a of item.assignments)
    engineeringTarget.append(
      el(
        "p",
        `${snapshot.agents.find((x) => x.id === a.agent_id)?.name || a.agent_id} · ${label(a.role)} · ${a.planned_provider} / ${a.planned_model}${a.current_stage ? historicalTask ? " · 当次岗位" : " · 当前阶段" : ""}`,
      ),
    );
  const history = item.execution_history?.length ? item.execution_history : item.timeline || [];
  const bodyLoaded = Array.isArray(item.documents);
  const currentTaskId = historicalTask ? null : item.task_id || item.id;
  const feedback = taskFeedbackSection(history, currentTaskId);
  if (feedback) current.append(feedback);
  dialog.append(current);
  const outputs = taskChapter("outputs");
  outputs.append(viewBlock(el("p", bodyLoaded ? `共 ${item.documents.length} 份已保存产物。` : "完整产物正文尚未读取，请查看上方读取提示。", "muted"), "task-document-count", bodyLoaded ? item.documents.length : null));
  const reports = viewGroup(el("div", undefined, "task-artifact-list"), "task-documents");
  if (bodyLoaded) documentList(reports, item.documents);
  outputs.append(reports);
  dialog.append(outputs);
  const executionRecords = taskChapter("history");
  const records = taskReadingFold(bodyLoaded ? `执行记录（完整历史） · ${history.length} 条` : "执行记录（尚未读取完整历史）", "task-history", true);
  records.append(viewBlock(el("p", bodyLoaded ? `共 ${history.length} 条记录。历史轮次完整保留，不代表当前状态。` : "完整执行历史尚未读取，请查看上方读取提示。", "muted"), "task-history-count", bodyLoaded ? history.length : null));
  engineeringTarget.append(el("p", (historicalTask ? "当次 Task · " : "当前 Task · ") + (item.task_id || item.id), "paths"));
  if (item.history_task_ids?.length > 1)
    engineeringTarget.append(el("p", "关联 Task · " + item.history_task_ids.join(" → "), "paths"));
  const list = viewGroup(el("ol", undefined, "execution-history"), "task-history-list");
  for (const entry of history) appendExecutionEntry(list, entry, currentTaskId);
  if (bodyLoaded && !history.length) list.append(el("li", "暂无已保存的执行记录。", "muted"));
  records.append(list);
  executionRecords.append(records);
  const calls = taskReadingFold(bodyLoaded ? `已完成的模型调用 · ${item.runs.length} 次` : "已完成的模型调用（尚未读取）", "task-model-calls");
  const callList = viewGroup(el("div", undefined, "task-model-call-list"), "task-model-call-list");
  if (bodyLoaded && !item.runs.length)
    callList.append(
      el("p", historicalTask ? "暂无已保存的完成调用记录；此处只展示当次记录。" : "暂无已提交调用记录；进行中的调用完成后才会出现。", "muted"),
    );
  for (const run of item.runs || []) {
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
function renderMaintenanceBanner() {
  let banner = document.getElementById("service-maintenance");
  const lastConfirmedInspection = consoleAvailable === null && consoleReadingIdentity?.mode === "inspection";
  const visible = consoleMode === "inspection" || lastConfirmedInspection;
  if (!banner && visible) {
    banner = el("div", undefined, "admin-notice");
    banner.id = "service-maintenance";
    banner.setAttribute("role", "status");
    document.getElementById("connection").before(banner);
  }
  if (banner) {
    banner.hidden = !visible;
    const summary = lastConfirmedInspection
      ? "上次确认服务处于维护仅查看模式；当前连接尚未确认。仍可查看已核验的记录，交付操作保持暂停。"
      : inspectionSummary;
    const guide = consoleMode === "inspection" ? maintenanceCompletionGuide : null;
    // Keep the guide, text selection and expanded state stable across polling.
    const signature = JSON.stringify([summary, guide, visible]);
    if (banner.dataset?.maintenanceSignature === signature) return;
    const wasOpen = banner.querySelector?.("details")?.open;
    banner.textContent = summary;
    if (banner.dataset) banner.dataset.maintenanceSignature = signature;
    if (visible && guide) {
      const details = el("details", undefined, "maintenance-completion");
      details.open = Boolean(wasOpen);
      details.append(el("summary", "完成维护并恢复普通模式"));
      details.append(el("p", "在运行 ASE 的本机终端完成。第一步会安全停止页面服务，页面会暂时离线；生成并检查方案后，再明确确认恢复普通模式。"));
      details.append(el("p", "1. 安全收尾并检查完整故障归档、待执行队列："));
      const prepare = el("pre");
      prepare.append(el("code", guide.prepare_command));
      details.append(prepare);
      details.append(el("p", "2. 核对输出中的队列计数及方案。将以下 PLAN_SHA256 替换为第一步输出的 record_sha256，再执行："));
      const complete = el("pre");
      complete.append(el("code", guide.complete_command));
      details.append(complete);
      details.append(el("p", "检查失败时维护限制仍保留，按终端中的中文原因处理。完成后刷新本页面；恢复普通模式不会批准或继续已暂停的需求。若显式设置了 ASE_CONSOLE_MODE=inspection，请先取消该设置。"));
      banner.append(details);
    }
  }
}
function render({ preserveComposer = false, incremental = false } = {}) {
  renderMaintenanceBanner();
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
  document.getElementById("team").textContent = snapshot?.team_name || unavailableTeamName();
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
        target.append(el("div", unavailableTeamMessage(), teamReadIssue === "busy" ? "muted" : "operation-error"));
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
  selectionIntentRevision++;
  clearTeamDetailRead();
  administrationNotice = null;
  page = target;
  selected = null;
  if (operationSummaryMode()) {
    operationSummaryReadRevision++;
    operationDetailReadyScope = null;
    currentOperationSources = [];
    operationDetailCache.clear();
    operations = [];
  }
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
  const generation = ++consoleInfoReadGeneration;
  try {
    const response = await fetch("/api/v1/console", { cache: "no-store", signal });
    if (generation !== consoleInfoReadGeneration) return;
    if (response.status === 404) {
      consoleAvailable = false;
      consoleConnectionFailed = false;
      consoleTeamId = null;
      consoleDeliveryReady = null;
      consoleMode = null;
      maintenanceCompletionGuide = null;
      consoleOperationContractVersion = null;
      consoleSupportedActions = null;
      consoleOperationSummaryContractVersion = null;
      consoleTeamReadContractVersion = null;
      consoleReadingIdentity = null;
      clearOperationReadScope();
      clearTeamDetailRead();
      return;
    }
    if (!response.ok) throw new Error("console unavailable");
    const info = await response.json();
    if (generation !== consoleInfoReadGeneration) return;
    if (
      info.schema_version !== "v0.2" ||
      typeof info.team_id !== "string" ||
      typeof info.delivery_ready !== "boolean"
    )
      throw new Error("invalid console response");
    const mode = info.mode ?? "normal";
    if (!["normal", "inspection"].includes(mode) ||
        mode === "inspection" && info.delivery_ready !== false)
      throw new Error("invalid console mode");
    const teamReadVersion = info.team_read_contract_version ?? null;
    if (teamReadVersion !== null && teamReadVersion !== "v0.1")
      throw new Error("unsupported Team read contract");
    const teamChanged = consoleReadingIdentity?.teamId !== info.team_id;
    const readVersionChanged = teamReadVersion !== consoleTeamReadContractVersion;
    if (consoleReadingIdentity && teamChanged) clearOperationReadScope();
    if (teamChanged || readVersionChanged) clearTeamDetailRead();
    if (teamChanged || readVersionChanged || consoleReadingIdentity?.mode !== mode)
      consoleReadingIdentity = {teamId:info.team_id, mode};
    consoleTeamReadContractVersion = teamReadVersion;
    consoleAvailable = true;
    consoleConnectionFailed = false;
    consoleTeamId = info.team_id;
    consoleMode = mode;
    const guide = info.maintenance_completion_guide;
    maintenanceCompletionGuide = mode === "inspection" && guide?.schema_version === "v1" &&
      [guide.prepare_command, guide.complete_command].every(value =>
        typeof value === "string" && value.length > 0 && value.length <= 16384)
      ? {prepare_command: guide.prepare_command, complete_command: guide.complete_command} : null;
    consoleDeliveryReady = info.delivery_ready;
    const actions = info.supported_actions;
    const validManifest = Number.isInteger(info.operation_contract_version) &&
      info.operation_contract_version >= 1 && Array.isArray(actions) && actions.length <= 64 &&
      actions.every(action => typeof action === "string" && /^[A-Z][A-Z0-9_]{0,99}$/.test(action)) &&
      new Set(actions).size === actions.length;
    consoleOperationContractVersion = validManifest ? info.operation_contract_version : null;
    consoleSupportedActions = validManifest ? [...actions] : null;
    consoleOperationSummaryContractVersion = info.operation_summary_contract_version === "v0.1" ? "v0.1" : null;
  } catch {
    if (generation !== consoleInfoReadGeneration) return;
    // Team identity and the negotiated read protocols remain read-only facts.
    // Do not fall back to full histories when just the control connection fails.
    consoleAvailable = null;
    consoleConnectionFailed = true;
    consoleDeliveryReady = null;
    consoleMode = null;
    consoleOperationContractVersion = null;
    consoleSupportedActions = null;
  }
}
async function refreshOperations(signal, {consoleRead} = {}) {
  if (consoleRead) await consoleRead;
  else await refreshConsoleInfo(signal);
  try {
    if (operationSummaryMode()) {
      const projectId = activeRefreshProject || currentProjectId();
      await readOperationSummaryPage(projectId, null, {signal});
      operationsAvailable = true;
      // Scope/selection may change while the independent Team read publishes.
      if (projectId === currentProjectId()) await loadCurrentOperationDetails(signal);
      syncRecoveryPreparationTarget();
      return;
    }
    const response = await fetch("/api/v1/operations", { cache: "no-store", signal });
    if (!response.ok) throw new Error("operations unavailable");
    const values = await response.json();
    if (!Array.isArray(values)) throw new Error("invalid operations response");
    operations = values;
    operationsAvailable = true;
    syncRecoveryPreparationTarget();
  } catch {
    // Retain the last verified history for reading; it is no longer current authority.
    operationsAvailable = false;
    operationDetailReadyScope = null;
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
    selectionIntentRevision++;
    clearTeamDetailRead();
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
  clearTimeout(teamRefreshTimer);
  teamRefreshTimer = null;
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
  finally {
    refreshFlight = null;
    activeRefreshProject = null;
    scheduleTeamRefresh();
  }
}
function scheduleTeamRefresh() {
  clearTimeout(teamRefreshTimer);
  teamRefreshTimer = setTimeout(pollTeamSnapshot, teamRefreshDelay);
}
function pollTeamSnapshot() {
  teamRefreshTimer = null;
  return refresh();
}
function recordTeamReadOutcome(issue) {
  teamRefreshDelay = ["busy", "timeout"].includes(issue)
    ? Math.min(teamRefreshDelay === 5000 ? 10000 : teamRefreshDelay * 2, 30000)
    : 5000;
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
  const priorConsoleMode = consoleMode;
  const priorConsoleTeam = consoleTeamId;
  const priorConsoleCapabilities = JSON.stringify([consoleOperationContractVersion, consoleSupportedActions]);
  const priorSettings = JSON.stringify(settingsSnapshot);
  const priorRuntimeStatus = JSON.stringify(runtimeStatusSnapshot);
  const priorOperations = JSON.stringify(operationRenderFacts());
  const priorOperationsAvailable = operationsAvailable;
  const priorKnowledge = JSON.stringify(pollingKnowledgeFacts());
  const priorTeamReadIssue = teamReadIssue;
  const selectedAtStart = selected, pageAtStart = page, selectionRevisionAtStart = selectionIntentRevision;
  const selectedRequestAtStart = selectedAtStart?.kind === "request" ? requestById(selectedAtStart.id) : null;
  const selectedTeamAtStart = snapshot?.team_id;
  const selectEditedReplacement = (sourceSelection) => {
    if (!operationsAvailable || selectionIntentRevision !== selectionRevisionAtStart || page !== pageAtStart ||
        sourceSelection?.kind !== "request" || !snapshot ||
        sourceSelection.id !== selectedRequestAtStart?.id ||
        requestById(sourceSelection.id) ||
        (selected && (selected.kind !== "request" || selected.id !== sourceSelection.id))) return false;
    const replacement = [...operationDetailCache.values()].map(item => item.value).concat(operations)
      .sort((left, right) => right.updated_at.localeCompare(left.updated_at))
      .map(operation => editedRequirementReplacement(operation, selectedRequestAtStart, selectedTeamAtStart))
      .find(Boolean);
    if (!replacement) return false;
    selected = {kind: "request", id: replacement.id};
    return true;
  };
  const refreshSystemViews = async () => {
    if (configurationApplyInFlight) await refreshConfigurationApply(controller.signal);
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
    priorConsoleTeam !== consoleTeamId || priorConsoleReady !== consoleDeliveryReady || priorConsoleMode !== consoleMode ||
    priorConsoleCapabilities !== JSON.stringify([consoleOperationContractVersion, consoleSupportedActions]) ||
    priorOperationsAvailable !== operationsAvailable ||
    priorSettings !== JSON.stringify(settingsSnapshot) ||
    priorRuntimeStatus !== JSON.stringify(runtimeStatusSnapshot);
  const renderCurrentFacts = (teamChanged = false) => {
    const modalActive = hasOpenComposer();
    const teamReadChanged = priorTeamReadIssue !== teamReadIssue;
    if ((teamReadChanged || !modalActive || (["settings", "status"].includes(page) && systemViewsChanged())) &&
        (teamChanged || teamReadChanged || priorOperations !== JSON.stringify(operationRenderFacts()) ||
          priorKnowledge !== JSON.stringify(pollingKnowledgeFacts()) || systemViewsChanged()))
      render({preserveComposer: Boolean(modalActive && !settingsSaveResult), incremental: true});
  };
  let systemReadFinished = false;
  let teamPublished = false;
  try {
    // Negotiate once, shared with Operations, before selecting the Team wire.
    const consoleRead = refreshConsoleInfo(controller.signal);
    const teamRead = (async () => {
      await consoleRead;
      controller.signal.throwIfAborted();
      const summaryRead = teamSummaryMode();
      const readingIdentity = consoleReadingIdentity, readingVersion = consoleTeamReadContractVersion;
      const currentRead = () => {
        if (superseded()) return false;
        if (readingIdentity !== consoleReadingIdentity || readingVersion !== consoleTeamReadContractVersion)
          throw new TeamReadFailure("unavailable");
        return true;
      };
      const endpoint = summaryRead ? "/api/v1/team-summary" : "/api/v1/team";
      const url = target ? endpoint + "?project_id=" + encodeURIComponent(target) : endpoint;
      const observation = await readCurrentTeamJson(url, controller.signal, {
        current: currentRead,
        publish: value => {
          if (superseded()) return null;
          const next = summaryRead ? verifiedTeamSummary(value, target) : value;
          if (
            next.schema_version !== (summaryRead ? "v0.1" : "v0.2") ||
            (target && next.selected_project_id !== target) ||
            !Array.isArray(next.tasks) || !Array.isArray(next.agents) || !Array.isArray(next.requests)
          ) throw new Error("invalid snapshot");
          const changed = !snapshot || JSON.stringify({...snapshot, as_of:null}) !== JSON.stringify({...next, as_of:null});
          const projectChanged = currentProjectId() !== next.selected_project_id;
          const selectedBeforeRefresh = selected;
          if (snapshot && (snapshot.team_id !== next.team_id || projectChanged)) clearTeamDetailRead();
          snapshot = next;
          teamReadIssue = null;
          recordTeamReadOutcome(null);
          teamPublished = true;
          if (requestedProjectId === target) requestedProjectId = null;
          if (selectedBeforeRefresh?.kind === "request" && !requestById(selectedBeforeRefresh.id)) {
            if (!selectEditedReplacement(selectedBeforeRefresh)) selected = null;
          }
          // Publish the current source before waking a queued body reader. It
          // must not issue an old locator between HTTP completion and publication.
          return {changed, projectChanged};
        },
      });
      if (!observation) return;
      const {changed, projectChanged} = observation;
      if (page === "knowledge") {
        if (projectChanged) {
          // Publish identity and its loading view together; a later navigation may
          // arrive while Knowledge is still loading for this accepted snapshot.
          knowledgeLoading = true;
          render({ preserveComposer: hasOpenComposer() });
        }
        // The refresh deadline owns every knowledge read, including its body.
        if (administrationAvailable) await loadKnowledge(controller.signal);
        else await loadAdministration(controller.signal, {refreshConsole: false});
      }
      renderCurrentFacts(changed);
      if (!superseded() && !systemReadFinished) {
        status.className = "";
        status.textContent = "团队记录已更新 · 正在读取交付操作记录…";
      }
    })().catch(error => {
      if (!superseded() && !teamPublished) {
        teamReadIssue = controller.signal.aborted ? "timeout"
          : error instanceof TeamReadFailure ? error.kind : "unavailable";
        recordTeamReadOutcome(teamReadIssue);
        // Revoke old Team authority without waiting for independent auxiliary reads.
        renderCurrentFacts();
        syncDeliveryControls();
      }
      throw error;
    });
    const systemRead = (async () => {
      try {
        await refreshOperations(controller.signal, {consoleRead});
        syncDeliveryControls();
        if (priorOperationsAvailable !== operationsAvailable) renderOperationStatus();
        await refreshSystemViews();
      } finally {
        systemReadFinished = true;
        renderCurrentFacts();
      }
    })();
    const [teamResult, systemResult] = await Promise.allSettled([teamRead, systemRead]);
    if (systemResult.status === "rejected") throw systemResult.reason;
    if (teamResult.status === "rejected") throw teamResult.reason;
    // An edit result can arrive after Team publishes the replacement identity.
    // Follow only the exact saved edit, without overwriting a later user selection.
    if (!superseded() && selectionIntentRevision === selectionRevisionAtStart && page === pageAtStart &&
        selectedRequestAtStart && !requestById(selectedRequestAtStart.id) &&
        (!selected || selected.kind === "request" && selected.id === selectedRequestAtStart.id)) {
      await readEditedRequirementReplacement(selectedRequestAtStart, selectedTeamAtStart, controller.signal);
      if (!superseded() && selectEditedReplacement(selectedAtStart)) renderCurrentFacts(true);
    }
    if (superseded()) {
      showRefreshProgress();
      return;
    }
    status.className = operationsAvailable && consoleAvailable === true ? "" : "error";
    status.textContent = consoleAvailable
      ? (consoleMode === "inspection" ? "维护仅查看服务已连接 · 需求交付已暂停" : consoleDeliveryReady
          ? "团队与交付控制台已连接"
          : "设置控制台已连接 · 交付运行时尚未就绪") +
        " · 最近读取 " +
        time(snapshot.as_of) +
        " · 读取完成后自动更新，繁忙时稍后重试" + (operationsAvailable ? "" : " · 交付操作记录读取失败，保留上次历史；当前操作暂不可用")
      : consoleAvailable === false ? "只读团队记录已连接；当前服务未提供交付控制接口。"
        : "团队记录已更新；交付控制连接暂不可用，当前操作暂停。";
  } catch (error) {
    if (superseded()) return;
    const issue = controller.signal.aborted ? "timeout"
      : teamReadIssue || (error instanceof TeamReadFailure ? error.kind : "unavailable");
    teamReadIssue = teamPublished ? null : issue;
    if (!snapshot || priorTeamReadIssue !== teamReadIssue || systemViewsChanged())
      render({preserveComposer: hasOpenComposer(), incremental: true});
    status.className = !teamPublished && issue === "busy" ? "" : "error";
    const destination = snapshot?.projects.find(item => item.id === requestedProjectId)?.name
      || requestedProjectId;
    const oldData = snapshot ? "以下为旧数据 · 上次成功读取 " + time(snapshot.as_of) + "。" : "";
    const reason = issue === "busy"
      ? "上一轮团队数据读取尚未完成，页面会自动重试。"
      : issue === "timeout"
        ? "团队数据读取超时；后台读取可能仍在进行，页面会自动重试。"
        : "团队数据读取失败，暂时无法读取数据；请查看平台状态与服务日志，页面会自动重试。";
    status.textContent = projectSwitchPending()
      ? issue === "busy"
        ? `切换到「${destination}」尚未完成，仍显示原 Project 数据。${reason}`
        : `切换到「${destination}」失败，仍显示原 Project 数据；刷新将重试该项目。${reason}`
      : teamPublished ? "团队数据已更新，但辅助记录刷新失败；请查看平台状态与服务日志。"
        : issue === "busy" ? reason + oldData
          : "刷新失败，" + reason + oldData;
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
setInterval(() => {void refreshRecoveryPreparationProgress();}, 5000);
