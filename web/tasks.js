"use strict";
const MATCH_TASK_STATUS={pending:"待确认",confirmed:"已确认",completed:"已完成",cancelled:"已取消"};
(() => {
  let creating=null,updating=null,saving=false;
  for(const id of ['match-task-form','task-update-form']) {const p=document.createElement('p');p.className='task-form-error';p.setAttribute('role','alert');$('#'+id).insertBefore(p,$('#'+id+' .dialog-actions'));}
  const taskTitle=t=>t.direction==="buy"?"看车待办":"买家跟进";
  function vehicleLabel(t) {const q=t.snapshot.query,c=t.snapshot.candidate;return t.direction==="buy"?`${c.vehicle.brand} ${c.vehicle.model} · ${c.vehicle.price}万 · ${c.vehicle.city}`:`${q.model} · 期望${q.price}万 · ${q.city}`;}
  window.renderMatchTasks=()=>{
    const tasks=state.tasks || [];
    $("#match-task-count").textContent=tasks.length;
    $("#match-task-body").innerHTML=tasks.map(t=>{
      let actions="";
      const buyer=state.leads.find(l=>l.id===t.lead_id),needReview=t.direction==="sell" && !["approved","contacted","appointment"].includes(buyer?.status);
      if(t.status==="pending") {
        if(needReview)actions+=`<button class="text-button teal" data-open="${esc(t.lead_id)}">审核咨询 →</button>`;
        else actions+=`<button class="text-button teal" data-task-state="confirmed" data-task-id="${t.id}">确认待办</button>`;
      }
      if(t.status==="confirmed")actions+=`<button class="text-button teal" data-task-state="completed" data-task-id="${t.id}">${t.direction==="buy"?"登记看车完成":"登记已联系"}</button>`;
      if(["pending","confirmed"].includes(t.status))actions+=`<button class="text-button" data-task-state="cancelled" data-task-id="${t.id}">取消</button>`;
      return `<tr data-task-row="${t.id}"><td><b>${taskTitle(t)} · ${esc(t.customer)}</b><small>${esc(vehicleLabel(t))}</small><details class="task-log"><summary>记录 · ${t.events.length}</summary>${t.note?`<p>备注：${esc(t.note)}</p>`:""}${t.events.map(e=>`<p>${date(e.at)} · ${MATCH_TASK_STATUS[e.status]}<br>${esc(e.note)}</p>`).join("")}</details></td><td>${esc(t.owner)}</td><td>${t.preferred_at?date(t.preferred_at):"待协商"}</td><td><span class="task-status ${t.status}">${MATCH_TASK_STATUS[t.status]}</span></td><td><div class="task-row-actions">${actions || '<span class="muted">已归档</span>'}</div></td></tr>`;
    }).join("") || '<tr><td colspan="5">暂无待办，可从匹配结果中建立。</td></tr>';
  };
  document.addEventListener("create-match-task",e=>{
    if(saving)return;
    creating=e.detail;
    const c=creating.candidate,isBuy=c.kind==="vehicle";
    $("#match-task-title").textContent=isBuy?"建立看车待办":"建立买家跟进待办";
    $("#match-task-context").textContent=isBuy?`${c.vehicle.brand} ${c.vehicle.model} · ${c.vehicle.price}万 · ${c.vehicle.city}`:`${c.buyer.name} · ${c.buyer.profile.city} · ${budget(c.buyer.profile)}`;
    $("#task-customer").value=isBuy?(creating.prefill?.customer || ""):c.buyer.name;$("#task-customer").readOnly=!isBuy;
    $("#task-owner").value=creating.prefill?.owner || "";$("#task-time").value=(creating.prefill?.preferred_at || "").slice(0,16);$("#task-note").value=creating.prefill?.note || "";
    $("#match-task-form .task-form-error").textContent="";
    $("#match-task-dialog").showModal();
  });
  $("#match-task-form").addEventListener("submit",async e=>{
    e.preventDefault();if(saving || !creating)return;saving=true;const button=e.submitter;button.disabled=true;
    try {
      const fields={customer:$("#task-customer").value,owner:$("#task-owner").value,preferred_at:$("#task-time").value,note:$("#task-note").value};
      if(creating.agentProposal){const r=await api("/api/agent/confirm",{...creating.agentProposal,...fields});document.dispatchEvent(new CustomEvent("agent-session-updated",{detail:r.session}));}
      else await api("/api/tasks/create",{run_id:creating.runId,candidate_id:creating.candidate.id,...fields});
      $("#match-task-dialog").close();await refresh();document.dispatchEvent(new Event("match-tasks-changed"));toast("待办已建立，等待人工确认");
    }catch(err){$("#match-task-form .task-form-error").textContent=err.message;error(err);}finally{saving=false;button.disabled=false;}
  });
  document.addEventListener("click",e=>{
    const b=e.target.closest("[data-task-state]");if(!b || saving)return;
    const task=(state.tasks || []).find(t=>t.id===b.dataset.taskId);if(!task)return;
    updating={id:task.id,version:task.version,status:b.dataset.taskState};
    $("#task-update-title").textContent=updating.status==="confirmed"?"确认待办":updating.status==="cancelled"?"取消待办":task.direction==="buy"?"登记看车完成":"登记已联系";
    $("#task-update-context").textContent=`${task.customer} · ${vehicleLabel(task)}`;
    $("#task-update-note").value="";$("#task-update-dialog").showModal();
    $("#task-update-form .task-form-error").textContent="";
  });
  $("#task-update-form").addEventListener("submit",async e=>{
    e.preventDefault();if(saving || !updating)return;saving=true;const button=e.submitter;button.disabled=true;
    try{await api("/api/tasks/update",{...updating,note:$("#task-update-note").value});$("#task-update-dialog").close();await refresh();document.dispatchEvent(new Event("match-tasks-changed"));toast("待办记录已保存");}catch(err){$("#task-update-form .task-form-error").textContent=err.message;error(err);}finally{saving=false;button.disabled=false;}
  });
  $("#match-task-dialog").addEventListener("close",()=>{creating=null;});
  $("#task-update-dialog").addEventListener("close",()=>{updating=null;});
  window.renderMatchTasks();
})();
