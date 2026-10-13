"use strict";

// The Python contract test supplies actual producer/store/HTTP snapshots here.
// Only transport and render hooks are fake; refresh, hydration and scope gates
// execute the shipped browser source unchanged.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

async function checkNavigation(data, mode) {
  const requests = [], nodes = new Map();
  let context, inspectedFullRead = false;
  const run = expression => vm.runInContext(expression, context);
  context = vm.createContext({TextEncoder, URLSearchParams, AbortController,
    console, structuredClone, data, setTimeout: () => 1, clearTimeout: () => {},
    document: {createElement: () => ({}), getElementById: id => {
      if (!nodes.has(id)) nodes.set(id, {});
      return nodes.get(id);
    }},
    fetch: async (url, options) => {
      requests.push({url, method: options?.method || "GET"});
      const parsed = new URL(url, "http://127.0.0.1");
      let body;
      if (parsed.pathname === "/api/v1/team") body = data.after;
      else if (parsed.pathname === "/api/v1/team-summary") body = data.after_summary;
      else if (parsed.pathname === "/api/v1/console") body = data.manifest;
      else if (parsed.pathname === "/api/v1/operation-summaries")
        body = parsed.searchParams.has("delivery_id") ? data.delivery_page : data.project_page;
      else if (parsed.pathname === "/api/v1/operations/" + data.operation.operation_id) {
        assert.equal(run("requestById(data.original.id)"), undefined,
          "the modern Team read removed the old draft before exact full hydration");
        assert.equal(run("selected"), null);
        inspectedFullRead = true;
        // Simulate a user navigation while the awaited full read is in flight.
        if (mode === "selection") run('selectionIntentRevision++; selected={kind:"task", id:"user_selected_task"}');
        if (mode === "project") run('selectionIntentRevision++; requestedProjectId="project_other"; selected=null');
        if (mode === "page") run('page="team"');
        body = data.operation;
      } else throw new Error("Unexpected HTTP read: " + url);
      return {ok: true, status: 200, headers: {get: () => '"current"'},
        json: async () => structuredClone(body)};
    },
  });
  const source = fs.readFileSync(path.join(__dirname,
    "../../../src/ai_software_engineer/team_view/app.js"), "utf8");
  run(source.slice(0, source.indexOf('for (const target of ["team"')));
  run(source.slice(source.indexOf("async function refreshConsoleInfo("),
    source.indexOf('document\n  .getElementById("refresh")')));
  run(`snapshot=data.before; page="requests"; selected={kind:"request", id:data.original.id};
    consoleTeamId=data.before.team_id; consoleOperationSummaryContractVersion="v0.1";
    consoleAvailable=true; consoleDeliveryReady=true; operationsAvailable=true;
    render=()=>{}; renderOperationStatus=()=>{}; renderNotification=()=>{};
    syncDeliveryControls=()=>{}; hasOpenComposer=()=>false;`);
  await run("refreshSnapshot(data.before.selected_project_id, false)");
  assert.equal(inspectedFullRead, true, "refresh follows the exact saved UPDATE via a full GET");
  assert.equal(requests.filter(item => item.url === "/api/v1/operations/" + data.operation.operation_id).length, 1);
  assert.equal(requests.some(item => item.url === "/api/v1/operations"), false);
  assert.ok(requests.every(item => item.method === "GET"), "navigation has no write authority");
  assert.equal(run("operationResult(data.operation)"), null);
  assert.equal(run("latestApproval(data.original.id, data.original.checkpoint_sha256)"), null);
  if (mode === "follow") {
    assert.equal(run("selected.id"), data.replacement.id);
    assert.equal(run("operationDetailCache.size"), 1);
    assert.equal(run("teamReadIssue"), null);
  } else if (mode === "selection") assert.equal(run("selected.id"), "user_selected_task");
  else {
    assert.equal(run("selected"), null, "late edit result cannot override later user navigation");
    if (mode === "project") assert.equal(run("requestedProjectId"), "project_other");
    if (mode === "page") assert.equal(run("page"), "team");
  }
}

const data = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
(async () => {
  for (const mode of ["follow", "selection", "project", "page"]) await checkNavigation(data, mode);
})().catch(error => {console.error(error); process.exitCode = 1;});
