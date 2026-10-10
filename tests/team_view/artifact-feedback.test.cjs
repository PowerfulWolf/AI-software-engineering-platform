const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class Element {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {}; this.attributes = {}; this.events = {}; this.textContent = ""; }
  append(...children) { this.children.push(...children); }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(key, handler) { this.events[key] = handler; }
  set innerHTML(value) { throw new Error("Unsafe HTML: " + value); }
}
const text = node => node.textContent + node.children.map(child => typeof child === "string" ? child : text(child)).join(" ");
const receipt = /Coder 已接收上轮 QA\/Review 反馈作为本轮输入/;
const artifact = (id, kind, taskId = "task_current", fields = {}) => ({
  id, kind: "artifact", task_id: taskId, source_uri: "artifact://" + id,
  source_sha256: "a".repeat(64),
  details: {kind, artifact_sha256: "a".repeat(64), ...fields},
});

function harness(parents, inputs, kind = "implementation-report") {
  const current = artifact("art_coder", kind, "task_current", {parent_artifact_ids: inputs});
  const task = {id: "delivery_current", task_id: "task_current", project_id: "project_current",
    history_task_ids: ["task_current"], execution_history: [...parents, current], timeline: [current]};
  const context = vm.createContext({document: {createElement: tag => new Element(tag)}, current, task});
  const source = fs.readFileSync(path.join(__dirname, "../../src/ai_software_engineer/team_view/app.js"), "utf8");
  vm.runInContext(source.slice(0, source.indexOf('for (const target of ["team"')), context);
  vm.runInContext('snapshot={selected_project_id:"project_current",tasks:[task]}; selected={kind:"task",id:task.id}; globalThis.submitted=[];', context);
  const run = code => vm.runInContext(code, context);
  return {current, task, run, render: () => run("(() => {const target=el('div'); appendExecutionArtifactDetails(target,current); return target;})()")};
}

for (const [reportKind, verdict] of [["qa-report", {status: "FAIL"}], ["review-report", {verdict: "REJECT"}]]) {
  test(`an exact verified ${reportKind} parent supports input receipt without claiming a fix`, () => {
    for (const coderKind of ["implementation-report", "coder-progress"]) {
      const parent = artifact("art_feedback", reportKind, "task_current", verdict);
      const h = harness([parent], [parent.id], coderKind);
      const before = h.run("JSON.stringify(snapshot)");
      const rendered = h.render();
      const output = text(rendered);
      assert.match(output, receipt);
      assert.match(output, /后续独立.*验收/);
      assert.equal(rendered.children.find(child => receipt.test(child.textContent)).className, "muted",
        "input receipt is not a successful QA or Review result");
      assert.doesNotMatch(output, /已完成修改|已修复|问题已经解决|本轮已通过/);
      assert.equal(h.run("JSON.stringify(snapshot)"), before);
      assert.equal(h.run("submitted.length"), 0);
    }
  });
}

test("plan and progress inputs cannot imply QA or Review feedback", () => {
  for (const inputKind of ["plan", "coder-progress", "implementation-report"]) {
    const parent = artifact("art_input", inputKind);
    const h = harness([parent], [parent.id]);
    assert.doesNotMatch(text(h.render()), receipt, inputKind);
    assert.match(text(h.render()), /输入产物已记录/);
  }
});

test("an unknown parent ID is neutral even when its name resembles a QA report", () => {
  const h = harness([], ["art_qa_unknown"]);
  assert.doesNotMatch(text(h.render()), receipt);
  assert.match(text(h.render()), /当前历史不足以确认/);
});

test("verified historical feedback is resolved within the selected successor Task history", () => {
  const parent = artifact("art_previous_review", "review-report", "task_old", {verdict: "REJECT"});
  const h = harness([parent], [parent.id]);
  h.task.history_task_ids.push("task_old");
  h.run('snapshot.tasks.push({id:"delivery_other",project_id:"project_other",execution_history:[{...current,id:"art_previous_review",details:{kind:"plan"}}]})');
  assert.match(text(h.render()), receipt);
  assert.match(text(h.render()), /后续独立.*验收/);
});

test("duplicate and conflicting parent facts cannot establish feedback receipt", () => {
  for (const conflict of [false, true]) {
    const parent = artifact("art_ambiguous", "qa-report", "task_current", {status: "FAIL"});
    const duplicate = {...parent, details: {...parent.details, ...(conflict ? {kind: "plan"} : {})}};
    const h = harness([parent, duplicate], [parent.id]);
    assert.doesNotMatch(text(h.render()), receipt);
    assert.match(text(h.render()), /当前历史不足以确认/);
  }
});

test("missing hash binding or foreign Task lineage remains neutral", () => {
  for (const mutate of [
    parent => { delete parent.source_sha256; },
    parent => { parent.details.artifact_sha256 = "b".repeat(64); },
    parent => { parent.source_uri = "artifact://other"; },
    parent => { parent.task_id = "task_foreign"; },
  ]) {
    const parent = artifact("art_bad_binding", "qa-report", "task_current", {status: "FAIL"});
    mutate(parent);
    const h = harness([parent], [parent.id]);
    assert.doesNotMatch(text(h.render()), receipt);
    assert.match(text(h.render()), /当前历史不足以确认/);
  }
});
