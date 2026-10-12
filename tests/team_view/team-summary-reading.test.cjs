const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const digest = value => value.repeat(64);
const request = (id = "delivery_current", overrides = {}) => ({id, project_id:"project_current",
  title:"当前标题", stage:"WAITING_PRODUCT_APPROVAL", scopes:[], checkpoint_sha256:digest("a"),
  next_action:"审阅当前产品文档", ...overrides});
function source(item, kind = "request") {
  return {team_id:"team_current", project_id:item.project_id, request_id:kind === "request" ? item.id : item.request_id,
    resource_kind:kind, resource_id:item.id, requirement_checkpoint_sha256:digest("a"),
    resource_checkpoint_sha256:kind === "request" ? item.checkpoint_sha256 : digest("b"),
    resource_state_sha256:digest("e"),
    work_kind:kind === "request" ? null : "delivery", task_id:kind === "request" ? null : "task_current",
    task_revision:kind === "request" ? null : 2, task_intent_sha256:kind === "request" ? null : digest("c"),
    source_task_id:null, verification_plan_sha256:null};
}
function harness() {
  const calls = [], replies = [], timers = new Map();
  const context = vm.createContext({console, TextEncoder, URLSearchParams, AbortController,
    structuredClone, document:{createElement:() => ({})},
    setTimeout:(fn, delay) => {const id=timers.size+1; timers.set(id,{fn,delay}); return id;},
    clearTimeout:id => timers.delete(id), fetch:async (url, options) => {
      calls.push({url,options}); const reply=replies.shift();
      if (!reply) throw new Error("Unexpected request: "+url);
      if (reply.wait) await reply.wait;
      if (reply.before) reply.before();
      return {ok:(reply.status || 200) < 400, status:reply.status || 200,
        json:async () => reply.body};
    }});
  const script = fs.readFileSync(path.join(__dirname,"../../src/ai_software_engineer/team_view/app.js"),"utf8");
  vm.runInContext(script.slice(0,script.indexOf('for (const target of ["team"')),context);
  vm.runInContext(script.slice(script.indexOf("async function refreshConsoleInfo("),
    script.indexOf('document\n  .getElementById("refresh")\n  .addEventListener')),context);
  const run = expression => vm.runInContext(expression,context);
  const item=request(); item.detail_source=source(item);
  item.product_spec_source={spec_id:"product_spec_current",sha256:digest("d"),source_uri:"ProductSpec://product_spec_current"};
  context.item=item;
  run('snapshot={schema_version:"v0.1",team_id:"team_current",selected_project_id:"project_current",projects:[],agents:[],tasks:[],requests:[item]}; selected={kind:"request",id:item.id}; page="requests"; consoleTeamReadContractVersion="v0.1"; consoleReadingIdentity={teamId:"team_current",mode:"normal"}; render=()=>{};');
  const detail = (resource = item, kind = "request") => ({schema_version:"v0.1",kind,
    as_of:"2026-10-12T00:01:00Z", scope:resource.detail_source,
    resource:{...resource, title:"旧详情标题", documents:[{name:"ProductSpec",source_uri:item.product_spec_source.source_uri,
      sha256:digest("d"),content:JSON.stringify({id:"product_spec_current",title:"完整规格"})}],
    ...(kind === "request" ? {dialogue:[]} : {timeline:[],execution_history:[],runs:[]})}});
  return {context,run,calls,replies,timers,item,detail,script};
}

test("same-source summary ticks read complete body only once and never publish old headers into snapshot",async () => {
  const h=harness(); h.replies.push({body:h.detail()});
  await h.run("readSelectedTeamDetail()");
  await h.run("readSelectedTeamDetail()");
  assert.equal(h.calls.length,1);
  assert.match(h.calls[0].url,/^\/api\/v1\/team-details\?/);
  assert.equal(h.run("snapshot.requests[0].documents"),undefined);
  assert.equal(h.run("detailReadingItem(item).title"),"当前标题");
  assert.equal(h.run("detailReadingItem(item).documents.length"),1);
});

test("complete ProductSpec must match current exact source, ID and original digest",async () => {
  for (const invalid of ["missing","id","digest","uri","forged_source_uri","none"]) {
    const h=harness(); const body=h.detail();
    if(invalid === "missing") body.resource.documents[0].content="";
    if(invalid === "id") body.resource.documents[0].content='{"id":"product_spec_old"}';
    if(invalid === "digest") body.resource.documents[0].sha256=digest("e");
    if(invalid === "uri") body.resource.documents[0].source_uri="request://other/ProductSpec";
    if(invalid === "forged_source_uri") {
      h.item.product_spec_source.source_uri="ProductSpec://product_spec_other";
      body.resource.documents[0].source_uri=h.item.product_spec_source.source_uri;
    }
    if(invalid === "none") body.resource.documents=[];
    assert.equal(h.run("productApprovalReadReady(item)"),false);
    h.replies.push({body}); await h.run("readSelectedTeamDetail()");
    assert.equal(h.run("productApprovalReadReady(item)"),false,invalid);
  }
  const h=harness();h.replies.push({body:h.detail()});await h.run("readSelectedTeamDetail()");
  assert.equal(h.run("productApprovalReadReady(item)"),true);
  h.run('item.checkpoint_sha256="'+digest("f")+'"; item.detail_source.resource_checkpoint_sha256=item.checkpoint_sha256; item.detail_source.requirement_checkpoint_sha256=item.checkpoint_sha256');
  assert.equal(h.run("productApprovalReadReady(item)"),false);
});

test("late complete responses cannot repopulate closed or superseded reading owners",async () => {
  for (const boundary of ["close","selection","project","team","page"]) {
    const h=harness();let resolve;
    const wait=new Promise(r=>resolve=r);h.replies.push({body:h.detail(),wait});
    const pending=h.run("readSelectedTeamDetail()");
    if(boundary === "close") h.run("selected=null; clearTeamDetailRead()");
    if(boundary === "selection") h.run('selected={kind:"request",id:"delivery_other"}');
    if(boundary === "project") h.run('snapshot.selected_project_id="project_other"');
    if(boundary === "team") h.run('snapshot.team_id="team_other"');
    if(boundary === "page") h.run('page="team"');
    resolve();await pending;
    assert.equal(h.run("teamDetailRead?.value ?? null"),null,boundary);
    assert.equal(h.calls.some(c=>c.options?.method === "POST"),false);
  }
});

test("failed or drifted detail never falls back to full Team or invents an empty body",async () => {
  for (const invalid of [409,503,"scope","resource","identity"]) {
    const h=harness(),body=h.detail();
    if(invalid === "scope") body.scope={...body.scope,team_id:"team_other"};
    if(invalid === "resource") body.resource.id="delivery_other";
    if(invalid === "identity") body.resource.checkpoint_sha256=digest("e");
    h.replies.push({body,status:Number.isInteger(invalid)?invalid:200});
    await h.run("readSelectedTeamDetail()");
    assert.equal(h.run("teamDetailRead.status"),"error");
    assert.equal(h.run("detailReadingItem(item).documents"),undefined);
    assert.equal(h.run("productApprovalReadReady(item)"),false);
    assert.equal(h.calls.length,1);
  }
});

test("task details preserve every rework round and use exact task identity in GET",async () => {
  const h=harness(), task={id:"delivery_child",project_id:"project_current",request_id:h.item.id,
    task_id:"task_current",task_revision:2,task_intent_sha256:digest("c"),work_kind:"delivery",title:"当前任务"};
  task.detail_source=source(task,"task");h.context.task=task;
  h.run('snapshot.tasks=[task];selected={kind:"task",id:task.id}');
  const body=h.detail(task,"task");body.resource.execution_history=Array.from({length:14},(_,i)=>({id:"entry_"+i,summary:"QA或Review返工 "+i}));
  h.replies.push({body});await h.run("readSelectedTeamDetail()");
  assert.match(h.calls[0].url,/expected_task_revision=2/);
  assert.match(h.calls[0].url,/expected_task_intent_sha256=/);
  assert.equal(new URL(h.calls[0].url,"http://fixture").searchParams.get("expected_resource_state_sha256"),digest("e"));
  assert.equal(h.run("detailReadingItem(task).execution_history.length"),14);
});

test("new verification findings reload complete history even when checkpoint and SQL identity stay unchanged",async () => {
  const h=harness(),task={id:"verification_"+digest("d").slice(0,32),project_id:"project_current",request_id:h.item.id,
    task_id:"task_verification",task_revision:null,task_intent_sha256:null,work_kind:"candidate_verification",
    source_task_id:"task_source",plan_sha256:digest("d"),title:"独立验收"};
  task.detail_source={...source(task,"task"),work_kind:task.work_kind,task_id:task.task_id,
    task_revision:null,task_intent_sha256:null,source_task_id:task.source_task_id,verification_plan_sha256:task.plan_sha256};
  h.context.task=task;h.run('snapshot.tasks=[task];selected={kind:"task",id:task.id}');
  const first=h.detail(task,"task");first.resource.execution_history=[{id:"qa_failed",summary:"QA 失败的完整原因"}];
  h.replies.push({body:first});await h.run("readSelectedTeamDetail()");
  const original=structuredClone(task.detail_source);
  task.detail_source={...task.detail_source,resource_state_sha256:digest("f")};
  const second=h.detail(task,"task");second.resource.execution_history=[...first.resource.execution_history,
    {id:"review_rejected",summary:"Review 拒绝的完整原因"}];
  h.replies.push({body:second});await h.run("readSelectedTeamDetail()");
  assert.equal(h.calls.length,2);
  assert.equal(task.detail_source.resource_checkpoint_sha256,original.resource_checkpoint_sha256);
  assert.equal(task.task_revision,null);
  assert.equal(new URL(h.calls[1].url,"http://fixture").searchParams.get("expected_resource_state_sha256"),digest("f"));
  assert.equal(h.run("detailReadingItem(task).execution_history.length"),2);
  assert.equal(h.run("detailReadingItem(task).execution_history[1].id"),"review_rejected");
  // A body from the old semantic version must never replace the new complete reading.
  h.replies.push({body:first});await h.run("readSelectedTeamDetail({force:true})");
  assert.equal(h.run("teamDetailRead.status"),"error");
  assert.equal(h.run("detailReadingItem(task).execution_history.length"),2);
});

test("joint ProductSpec uses its real version and complete product, with no fabricated native ID",async () => {
  for(const invalid of [null,"version","product","both"]) {
    const h=harness();h.item.product_spec_source={spec_id:null,version:2,sha256:digest("d"),source_uri:"request://delivery_current/ProductSpec"};
    const body=h.detail();body.resource.documents[0].content=JSON.stringify({scope_sha256:digest("a"),version:invalid === "version" ? 1 : 2,
      ...(invalid === "product" ? {} : {product:{requirements:["完整需求"]}})});
    if(invalid === "both") h.item.product_spec_source.spec_id="product_spec_current";
    h.replies.push({body});await h.run("readSelectedTeamDetail()");
    assert.equal(h.run("productApprovalReadReady(item)"),invalid == null);
  }
});

test("the real Product approval POST boundary refuses detail drift during awaited Operation recheck",async () => {
  for(const invalid of ["unread","changed","cleared",null]) {
    const h=harness();
    if(invalid !== "unread") {h.replies.push({body:h.detail()});await h.run("readSelectedTeamDetail()");}
    h.run('consoleAvailable=true; consoleDeliveryReady=true; operationsAvailable=true; consoleTeamId=snapshot.team_id; consoleOperationContractVersion=1; consoleSupportedActions=["PRODUCT_APPROVAL"]; renderNotification=()=>{}; renderDetail=()=>{}; renderOperationStatus=()=>{}; observeSubmittedOperation=()=>{};');
    h.context.invalidate=invalid;
    h.run('recheckOperationWriteFacts=async()=>{if(invalidate === "changed") item.product_spec_source.sha256="'+digest("f")+'"; if(invalidate === "cleared") clearTeamDetailRead();}');
    if(invalid == null) h.replies.push({body:{operation_id:"operation_accepted",intent:{action:"PRODUCT_APPROVAL",project_id:h.item.project_id,delivery_id:h.item.id},status:"QUEUED"}});
    await h.run('submitOperation({action:"PRODUCT_APPROVAL",project_id:item.project_id,delivery_id:item.id,expected_checkpoint_sha256:item.checkpoint_sha256})');
    assert.equal(h.calls.filter(call=>call.options?.method === "POST").length,invalid == null ? 1 : 0,invalid);
  }
});

test("summary-source version changes keep labelled old body for reading and revoke Product authority",async () => {
  const h=harness();h.replies.push({body:h.detail()});await h.run("readSelectedTeamDetail()");
  const prior=h.run("teamDetailRead.value");h.context.newSource={...h.item.detail_source,
    requirement_checkpoint_sha256:digest("f"),resource_checkpoint_sha256:digest("f")};
  h.run('item.checkpoint_sha256=newSource.resource_checkpoint_sha256;item.detail_source=newSource');
  h.replies.push({status:503,body:{error:{message:"不可暴露的服务内部细节"}}});
  await h.run("readSelectedTeamDetail()");
  assert.equal(h.run("teamDetailRead.value"),prior);
  assert.equal(h.run("teamDetailRead.status"),"error");
  assert.equal(h.run("productApprovalReadReady(item)"),false);
  assert.equal(h.run("detailReadingItem(item).documents.length"),1);
});

test("summary wire cannot smuggle fake empty bodies or mismatched current resource locators",()=>{
  for(const invalid of ["body","duplicate","owner","scope","state_missing","state_bad"]) {
    const h=harness(),value={schema_version:"v0.1",team_id:"team_current",selected_project_id:"project_current",projects:[],agents:[],requests:[structuredClone(h.item)],tasks:[]};
    if(invalid === "body") value.requests[0].documents=[];
    if(invalid === "duplicate") value.requests.push(value.requests[0]);
    if(invalid === "owner") value.requests[0].project_id="project_other";
    if(invalid === "scope") value.requests[0].detail_source.resource_checkpoint_sha256=digest("f");
    if(invalid === "state_missing") delete value.requests[0].detail_source.resource_state_sha256;
    if(invalid === "state_bad") value.requests[0].detail_source.resource_state_sha256="not-a-digest";
    h.context.value=value;h.run('consoleTeamId="team_current"');
    assert.throws(()=>h.run('verifiedTeamSummary(value,"project_current")'),invalid);
  }
});

test("shipped refresh negotiates Team read wire once; new read failures do not fallback",async()=>{
  for(const variant of ["summary","legacy","failure"]) {
    const h=harness(),calls=[];
    const value={schema_version:variant === "legacy" ? "v0.2" : "v0.1",as_of:"2026-10-12T00:00:00Z",
      team_id:"team_current",selected_project_id:"project_current",team_name:"Team",projects:[],agents:[],requests:[h.item],tasks:[]};
    if(variant === "legacy") {value.requests[0]={...h.item,documents:[],dialogue:[]};delete value.requests[0].detail_source;delete value.requests[0].product_spec_source;}
    h.context.recordCalls=calls;h.context.value=value;h.context.variant=variant;
    h.run(`document.getElementById=()=>({disabled:false,className:"",textContent:""});
      showRefreshProgress=()=>{};syncDeliveryControls=()=>{};renderOperationStatus=()=>{};renderNotification=()=>{};
      fetch=async(url,options)=>{recordCalls.push({url,options});
        if(url==="/api/v1/console") return {ok:true,json:async()=>({schema_version:"v0.2",team_id:"team_current",delivery_ready:true,operation_contract_version:1,supported_actions:[],...(variant === "legacy" ? {} : {team_read_contract_version:"v0.1"})})};
        if(url==="/api/v1/operations") return {ok:true,json:async()=>[]};
        if(url.startsWith("/api/v1/team")) return {ok:variant !== "failure",status:variant === "failure" ? 503 : 200,json:async()=>variant === "failure" ? {error:{code:"UNAVAILABLE"}} : value};
        throw Error("Unexpected route "+url);};`);
    await h.run('refreshSnapshot("project_current",false)');
    assert.equal(calls.filter(call=>call.url === "/api/v1/console").length,1);
    assert.equal(calls.filter(call=>call.url.startsWith("/api/v1/team-summary")).length,variant === "legacy" ? 0 : 1);
    assert.equal(calls.filter(call=>call.url.startsWith("/api/v1/team?")).length,variant === "legacy" ? 1 : 0);
    assert.equal(h.run("teamReadIssue"),variant === "failure" ? "unavailable" : null);
  }
});

test("a confirmed read-only Console 404 clears the new capability while temporary failures retain it",async()=>{
  for(const status of [404,503]) {
    const h=harness();h.replies.push({status,body:{error:{message:"unavailable"}}});
    await h.run("refreshConsoleInfo()");
    assert.equal(h.run("consoleTeamReadContractVersion"),status === 404 ? null : "v0.1");
    assert.equal(h.run("teamDetailRead"),null);
  }
});

test("409 body retry first refreshes current summary and joins the new exact body; navigation cancels retry",async()=>{
  for(const boundary of [null,"close","failed"]) {
    const h=harness();h.replies.push({status:409,body:{}});await h.run("readSelectedTeamDetail()");
    h.context.boundary=boundary;
    h.run('refresh=async()=>{ if(boundary === "close") {selected=null;clearTeamDetailRead();return;} if(boundary === "failed") {teamReadIssue="unavailable";return;} item.checkpoint_sha256="'+digest("f")+'";item.detail_source={...item.detail_source,requirement_checkpoint_sha256:item.checkpoint_sha256,resource_checkpoint_sha256:item.checkpoint_sha256}; await readSelectedTeamDetail(); }');
    if(boundary == null) {const body=h.detail();body.scope={...body.scope,requirement_checkpoint_sha256:digest("f"),resource_checkpoint_sha256:digest("f")};body.resource.checkpoint_sha256=digest("f");h.replies.push({body});}
    await h.run("retrySelectedTeamDetail()");
    assert.equal(h.calls.length,boundary == null ? 2 : 1,boundary);
    if(boundary == null) assert.equal(h.run("teamDetailRead.status"),"ready");
  }
});

function coordinatedReads() {
  const h=harness(),calls=[],state={holdSummary:null,holdDetail:null,consoleFailure:null,methods:[],
    manifest:{schema_version:"v0.2",team_id:"team_current",delivery_ready:true,
      operation_contract_version:1,supported_actions:[],team_read_contract_version:"v0.1"}};
  const value={schema_version:"v0.1",as_of:"2026-10-12T00:00:00Z",team_id:"team_current",
    selected_project_id:"project_current",team_name:"Team",projects:[],agents:[],requests:[h.item],tasks:[]};
  const reply=(body,status=200)=>({ok:status<400,status,json:async()=>body});
  let summaryEntered,detailEntered;
  const summaryStarted=new Promise(resolve=>summaryEntered=resolve),detailStarted=new Promise(resolve=>detailEntered=resolve);
  h.context.readFixture=async (url,options={})=>{
    calls.push(url);state.methods.push(options.method || "GET");
    if(url === "/api/v1/console") {
      if(state.consoleFailure === "network") throw Error("offline Console fixture");
      if(state.consoleFailure === "json") return {ok:true,status:200,json:async()=>{throw Error("invalid JSON fixture");}};
      return reply(state.manifest,state.consoleFailure || 200);
    }
    if(url === "/api/v1/operations") return reply([]);
    if(url.startsWith("/api/v1/operation-summaries?")) {
      const query=new URL(url,"http://fixture").searchParams;
      return reply({schema_version:"v0.1",team_id:state.manifest.team_id,
        scope:{project_id:query.get("project_id"),delivery_id:query.get("delivery_id")},
        inventory_sha256:digest("a"),items:[],active:[],active_complete:true,total_count:0,next_cursor:null});
    }
    if(url === "/api/v1/team" || url.startsWith("/api/v1/team?")) return reply({...value,schema_version:"v0.2",
      requests:value.requests.map(item=>{const full={...item,documents:[],dialogue:[]};delete full.detail_source;return full;})});
    if(url.startsWith("/api/v1/team-summary")) {
      summaryEntered();
      if(state.holdSummary) await state.holdSummary;
      const project=new URL(url,"http://fixture").searchParams.get("project_id");
      return reply(project === value.selected_project_id ? value
        : {...value,selected_project_id:project,requests:[],tasks:[]});
    }
    if(url.startsWith("/api/v1/team-details")) {
      detailEntered();
      const body=h.detail();
      if(state.holdDetail) await state.holdDetail;
      return reply(body);
    }
    throw Error("Unexpected offline route "+url);
  };
  h.run(`document.getElementById=()=>({disabled:false,className:"",textContent:""});
    showRefreshProgress=()=>{};syncDeliveryControls=()=>{};renderOperationStatus=()=>{};renderNotification=()=>{};
    fetch=readFixture;render=()=>{void readSelectedTeamDetail();};`);
  return {...h,calls,state,value,summaryStarted,detailStarted};
}

test("summary refresh retries fixed external busy without publishing a read failure",async()=>{
  const h=coordinatedReads(),original=h.context.readFixture;let summaries=0;
  h.context.readFixture=async(url,options)=>{
    if(url.startsWith("/api/v1/team-summary") && summaries++ === 0) {
      h.calls.push(url);
      return {ok:false,status:503,json:async()=>({error:{code:"TEAM_READ_IN_PROGRESS"}})};
    }
    return original(url,options);
  };
  h.run("fetch=readFixture");
  const refreshing=h.run("refresh()");
  for(let turn=0;turn<50 && ![...h.timers.values()].some(timer=>timer.delay === 1000);turn++) await Promise.resolve();
  const retry=[...h.timers.values()].find(timer=>timer.delay === 1000);
  assert.ok(retry,"fixed busy should be retried inside the current refresh deadline");
  assert.equal(h.run("teamReadIssue"),null);
  retry.fn();await refreshing;
  await h.run("teamDetailRead?.promise");
  assert.equal(summaries,2);
  assert.equal(h.run("teamReadIssue"),null);
  assert.equal(h.run("teamDetailRead.status"),"ready");
});

test("summary busy retries stay bounded and never hide actual integrity failure",async()=>{
  for(const failure of ["busy","unavailable"]) {
    const h=coordinatedReads(),original=h.context.readFixture;let attempts=0;
    h.context.readFixture=async(url,options)=>{
      if(url.startsWith("/api/v1/team-summary")) {
        h.calls.push(url);attempts++;
        return {ok:false,status:503,json:async()=>({error:{code:failure === "busy" ? "TEAM_READ_IN_PROGRESS" : "TEAM_UNAVAILABLE"}})};
      }
      return original(url,options);
    };
    h.run("fetch=readFixture");
    const reading=h.run("refresh()");
    if(failure === "busy") for(const delay of [1000,2000,4000]) {
      for(let turn=0;turn<60 && ![...h.timers.values()].some(timer=>timer.delay === delay);turn++) await Promise.resolve();
      const timer=[...h.timers.values()].find(timer=>timer.delay === delay);assert.ok(timer);timer.fn();
    }
    await reading;
    assert.equal(attempts,failure === "busy" ? 4 : 1);
    assert.equal(h.run("teamReadIssue"),failure);
    assert.equal(h.run("canControlCurrentTeam()"),false);
  }
});

test("Project navigation during summary busy delay sends no stale retry GET",async()=>{
  const h=coordinatedReads(),original=h.context.readFixture;let attempts=0;
  h.run("mayCloseComposer=()=>true");
  h.context.readFixture=async(url,options)=>{
    if(url.startsWith("/api/v1/team-summary") && attempts++ === 0) {
      h.calls.push(url);return {ok:false,status:503,json:async()=>({error:{code:"TEAM_READ_IN_PROGRESS"}})};
    }
    return original(url,options);
  };
  h.run("fetch=readFixture");
  const reading=h.run("refresh()");
  for(let turn=0;turn<60 && ![...h.timers.values()].some(timer=>timer.delay === 1000);turn++) await Promise.resolve();
  const retry=[...h.timers.values()].find(timer=>timer.delay === 1000);assert.ok(retry);
  const navigation=h.run('refresh("project_next")');retry.fn();
  await Promise.all([reading,navigation]);
  const projects=h.calls.filter(url=>url.startsWith("/api/v1/team-summary"))
    .map(url=>new URL(url,"http://fixture").searchParams.get("project_id"));
  assert.deepEqual(projects,["project_current","project_next"]);
  assert.equal(h.run("currentProjectId()"),"project_next");
  assert.equal(h.run("teamReadWaiters.size"),0);
});

test("real refresh holds summary while selected body waits and automatically reads after publication",async()=>{
  const h=coordinatedReads();let release;
  h.state.holdSummary=new Promise(resolve=>release=resolve);
  const refresh=h.run("refresh()");await h.summaryStarted;
  const detail=h.run("readSelectedTeamDetail()");
  assert.equal(h.calls.filter(url=>url.startsWith("/api/v1/team-details")).length,0,
    "the page must not send its own selected body into its active summary worker");
  assert.ok(h.calls.includes("/api/v1/operations"),"auxiliary records remain independent");
  release();await Promise.all([refresh,detail]);
  assert.equal(h.run("teamReadIssue"),null);
  assert.equal(h.run("teamDetailRead.status"),"ready");
  assert.equal(h.calls.filter(url=>url.startsWith("/api/v1/team-details")).length,1);
});

test("real refresh waits for selected detail without blocking auxiliary records or replacing its owner",async()=>{
  const h=coordinatedReads();let release;
  h.state.holdDetail=new Promise(resolve=>release=resolve);
  const detail=h.run("readSelectedTeamDetail()");await h.detailStarted;
  const refresh=h.run("refresh()");
  for(let turn=0;turn<20;turn++) await Promise.resolve();
  assert.equal(h.calls.filter(url=>url.startsWith("/api/v1/team-summary")).length,0);
  assert.ok(h.calls.includes("/api/v1/operations"));
  release();await Promise.all([detail,refresh]);
  assert.equal(h.run("teamDetailRead.status"),"ready");
  assert.equal(h.calls.filter(url=>url.startsWith("/api/v1/team-summary")).length,1);
  assert.equal(h.calls.filter(url=>url.startsWith("/api/v1/team-details")).length,1);
});

test("a summary queued behind held detail skips its superseded Project before sending any GET",async()=>{
  const h=coordinatedReads();let release;
  h.state.holdDetail=new Promise(resolve=>release=resolve);
  h.run("mayCloseComposer=()=>true");
  const detail=h.run("readSelectedTeamDetail()");await h.detailStarted;
  const polling=h.run("refresh()");
  for(let turn=0;turn<30 && h.run("teamReadWaiters.size") !== 1;turn++) await Promise.resolve();
  assert.equal(h.run("teamReadWaiters.size"),1);
  const navigation=h.run('refresh("project_next")');
  for(let turn=0;turn<20;turn++) await Promise.resolve();
  assert.equal(h.calls.filter(url=>url.startsWith("/api/v1/team-summary")).length,0,
    "a browser abort alone must not retire a still-pending HTTP reader");
  release();await Promise.all([detail,polling,navigation]);
  const projects=h.calls.filter(url=>url.startsWith("/api/v1/team-summary"))
    .map(url=>new URL(url,"http://fixture").searchParams.get("project_id"));
  assert.deepEqual(projects,["project_next"]);
  assert.equal(h.run("currentProjectId()"),"project_next");
  assert.equal(h.run("teamReadWaiters.size"),0);
  assert.equal(h.run("teamReadFlight"),null);
  assert.equal(h.run("refreshing || refreshFlight !== null"),false);
});

test("external detail busy uses exactly three delayed retries then an explicit current-source retry",async()=>{
  const h=harness();
  for(let attempt=0;attempt<4;attempt++) h.replies.push({status:503,body:{error:{code:"TEAM_READ_IN_PROGRESS",message:"private secret"}}});
  const reading=h.run("readSelectedTeamDetail()");
  for(const [index,delay] of [1000,2000,4000].entries()) {
    for(let turn=0;turn<30 && ![...h.timers.values()].some(timer=>timer.delay === delay);turn++) await Promise.resolve();
    assert.equal(h.calls.length,index+1);
    assert.equal(h.run("teamDetailRead.status"),"waiting");
    assert.equal(h.run("teamDetailRead.issue"),"busy");
    assert.equal(h.run("productApprovalReadReady(item)"),false);
    const timer=[...h.timers.values()].find(timer=>timer.delay === delay);
    assert.ok(timer,"retry delay is bounded and observable");timer.fn();
  }
  await reading;
  assert.equal(h.calls.length,4);
  assert.equal(h.run("teamDetailRead.status"),"error");
  assert.equal(h.run("teamDetailRead.issue"),"busy");
  assert.equal(h.timers.size,0);
  h.replies.push({body:h.detail()});await h.run("retrySelectedTeamDetail()");
  assert.equal(h.calls.length,5);
  assert.equal(h.run("teamDetailRead.status"),"ready");
});

test("queued body readers detach on selection changes and only the latest owner sends a GET",async()=>{
  const h=coordinatedReads();let release;
  h.state.holdSummary=new Promise(resolve=>release=resolve);
  const refresh=h.run("refresh()");await h.summaryStarted;
  const pending=[];
  for(let revision=0;revision<20;revision++) {
    h.run('selected={kind:"request",id:item.id}');
    pending.push(h.run("readSelectedTeamDetail()"));
    for(let turn=0;turn<5;turn++) await Promise.resolve();
    assert.equal(h.run("teamReadWaiters.size"),1);
    h.run("selected=null;selectionIntentRevision++;clearTeamDetailRead()");
    for(let turn=0;turn<5;turn++) await Promise.resolve();
    assert.equal(h.run("teamReadWaiters.size"),0);
  }
  h.run('selected={kind:"request",id:item.id}');
  pending.push(h.run("readSelectedTeamDetail()"));
  release();await Promise.all([refresh,...pending]);
  assert.equal(h.run("teamDetailRead.status"),"ready");
  assert.equal(h.run("teamReadWaiters.size"),0);
  assert.equal(h.calls.filter(url=>url.startsWith("/api/v1/team-details")).length,1);
});

test("a publishing summary changes the queued locator before any old-source body GET",async()=>{
  const h=coordinatedReads();let release;
  h.state.holdSummary=new Promise(resolve=>release=resolve);
  const refresh=h.run("refresh()");await h.summaryStarted;
  const oldBody=h.run("readSelectedTeamDetail()");
  const current={...h.item,checkpoint_sha256:digest("f"),detail_source:{...h.item.detail_source,
    requirement_checkpoint_sha256:digest("f"),resource_checkpoint_sha256:digest("f")}};
  h.value.requests=[current];h.context.newItem=current;
  h.context.readFixture=async url=>{
    h.calls.push(url);
    const body={...h.detail(current),scope:current.detail_source,resource:{...h.detail(current).resource,
      checkpoint_sha256:current.checkpoint_sha256}};
    return {ok:true,status:200,json:async()=>body};
  };
  // Only replace the waiting body port; the already held summary owns its frozen response.
  h.run("fetch=readFixture");
  release();await Promise.all([refresh,oldBody]);
  await h.run("readSelectedTeamDetail()");
  const detailCalls=h.calls.filter(url=>url.startsWith("/api/v1/team-details"));
  assert.equal(detailCalls.length,1);
  assert.match(detailCalls[0],new RegExp("expected_requirement_checkpoint_sha256="+digest("f")));
  assert.equal(h.run("teamDetailRead.status"),"ready");
});

test("closing a body during external busy cancels its timer and never retries a stale selection",async()=>{
  const h=harness();h.replies.push({status:503,body:{error:{code:"TEAM_READ_IN_PROGRESS"}}});
  const reading=h.run("readSelectedTeamDetail()");
  for(let turn=0;turn<30 && h.run("teamDetailRead.status") !== "waiting";turn++) await Promise.resolve();
  assert.equal(h.run("teamDetailRead.status"),"waiting");
  h.run("selected=null;selectionIntentRevision++;clearTeamDetailRead()");await reading;
  assert.equal(h.timers.size,0);
  assert.equal(h.calls.length,1);
  assert.equal(h.run("teamDetailRead"),null);
});

test("busy retry stops at a genuine unavailable, changed or invalid body and never authorizes Product",async()=>{
  for(const failure of ["unavailable","changed","invalid"]) {
    const h=harness();h.replies.push({status:503,body:{error:{code:"TEAM_READ_IN_PROGRESS"}}});
    const body=h.detail();if(failure === "invalid") body.scope={...body.scope,team_id:"team_foreign"};
    h.replies.push(failure === "invalid" ? {body} : {status:failure === "changed" ? 409 : 503,
      body:{error:{code:"TEAM_UNAVAILABLE",message:"private provider details"}}});
    const reading=h.run("readSelectedTeamDetail()");
    for(let turn=0;turn<30 && ![...h.timers.values()].some(timer=>timer.delay === 1000);turn++) await Promise.resolve();
    [...h.timers.values()].find(timer=>timer.delay === 1000).fn();await reading;
    assert.equal(h.calls.length,2);
    assert.equal(h.run("teamDetailRead.status"),"error");
    assert.equal(h.run("teamDetailRead.issue"),failure === "changed" ? "changed" : "unavailable");
    assert.equal(h.run("productApprovalReadReady(item)"),false);
    assert.equal(h.timers.size,0);
    await h.run("readSelectedTeamDetail()");assert.equal(h.calls.length,2);
  }
});

// Exercise actual refresh -> metadata -> HTTP summary -> publication, not isolated decoder calls.
test("Console interruptions keep same-Team summaries readable but revoke all delivery writes",async()=>{
  for(const mode of ["normal","inspection"]) for(const failure of ["network",503,"json"]) {
    const h=coordinatedReads();
    Object.assign(h.state.manifest,{mode,delivery_ready:mode === "normal",supported_actions:["PRODUCT_APPROVAL"]});
    await h.run("refresh()");await h.run("teamDetailRead.promise");
    const previous=h.run("teamDetailRead.value");
    assert.equal(h.run("teamReadIssue"),null);
    assert.equal(h.run("canControlCurrentTeam()"),mode === "normal");
    h.state.consoleFailure=failure;
    await h.run("refresh()");
    assert.equal(h.run("teamReadIssue"),null,`${mode}: ${failure} must not reject valid summary`);
    assert.equal(h.run("consoleAvailable"),null);
    assert.equal(h.run("consoleTeamId"),"team_current","verified Team identity is retained only as a read scope");
    assert.equal(h.run("consoleDeliveryReady"),null);
    assert.equal(h.run("consoleSupportedActions"),null);
    assert.equal(h.run("canControlCurrentTeam()"),false);
    assert.equal(h.run("teamDetailRead.value"),previous,"complete same-source body remains readable");
    await h.run('submitOperation({action:"PRODUCT_APPROVAL",project_id:item.project_id,delivery_id:item.id,expected_checkpoint_sha256:item.checkpoint_sha256})');
    assert.equal(h.calls.filter(url=>url.startsWith("/api/v1/team-summary")).length,2);
    assert.equal(h.calls.filter(url=>url.startsWith("/api/v1/team?")).length,0);
    assert.equal(h.state.methods.includes("POST"),false);
    h.state.consoleFailure=null;
    await h.run("refresh()");
    assert.equal(h.run("teamReadIssue"),null);
    assert.equal(h.run("consoleConnectionFailed"),false);
    assert.equal(h.run("canControlCurrentTeam()"),mode === "normal");
  }
});

test("transient Console loss retains the negotiated bounded Operation protocol with no full-history fallback",async()=>{
  const h=coordinatedReads();h.state.manifest.operation_summary_contract_version="v0.1";
  await h.run("refresh()");await h.run("teamDetailRead.promise");
  h.state.consoleFailure=503;await h.run("refresh()");
  assert.equal(h.run("teamReadIssue"),null);
  assert.equal(h.run("operationsAvailable"),true);
  assert.equal(h.run("consoleOperationSummaryContractVersion"),"v0.1");
  assert.equal(h.calls.includes("/api/v1/operations"),false,"a metadata outage must not reload complete history");
  assert.ok(h.calls.filter(url=>url.startsWith("/api/v1/operation-summaries?")).length >= 2);
  assert.equal(h.run("canControlCurrentTeam()"),false);
});

test("initial Console failure cannot negotiate summary identity; confirmed 404 clears prior summary scope",async()=>{
  for(const initial of [true,false]) {
    const h=coordinatedReads();
    if(initial) h.run('snapshot=null;selected=null;consoleReadingIdentity=null;consoleTeamReadContractVersion=null;consoleTeamId=null');
    else {await h.run("refresh()");await h.run("teamDetailRead.promise");}
    h.calls.length=0;h.state.consoleFailure=initial ? 503 : 404;
    await h.run("refresh()");
    assert.equal(h.run("consoleReadingIdentity"),null);
    assert.equal(h.run("consoleTeamReadContractVersion"),null);
    assert.equal(h.calls.filter(url=>url.startsWith("/api/v1/team-summary")).length,0);
    assert.equal(h.calls.filter(url=>url.startsWith("/api/v1/team?") || url === "/api/v1/team").length,1,
      "retain the legacy read-only dashboard contract without inventing a summary identity");
    assert.equal(h.run("snapshot.schema_version"),"v0.2");
    assert.equal(h.run("teamDetailRead"),null);
    assert.equal(h.run("canControlCurrentTeam()"),false);
    h.context.unsolicited={...h.value,schema_version:"v0.1"};
    assert.throws(()=>h.run('verifiedTeamSummary(unsolicited,"project_current")'));
  }
});

test("read outage still rejects foreign Team or altered checkpoint and a new verified Team clears old bodies",async()=>{
  for(const invalid of ["team","checkpoint"]) {
    const h=coordinatedReads();await h.run("refresh()");await h.run("teamDetailRead.promise");
    const snapshot=structuredClone(h.value);
    h.state.consoleFailure=503;
    h.context.responseValue=structuredClone(h.value);
    if(invalid === "team") h.context.responseValue.team_id="team_other";
    else h.context.responseValue.requests[0].detail_source.resource_checkpoint_sha256=digest("f");
    h.context.originalRead=h.context.readFixture;
    h.run('fetch=async(url,options)=>url.startsWith("/api/v1/team-summary") ? {ok:true,status:200,json:async()=>responseValue} : originalRead(url,options)');
    await h.run("refresh()");
    assert.equal(h.run("teamReadIssue"),"unavailable",invalid);
    assert.equal(h.run("snapshot.team_id"),snapshot.team_id);
    assert.equal(h.run("snapshot.requests[0].checkpoint_sha256"),snapshot.requests[0].checkpoint_sha256);
    assert.equal(h.run("canControlCurrentTeam()"),false);
  }
  const h=coordinatedReads();await h.run("refresh()");await h.run("teamDetailRead.promise");
  h.state.consoleFailure=503;await h.run("refresh()");
  h.state.consoleFailure=null;h.state.manifest.team_id="team_other";
  await h.run("refresh()");
  assert.equal(h.run("teamReadIssue"),"unavailable","old Team summary cannot follow a newly negotiated Team");
  assert.equal(h.run("teamDetailRead"),null);
  assert.equal(h.run("consoleReadingIdentity.teamId"),"team_other");
  assert.equal(h.run("canControlCurrentTeam()"),false);
  h.value.team_id="team_other";h.item.detail_source.team_id="team_other";
  await h.run("refresh()");await h.run("teamDetailRead.promise");
  assert.equal(h.run("teamReadIssue"),null);
  assert.equal(h.run("snapshot.team_id"),"team_other");
});

test("successful protocol changes invalidate complete bodies; unsupported metadata cannot partially replace scope",async()=>{
  const h=coordinatedReads();await h.run("refresh()");await h.run("teamDetailRead.promise");
  const previous=h.run("consoleReadingIdentity");
  h.state.manifest={...h.state.manifest,team_id:"team_foreign",mode:"invalid"};
  await h.run("refresh()");
  assert.equal(h.run("consoleReadingIdentity"),previous,"invalid metadata is never a partial Team replacement");
  assert.equal(h.run("teamReadIssue"),null);
  assert.equal(h.run("canControlCurrentTeam()"),false);
  h.state.manifest={...h.state.manifest,team_id:"team_current",mode:"normal",team_read_contract_version:"v9"};
  await h.run("refresh()");
  assert.equal(h.run("consoleAvailable"),null);
  assert.equal(h.run("consoleTeamReadContractVersion"),"v0.1");
  assert.equal(h.calls.filter(url=>url.startsWith("/api/v1/team?")).length,0);
  delete h.state.manifest.team_read_contract_version;
  await h.run("refresh()");
  assert.equal(h.run("consoleTeamReadContractVersion"),null);
  assert.equal(h.run("teamDetailRead"),null);
  assert.equal(h.run("snapshot.schema_version"),"v0.2");
  h.state.manifest.team_read_contract_version="v0.1";
  await h.run("refresh()");await h.run("teamDetailRead.promise");
  assert.equal(h.run("teamReadIssue"),null);
  assert.equal(h.run("snapshot.schema_version"),"v0.1");
});

test("a late Console success, failure or 404 cannot replace newer verified metadata",async()=>{
  for(const status of [200,503,404]) for(const pause of ["headers","body"]) {
    const h=harness();let release,entered;
    const hold=new Promise(resolve=>release=resolve),started=new Promise(resolve=>entered=resolve);
    const info={schema_version:"v0.2",team_id:"team_old",delivery_ready:true,team_read_contract_version:"v0.1"};
    let calls=0;
    h.context.fetch=async()=>{
      calls++;
      if(calls === 1) {
        if(pause === "headers") {entered();await hold;}
        return {ok:status===200,status,json:async()=>{if(pause === "body") {entered();await hold;} return info;}};
      }
      return {ok:true,status:200,json:async()=>({...info,team_id:"team_new",mode:"inspection",delivery_ready:false})};
    };
    const old=h.run("refreshConsoleInfo()");
    if(pause === "body" && status !== 200) {await old;continue;}
    await started;await h.run("refreshConsoleInfo()");release();await old;
    assert.equal(h.run("consoleReadingIdentity.teamId"),"team_new");
    assert.equal(h.run("consoleTeamId"),"team_new");
    assert.equal(h.run("consoleAvailable"),true);
    assert.equal(h.run("consoleMode"),"inspection");
  }
});

test("Team publication cannot follow an old binding after independent metadata selects another Team",async()=>{
  const h=coordinatedReads();await h.run("refresh()");await h.run("teamDetailRead.promise");
  let release;h.state.holdSummary=new Promise(resolve=>release=resolve);
  const reading=h.run("refresh()");
  for(let i=0;i<30 && h.calls.filter(url=>url.startsWith("/api/v1/team-summary")).length<2;i++) await Promise.resolve();
  h.state.manifest.team_id="team_other";await h.run("refreshConsoleInfo()");
  release();await reading;
  assert.equal(h.run("snapshot.team_id"),"team_current");
  assert.equal(h.run("teamReadIssue"),"unavailable");
  assert.equal(h.run("teamDetailRead"),null);
  assert.equal(h.run("canControlCurrentTeam()"),false);
});

test("inspection banner distinguishes last confirmed mode from current connection and clears on 404",async()=>{
  const h=coordinatedReads();Object.assign(h.state.manifest,{mode:"inspection",delivery_ready:false});
  const nodes=new Map();
  const node=()=>({hidden:false,textContent:"",setAttribute(){},before(child){nodes.set(child.id,child);}});
  h.context.document={createElement:node,getElementById:id=>{
    if(id === "service-maintenance") return nodes.get(id) || null;
    if(!nodes.has(id)) nodes.set(id,node());return nodes.get(id);
  }};
  await h.run("refresh()");h.run("renderMaintenanceBanner()");
  assert.match(nodes.get("service-maintenance").textContent,/平台处于维护仅查看模式/);
  h.state.consoleFailure=503;await h.run("refresh()");h.run("renderMaintenanceBanner()");
  assert.equal(h.run("consoleMode"),null);
  assert.equal(nodes.get("service-maintenance").hidden,false);
  assert.match(nodes.get("service-maintenance").textContent,/上次确认.*当前连接尚未确认/);
  assert.match(h.run("deliveryControlUnavailableReason().reason"),/暂时无法连接/);
  h.state.consoleFailure=null;await h.run("refresh()");h.run("renderMaintenanceBanner()");
  assert.doesNotMatch(nodes.get("service-maintenance").textContent,/上次确认/);
  h.state.consoleFailure=404;await h.run("refresh()");h.run("renderMaintenanceBanner()");
  assert.equal(nodes.get("service-maintenance").hidden,true);
});
