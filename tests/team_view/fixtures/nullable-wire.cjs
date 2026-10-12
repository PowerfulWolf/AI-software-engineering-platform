"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const data = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const script = fs.readFileSync(path.resolve(__dirname, "../../../src/ai_software_engineer/team_view/app.js"), "utf8");
const context = vm.createContext({data, URLSearchParams, TextEncoder,
  document:{createElement:()=>({})}, console});
vm.runInContext(script.slice(0, script.indexOf('for (const target of ["team"')), context);
const run = code => vm.runInContext(code, context);
run('consoleTeamId=data.summary.team_id;consoleReadingIdentity={teamId:data.summary.team_id,mode:"normal"}');
run('verifiedTeamSummary(data.summary,data.summary.selected_project_id)');
for (let index=0; index<data.details.length; index++) {
  const detail = data.details[index], source=data.summary.tasks[index].detail_source;
  context.detail=detail; context.source=source;
  run('verifiedTeamDetail(detail,source)');
  for (const field of ["task_id", "task_revision", "task_intent_sha256"]) {
    // Null/missing are equivalent in both directions, real values remain exact.
    if (!(field in source)) {
      const explicit=structuredClone(detail); explicit.scope[field]=null; explicit.resource[field]=null;
      context.explicit=explicit;
      run('verifiedTeamDetail(explicit,source)');
      context.nullSource={...source,[field]:null};
      run('verifiedTeamDetail(detail,nullSource)');
      const nullable=structuredClone(data.summary);
      nullable.tasks[index].detail_source[field]=null;
      context.nullable=nullable;
      run('verifiedTeamSummary(nullable,nullable.selected_project_id)');
    }
    for (const changeSource of [true,false]) {
      const bad=structuredClone(data.summary), item=bad.tasks[index];
      (changeSource ? item.detail_source : item)[field] = field === "task_revision" ? 17
        : field === "task_id" ? "task_foreign" : "f".repeat(64);
      context.bad=bad;
      assert.throws(()=>run('verifiedTeamSummary(bad,bad.selected_project_id)'), field);
    }
    const badDetail=structuredClone(detail);
    badDetail.resource[field]=field === "task_revision" ? 17 : field === "task_id" ? "task_foreign" : "f".repeat(64);
    context.badDetail=badDetail;
    assert.throws(()=>run('verifiedTeamDetail(badDetail,source)'),field);
  }
}
for (const field of ["team_id","project_id","request_id","resource_id","requirement_checkpoint_sha256"]) {
  const bad=structuredClone(data.summary);
  bad.tasks[0].detail_source[field] = field.endsWith("sha256") ? "f".repeat(64) : "foreign_identity";
  context.bad=bad;
  assert.throws(()=>run('verifiedTeamSummary(bad,bad.selected_project_id)'),field);
}
const verification=data.summary.tasks.findIndex(task=>task.work_kind === "candidate_verification");
for (const field of ["source_task_id","verification_plan_sha256"]) {
  const bad=structuredClone(data.summary);
  bad.tasks[verification].detail_source[field]=field.endsWith("sha256") ? "f".repeat(64) : "task_foreign";
  context.bad=bad;
  assert.throws(()=>run('verifiedTeamSummary(bad,bad.selected_project_id)'),field);
}
console.log("canonical nullable wire and exact identity rejection passed");
