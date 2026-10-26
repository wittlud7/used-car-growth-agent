"use strict";
const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const STATUS = {new:"未分析", pending:"待人工审核", approved:"待联系", contacted:"已联系", appointment:"已预约", won:"已成交", lost:"未转化", rejected:"已驳回", failed:"运行失败"};
const PRIORITY = {A:"A · 优先跟进", B:"B · 待补充", C:"C · 低频培育", D:"D · 停止联系"};
const TIME = {"7d":"7天内", "30d":"30天内", "90d":"较远 / 不急", unknown:"待确认"};
const VIEW = {agent:["Agent 对话","买卖车 Agent","说出需求，让 Agent 查询、对比，再确认下一步。"],matching:["条件匹配","条件匹配","买车找车源，卖车找买家。"],work:["咨询管理","咨询管理","提取需求，审核跟进。"],queue:["跟进队列","跟进队列","登记联系、预约与成交结果。"],review:["复盘与评估","复盘与评估","来源统计与样例核验。"],about:["项目说明","项目说明",""]};
VIEW.workflow=["咨询自动处理","咨询自动处理","批量读需求，准备下一步，把例外交给人工。"];
let state = {leads:[],metrics:{channels:[],funnel:{}},config:{}}, selected=null, current=null, filter="all", view="agent", mode="rules", busy=false, evaluation=null, pendingAction=null, toastTimer;

async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:"POST", headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  let result;
  try { result = await response.json(); } catch { throw Error("服务返回异常，请检查本地服务是否运行"); }
  if (!response.ok) throw Error(result.error || "操作失败");
  return result;
}
function toast(text) { clearTimeout(toastTimer); $("#toast").textContent=text; $("#toast").hidden=false; toastTimer=setTimeout(()=>$("#toast").hidden=true,4200); }
function error(error) { const message=error?.message || String(error); $("#global-status").innerHTML=`<div class="error-status">${esc(message)}</div>`; toast(message); }
function setBusy(value, text="") { busy=value; $("#global-status").innerHTML=value?`<div class="busy-status"><span class="live-dot"></span>${esc(text)}</div>`:""; document.querySelectorAll("[data-mutation],#run-all,#import-open,#mode").forEach(b=>b.disabled=value); }
function badge(priority) { return `<span class="priority ${priority || "new"}">${esc(PRIORITY[priority] || "待分析")}</span>`; }
function date(value) { return new Intl.DateTimeFormat("zh-CN",{timeZone:"Asia/Shanghai",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}).format(new Date(value)); }
function successful(lead) { return lead.result?.decision; }
function budget(profile) { if(profile.budget_max===null) return "待确认"; if(profile.budget_min===0) return `${profile.budget_max}万以内`; return profile.budget_min===profile.budget_max?`${profile.budget_max}万`:`${profile.budget_min}–${profile.budget_max}万`; }

function showView(next) {
  view=next;
  document.querySelectorAll(".view").forEach(el=>el.hidden=el.id!==`view-${next}`);
  document.querySelectorAll(".nav").forEach(el=>el.classList.toggle("active",el.dataset.view===next));
  $("#breadcrumb").textContent=VIEW[next][0]; $("#page-title").textContent=VIEW[next][1]; $("#page-subtitle").textContent=VIEW[next][2];
  $("#import-open").hidden=["matching","about","agent","workflow"].includes(next);
  if(next==="queue") renderQueue(); if(next==="review") renderReview();
}

async function refresh() {
  state=await api("/api/state");
  if(!selected || !state.leads.some(x=>x.id===selected)) selected=state.leads[0]?.id || null;
  renderStats(); renderList(); renderQueue(); renderReview(); renderMode();
  if(selected) { current=await api(`/api/leads/${selected}`); renderDetail(); }
  else { current=null; $("#detail").innerHTML='<div class="empty-detail"><h2>从第一条咨询开始</h2><p>导入咨询后，就可以体验完整处理流程。</p></div>'; }
}

function renderMode() {
  $("#mode-caption").textContent=mode==="rules"?"规则基线":"模型 Agent";
  $("#mode-description").textContent=mode==="rules"?"无需密钥，可验证完整业务流程":state.config.llm_ready?`已配置 ${state.config.model} · 单条运行` : "尚未配置模型 API · 见项目说明与 README";
}

function renderStats() {
  const total=state.leads.length, analyzed=state.metrics.funnel.analyzed || 0, priority=state.leads.filter(l=>successful(l)?.priority==="A").length, pending=state.leads.filter(l=>l.status==="pending").length, approved=state.metrics.funnel.approved || 0;
  const items=[["收到的咨询",`${total}<small> 条</small>`,`${analyzed} 条已完成分析`,"↙"],["优先跟进",`${priority}<small> 条</small>`,"需求明确 · 等待人工判断","↗"],["待人工审核",`${pending}<small> 条</small>`,"草稿已准备，尚未对外发送","◷"],["已通过审核",`${approved}<small> 条</small>`,"按历史审核记录去重","✓"]];
  $("#stats").innerHTML=items.map(([label,value,caption,mark])=>`<article class="stat"><div class="stat-label">${label}</div><span class="stat-mark">${mark}</span><div class="stat-value">${value}</div><div class="stat-caption">${caption}</div></article>`).join("");
  $("#nav-count").textContent=total;
}

function visibleLeads() {
  const query=$("#search").value.trim().toLowerCase();
  return state.leads.filter(l=>(filter==="all" || l.status===filter || successful(l)?.priority===filter) && (!query || `${l.name} ${l.channel} ${l.text}`.toLowerCase().includes(query))).sort((a,b)=>{
    const rank=l=>({A:0,B:1,C:2,D:3}[successful(l)?.priority] ?? 4);
    return rank(a)-rank(b) || a.name.localeCompare(b.name,"zh-CN");
  });
}
function renderList() {
  const leads=visibleLeads(); $("#inbox-count").textContent=leads.length;
  $("#lead-list").innerHTML=leads.length?leads.map(l=>`<button class="lead-card ${selected===l.id?"selected":""}" data-select="${esc(l.id)}" aria-label="查看${esc(l.name)}的咨询" aria-pressed="${selected===l.id}"><div class="lead-top"><span class="avatar">${esc(l.name[0])}</span><span class="lead-name">${esc(l.name)}</span>${badge(successful(l)?.priority)}</div><p class="lead-quote">${esc(l.text)}</p><div class="lead-meta"><span>${esc(l.channel)}</span><span>·</span><span>${successful(l)?.city || esc(l.result?.profile?.city || "合成咨询")}</span><span class="status-text">${esc(STATUS[l.status])}</span></div></button>`).join(""):'<div class="empty-inline">没有符合条件的咨询<br>试试其他筛选条件。</div>';
}

async function selectLead(id) {
  selected=id; renderList();
  const lead=await api(`/api/leads/${id}`);
  if(selected!==id) return;
  current=lead; renderDetail();
}

function renderDetail() {
  const l=current; if(!l) return;
  let body="";
  const head=`<div class="detail-heading"><div><div class="detail-id">CONSULTATION / ${esc(l.id.slice(0,8).toUpperCase())}</div><div class="detail-person"><span class="avatar">${esc(l.name[0])}</span><div><h2>${esc(l.name)}</h2><p>${esc(l.channel)} · ${date(l.created_at)} · ${esc(STATUS[l.status])}</p></div></div></div><div class="detail-tools">${badge(successful(l)?.priority)}${l.status==="pending"?`<button class="text-button teal" data-mutation data-action="analyze" ${busy?"disabled":""}>${mode==="llm"?"用模型重跑 ↻":"重新分析 ↻"}</button>`:""}</div></div>`;
  const original=`<div class="section-label">咨询原文 <small>原始输入，保留以供核验</small></div><blockquote class="quote-block" style="margin:0">${esc(l.text)}</blockquote>`;
  if(!successful(l)) {
    body=original+`<div class="empty-detail"><div class="empty-symbol">⌁</div><h2>${l.status==="failed"?"这次处理未完成":"先读懂需求，再决定下一步。"}</h2><p>${l.status==="failed"?esc(l.result?.error || "运行失败，请重试"):"运行分析，查看信息提取、优先级和待审核草稿。"}</p><button class="button dark" data-mutation data-action="analyze" ${busy?"disabled":""}>${mode==="llm"?"运行模型 Agent":"运行规则分析"} →</button><p class="microcopy">${mode==="llm"?"调用配置的模型API，工具轨迹将逐步记录。":"当前为规则演示，不调用大模型。"}</p></div>`;
    if(l.result) body+=renderTrace(l.result);
  } else {
    const r=l.result,p=r.profile,d=r.decision;
    const facts=[["购车城市",p.city || "待确认"],["总购车预算",budget(p)],["购车时间",TIME[p.timeline]],["车型偏好",p.vehicle || "待确认"]];
    body=original+`<div class="section-label">需求画像 <small>${r.mode==="llm"?"模型提取 · 原文校验":"规则提取 · 可重复核验"}</small></div><div class="facts">${facts.map(([k,v])=>`<div class="fact ${v==="待确认"?"unknown":""}"><label>${k}</label><b>${esc(v)}</b></div>`).join("")}</div><div class="reason-box"><span class="reason-icon">↗</span><div><p>${esc(d.reason)}</p><small>规则分：${d.score} / 90 · 用于解释完整度，不代表成交概率</small></div></div>`;
    if(d.missing.length) body+=`<div class="missing"><span class="tag">待补充</span>${d.missing.map(x=>`<span class="tag">${esc(x)}</span>`).join("")}</div>`;
    if(d.flags.length) body+=`<div class="warning">${d.flags.map(esc).join("<br>")}</div>`;
    body+=`<div class="section-label">${d.stop_contact?"停止联系记录":"建议跟进草稿"}<small>${l.status==="pending"?"可修改 · 通过后进入待联系队列":"已保存 · 人工决定下一步"}</small></div><textarea class="draft-area" id="draft" aria-label="跟进草稿" maxlength="3000" rows="3" ${l.status!=="pending"?"readonly":""}>${esc(l.draft)}</textarea>`;
    if(l.status==="pending") {
      body+=`<div class="approval-row"><input id="owner" aria-label="跟进负责人" placeholder="填写跟进负责人" maxlength="40" value="${esc(l.owner)}"><div class="button-group"><button class="button outline" data-mutation data-action="rejected" ${busy?"disabled":""}>驳回归档</button>${!d.stop_contact?`<button class="button green" data-mutation data-action="approved" ${busy?"disabled":""}>通过审核 →</button>`:""}</div></div><p class="microcopy">通过审核仅建立本地待办。系统不会联系客户，实际沟通由负责人决定。</p>`;
    } else {
      body+=`<div class="lock-note">${esc(STATUS[l.status])} · 负责人：${esc(l.owner || "未分配")} ${l.status==="approved"?"· 待人工决定联系安排":""}</div>`;
      const actions={approved:[["contacted","登记已联系"]],contacted:[["appointment","登记预约"],["lost","登记未转化"]],appointment:[["won","登记成交"],["lost","登记未转化"]]}[l.status] || [];
      if(actions.length) body+=`<div class="approval-row"><span class="muted">记录实际进展</span><div class="button-group">${actions.map(([status,text])=>`<button class="button ${status==="lost"?"outline":"green"}" data-mutation data-action="${status}" ${busy?"disabled":""}>${text}</button>`).join("")}</div></div>`;
    }
    body+=`<details class="trace-details"><summary>原文证据 · ${p.evidence.length} 项</summary>${p.evidence.map(e=>`<div class="evidence-row"><b>${({city:"城市",budget:"预算",timeline:"时间",vehicle:"车型"})[e.field]}</b><q>${esc(e.quote)}</q> <span>字符 ${e.start}–${e.end}</span></div>`).join("") || '<p class="microcopy">原文未提取到可确认的信息。</p>'}</details>`;
    body+=renderTrace(r);
  }
  body+=renderHistory(l);
  $("#detail").innerHTML=head+`<div class="detail-content">${body}</div>`;
}

function renderTrace(r) {
  return `<details class="trace-details"><summary>处理轨迹 · ${r.mode==="llm"?"模型工具调用":"规则工作流"} · ${r.trace?.length || 0} 步</summary><p class="microcopy">${r.elapsed_ms ?? "—"} ms · 输入 ${r.usage?.input_tokens || 0} / 输出 ${r.usage?.output_tokens || 0} tokens · ${r.mode==="llm"?"实际API返回用量；未核算费用":"无模型调用成本"}</p><div class="trace-list">${(r.trace || []).map((t,i)=>`<div class="trace-item"><span>${String(i+1).padStart(2,"0")}</span><div><code class="${t.status==="error"?"error":""}">${esc(t.tool)} ${t.status==="ok"?"✓":"×"}</code><p>${esc(t.detail)}</p></div></div>`).join("")}</div></details>`;
}
function renderHistory(l) {
  return `<details class="trace-details"><summary>操作记录 · ${l.events?.length || 0} 条</summary><div class="trace-list">${(l.events || []).slice().reverse().map(e=>{let text=e.detail;try{const d=JSON.parse(e.detail);text=`${STATUS[d.from]} → ${STATUS[d.to]}${d.owner?` · ${d.owner}`:""}${d.note?`\n${d.note}`:""}${d.draft_edited?" · 已修改草稿":""}`;}catch{}return `<div class="trace-item"><span>·</span><div><code>${date(e.at)} · ${esc(({import:"导入",analysis:"分析完成",failure:"处理失败",human_review:"人工审核",human_outcome:"结果登记"})[e.kind] || e.kind)}</code><p>${esc(text)}</p></div></div>`;}).join("")}</div></details>`;
}

function renderQueue() {
  window.renderMatchTasks?.();
  const stages=[["待审核","pending"],["待联系","approved"],["跟进中",null],["已结束",null]];
  $("#queue-summary").innerHTML=stages.map(([label,status],i)=>{const n=state.leads.filter(l=>status?l.status===status:i===2?["contacted","appointment"].includes(l.status):["won","lost","rejected"].includes(l.status)).length;return `<div class="stage-card">${label}<b>${n}</b></div>`;}).join("");
  const leads=state.leads.filter(l=>successful(l));
  $("#queue-body").innerHTML=leads.map(l=>`<tr><td>${esc(l.name)}<small>${esc(l.channel)}</small></td><td>${badge(l.result.decision.priority)}</td><td>${esc(l.owner || "待分配")}</td><td>${esc(STATUS[l.status])}</td><td><button class="text-button teal" data-open="${l.id}">查看处理 →</button></td></tr>`).join("") || '<tr><td colspan="5">还没有待办，先在工作台分析咨询。</td></tr>';
}
function renderReview() {
  const funnel=state.metrics.funnel;
  const stages=[["total","收到咨询"],["analyzed","完成分析"],["approved","审核通过"],["contacted","已联系"],["appointment","已预约"],["won","已成交"]];
  $("#funnel").innerHTML=stages.map(([key,label],i)=>`<div class="funnel-cell"><span>${String(i+1).padStart(2,"0")} / ${label}</span><b>${funnel[key] || 0}</b><div class="funnel-bar"><i style="width:${funnel.total?Math.round((funnel[key] || 0)/funnel.total*100):0}%"></i></div></div>`).join("");
  $("#channels").innerHTML=state.metrics.channels.map(c=>`<tr><td>${esc(c.channel)}</td>${["total","analyzed","approved","contacted","appointment","won"].map(k=>`<td>${c[k]}</td>`).join("")}</tr>`).join("");
  if(evaluation) renderEvaluation();
}
function renderEvaluation() {
  const e=evaluation;
  $("#evaluation").innerHTML=`<div class="evaluation-stats"><div class="evaluation-stat"><b>${e.passed_cases}<small> / ${e.sample_count}</small></b><span>案例全部字段符合预期</span></div><div class="evaluation-stat"><b>${e.correct_fields}<small> / ${e.total_fields}</small></b><span>分级、城市、预算、时间</span></div><div class="evaluation-stat"><b>${e.supported_evidence}<small> / ${e.total_evidence}</small></b><span>引文可定位到原文</span></div><div class="evaluation-stat"><b>${e.elapsed_ms}<small> ms</small></b><span>本轮规则总耗时 · 非人工提效</span></div></div><div class="evaluation-notice">${e.limitations.map(esc).join("<br>")}</div><div class="table-wrap"><table><thead><tr><th>样例</th><th>预期分级</th><th>实际分级</th><th>四字段核验</th><th>原文</th></tr></thead><tbody>${e.cases.map(c=>`<tr><td>${c.id}</td><td>${badge(c.expected.priority)}</td><td>${badge(c.actual.priority)}</td><td class="${c.pass?"pass":"fail"}">${c.pass?"4 / 4 通过":Object.entries(c.checks).filter(([,v])=>!v).map(([k])=>esc(k)).join("、")+"不符"}</td><td style="white-space:normal;min-width:260px;max-width:420px;line-height:1.8">${esc(c.text)}</td></tr>`).join("")}</tbody></table></div>`;
}

async function run(ids, runMode) {
  if(busy) return;
  if(runMode==="llm" && !state.config.llm_ready) return error(Error("模型API尚未配置；先用规则演示，配置方法见 README。"));
  setBusy(true,runMode==="llm"?"模型正在调用工具处理当前咨询，请稍候。":"正在提取需求、应用规则并生成待审核草稿…");
  try {
    const result=await api("/api/analyze",{ids,mode:runMode});
    await refresh();
    const failures=result.results.filter(x=>x.error || x.status==="failed");
    if(failures.length) error(Error(`${failures.length} 条处理未完成。${failures[0].error || "查看线索详情中的错误和轨迹。"}`));
    else toast(`${result.results.length} 条咨询已处理，草稿等待人工审核`);
  } catch(e) { error(e); }
  finally { busy=false; document.querySelectorAll("[data-mutation],#run-all,#import-open,#mode").forEach(b=>b.disabled=false); if(!$("#global-status .error-status")) $("#global-status").innerHTML=""; }
}

async function transition(status, note="") {
  if(busy) return;
  const item=pendingAction || current;
  const payload={id:item.id,status,version:item.version,note};
  if(status==="approved") { payload.owner=$("#owner").value; payload.draft=$("#draft").value; }
  setBusy(true,"正在保存人工审核与跟进记录…");
  try { await api("/api/transition",payload); $("#outcome-dialog").close(); pendingAction=null; await refresh(); toast("记录已保存；未发送任何客户消息"); }
  catch(e) {error(e);}
  finally {busy=false;document.querySelectorAll("[data-mutation],#run-all,#import-open,#mode").forEach(b=>b.disabled=false);if(!$("#global-status .error-status")) $("#global-status").innerHTML="";}
}

document.addEventListener("click",async event=>{
  const button=event.target.closest("button"); if(!button) return;
  try {
    if(button.dataset.view) showView(button.dataset.view);
    if(button.dataset.select) await selectLead(button.dataset.select);
    if(button.dataset.open) {showView("work");await selectLead(button.dataset.open);$("#detail").scrollIntoView({behavior:"smooth",block:"start"});}
    if(button.dataset.filter) {filter=button.dataset.filter;document.querySelectorAll(".filter").forEach(b=>b.classList.toggle("active",b===button));renderList();}
    if(button.dataset.close) $("#"+button.dataset.close).close();
    if(button.dataset.action) {
      if(busy) return;
      if(button.dataset.action==="analyze") return run([current.id],mode);
      if(button.dataset.action==="approved") return transition("approved");
      pendingAction={id:current.id,version:current.version,status:button.dataset.action};
      $("#outcome-title").textContent=({rejected:"驳回并归档",contacted:"登记已联系",appointment:"登记预约",won:"登记成交",lost:"登记未转化"})[pendingAction.status];
      $("#outcome-note").value="";$("#outcome-dialog").showModal();
    }
  }catch(e){error(e);}
});
$("#search").addEventListener("input",renderList);
$("#mode").addEventListener("change",e=>{mode=e.target.value;renderMode();renderDetail();});
$("#run-all").addEventListener("click",()=>{const ids=visibleLeads().filter(l=>["new","failed"].includes(l.status)).map(l=>l.id);if(!ids.length)return toast("当前筛选下没有未分析线索。请选中单条查看或重试。");if(mode==="llm")return toast("模型模式请选中单条线索运行，便于查看调用与用量。");run(ids,"rules");});
$("#import-open").addEventListener("click",()=>$("#import-dialog").showModal());
$("#import-form").addEventListener("submit",async e=>{e.preventDefault();await importItems([{name:$("#import-name").value,channel:$("#import-channel").value,text:$("#import-text").value}]);});
async function importItems(items) {
  if(busy) return;
  setBusy(true,"正在导入咨询并检查重复内容…");
  try {const r=await api("/api/import",{items});selected=r.ids[0];$("#import-dialog").close();$("#import-form").reset();filter="all";$("#search").value="";document.querySelectorAll(".filter").forEach(b=>b.classList.toggle("active",b.dataset.filter==="all"));showView("work");await refresh();toast(`新增 ${r.added} 条，跳过 ${r.duplicates} 条重复咨询`);}catch(e){error(e);}finally{busy=false;document.querySelectorAll("[data-mutation],#run-all,#import-open,#mode").forEach(b=>b.disabled=false);if(!$("#global-status .error-status"))$("#global-status").innerHTML="";}
}
function parseCsv(text) {
  const rows=[];let row=[],cell="",quoted=false;
  for(let i=0;i<text.length;i++){const c=text[i];if(c==='"'){if(quoted && text[i+1]==='"'){cell+='"';i++;}else quoted=!quoted;}else if(c===","&&!quoted){row.push(cell);cell="";}else if((c==="\n"||c==="\r")&&!quoted){if(c==="\r"&&text[i+1]==="\n")i++;row.push(cell);if(row.some(x=>x.trim()))rows.push(row);row=[];cell="";}else cell+=c;}
  if(quoted) throw Error("CSV引号未闭合");row.push(cell);if(row.some(x=>x.trim()))rows.push(row);
  const header=(rows.shift() || []).map(x=>x.trim());if(!["name","channel","text"].every(k=>header.includes(k)))throw Error("CSV须含name、channel、text三列");
  return rows.map(r=>Object.fromEntries(header.map((h,i)=>[h,r[i] || ""])));
}
$("#import-file").addEventListener("change",async e=>{const f=e.target.files[0];if(!f)return;try{if(f.size>500000)throw Error("文件超过500KB");const text=(await f.text()).replace(/^\uFEFF/,"");const items=f.name.toLowerCase().endsWith(".json")?JSON.parse(text):parseCsv(text);await importItems(items);}catch(err){error(err);}finally{e.target.value="";}});
$("#outcome-form").addEventListener("submit",e=>{e.preventDefault();transition(pendingAction.status,$("#outcome-note").value);});
$("#outcome-dialog").addEventListener("close",()=>{pendingAction=null;});
$("#evaluate").addEventListener("click",async()=>{const b=$("#evaluate");b.disabled=true;b.textContent="正在核验…";try{evaluation=await api("/api/evaluation");renderEvaluation();toast("评估完成，可逐条检查结果与限制");}catch(e){error(e);}finally{b.disabled=false;b.textContent="重新运行评估 ↗";}});
$("#export").addEventListener("click",async()=>{try{const data=await api("/api/export");const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:"application/json"}));const a=document.createElement("a");a.href=url;a.download="intent-studio-records.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),2000);}catch(e){error(e);}});
refresh().catch(error);
