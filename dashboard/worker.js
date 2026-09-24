const json = (data, status=200) => Response.json(data, {status, headers:{'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}});
const now = () => Math.floor(Date.now()/1000);
async function authorized(req, secret) {
  if (!secret) return false;
  const candidate = req.headers.get('Authorization') || '';
  const digest = async v => new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(v)));
  const [a,b] = await Promise.all([digest(candidate),digest('Bearer '+secret)]);
  return a.reduce((v,x,i)=>v|(x^b[i]),0)===0;
}
export default {
 async fetch(req, env) {
  const url = new URL(req.url), path=url.pathname, time=now();
  if (!path.startsWith('/api/')) return env.ASSETS.fetch(req);
  try {
   const admin=await authorized(req,env.ADMIN_TOKEN), device=await authorized(req,env.DEVICE_TOKEN);
   if (req.method==='GET' && path==='/api/status') {
    const stations=await env.DB.prepare("SELECT s.*,COALESCE(l.location,'1850 Gateway Drive') AS location FROM stations s LEFT JOIN station_locations l ON l.id=s.id ORDER BY s.id").all();
    const d=await env.DB.prepare('SELECT * FROM device WHERE id=1').first();
    const result={time,location:'1850 Gateway Drive',stations:stations.results.filter(s=>s.location==='1850 Gateway Drive'),other_locations:[{name:'Redwood City - CN37-12',address:'1250 Veterans Boulevard, Redwood City',stations:stations.results.filter(s=>s.location==='Redwood City - CN37-12')}],device:d?{checked:d.checked,...JSON.parse(d.data)}:null,admin};
    result.sessions=(await env.DB.prepare(admin?'SELECT * FROM sessions ORDER BY updated DESC LIMIT 100':"SELECT * FROM sessions WHERE state!='ended' ORDER BY updated DESC LIMIT 100").all()).results.map(s=>{
     const data=JSON.parse(s.data);
     return admin?{...s,data}:{station:s.station,started:s.started,updated:s.updated,state:s.state,kwh:s.kwh,data:{station_candidate:data.station_candidate,kw:data.kw,elapsed:data.elapsed,start_is_observation:data.start_is_observation}};
    });
    result.statistics=(await env.DB.prepare("SELECT station,COUNT(*) AS sessions,SUM(CASE WHEN kwh<1 THEN 1 ELSE 0 END) AS low_delivery,ROUND(SUM(kwh),2) AS kwh,MAX(CASE WHEN kwh>0 THEN started END) AS last_energy,MAX(CASE WHEN kwh>=1 THEN started END) AS last_success FROM (SELECT DISTINCT station,started,kwh FROM sessions WHERE state='ended' AND station IS NOT NULL) GROUP BY station").all()).results;
    result.usage=(await env.DB.prepare("SELECT station,MIN(time) AS first_observed,SUM(CASE WHEN json_extract(data,'$.status') IN ('In Use','Charging') THEN 1 ELSE 0 END) AS in_use_observations,MAX(CASE WHEN json_extract(data,'$.status') IN ('In Use','Charging') THEN time END) AS last_in_use FROM events WHERE kind='station status' AND station IS NOT NULL GROUP BY station").all()).results;
    if(admin) {
     result.commands=(await env.DB.prepare('SELECT * FROM commands ORDER BY created DESC LIMIT 20').all()).results;
    }
    return json(result);
   }
   if (req.method==='GET' && path==='/api/history') {
    if(!admin) return json({error:'Sign in required'},401);
    const station=url.searchParams.get('station');
    const q=station?env.DB.prepare('SELECT * FROM events WHERE station=? ORDER BY time DESC LIMIT 500').bind(station):env.DB.prepare('SELECT * FROM events ORDER BY time DESC LIMIT 500');
    return json((await q.all()).results.map(e=>({...e,data:JSON.parse(e.data)})));
   }
   if (req.method==='POST' && path==='/api/start') {
    if(!admin) return json({error:'Sign in required'},401);
    if(req.headers.get('Origin')!==url.origin) return json({error:'Origin mismatch'},403);
    const b=await req.json();
    if(!/^BAE\d{6}$/.test(b.station||'') || !/^[a-f0-9-]{36}$/.test(b.id||'')) return json({error:'Invalid request'},400);
    const prior=await env.DB.prepare('SELECT * FROM commands WHERE id=?').bind(b.id).first();
    if(prior) return json(prior);
    const s=await env.DB.prepare('SELECT * FROM stations WHERE id=?').bind(b.station).first();
    const d=await env.DB.prepare('SELECT checked,data FROM device WHERE id=1').first();
    if(!s || s.status!=='Connected' || time-s.checked>180 || !d || time-d.checked>45 || time-(JSON.parse(d.data).observer_checked||0)>90) return json({error:'Station must be freshly Connected and phone observer online'},409);
    await env.DB.prepare("UPDATE commands SET state='expired',result='Expired before execution' WHERE state='queued' AND expires<?").bind(time).run();
    // A stale claimed command remains blocked: never silently replay a charge action.
    try {await env.DB.prepare("INSERT INTO commands(id,station,created,expires,state) VALUES(?,?,?,?,'queued')").bind(b.id,b.station,time,time+120).run();}
    catch {return json({error:'Another start is pending or needs review'},409);}
    return json({id:b.id,state:'queued'},202);
   }
   if(!device) return json({error:'Unauthorized'},401);
   if(req.method==='POST' && path==='/api/ingest') {
    if(Number(req.headers.get('content-length')||0)>250000) return json({error:'Too large'},413);
    const b=await req.json(), statements=[];
    for(const s of (b.stations||[]).slice(0,100)) {
     if(!/^BAE\d{6}$/.test(s.id)||!Number.isFinite(s.checked)) continue;
     if(s.location&&!['1850 Gateway Drive','Redwood City - CN37-12'].includes(s.location)) continue;
     statements.push(env.DB.prepare('INSERT INTO stations VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,changed=CASE WHEN stations.status<>excluded.status THEN excluded.checked ELSE stations.changed END,checked=excluded.checked WHERE excluded.checked>stations.checked').bind(s.id,s.status,s.checked,s.checked));
     statements.push(env.DB.prepare("INSERT INTO station_locations(id,location) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET location=excluded.location").bind(s.id,s.location||'1850 Gateway Drive'));
    }
    for(const e of (b.events||[]).slice(0,100)) statements.push(env.DB.prepare('INSERT OR IGNORE INTO events VALUES(?,?,?,?,?)').bind(e.id,e.station||null,e.time,e.kind,JSON.stringify(e.data)));
    for(const s of (b.sessions||[]).slice(0,100)) statements.push(env.DB.prepare('INSERT INTO sessions VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET station=COALESCE(excluded.station,sessions.station),updated=excluded.updated,state=excluded.state,kwh=excluded.kwh,data=excluded.data WHERE excluded.updated>sessions.updated').bind(s.id,s.station||null,s.started||null,s.updated,s.state,s.kwh??null,JSON.stringify(s)));
    statements.push(env.DB.prepare('INSERT INTO device VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET checked=excluded.checked,data=excluded.data').bind(time,JSON.stringify(b.device||{})));
    await env.DB.batch(statements);
    return json({ok:true});
   }
   if(req.method==='POST' && path==='/api/claim') {
    await env.DB.prepare("UPDATE commands SET state='expired',result='Expired before execution' WHERE state='queued' AND expires<?").bind(time).run();
    const command=await env.DB.prepare("UPDATE commands SET state='claimed' WHERE id=(SELECT id FROM commands WHERE state='queued' AND expires>=? ORDER BY created LIMIT 1) AND state='queued' RETURNING *").bind(time).first();
    return json({command});
   }
   if(req.method==='POST' && path==='/api/result') {
    const b=await req.json();
    if(!['confirmed','rejected','uncertain'].includes(b.state)) return json({error:'Bad state'},400);
    await env.DB.prepare("UPDATE commands SET state=?,result=? WHERE id=? AND state='claimed'").bind(b.state,String(b.result).slice(0,1000),b.id).run();
    return json({ok:true});
   }
   return json({error:'Not found'},404);
  } catch(error) { console.error(error.message); return json({error:'Request failed'},500); }
 }
};
