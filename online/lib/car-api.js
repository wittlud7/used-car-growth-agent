import { runTurn, INVENTORY } from './car-engine.js';
import benchmark from './benchmark.json' with {type:'json'};

const json=(value,status=200,extra={})=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff',...extra}});
const hash=async text=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text)))).map(x=>x.toString(16).padStart(2,'0')).join('');
export function publicSession(row){const s=JSON.parse(row.payload);return {id:row.id,title:row.title,version:row.version,requirements:s.requirements,evidence:s.evidence,turns:s.turns,matching:s.matching,proposal:s.proposal,tasks:s.tasks};}
async function quota(db,id,limit){const row=await db.prepare('INSERT INTO car_quota(id,count) VALUES(?,1) ON CONFLICT(id) DO UPDATE SET count=count+1 WHERE count < ? RETURNING count').bind(id,limit).first();if(!row)throw Error('今日演示调用额度已用完，请明天再试或下载源码本地运行');}
export async function carApi(request,env){
  const url=new URL(request.url),path=url.pathname;
  if(request.method==='GET'&&path==='/api/benchmark')return json(benchmark);
  if(request.method==='GET'&&path==='/api/config')return json({ready:!!env.DEEPSEEK_API_KEY,model:env.DEEPSEEK_MODEL||'deepseek-v4-flash',synthetic:true,per_visitor_daily_limit:20,global_daily_limit:120});
  if(!env.DB)return json({error:'数据库尚未就绪'},503);
  const old=request.headers.get('Cookie')?.match(/(?:^|;\s*)intent_visitor=([a-f0-9-]{36})(?:;|$)/)?.[1],cookie=old||crypto.randomUUID();
  const identity=request.headers.get('oai-authenticated-user-id')||cookie;
  const owner=await hash((env.SESSION_SECRET||'')+'|'+identity),ip=await hash((env.SESSION_SECRET||'')+'|'+(request.headers.get('CF-Connecting-IP')||'local-preview'));
  const headers=old?{}:{'Set-Cookie':`intent_visitor=${cookie}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000${url.protocol==='https:'?'; Secure':''}`};
  const day=new Date().toISOString().slice(0,10);
  const send=(v,s=200)=>json(v,s,headers);
  try{
    if(request.method==='GET'&&path==='/api/sessions'){
      const rows=await env.DB.prepare('SELECT id,title,updated FROM car_sessions WHERE owner=? ORDER BY updated DESC LIMIT 20').bind(owner).all();return send(rows.results);
    }
    if(request.method==='GET'&&path.startsWith('/api/session/')){
      const row=await env.DB.prepare('SELECT * FROM car_sessions WHERE id=? AND owner=?').bind(path.split('/').pop(),owner).first();if(!row)return send({error:'对话不存在或不属于当前访客'},404);return send(publicSession(row));
    }
    if(request.method!=='POST')return send({error:'接口不存在'},404);
    const raw=await request.text();
    if(request.headers.get('Origin')&&request.headers.get('Origin')!==url.origin)return send({error:'不接受跨站写入'},403);
    if(new TextEncoder().encode(raw).length>12000)return send({error:'请求过大'},413);const body=JSON.parse(raw);
    if(!body||typeof body!=='object'||Array.isArray(body))throw Error('请求须为JSON对象');
    if(path==='/api/session/new'){
      await quota(env.DB,day+':create:'+ip,60);
      const id=crypto.randomUUID(),payload={requirements:{},evidence:{},messages:[],turns:[],matching:null,proposal:null,tasks:[]};
      await env.DB.prepare('INSERT INTO car_sessions(id,owner,title,payload,version,busy,updated) VALUES(?,?,?,?,0,0,?)').bind(id,owner,'新对话',JSON.stringify(payload),Date.now()).run();return send({id,title:'新对话',...payload,messages:undefined,version:0});
    }
    if(!['/api/chat','/api/task/confirm'].includes(path))return send({error:'接口不存在'},404);
    const row=await env.DB.prepare('SELECT * FROM car_sessions WHERE id=? AND owner=?').bind(body.session_id,owner).first();if(!row)return send({error:'对话不存在或不属于当前访客'},404);
    if(path==='/api/chat'&&(typeof body.message!=='string'||!body.message.trim()||body.message.length>4000))throw Error('消息须为1至4000字');
    if(path==='/api/chat'&&env.DEEPSEEK_API_KEY&&body.message.includes(env.DEEPSEEK_API_KEY))throw Error('请勿将API密钥输入对话');
    const state=JSON.parse(row.payload);if(state.turns.length>=30&&path==='/api/chat')throw Error('本段对话已达30轮，请新建');
    const locked=await env.DB.prepare('UPDATE car_sessions SET busy=? WHERE id=? AND owner=? AND version=? AND busy<? RETURNING id').bind(Date.now()+250000,row.id,owner,row.version,Date.now()).first();
    if(!locked)return send({error:'对话正在处理，请稍后再试'},409);
    try{
      if(path==='/api/chat'){
        await runTurn(state,body.message.trim(),env,async()=>{await quota(env.DB,day+':visitor:'+ip,20);await quota(env.DB,day+':global',120);});
      }else{
        const p=state.proposal;if(!p||body.token!==p.token)throw Error('确认卡已失效，请重新生成');
        if(p.status!=='confirmed'){
          if(typeof body.owner!=='string'||!body.owner.trim()||body.owner.length>40)throw Error('请填写1至40字负责人');
          if(p.candidate.kind==='vehicle'&&!INVENTORY.some(v=>v.id===p.candidate.id&&v.status==='在售'))throw Error('车源已不在售');
          if(p.candidate.kind==='buyer'&&body.reviewed!==true)throw Error('请先勾选已人工核查买家意愿与需求');
          const task={id:crypto.randomUUID(),candidate:p.candidate,owner:body.owner.trim(),at:new Date().toISOString(),status:'pending',note:p.note};state.tasks.push(task);p.status='confirmed';p.task_id=task.id;
        }
      }
      const title=state.turns[0]?.user.slice(0,28)||row.title;
      await env.DB.prepare('UPDATE car_sessions SET payload=?,title=?,version=version+1,busy=0,updated=? WHERE id=? AND owner=? AND version=?').bind(JSON.stringify(state),title,Date.now(),row.id,owner,row.version).run();
      return send(publicSession({...row,title,payload:JSON.stringify(state),version:row.version+1}));
    }finally{await env.DB.prepare('UPDATE car_sessions SET busy=0 WHERE id=? AND owner=? AND version=?').bind(row.id,owner,row.version).run();}
  }catch(e){return send({error:e.message||'操作未完成'},400);}
}
