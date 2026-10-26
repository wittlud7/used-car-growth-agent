"use strict";
(() => {
  const actions={match:'可匹配',clarify:'需追问',no_match:'暂无匹配',review:'人工复核',stop:'停止跟进',nurture:'暂缓跟进',failed:'处理失败'};
  const modes={agent:'Agent＋业务校验',direct:'直接问模型',rules:'规则演练'};
  const outcomes={reviewed:'已核查',contacted:'已联系',appointment:'已预约',won:'已成交',lost:'未转化',stop:'停止跟进'};
  let job=null,jobs=[],examples=[],running=false,submitting=false,filter='all',timer=null,selectedItem=null,imported=null;
  const fmt=ms=>`${(ms/1000).toFixed(1)}s`;
  function controls(){document.querySelectorAll('#wf-start,#wf-benchmark,#wf-inbox,#wf-inbox-form button[type=submit],#wf-follow-form button[type=submit]').forEach(b=>b.disabled=running||submitting);$('#wf-model-note').textContent=running?'批次后台处理中，刷新页面可恢复':$('#wf-mode').value==='rules'?'本地规则演练，不调用模型':'使用本地 DeepSeek 配置，逐条调用模型';}
  async function load(id){
    const data=await api('/api/workflow');jobs=data.jobs;examples=data.examples;
    running=jobs.some(j=>['queued','running'].includes(j.status));controls();
    $('#wf-history').innerHTML=jobs.length?jobs.map(j=>`<option value="${j.id}">${date(j.at)} · ${j.kind==='benchmark'?'对照实验':modes[j.mode]} · ${j.summary.done}/${j.summary.total}</option>`).join(''):'<option value="">暂无批次</option>';
    let remembered='';try{remembered=localStorage.getItem('intent-workflow-job')||'';}catch{}
    const target=id||job?.id||jobs.find(j=>j.id===remembered)?.id||jobs[0]?.id;
    if(target && jobs.some(j=>j.id===target)){
      job=await api('/api/workflow/job/'+target);$('#wf-history').value=job.id;
      try{localStorage.setItem('intent-workflow-job',job.id);}catch{}
      render();
    }
    clearTimeout(timer);if(running)timer=setTimeout(()=>load().catch(e=>{error(e);$('#wf-job-status').textContent='读取失败，请点击刷新';}),1500);
  }
  function render(){
    if(!job)return;
    const s=job.summary,batch=job.kind==='batch',results=job.items.flatMap(i=>Object.values(i.results));
    const counts=Object.fromEntries(Object.keys(actions).map(a=>[a,results.filter(r=>r.action===a).length]));
    $('#wf-job-status').textContent=`${({queued:'等待处理',running:'后台处理中',completed:'已完成',interrupted:'已中断',cancelled:'已停止'})[job.status]} · ${s.done}/${s.total}`;
    $('#wf-cancel').hidden=!['queued','running'].includes(job.status);
    const cards=batch?[['已处理',`${s.done}/${s.total}`],['可匹配',counts.match],['需追问 / 无匹配',counts.clarify+counts.no_match],['人工复核 / 失败',counts.review+counts.failed],['停止 / 暂缓',counts.stop+counts.nurture]]:[['已完成案例',`${s.done}/${s.total}`],['直接模型通过',`${s.groups.direct?.passed||0}/${s.groups.direct?.count||0}`],['Agent方案通过',`${s.groups.agent?.passed||0}/${s.groups.agent?.count||0}`],['两组错误推荐',Object.values(s.groups).reduce((n,g)=>n+g.unsafe_ids,0)],['两组失败',Object.values(s.groups).reduce((n,g)=>n+g.failed,0)]];
    $('#wf-summary').innerHTML=cards.map(([a,b])=>`<div class="panel"><span>${a}</span><b>${b}</b></div>`).join('');
    const groups=Object.entries(s.groups);
    $('#wf-comparison').innerHTML=!batch?`<section class="panel wf-report"><div class="panel-heading"><h2>实测对照结果</h2><span class="tag">${esc(job.model)}</span></div><div class="table-wrap"><table><thead><tr><th>方案</th><th>案例通过</th><th>分流正确</th><th>错误推荐数</th><th>遗漏候选数</th><th>失败数</th><th>平均耗时</th><th>输入 / 输出 tokens</th></tr></thead><tbody>${groups.map(([m,g])=>`<tr><td>${modes[m]}</td><td>${g.passed}/${g.count}</td><td>${g.action_correct}/${g.count}</td><td>${g.unsafe_ids}</td><td>${g.missed_ids}</td><td>${g.failed}</td><td>${fmt(g.elapsed_ms/g.count)}</td><td>${g.input_tokens} / ${g.output_tokens}</td></tr>`).join('')}</tbody></table></div><p class="muted wf-padding">通过＝分流及候选集合均符合人工标注。错误推荐＝标注允许集合之外的编号。耗时为各条串行处理实测；没有同场人工计时，不计算节省比例。Agent方案包含程序校验，部分拦截不调用模型。小样本允许两组都通过，不能据此推断线上收益。</p></section>`:`<div class="wf-batch-note">${groups.map(([m,g])=>`${modes[m]} · ${g.count}条 · 平均${fmt(g.elapsed_ms/g.count)} · ${g.input_tokens+g.output_tokens} tokens · 需复核或失败 ${g.manual}/${g.count}`).map(esc).join('')}<br>所有下一步均是本地建议。${job.parent?'本批次保留了上一批次的原始需求和补充记录。':''} ${job.feedback.length}条人工结果记录${job.feedback.some(f=>f.seconds)?` · 实测人工处理共 ${job.feedback.reduce((n,f)=>n+(f.seconds||0),0).toFixed(1)}s`:''}</div>`;
    $('#wf-filters').innerHTML=[['all','全部'],...Object.entries(actions)].map(([a,n])=>`<button class="filter ${filter===a?'active':''}" data-wf-filter="${a}">${n}${a==='all'?'':` ${counts[a]}`}</button>`).join('');
    const visible=job.items.filter(i=>filter==='all'||Object.values(i.results).some(r=>r.action===filter));
    $('#wf-results').innerHTML=visible.length?visible.map(i=>`<article class="panel wf-item"><div class="wf-item-head"><div><b>${esc(i.name)}</b><span>${esc(i.channel)}${i.case_id?' · '+i.case_id:''}</span></div><span class="tag">${i.status==='done'?'已处理':i.status==='running'?'处理中':i.status==='interrupted'?'已中断':'等待处理'}</span></div><blockquote>${esc(i.text)}</blockquote>${i.error?`<p class="wf-padding">${esc(i.error)}</p>`:''}${i.expected?`<p class="wf-gold">人工标注：${actions[i.expected.action]} · ${i.expected.ids.join('、')||'无候选'}</p>`:''}<div class="wf-decisions ${batch?'':'wf-two'}">${Object.entries(i.results).map(([m,r])=>`<section><div class="wf-decision-title"><span>${modes[m]}</span><b class="wf-action ${r.action}">${actions[r.action]}</b>${r.score?`<span class="${r.score.passed?'wf-pass':'wf-fail'}">${r.score.passed?'通过':'未通过'}</span>`:''}</div><p>${esc(r.reason||r.reply)}</p>${r.reason&&r.reply!==r.reason?`<details><summary>查看对话回复</summary><p>${esc(r.reply)}</p></details>`:''}${r.ids.length?`<div class="wf-candidates">${r.ids.map(id=>{const c=r.candidates.find(c=>c.id===id);return `<span>${esc(id)}${c?.vehicle?' · '+esc(c.vehicle.model)+' · '+c.vehicle.price+'万':''}${c?.buyer?' · '+esc(c.buyer.name):''}</span>`;}).join('')}</div>`:''}<small>${fmt(r.elapsed_ms)} · ${r.usage.input_tokens} / ${r.usage.output_tokens} tokens</small><details class="wf-trace"><summary>处理路径 · ${r.trace.length}步</summary><ol>${r.trace.map(t=>`<li><b>${esc(t.step)}</b><span>${esc(t.detail)}</span></li>`).join('')}</ol><pre>${esc(JSON.stringify({requirements:r.requirements,evidence:r.evidence||{},score:r.score},null,2))}</pre></details>${batch?`<div class="wf-actions">${r.session_id?`<button class="text-button teal" data-wf-session="${r.session_id}">打开对话与工具记录 →</button>`:''}${!['stop','nurture'].includes(r.action)?`<button class="text-button" data-wf-follow="${i.id}" ${running?'disabled':''}>补充需求 / 重新匹配</button>`:''}<button class="text-button" data-wf-feedback="${i.id}">登记人工结果</button></div>`:''}</section>`).join('')}</div>${batch?job.feedback.filter(f=>f.item_id===i.id).map(f=>`<p class="wf-feedback">${date(f.at)} · ${esc(f.owner)} · ${outcomes[f.outcome]}：${esc(f.note)}${f.seconds?' · 实测'+f.seconds+'s':''}</p>`).join(''):''}</article>`).join(''):'<div class="panel empty-inline">暂无这类处理结果。</div>';
  }
  async function start(body,benchmark=false){
    if(running||submitting)return;submitting=true;controls();
    $('#wf-job-status').textContent='正在提交…';
    try{job=await api(benchmark?'/api/workflow/benchmark':'/api/workflow/start',body);filter='all';await load(job.id);toast('已提交，逐条处理结果会自动更新');}
    catch(e){error(e);}finally{submitting=false;controls();}
  }
  $('#wf-start').addEventListener('click',()=>{
    const lines=$('#wf-input').value.split('\n').map(t=>t.trim()).filter(Boolean);
    const items=imported||lines.map((text,i)=>({name:'咨询'+(i+1),channel:'手动录入',text}));
    start({items,mode:$('#wf-mode').value});
  });
  $('#wf-input').addEventListener('input',()=>imported=null);
  $('#wf-mode').addEventListener('change',controls);
  $('#wf-examples').addEventListener('click',()=>{imported=examples;$('#wf-input').value=examples.map(c=>c.text).join('\n');});
  $('#wf-benchmark').addEventListener('click',()=>start({},true));
  $('#wf-refresh').addEventListener('click',()=>load().catch(error));
  $('#wf-cancel').addEventListener('click',async()=>{try{const r=await api('/api/workflow/cancel',{job_id:job.id});toast(r.message);}catch(e){error(e);}});
  $('#wf-history').addEventListener('change',e=>{filter='all';load(e.target.value).catch(error);});
  $('#wf-filters').addEventListener('click',e=>{const b=e.target.closest('[data-wf-filter]');if(b){filter=b.dataset.wfFilter;render();}});
  $('#wf-results').addEventListener('click',e=>{
    const b=e.target.closest('button');if(!b)return;
    if(b.dataset.wfSession)document.dispatchEvent(new CustomEvent('open-agent-session',{detail:b.dataset.wfSession}));
    if(b.dataset.wfFollow){selectedItem=job.items.find(i=>i.id===b.dataset.wfFollow);$('#wf-follow-text').value='';$('#wf-follow-dialog').showModal();}
    if(b.dataset.wfFeedback){selectedItem=job.items.find(i=>i.id===b.dataset.wfFeedback);$('#wf-feedback-form').reset();const stop=selectedItem.results[job.mode].action==='stop';Array.from($('#wf-outcome').options).forEach(o=>o.disabled=stop&&!['reviewed','stop'].includes(o.value));$('#wf-feedback-dialog').showModal();}
  });
  $('#wf-follow-form').addEventListener('submit',async e=>{e.preventDefault();const source=selectedItem,parent={job_id:job.id,item_id:source.id};await start({mode:job.mode,parent,items:[{name:source.name,channel:source.channel,text:$('#wf-follow-text').value}]});if(job?.parent?.job_id===parent.job_id)$('#wf-follow-dialog').close();});
  $('#wf-feedback-form').addEventListener('submit',async e=>{e.preventDefault();const b=e.submitter;b.disabled=true;try{job=await api('/api/workflow/feedback',{job_id:job.id,item_id:selectedItem.id,owner:$('#wf-owner').value,outcome:$('#wf-outcome').value,note:$('#wf-note').value,seconds:$('#wf-seconds').value?Number($('#wf-seconds').value):null});render();$('#wf-feedback-dialog').close();}catch(err){error(err);}finally{b.disabled=false;}});
  $('#wf-inbox').addEventListener('click',async()=>{try{const data=await api('/api/state');$('#wf-inbox-list').innerHTML=data.leads.map(l=>`<label class="wf-inbox-row"><input type="checkbox" name="lead" value="${l.id}"><span><b>${esc(l.name)}</b> · ${esc(l.channel)}<small>${esc(l.text)}</small></span></label>`).join('');$('#wf-inbox-dialog').showModal();}catch(e){error(e);}});
  $('#wf-inbox-form').addEventListener('submit',async e=>{e.preventDefault();const ids=Array.from(document.querySelectorAll('#wf-inbox-list input:checked')).map(n=>n.value);if(!ids.length||ids.length>20)return toast('请选择1至20条咨询');$('#wf-inbox-dialog').close();await start({ids,mode:$('#wf-mode').value});});
  $('#wf-file').addEventListener('change',async e=>{try{const f=e.target.files[0];if(!f)return;if(f.size>500000)throw Error('文件超过500KB');const raw=(await f.text()).replace(/^\uFEFF/,'');const items=f.name.endsWith('.json')?JSON.parse(raw):parseCsv(raw);if(!Array.isArray(items)||!items.length||items.length>20||items.some(i=>!i||!['name','channel','text'].every(k=>typeof i[k]==='string')))throw Error('需1至20条，字段为name、channel、text');imported=items;$('#wf-input').value=items.map(i=>i.text).join('\n');toast('已载入，点击开始处理');}catch(err){error(err);}finally{e.target.value='';}});
  $('#wf-export').addEventListener('click',()=>{if(!job)return toast('请先选择批次');const url=URL.createObjectURL(new Blob([JSON.stringify(job,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`workflow-${job.id.slice(0,8)}.json`;a.click();URL.revokeObjectURL(url);});
  load().catch(error);
})();
