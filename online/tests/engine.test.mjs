import test from 'node:test';
import assert from 'node:assert/strict';
import {execute,search,runTurn,route} from '../lib/car-engine.js';
const fresh=()=>({requirements:{},evidence:{},messages:[],turns:[],matching:null,proposal:null,tasks:[]});
const update=(state,field,value,evidence,current=evidence)=>{state.messages.push({role:'user',content:evidence});return execute('update_requirements',{changes:[{field,value,evidence}]},state,current,state.messages);};
test('search excludes sold and booked inventory and never widens conditions',()=>{
 assert.deepEqual(search({city:'北京',budget_max:15,preference:'卡罗拉'}).matches.map(v=>v.id),['V001','V002']);
 assert.equal(search({city:'北京',budget_max:11.5,preference:'卡罗拉',year_min:2021,mileage_max:4.5}).matches.length,0);
});
test('downpayment cannot become total budget; unsupported quote does not mutate',()=>{
 const s=fresh();assert.throws(()=>update(s,'budget_max',3,'首付3万'));assert.deepEqual(s.requirements,{});
 assert.throws(()=>update(s,'budget_max',15,'预算10万'));assert.deepEqual(s.requirements,{});
});
test('missing conditions ask rather than invent city or budget',()=>{
 const s=fresh();const r=execute('search_vehicles',{},s,'买车',[]);assert.ok(r.needs_clarification.includes('城市'));assert.equal(s.matching,null);assert.equal(route(s).action,'clarify');
});
test('old evidence cannot change an existing constraint; updates invalidate proposal',()=>{
 const s=fresh();update(s,'budget_max',15,'预算15万');s.messages.push({role:'user',content:'预算20万'});
 assert.throws(()=>execute('update_requirements',{changes:[{field:'budget_max',value:20,evidence:'预算20万'}]},s,'随便看看',s.messages));
 s.proposal={token:'old'};update(s,'budget_max',20,'预算20万');assert.equal(s.proposal,null);
});
test('comparison and proposal use only current query results, no task is created',()=>{
 const s=fresh();s.matching=search({city:'北京',budget_max:15,preference:'卡罗拉'});
 assert.throws(()=>execute('compare_vehicles',{ids:['V001','V015']},s,'',[]));
 execute('propose_task',{candidate_id:'V001',note:'模拟'},s,'',[]);assert.equal(s.proposal.status,'pending');assert.deepEqual(s.tasks,[]);
});
test('refusal clears recommendations and never calls model',async()=>{
 const s=fresh();s.matching=search({city:'北京',budget_max:15,preference:'卡罗拉'});
 const turn=await runTurn(s,'不要联系我',{},()=>assert.fail(),()=>assert.fail());assert.equal(turn.decision.action,'stop');assert.equal(s.matching,null);
});
test('model failure remains a failure',async()=>{
 const s=fresh();const t=await runTurn(s,'我要买车',{},()=>{},async()=>{throw Error('服务失败');});assert.equal(t.ok,false);assert.equal(t.decision.action,'failed');assert.deepEqual(s.tasks,[]);
});
test('model tool loop records actual queries and usage',async()=>{
 const s=fresh(),quote='我要买车，北京，预算15万以内，卡罗拉';let n=0;
 const responses=[{tool_calls:[{id:'a',function:{name:'update_requirements',arguments:JSON.stringify({changes:[{field:'direction',value:'buy',evidence:'买车'},{field:'city',value:'北京',evidence:'北京'},{field:'budget_max',value:15,evidence:'15万以内'},{field:'preference',value:'卡罗拉',evidence:'卡罗拉'}]})}}]}, {tool_calls:[{id:'b',function:{name:'search_vehicles',arguments:'{}'}}]}, {content:'找到V001、V002'}];
 const turn=await runTurn(s,quote,{},()=>{},async()=>({choices:[{message:responses[n++]}],usage:{prompt_tokens:1,completion_tokens:1}}));assert.equal(turn.ok,true);assert.equal(turn.decision.action,'match');assert.equal(turn.usage.input_tokens,3);assert.equal(turn.trace.length,2);
});
