"use strict";
(() => {
  let trade="buy", record=null, history=[], matchBusy=false, catalog=[], textDirty=false;
  const comparing=new Set();
  const examples={buy:"我在北京，预算15万以内，想买丰田卡罗拉，2020年以后，6万公里以内。",sell:"卖车，北京，2022年丰田卡罗拉，3.2万公里，想卖12.6万。"};
  const defaults={buy:{city:"北京",preference:"卡罗拉",budget_min:0,budget_max:15,year_min:2020,mileage_max:6,nationwide:false},sell:{city:"北京",model:"卡罗拉",year:2022,mileage:3.2,price:12.6}};
  const ids={city:"match-city",preference:"match-preference",budget_min:"match-budget-min",budget_max:"match-budget-max",year_min:"match-year-min",mileage_max:"match-mileage-max",nationwide:"match-nationwide",model:"match-model",year:"match-year",mileage:"match-mileage",price:"match-price"};
  function renderCount() { $("#match-stock-count").textContent=trade==="buy"?`${catalog.filter(v=>v.status==="在售").length} 辆模拟在售车`:`${record?.result?.total_scanned ?? state.leads.length} 条已有咨询`; }
  function setValues(values) { for(const [key,id] of Object.entries(ids)) { if(!(key in values))continue;const node=$("#"+id);if(node.type==="checkbox")node.checked=!!values[key];else node.value=values[key] ?? "";} }
  function setTrade(next, reset=true) {
    trade=next;record=null;
    comparing.clear();renderCompareBar();
    document.querySelectorAll("[data-trade]").forEach(b=>{b.classList.toggle("active",b.dataset.trade===trade);b.setAttribute("aria-pressed",String(b.dataset.trade===trade));});
    $("#buy-fields").hidden=trade!=="buy";$("#sell-fields").hidden=trade!=="sell";
    document.querySelectorAll('#buy-fields input,#buy-fields select').forEach(n=>n.disabled=trade!=="buy");
    document.querySelectorAll('#sell-fields input,#sell-fields select').forEach(n=>n.disabled=trade!=="sell");
    $("#run-match").textContent=trade==="buy"?"匹配车源 →":"匹配买家 →";
    $("#match-caption").textContent=trade==="buy"?"只匹配在售且符合条件的模拟车源。":"匹配已有购车咨询；不提供估价或自动联系。";
    $("#match-result-title").textContent=trade==="buy"?"匹配车源":"潜在买家";
    renderCount();
    $("#parse-note").textContent="";
    if(reset) {setValues(defaults[trade]);$("#match-text").value=examples[trade];textDirty=false;renderEmpty();}
  }
  function renderEmpty() {
    comparing.clear();renderCompareBar();
    $("#match-result-summary").textContent="填写需求后开始匹配。";
    $("#match-results").innerHTML=`<div class="panel matching-empty"><span>⇄</span><h3>${trade==="buy"?"按需求筛选车辆":"为车辆寻找潜在买家"}</h3><p>${trade==="buy"?"城市、预算、车型、年限、里程。":"城市、车型、期望售价与买家需求。"}</p><button class="button outline" type="button" id="try-match">试试当前需求 →</button></div>`;
  }
  function lock(value) {matchBusy=value;document.querySelectorAll("#matching-form button,[data-trade],#match-history").forEach(n=>n.disabled=value);document.querySelectorAll('#matching-form input,#matching-form textarea,#matching-form select').forEach(n=>n.disabled=value || (!!n.closest('#buy-fields') && trade!=="buy") || (!!n.closest('#sell-fields') && trade!=="sell"));$("#run-match").textContent=value?"匹配中…":trade==="buy"?"匹配车源 →":"匹配买家 →";}
  function getQuery() {
    const q={direction:trade,text:$("#match-text").value};
    const fields=trade==="buy"?["city","preference","budget_min","budget_max","year_min","mileage_max","nationwide"]:["city","model","year","mileage","price"];
    for(const key of fields) {const n=$("#"+ids[key]);q[key]=n.type==="checkbox"?n.checked:n.value;}
    return q;
  }
  async function loadHistory() {
    const data=await api("/api/matching");history=data.history;catalog=data.inventory;state.tasks=data.tasks;
    window.renderMatchTasks?.();
    const selectedModel=$("#match-model").value;
    $("#match-model").innerHTML=data.models.map(m=>`<option>${esc(m)}</option>`).join("");if(data.models.includes(selectedModel))$("#match-model").value=selectedModel;
    renderCount();
    $("#match-history").innerHTML='<option value="">选择匹配记录</option>'+history.map(h=>`<option value="${h.id}">${date(h.at)} · ${h.direction==="buy"?"买车":"卖车"} · ${esc(h.result.query.city)} · ${h.result.matches.length}个结果</option>`).join("");
    if(record)$("#match-history").value=record.id;
  }
  async function parse() {
    if(matchBusy)return;lock(true);
    try {
      const p=await api("/api/matching/parse",{text:$("#match-text").value,direction:trade});
      const fields=trade==="buy"?["city","preference","budget_min","budget_max","year_min","mileage_max"]:["city","model","year","mileage","price"];
      setValues(Object.fromEntries(fields.map(k=>[k,p[k] ?? ""])));
      $("#parse-note").innerHTML=p.flags.length?`<div class="warning">${p.flags.map(esc).join("<br>")}</div>`:'<p class="microcopy">已填写，请核对条件。</p>';
      textDirty=false;
      return p;
    }catch(e){error(e);}finally{lock(false);}
  }
  async function runMatch() {
    if(matchBusy)return;
    if(textDirty) {
      const parsed=await parse();
      if(!parsed || parsed.flags.some(f=>/排除条件|方向不同|买卖混合/.test(f)))return;
    }
    lock(true);$("#global-status").innerHTML="";
    try {record=await api("/api/matching/run",getQuery());comparing.clear();renderCompareBar();renderResults();await loadHistory();}
    catch(e){error(e);}finally{lock(false);}
  }
  const carArt=(v)=>`<svg class="car-art" viewBox="0 0 300 100" aria-hidden="true"><ellipse cx="155" cy="82" rx="117" ry="7" fill="#dce4df"/><path d="M30 69L39 50Q44 44 69 41L101 17Q109 12 123 12H191Q204 13 219 36L256 46Q269 49 272 67L269 77H30Z" fill="${v.energy==="燃油"?"#b7c9c0":"#9dbdb8"}"/><path d="M82 39L108 20H147V39Z M155 20H187Q199 22 211 39H155Z" fill="#31594e"/><path d="M33 63H269M151 44V72" stroke="#92aea0" stroke-width="2"/><rect x="43" y="51" width="21" height="6" rx="2" fill="#f2edd7"/><rect x="252" y="53" width="12" height="6" rx="2" fill="#d79578"/><circle cx="83" cy="75" r="16" fill="#344d44"/><circle cx="83" cy="75" r="8" fill="#d7e0da"/><circle cx="228" cy="75" r="16" fill="#344d44"/><circle cx="228" cy="75" r="8" fill="#d7e0da"/></svg>`;
  function renderResults() {
    if(!record)return;const r=record.result;
    renderCount();
    $("#match-result-title").textContent=r.direction==="buy"?"匹配车源":"潜在买家";
    $("#match-result-summary").textContent=`找到 ${r.matches.length} 个结果 · ${r.order}`;
    let html=r.warnings.map(x=>`<div class="warning">${esc(x)}</div>`).join("");
    if(!r.matches.length) html+='<div class="panel matching-empty"><span>∅</span><h3>暂无符合条件的结果</h3><p>可修改条件再试；系统不会自动放宽预算或城市。</p></div>';
    else html+=`<div class="match-card-grid">${r.matches.map(m=>{
      const saved=record.shortlist.includes(m.id);
      const save=`<button class="button ${saved?"outline":"dark"}" type="button" data-shortlist="${esc(m.id)}" ${saved?"disabled":""}>${saved?"已保存 ✓":"保存匹配"}</button>`;
      const existing=(state.tasks || []).find(t=>t.run_id===record.id && t.candidate_id===m.id);
      const task=existing?`<button class="button outline" data-view="queue">查看待办</button>`:`<button class="button outline" data-create-task="${esc(m.id)}">${m.kind==="vehicle"?"看车待办":"跟进待办"}</button>`;
      if(m.kind==="vehicle") {const v=m.vehicle;return `<article class="panel vehicle-card"><div class="vehicle-visual"><span class="tag">${esc(v.city)} · ${esc(v.id)} · 模拟车源</span>${carArt(v)}</div><div class="vehicle-content"><div class="vehicle-name"><h3>${esc(v.brand)} ${esc(v.model)}</h3><strong>${v.price}<small> 万</small></strong></div><p class="vehicle-specs">${v.year}年上牌 · ${v.mileage}万公里 · ${esc(v.body)} · ${esc(v.energy)}</p><div class="match-reasons">${m.reasons.map(x=>`<span>✓ ${esc(x)}</span>`).join("")}</div><div class="match-card-bottom"><label class="compare-check"><input type="checkbox" data-compare="${v.id}" ${comparing.has(v.id)?"checked":""} aria-label="对比${v.id}">对比</label><div class="match-card-actions">${save}${task}</div></div></div></article>`;}
      const b=m.buyer,p=b.profile;return `<article class="panel buyer-match"><div class="buyer-match-top"><span class="avatar">${esc(b.name[0])}</span><div><h3>${esc(b.name)}</h3><p>${esc(b.channel)} · ${esc(STATUS[b.status])}</p></div>${badge(b.priority)}</div><blockquote>${esc(b.text)}</blockquote><p class="vehicle-specs">${esc(p.city)} · ${esc(budget(p))} · ${esc(p.vehicle || "车型未明确")}</p><div class="match-reasons">${m.reasons.map(x=>`<span>${x.includes("待确认")||x.includes("需确认")?"?":"✓"} ${esc(x)}</span>`).join("")}</div><div class="match-card-bottom"><button class="text-button teal" data-open="${esc(b.id)}">查看咨询 →</button><div class="match-card-actions">${save}${task}</div></div></article>`;
    }).join("")}</div>`;
    html+=`<details class="match-exclusions"><summary>查看未匹配项 · ${r.excluded.length}</summary><div>${r.excluded.map(e=>`<p><b>${esc(e.id)}</b> ${e.reasons.map(esc).join(" · ")}</p>`).join("")}</div></details>`;
    $("#match-results").innerHTML=html;
    renderCompareBar();
  }
  function renderCompareBar() {
    $("#compare-bar").hidden=comparing.size===0;
    $("#compare-bar").innerHTML=`<span>已选 ${comparing.size} 辆，最多3辆</span><div><button class="text-button" id="clear-compare">清空</button><button class="button dark" id="open-compare" ${comparing.size<2?"disabled":""}>对比车源 →</button></div>`;
  }
  $("#match-results").addEventListener("change",e=>{
    const input=e.target.closest("[data-compare]");if(!input)return;
    if(input.checked && comparing.size>=3){input.checked=false;toast("最多同时对比3辆车");return;}
    input.checked?comparing.add(input.dataset.compare):comparing.delete(input.dataset.compare);renderCompareBar();
  });
  $("#compare-bar").addEventListener("click",e=>{
    if(e.target.closest("#clear-compare")){comparing.clear();renderResults();return;}
    if(!e.target.closest("#open-compare") || !record)return;
    const vehicles=record.result.matches.filter(m=>comparing.has(m.id) && m.kind==="vehicle").map(m=>m.vehicle);
    if(vehicles.length<2)return;
    const specs=[["价格",v=>`${v.price}万`],["上牌年份",v=>`${v.year}年`],["里程",v=>`${v.mileage}万公里`],["城市",v=>v.city],["车身",v=>v.body],["能源",v=>v.energy]];
    $("#compare-content").innerHTML=`<div class="table-wrap"><table class="comparison-table"><thead><tr><th>项目</th>${vehicles.map(v=>`<th>${esc(v.brand)} ${esc(v.model)}<small>${v.id}</small></th>`).join("")}</tr></thead><tbody>${specs.map(([name,get])=>`<tr><th>${name}</th>${vehicles.map(v=>`<td>${esc(get(v))}</td>`).join("")}</tr>`).join("")}</tbody></table></div><p class="footnote">仅比较模拟车源数据；车况和实际可售状态需另行核实。</p>`;
    $("#compare-dialog").showModal();
  });
  document.querySelectorAll("[data-trade]").forEach(b=>b.addEventListener("click",()=>{if(!matchBusy)setTrade(b.dataset.trade);}));
  $("#parse-match").addEventListener("click",parse);
  $("#match-example").addEventListener("click",()=>{setTrade(trade);parse();});
  $("#matching-form").addEventListener("submit",e=>{e.preventDefault();runMatch();});
  $("#match-text").addEventListener("input",()=>{textDirty=true;record=null;renderEmpty();});
  for(const id of Object.values(ids))$("#"+id).addEventListener("input",()=>{textDirty=false;record=null;renderEmpty();});
  $("#match-results").addEventListener("click",async e=>{
    if(e.target.closest("#try-match"))return runMatch();
    const taskButton=e.target.closest("[data-create-task]");
    if(taskButton && record && !matchBusy){const candidate=record.result.matches.find(m=>m.id===taskButton.dataset.createTask);if(candidate)document.dispatchEvent(new CustomEvent("create-match-task",{detail:{runId:record.id,candidate}}));return;}
    const b=e.target.closest("[data-shortlist]");if(!b || !record || matchBusy)return;b.disabled=true;
    try{record=await api("/api/matching/shortlist",{id:record.id,candidate_id:b.dataset.shortlist});renderResults();await loadHistory();toast("匹配已保存");}catch(err){b.disabled=false;error(err);}
  });
  $("#match-history").addEventListener("change",e=>{const h=history.find(x=>x.id===e.target.value);if(!h)return;setTrade(h.direction,false);record=h;setValues(h.result.query);$("#match-text").value=h.result.query.text || "";renderResults();});
  document.addEventListener("match-tasks-changed",async()=>{try{await loadHistory();if(record){record=history.find(h=>h.id===record.id) || record;renderResults();}}catch(err){error(err);}});
  for(const id of ['match-budget-min','match-budget-max','match-price','match-mileage','match-mileage-max'])$("#"+id).step="any";
  setTrade("buy",false);
  loadHistory().catch(error);
})();
