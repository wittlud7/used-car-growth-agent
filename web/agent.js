"use strict";
(() => {
  let session=null,waiting=false,timer=null,started=0;
  const names={read_requirements:"读取已有条件",list_models:"查询车型目录",update_requirements:"更新需求条件",search_vehicles:"查询在售车源",find_buyers:"查询潜在买家",compare_vehicles:"对比车辆",propose_task:"生成待办确认卡"};
  const labels={direction:"方向",city:"城市",budget_min:"预算下限",budget_max:"预算上限",preference:"车型偏好",year_min:"最早上牌",mileage_max:"最高里程",nationwide:"异地",model:"车型",year:"上牌年份",mileage:"行驶里程",price:"期望售价"};
  const inline=text=>esc(text).replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/`([^`]+)`/g,'<code>$1</code>');
  function content(text) {
    const lines=String(text).split('\n'),parts=[];
    const cells=line=>line.trim().replace(/^\|/,'').replace(/\|$/,'').split('|').map(s=>s.trim());
    for(let i=0;i<lines.length;i++) {
      if(lines[i].includes('|') && i+1<lines.length && lines[i+1].includes('-') && !lines[i+1].replace(/[|:\-\s]/g,'')) {
        const headers=cells(lines[i]),rows=[];
        i+=2;
        while(i<lines.length && lines[i].includes('|')) {rows.push(cells(lines[i]));i++;}
        i--;
        parts.push(`<div class="agent-table-wrap"><table><thead><tr>${headers.map(h=>`<th>${inline(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${headers.map((_,j)=>`<td>${inline(row[j] || '')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`);
      } else parts.push(inline(lines[i]));
    }
    return parts.join('\n');
  }
  const remember=id=>{try{localStorage.setItem('intent-agent-session',id);}catch{}};
  function lock(value) {
    waiting=value;$("#agent-working").hidden=!value;
    document.querySelectorAll('#agent-chat-form button,#agent-chat-form textarea,#agent-new,#agent-history,[data-agent-prompt]').forEach(n=>n.disabled=value);
    if(value){started=Date.now();$("#agent-seconds").textContent='';timer=setInterval(()=>{$('#agent-seconds').textContent=Math.floor((Date.now()-started)/1000)+'s';},1000);}
    else {clearInterval(timer);timer=null;}
  }
  async function history() {
    const data=await api('/api/agent');
    $("#agent-history").innerHTML=data.sessions.map(s=>`<option value="${s.id}">${esc(s.title)}</option>`).join('');
    if(session)$("#agent-history").value=session.id;
  }
  async function newSession() {session=await api('/api/agent/new',{});remember(session.id);await history();render();}
  function render() {
    if(!session)return;
    const cfg=session.config;
    $("#agent-model-status").textContent=cfg.ready?`${cfg.provider==='deepseek'?'DeepSeek':cfg.provider} · ${cfg.model} · 工具调用`:'模型未配置';
    const turns=session.turns;
    $("#agent-starters").hidden=turns.length>0;
    $("#agent-messages").innerHTML=turns.length?turns.map(t=>`<div class="agent-user"><span>你</span><p>${esc(t.user)}</p></div><div class="agent-answer ${t.ok?'':'agent-failed'}"><div class="agent-answer-label"><span class="agent-symbol">✧</span><b>行意 Agent</b>${t.ok?'':'<small>本轮未完成</small>'}</div><div class="agent-answer-text">${content(t.reply)}</div><div class="agent-turn-meta">${(t.elapsed_ms/1000).toFixed(1)}s · 输入 ${t.usage.input_tokens} / 输出 ${t.usage.output_tokens} tokens</div>${t.trace.length?`<details class="agent-trace"><summary>工具记录 · ${t.trace.length} 次</summary>${t.trace.map((s,i)=>`<div class="agent-tool-step"><span class="${s.status==='ok'?'pass':'fail'}">${s.status==='ok'?'✓':'×'}</span><div><b>${esc(names[s.tool] || s.tool)}</b><small>${s.elapsed_ms}ms</small><details><summary>参数与结果</summary><pre>${esc(JSON.stringify({arguments:s.arguments,result:s.result},null,2))}</pre></details></div></div>`).join('')}</details>`:''}</div>`).join(''):'<div class="agent-welcome"><span>✧</span><h2>买车，还是卖车？</h2><p>买车说城市、预算和偏好。<br>卖车说车型、年限、里程和期望售价。</p></div>';
    const entries=Object.entries(session.state.requirements);
    $("#agent-requirements").innerHTML=entries.length?entries.map(([k,v])=>{let value=v;if(k==='direction')value=v==='buy'?'买车':'卖车';if(k==='nationwide')value=v?'接受异地':'同城';if(['budget_min','budget_max','price'].includes(k))value+='万';if(['mileage','mileage_max'].includes(k))value+='万公里';return `<div title="${esc(session.state.evidence[k] || '')}"><span>${labels[k] || esc(k)}</span><b>${esc(value)}</b></div>`;}).join(''):'<p class="agent-side-empty">还没有已确认条件。</p>';
    const record=session.matching;
    const matches=record?.result.matches || [];
    $("#agent-results-title").textContent=record?`${record.direction==='buy'?'车源':'潜在买家'} · ${matches.length}`:'查询结果';
    $("#agent-compare").hidden=!(record?.direction==='buy' && matches.length>=2);
    $("#agent-results").innerHTML=record?matches.length?matches.map(m=>m.kind==='vehicle'?`<article class="agent-result-card"><div><b>${esc(m.vehicle.brand)} ${esc(m.vehicle.model)}</b><strong>${m.vehicle.price}万</strong></div><p>${m.id} · ${m.vehicle.city} · ${m.vehicle.year}年 · ${m.vehicle.mileage}万公里</p><div class="agent-result-tags">${m.reasons.map(x=>`<span>${esc(x)}</span>`).join('')}</div><button class="text-button teal" data-agent-candidate="${m.id}">生成看车待办 →</button></article>`:`<article class="agent-result-card"><div><b>${esc(m.buyer.name)}</b>${badge(m.buyer.priority)}</div><p>${esc(m.buyer.profile.city)} · ${esc(budget(m.buyer.profile))}</p><div class="agent-result-tags">${m.reasons.map(x=>`<span>${esc(x)}</span>`).join('')}</div><button class="text-button teal" data-agent-candidate="${m.id}">生成跟进待办 →</button></article>`).join(''):'<p class="agent-side-empty">没有符合当前条件的结果。可在对话中说明愿意调整哪些条件。</p>':'<p class="agent-side-empty">Agent 查询后，结果会出现在这里。</p>';
    const p=session.state.proposal;
    $("#agent-proposal").innerHTML=p?`<section class="panel agent-proposal-card"><div class="panel-heading"><h2>待办确认卡</h2><span class="tag">${p.status==='confirmed'?'已建立':'待确认'}</span></div><div class="agent-proposal-content"><b>${p.candidate.kind==='vehicle'?esc(p.candidate.vehicle.brand+' '+p.candidate.vehicle.model):esc(p.candidate.buyer.name)}</b><p>${esc(p.note || '请核对客户、负责人和期望时间。')}</p>${p.status==='confirmed'?'<button class="button outline" data-view="queue">查看待办</button>':'<button class="button dark" id="agent-confirm-proposal">核对并确认 →</button>'}</div></section>`:'';
    $("#agent-messages").scrollTop=$("#agent-messages").scrollHeight;
  }
  async function send(text) {
    if(waiting || !text.trim())return;
    if(!session)return toast('对话正在初始化，请稍候。');
    lock(true);$("#agent-input").value='';
    const pending=document.createElement('div');pending.className='agent-user';pending.innerHTML=`<span>你</span><p>${esc(text)}</p>`;$("#agent-messages").append(pending);$('#agent-messages').scrollTop=$('#agent-messages').scrollHeight;
    try{session=await api('/api/agent/chat',{session_id:session.id,message:text});remember(session.id);await history();render();}
    catch(e){pending.remove();$("#agent-input").value=text;error(e);}finally{lock(false);}
  }
  $("#agent-chat-form").addEventListener('submit',e=>{e.preventDefault();send($("#agent-input").value);});
  $("#agent-input").addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();$('#agent-chat-form').requestSubmit();}});
  $("#agent-new").addEventListener('click',async()=>{if(waiting)return;lock(true);try{await newSession();}catch(e){error(e);}finally{lock(false);}});
  $("#agent-history").addEventListener('change',async e=>{if(waiting)return;lock(true);try{session=await api('/api/agent/session/'+e.target.value);remember(session.id);render();}catch(err){error(err);}finally{lock(false);}});
  $("#agent-starters").addEventListener('click',e=>{const b=e.target.closest('[data-agent-prompt]');if(b)send(b.dataset.agentPrompt);});
  $("#agent-compare").addEventListener('click',()=>{const m=session.matching.result.matches;send(`请对比${m[0].id}和${m[1].id}。`);});
  $("#agent-results").addEventListener('click',e=>{const b=e.target.closest('[data-agent-candidate]');if(!b)return;send(`请为编号${b.dataset.agentCandidate}生成一个${session.matching.direction==='buy'?'看车':'买家跟进'}待办确认卡。`);});
  $("#agent-proposal").addEventListener('click',e=>{if(!e.target.closest('#agent-confirm-proposal') || waiting)return;const p=session.state.proposal;if(!p || p.status!=='pending')return;document.dispatchEvent(new CustomEvent('create-match-task',{detail:{runId:p.run_id,candidate:p.candidate,prefill:p,agentProposal:{session_id:session.id,token:p.token}}}));});
  document.addEventListener('agent-session-updated',e=>{if(e.detail.id===session?.id){session=e.detail;render();}});
  document.addEventListener('open-agent-session',async e=>{if(waiting)return toast('请等待当前对话完成');lock(true);try{session=await api('/api/agent/session/'+e.detail);remember(session.id);await history();render();showView('agent');}catch(err){error(err);}finally{lock(false);}});
  async function init(){lock(true);try{const data=await api('/api/agent');let remembered='';try{remembered=localStorage.getItem('intent-agent-session') || '';}catch{}const id=data.sessions.find(s=>s.id===remembered)?.id || data.sessions[0]?.id;if(id){session=await api('/api/agent/session/'+id);await history();render();}else await newSession();}catch(e){error(e);$('#agent-model-status').textContent='Agent 服务未就绪';}finally{lock(false);}}
  init();
})();
