"""Local built Worker HTTP verification; starts no real model calls."""
import http.cookiejar,json,urllib.request,urllib.error
BASE='http://127.0.0.1:8770'
def client():return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
def req(c,path,body=None,headers=None):
    r=urllib.request.Request(BASE+path,data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None,headers={'Content-Type':'application/json',**(headers or {})})
    try:
        with c.open(r,timeout=15) as response:return response.status,json.load(response)
    except urllib.error.HTTPError as e:
        raw=e.read().decode()
        try:return e.code,json.loads(raw)
        except json.JSONDecodeError:raise RuntimeError(f'Non-JSON HTTP {e.code}: {raw[:800]}')
if __name__=='__main__':
    a,b=client(),client()
    status,s=req(a,'/api/session/new',{});assert status==200,s
    assert req(b,'/api/session/'+s['id'])[0]==404
    assert req(b,'/api/sessions')[1]==[]
    status,stopped=req(a,'/api/chat',{'session_id':s['id'],'message':'不要联系我'});assert status==200,stopped
    assert stopped['turns'][-1]['decision']['action']=='stop'
    assert 'messages' not in stopped
    assert req(a,'/api/chat',{'session_id':s['id'],'message':'hello'},{'Origin':'https://other.example'})[0]==403
    assert req(a,'/api/task/confirm',{'session_id':s['id'],'token':'fake','owner':'x'})[0]==400
    assert req(a,'/api/session/'+s['id'])[1]['turns'][-1]['user']=='不要联系我'
    print('Built Worker: visitor isolation, persisted session, stop guard, CSRF, fake confirmation and private message filtering passed.')
