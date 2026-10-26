"""Explicit opt-in real API verification. Not collected by unittest discovery."""
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from car_agent import CarAgent
from store import Store

root=Path(__file__).resolve().parents[1]
store=Store(root/'output'/'live-agent.db')
store.seed()
agent=CarAgent(store)
session=agent.create()
results=[]
messages=[
    ('clarification','我想买车。'),
    ('search','北京，预算十五万以内，想看卡罗拉，2020年以后，6万公里以内。'),
    ('comparison','对比V001和V002。'),
    ('proposal','帮我给V001建一个看车待办，称呼模拟买家，负责人模拟顾问。'),
]
for label,message in messages:
    session=agent.chat(session['id'],message)
    turn=session['turns'][-1]
    row={'check':label,'ok':turn['ok'],'tools':[(s['tool'],s['status']) for s in turn['trace']],'reply':turn['reply'],'usage':turn['usage']}
    results.append(row)
    print(json.dumps({k:row[k] for k in ('check','ok','tools')},ensure_ascii=False),flush=True)
    if not turn['ok']:break
if len(results)==4:
    assert session['state']['proposal'] and session['state']['proposal']['status']=='pending'
    assert not store.tasks(),'Proposal must not execute a task'
seller=agent.create()
seller=agent.chat(seller['id'],'我要卖车，北京，2022年卡罗拉，3.2万公里，期望售价12.6万。')
turn=seller['turns'][-1]
results.append({'check':'seller','ok':turn['ok'],'tools':[(s['tool'],s['status']) for s in turn['trace']],'reply':turn['reply'],'usage':turn['usage']})
print(json.dumps({k:results[-1][k] for k in ('check','ok','tools')},ensure_ascii=False),flush=True)
report={'provider':session['config'],'checks':results,'buyer_session':session['id'],'seller_session':seller['id'],'mutating_tasks_created':len(store.tasks())}
(root/'output'/'live-agent-smoke.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
assert len(results)==5 and all(r['ok'] for r in results)
assert session['matching'] and [m['id'] for m in session['matching']['result']['matches']]==['V001','V002']
assert seller['matching'] and len(seller['matching']['result']['matches'])>=1
assert any(s['tool']=='compare_vehicles' and s['status']=='ok' for t in session['turns'] for s in t['trace'])
print('Real API smoke passed; task proposals remained unexecuted.',flush=True)
