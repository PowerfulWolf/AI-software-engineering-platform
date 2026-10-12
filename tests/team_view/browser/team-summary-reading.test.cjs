const {test} = require("node:test");
const assert = require("node:assert/strict");
const {ui} = require("./fixture.cjs");
const sha = value => value.repeat(64);
function summarySource(item,kind) {
  return {team_id:"team_fixture",project_id:item.project_id,request_id:kind === "request" ? item.id : item.request_id,
    resource_kind:kind,resource_id:item.id,requirement_checkpoint_sha256:sha("a"),
    resource_checkpoint_sha256:kind === "request" ? item.checkpoint_sha256 : sha("b"),
    resource_state_sha256:sha("e"),
    work_kind:kind === "request" ? null : item.work_kind,task_id:kind === "request" ? null : item.task_id,
    task_revision:kind === "request" ? null : item.task_revision,task_intent_sha256:kind === "request" ? null : item.task_intent_sha256,
    source_task_id:null,verification_plan_sha256:null};
}
async function summaryBrowser(t,{product=false}={}) {
  const h=await ui(t),calls=[],state={hold:null,fail:false};
  const request=h.team.requests[0];
  Object.assign(request,{stage:product?"WAITING_PRODUCT_APPROVAL":"DELIVERING",checkpoint_sha256:sha("a"),
    documents:[{name:"ProductSpec",source_uri:"request://request_fixture/ProductSpec",sha256:sha("d"),
      content:JSON.stringify({scope_sha256:sha("a"),version:1,product:{title:"Selected requirement evidence",requirements:["完整规格"]}},null,2)}],
    dialogue:[{sequence:1,speaker:"user",text:"保留完整讨论"}],
    product_spec_source:{spec_id:null,version:1,sha256:sha("d"),source_uri:"request://request_fixture/ProductSpec"}});
  const task={id:"delivery_fixture",task_id:"task_fixture",task_revision:2,task_intent_sha256:sha("c"),
    request_id:request.id,project_id:request.project_id,work_kind:"delivery",title:"开发与验收记录",status:"IMPLEMENTING",
    checkpoint_stage:"DELIVERING",terminal:false,last_activity:"2026-10-12T00:00:00Z",scope:{root:"/fixture",selected_paths:["."]},
    assignments:[],role_queue:[],timeline:[],execution_history:Array.from({length:14},(_,i)=>({id:"entry_"+i,task_id:"task_fixture",
      kind:"artifact",summary:"QA 报告 · FAIL · "+i,occurred_at:"2026-10-12T00:00:00Z",source_uri:"artifact://qa_"+i,
      details:{kind:"qa-report",status:"FAIL",summary:"Selected QA evidence "+i,artifact_sha256:sha("e"),findings:[{message:"完整失败理由 "+i,recommendation:"补足测试 "+i}]}})),
    documents:[{name:"完整报告",source_uri:"artifact://task_fixture",sha256:sha("f"),content:"报告正文\n"+"保持阅读位置\n".repeat(80)}],runs:[]};
  request.detail_source=summarySource(request,"request");task.detail_source=summarySource(task,"task");
  request.scopes=[{...task.scope,delivery_id:task.id,reference_only:false}];h.team.tasks=[task];
  const body=kind=>{const resource=kind === "request" ? request : task;return {schema_version:"v0.1",kind,
    as_of:h.team.as_of,scope:structuredClone(resource.detail_source),resource:structuredClone(resource)};};
  await h.page.route("http://ui.test/api/v1/console",route=>route.fulfill({json:{schema_version:"v0.2",team_id:h.team.team_id,
    delivery_ready:true,...h.state.operationManifest,team_read_contract_version:"v0.1"}}));
  await h.page.route("http://ui.test/api/v1/team-summary*",route=>{
    calls.push({kind:"summary",url:route.request().url()});
    const value=structuredClone(h.team);value.schema_version="v0.1";
    value.requests.forEach(item=>{delete item.documents;delete item.dialogue;});
    value.tasks.forEach(item=>{delete item.documents;delete item.timeline;delete item.execution_history;delete item.runs;});
    return route.fulfill({json:value});
  });
  await h.page.route("http://ui.test/api/v1/team-details*",async route=>{
    const query=new URL(route.request().url()).searchParams,kind=query.get("kind"),response=body(kind);
    calls.push({kind:"detail",url:route.request().url()});
    if(state.hold) await state.hold;
    try {await route.fulfill(state.fail?{status:503,json:{error:{code:"UNAVAILABLE"}}}:{json:response});} catch { /* Closed/aborted browser read. */ }
  });
  await h.tick();
  return {...h,calls,state,request,task};
}

test("summary ticks retain complete selected documents, text selection, scroll and all fourteen rework rounds",async t=>{
  const h=await summaryBrowser(t);await h.page.evaluate(()=>showDetail("task","delivery_fixture"));
  const dialog=h.page.locator(".task-detail-dialog"),report=dialog.locator('details[data-key="artifact://task_fixture"]');
  await report.waitFor();await report.locator(":scope > summary").click();
  assert.equal(await dialog.locator(".execution-history-entry").count(),14);
  await report.locator("pre").evaluate(node=>{window.readingReport=node;const range=document.createRange();range.selectNodeContents(node.firstChild);
    getSelection().removeAllRanges();getSelection().addRange(range);node.closest(".task-detail-dialog").scrollTop=140;});
  const before=h.calls.filter(call=>call.kind === "detail").length;
  h.task.last_activity="2026-10-12T00:01:00Z";await h.tick();await h.tick();
  assert.equal(h.calls.filter(call=>call.kind === "detail").length,before);
  assert.equal(await report.locator("pre").evaluate(node=>node === window.readingReport && node.isConnected),true);
  assert.match(await h.page.evaluate(()=>getSelection().toString()),/报告正文/);
  assert.equal(await report.evaluate(node=>node.open),true);
  assert.equal(await h.page.evaluate(()=>snapshot.tasks[0].execution_history),undefined);
  await h.page.setViewportSize({width:390,height:844});
  assert.equal(await dialog.evaluate(node=>node.scrollWidth<=node.clientWidth+1),true);
});

test("current status stays fresh while changed detail fails and preserves labelled old reports",async t=>{
  const h=await summaryBrowser(t);await h.page.evaluate(()=>showDetail("request","request_fixture"));
  const report=h.page.locator('details[data-key="request://request_fixture/ProductSpec"]');await report.waitFor();await report.locator(":scope > summary").click();
  await report.locator("pre").evaluate(node=>window.oldReport=node);
  h.state.fail=true;h.request.stage="BLOCKED";h.request.title="最新需求标题";h.request.checkpoint_sha256=sha("f");
  h.request.detail_source.requirement_checkpoint_sha256=sha("f");h.request.detail_source.resource_checkpoint_sha256=sha("f");
  h.task.detail_source.requirement_checkpoint_sha256=sha("f");await h.tick();
  await h.page.waitForFunction(()=>teamDetailRead?.status === "error");
  assert.match(await h.page.locator(".detail-body-read-status").innerText(),/保留上次读取的正文/);
  assert.match(await h.page.locator(".request-title-row").innerText(),/最新需求标题/);
  assert.equal(await h.page.evaluate(()=>requestById("request_fixture").stage),"BLOCKED");
  assert.equal(await report.locator("pre").evaluate(node=>node === window.oldReport),true);
  assert.equal(await h.page.locator(".detail-body-read-status").getByRole("button",{name:"重新读取完整正文"}).count(),1);
});

test("a new feedback record updates the complete visible history without inventing a Task revision",async t=>{
  const h=await summaryBrowser(t);await h.page.evaluate(()=>showDetail("task","delivery_fixture"));
  await h.page.waitForFunction(()=>teamDetailRead?.status === "ready");
  const before=h.calls.filter(call=>call.kind === "detail").length;
  h.task.execution_history.push({...h.task.execution_history[13],id:"entry_14",summary:"Review 报告 · REJECT · 新一轮反馈",
    source_uri:"artifact://review_14",details:{...h.task.execution_history[13].details,kind:"review-report",status:"REJECT",
      summary:"新增完整审查理由",findings:[{message:"新增完整审查理由",recommendation:"补足边界处理"}]}});
  h.task.detail_source.resource_state_sha256=sha("f");
  await h.tick();await h.page.waitForFunction(()=>teamDetailRead?.status === "ready" &&
    teamDetailRead.value.scope.resource_state_sha256 === "f".repeat(64));
  assert.equal(h.calls.filter(call=>call.kind === "detail").length,before+1);
  assert.equal(await h.page.locator(".task-detail-dialog .execution-history-entry").count(),15);
  assert.match(await h.page.locator(".task-detail-dialog .execution-history-entry").last().innerText(),/新一轮反馈/);
  assert.equal(h.task.task_revision,2);
  assert.equal(h.task.detail_source.resource_checkpoint_sha256,sha("b"));
});

test("Product approval waits for the complete current spec and late closed detail cannot restore it",async t=>{
  const h=await summaryBrowser(t,{product:true});let release;h.state.hold=new Promise(resolve=>release=resolve);
  await h.page.evaluate(()=>showDetail("request","request_fixture"));
  const approve=h.page.getByRole("button",{name:"批准 ProductSpec 并开始交付",exact:true});
  assert.equal(await approve.isDisabled(),true);
  await h.page.locator("#detail").getByRole("button",{name:"关闭详情",exact:true}).click();release();h.state.hold=null;
  await h.page.waitForTimeout(50);
  assert.equal(await h.page.evaluate(()=>teamDetailRead),null);
  await h.page.evaluate(()=>showDetail("request","request_fixture"));
  await h.page.waitForFunction(()=>productApprovalReadReady(requestById("request_fixture")));
  assert.equal(await approve.isDisabled(),false);
  assert.equal(await h.page.evaluate(()=>snapshot.requests[0].documents),undefined);
});
