"""Explicit real-API smoke test. Run against an isolated QA server, never unittest discovery."""
import json
import time
import urllib.request


BASE = 'http://127.0.0.1:8766'


def api(path, body=None):
    req = urllib.request.Request(BASE+path, data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None, headers={'Content-Type':'application/json'})
    return json.load(urllib.request.urlopen(req, timeout=15))


def wait(job):
    deadline = time.monotonic()+180
    while job['status'] in {'queued','running'}:
        if time.monotonic()>deadline:raise RuntimeError('QA job timeout')
        time.sleep(.25)
        job=api('/api/workflow/job/'+job['id'])
    assert job['status']=='completed',job['status']
    return job


if __name__=='__main__':
    items=[{'name':'模拟缺预算','channel':'API验收','text':'我要买车，北京，想看卡罗拉。'},
           {'name':'模拟卖车','channel':'API验收','text':'我要卖车，北京，2022年卡罗拉，3.2万公里，期望售价12.6万。'},
           {'name':'模拟拒绝','channel':'API验收','text':'我想买车，北京，15万以内，卡罗拉，不要联系我。'}]
    job=wait(api('/api/workflow/start',{'mode':'agent','items':items}))
    actions=[i['results']['agent']['action'] for i in job['items']]
    assert actions==['clarify','match','stop'],actions
    parent={'job_id':job['id'],'item_id':job['items'][0]['id']}
    follow=wait(api('/api/workflow/start',{'mode':'agent','parent':parent,'items':[dict(items[0],text='总预算15万以内。')]}))
    result=follow['items'][0]['results']['agent']
    assert result['action']=='match',result['action']
    assert result['ids']==['V001','V002'],result['ids']
    assert result['session_id']==job['items'][0]['results']['agent']['session_id']
    assert not api('/api/state')['tasks']
    with open('output/workflow-live-smoke.json','w',encoding='utf-8') as f:json.dump({'batch':job,'followup':follow},f,ensure_ascii=False,indent=2)
    print(json.dumps({'batch_actions':actions,'followup':result['action'],'matched':result['ids'],'same_session':True,'tasks':0},ensure_ascii=False))
