let token=localStorage.getItem('blink-admin')||'';
const $=s=>document.querySelector(s), age=t=>t?Math.max(0,Math.floor(Date.now()/1000-t)):null;
const time=t=>t?new Date(t*1000).toLocaleString():'unknown';
const monthsAgo=months=>{const cutoff=new Date(),day=cutoff.getUTCDate();cutoff.setUTCDate(1);cutoff.setUTCMonth(cutoff.getUTCMonth()-months);const monthEnd=new Date(Date.UTC(cutoff.getUTCFullYear(),cutoff.getUTCMonth()+1,0)).getUTCDate();cutoff.setUTCDate(Math.min(day,monthEnd));return cutoff.getTime()/1000;};
async function api(path,body){const r=await fetch('/api/'+path,{method:body?'POST':'GET',headers:{...(token?{Authorization:'Bearer '+token}:{}),...(body?{'Content-Type':'application/json'}:{})},body:body?JSON.stringify(body):undefined});const d=await r.json();if(!r.ok)throw Error(d.error||r.status);return d;}
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
const duration=seconds=>{const minutes=Math.max(0,Math.ceil(seconds/60));return `${Math.floor(minutes/60)}:${String(minutes%60).padStart(2,'0')}`;};
const statusAge=t=>{const seconds=age(t);if(seconds===null)return 'unknown';if(seconds<60)return `${seconds}s`;const minutes=Math.floor(seconds/60);if(minutes<60)return `${minutes}m`;const hours=Math.floor(minutes/60);if(hours<24)return `${hours}h ${minutes%60}m`;return `${Math.floor(hours/24)}d ${hours%24}h`;};
const stationGroups=[['BAE607154'],['BAE607189','BAE607180'],['BAE607174','BAE607177'],['BAE607183','BAE607195'],['BAE607191','BAE607192'],['BAE607190','BAE607152'],['BAE607150','BAE607175'],['BAE607160'],['BAE605915','BAE610619'],['BAE607163','BAE607172']];
const stationOrder=Object.fromEntries(stationGroups.flatMap((g,i)=>g.map((id,j)=>[id,[i,j]])));
const gatewayStaleAfter=300,redwoodStaleAfter=900;
document.addEventListener('copy',event=>{
 const cell=event.target.closest?.('.station-id');
 if(cell){event.clipboardData.setData('text/plain',cell.textContent.trim());event.preventDefault();}
});
function completionEstimate(s){
 if(!s)return 'ETA unknown';
 if(s.state==='stopped')return 'Complete — unplug your car';
 if(age(s.updated)>90||s.state!=='charging'||!(s.data?.kw>0)||s.kwh==null)return 'ETA unavailable';
 const remaining=Math.max(0,(5.65-s.kwh)/s.data.kw*3600-age(s.updated));
 return remaining>0?`${duration(remaining)} left · ~${new Date(Date.now()+remaining*1000).toLocaleTimeString([],{hour:'numeric',minute:'2-digit'})}`:'Near expected full — awaiting Blink';
}
function chargingDetails(d){
 const panel=$('#charging');panel.hidden=false;
 const sessions=(d.sessions||[]).filter(s=>s.state!=='ended');
 panel.replaceChildren(el('h2','Your charging'));
 if(!sessions.length){panel.append(el('p','No ongoing session recorded.','muted'));return;}
 for(const s of sessions){
   const data=s.data||{},stale=age(s.updated)>90,box=el('article',undefined,'charging-detail');
   box.append(el('h3',s.station||(data.station_candidate?`Likely ${data.station_candidate} — awaiting confirmation`:'Station unconfirmed')));
   const fields=el('dl',undefined,'charging-fields');
   const field=(label,value)=>{const item=el('div');item.append(el('dt',label),el('dd',value));fields.append(item);};
   field('Status',s.state+(stale?' · stale reading':''));
   field('Energy delivered',s.kwh==null?'Unknown':`${s.kwh.toFixed(2)} kWh`);
   field('Power',data.kw==null?'Unknown':`${data.kw.toFixed(2)} kW`);
   field('Elapsed (Blink)',data.elapsed||'Unknown');
   field('Estimated completion (h:mm)',completionEstimate(s));
   field(data.start_is_observation?'First observed':'Started',time(s.started));
   box.append(fields,el('p','Estimate assumes an empty Prius Prime, about 5.65 kWh input, at the reported power. Completion alerts rely on Blink’s actual status, not this estimate.','muted'));
   panel.append(box);
 }
}
$('#login').onclick=async()=>{const entered=prompt('Paste your private dashboard control key (not your Blink password)');if(entered===null)return;token=entered;localStorage.setItem('blink-admin',token);await refresh();};
async function refresh(){try{
 const d=await api('status'),online=d.device&&age(d.device.checked)<45&&d.device.observer_checked&&age(d.device.observer_checked)<90;
 $('#connection').textContent=(online?`Phone online · ${d.device.mode||'monitoring'} · heartbeat ${age(d.device.checked)}s ago`:`Phone observer delayed · ${d.device?.mode||'starting'} · last heartbeat ${d.device?time(d.device.checked):'not yet received'}`)+(d.device?.error?' · '+d.device.error:'');
 $('#login').textContent='Unlock controls';$('#login').hidden=!!d.admin;
 const counts={};for(const s of d.stations)counts[age(s.checked)>gatewayStaleAfter?'Stale':s.status]=(counts[age(s.checked)>gatewayStaleAfter?'Stale':s.status]||0)+1;
 $('#summary').replaceChildren(...Object.entries(counts).map(([k,v])=>el('span',`${v} ${k}`)));
 const monthCutoff=monthsAgo(1),personalCutoff=monthsAgo(6);
 const markUsage=(node,s)=>{
   const usage=d.usage?.find(x=>x.station===s.id);
   const stats=d.statistics?.find(x=>x.station===s.id);
   const lastUse=Math.max(usage?.last_in_use||0,stats?.last_energy||0,['In Use','Charging'].includes(s.status)?s.checked||0:0);
   if(!s.missing&&usage&&lastUse<monthCutoff){
     node.classList.add('no-recent-use');
     node.title+=(node.title?' · ':'')+`No recorded use in the past month. ${lastUse?'Last recorded use: '+time(lastUse)+'. ':'No use recorded. '}Includes monitored use and your charges delivering energy. Monitoring began ${time(usage.first_observed)}; gaps may miss use.`;
   }
 };
 const connectedButton=s=>{
   const button=el('button','Connected','status connected status-button');
   button.title=d.admin?'Start charging here':'Unlock controls to start charging';
   button.disabled=!d.admin||!online||age(s.checked)>180;
   button.onclick=async()=>{if(!confirm(`Start a PAID Blink session at ${s.id}? The phone will verify this exact station is Connected. Posted fees apply.`))return;button.disabled=true;try{const r=await api('start',{station:s.id,id:crypto.randomUUID()});$('#message').textContent=`Request ${r.state} for ${s.id}. Waiting for phone verification.`;}catch(e){$('#message').textContent=e.message;}};
   return button;
 };
 const row=(s,staleAfter=gatewayStaleAfter)=>{
   const stale=age(s.checked)>staleAfter,card=el('tr',undefined,'station-row');card.dataset.station=s.id;
   const since=el('td',s.missing?'':statusAge(s.changed),'status-duration');
   if(!s.missing){
     since.title=`Status first observed ${time(s.changed)}. Observed duration, not an exact transition time; stale readings do not confirm it continued.`;
     if(age(s.changed)>7*86400)since.classList.add('old-status');
   }
   let statusNode=el('span',s.status+(stale?' · stale':''),'status '+s.status.toLowerCase().replaceAll(' ','-'));
   const statusCell=el('td',undefined,'status-cell');statusCell.append(statusNode);
   const eta=el('td','','station-eta');
   card.append(el('td',s.id,'station-id'),statusCell,since,eta);
   if(s.status==='Charging'){
     const session=(d.sessions||[]).find(x=>x.state!=='ended'&&(x.station===s.id||(!x.station&&x.data?.station_candidate===s.id)));
     eta.textContent=(session&&!session.station?'Likely yours · ':'')+completionEstimate(session);
     eta.title='Estimate for your recorded session only. Assumes an empty Prius Prime and 5.65 kWh input. Other vehicles’ completion times are unknown.';
   }
   const stats=d.statistics?.find(x=>x.station===s.id);
   if(s.status==='Available'){
     const success=stats?.last_success&&stats.last_success>=personalCutoff;
     if(!success){card.classList.add('unproven');card.querySelector('.status').classList.add('unproven-status');card.querySelector('.status').title='No successful charge recorded here in the last six months; missing history is not evidence of failure.';}
   }
   const detail=el('td',stats?`${stats.sessions} sessions · ${stats.kwh} kWh · ${stats.low_delivery} low`:'','station-stats');detail.title='Your recorded sessions; below 1 kWh flagged for review, not proof of failure';card.append(detail);
   markUsage(statusNode,s);
   return card;
 };
 const ordered=d.stations.slice().sort((a,b)=>(stationOrder[a.id]?.[0]??99)-(stationOrder[b.id]?.[0]??99)||(stationOrder[a.id]?.[1]??99)-(stationOrder[b.id]?.[1]??99)||a.id.localeCompare(b.id));
 const groups=stationGroups.map(ids=>ids.map(id=>ordered.find(s=>s.id===id)||{id,status:'Unknown',missing:true}));
 const unlisted=ordered.filter(s=>!stationOrder[s.id]);
 if(unlisted.length)groups.push(unlisted);
 const renderGroups=(table,connectedOnly)=>{
   const bodies=[];
   groups.forEach((stations,index)=>{
     const members=connectedOnly?stations.filter(s=>s.status==='Connected'):stations;
     if(!members.length)return;
     const body=el('tbody');body.dataset.group=String(index+1);
     members.forEach((s,i)=>{
       const tr=row(s);
       if(i===0){const number=el('th',String(index+1),'group-number');number.scope='rowgroup';number.rowSpan=members.length;tr.prepend(number);}
       body.append(tr);
     });
     bodies.push(body);
   });
   table.replaceChildren(...bodies);
   return bodies.length;
 };
 const activeSessions=(d.sessions||[]).filter(s=>s.state==='charging'&&s.station);
 const chargingIds=new Set(activeSessions.map(s=>s.station));
 const cards=[];
 groups.forEach((stations,index)=>{
   for(const s of stations.filter(s=>s.status==='Connected'&&!chargingIds.has(s.id))){
     const card=el('article',undefined,'connected-card');card.dataset.station=s.id;
     const heading=el('div',undefined,'connected-heading');
     const since=el('span',`${statusAge(s.changed)} connected${age(s.checked)>gatewayStaleAfter?' · stale':''}`,'connected-since');
     const button=connectedButton(s);markUsage(button,s);
     heading.append(el('span',`#${index+1}`,'connected-group'),el('strong',s.id),button,since);
     card.append(heading);
     const stats=d.statistics?.find(x=>x.station===s.id);
     const metrics=el('div',undefined,'connected-metrics');
     const metric=(value,label)=>{const item=el('span');item.append(el('strong',String(value)),document.createTextNode(' '+label));metrics.append(item);};
     if(stats){
       metric(stats.sessions,'sessions');metric(stats.kwh,'kWh');metric(stats.low_delivery,'below 1 kWh');
       if(stats.last_success)metric(new Date(stats.last_success*1000).toLocaleDateString([],{month:'short',day:'numeric',year:'numeric'}),'last success');
     }else{metrics.textContent='No recorded sessions';}
     card.append(metrics);
     const session=(d.sessions||[]).find(x=>x.state!=='ended'&&x.station===s.id);
     if(session){
       const info=[`Your session: ${session.state}`];
       if(session.kwh!=null)info.push(`${session.kwh.toFixed(2)} kWh`);
       if(session.data?.kw!=null)info.push(`${session.data.kw.toFixed(2)} kW`);
       if(session.data?.elapsed)info.push(session.data.elapsed+' elapsed');
       info.push(completionEstimate(session));
       card.append(el('div',info.join(' · '),'connected-session'));
     }
     cards.push(card);
   }
 });
 const priority=$('#priority');
 let sessionSummaryShown=false,liveChargingShown=false;
 for(const session of activeSessions){
   const s=d.stations.find(x=>x.id===session.station), data=session.data||{};
   const stationLive=!!s&&['Connected','In Use','Charging'].includes(s.status);
   // If Blink has already changed this station to Available, retain the summary
   // only while there is no other Connected station to surface.
   if(!stationLive&&cards.length)continue;
   const card=el('article',undefined,'connected-card charging-priority');
   const title=el('div',undefined,'charging-title');
   title.append(el('span',`${stationLive?'':'Charging Complete · '}#${s?((stationOrder[s.id]?.[0]??'')+1):'?'} ${session.station}`));
   if(stationLive){
     const connected=el('button','Connected','status connected status-button');
     connected.disabled=true;connected.title='Already charging at this station';title.append(connected);
     liveChargingShown=true;
   }else sessionSummaryShown=true;
   card.append(title);
   const metrics=el('div',undefined,'connected-metrics');
   const metric=(label,value)=>{const item=el('span');item.append(el('strong',String(value)),document.createTextNode(' '+label));metrics.append(item);};
   metric('station',s?.status||'unknown');metric('session',stationLive?session.state:'Charging Complete');
   metric('energy',session.kwh==null?'unknown':`${session.kwh.toFixed(2)} kWh`);
   metric('power',data.kw==null?'unknown':`${data.kw.toFixed(2)} kW`);
   metric('elapsed',data.elapsed||'unknown');
   metric('completion',stationLive?completionEstimate(session):'status changed');
   card.append(metrics,el('div',`Blink reading ${statusAge(session.updated)} ago`,'connected-session'));
   cards.push(card);
 }
 $('#priority-heading').textContent=liveChargingShown?'Charging':sessionSummaryShown?'Charging Complete':'Connected';
 $('#empty-connected').hidden=!!cards.length;
 priority.replaceChildren(...cards);priority.hidden=!cards.length;
 renderGroups($('#stations'),false);
 const redwood=d.other_locations?.find(x=>x.name==='Redwood City - CN37-12');
 const remoteStations=redwood?.stations||[];
 const spacerText=[...$('#stations').querySelectorAll('.station-stats')].map(n=>n.textContent).sort((a,b)=>b.length-a.length)[0]||'';
 const remoteBody=el('tbody');
 remoteStations.forEach((s,i)=>{
   const tr=row(s,redwoodStaleAfter);
   const spacer=el('td','\u00a0','station-spacer');
   const sizing=el('span',spacerText,'spacer-sizing');sizing.setAttribute('aria-hidden','true');
   spacer.append(sizing);tr.append(spacer);
   if(i===0){const number=el('th','1','group-number');number.scope='rowgroup';number.rowSpan=remoteStations.length;tr.prepend(number);}
   remoteBody.append(tr);
 });
 $('#redwood-stations').replaceChildren(...(remoteStations.length?[remoteBody]:[]));
 const remoteCounts={};for(const s of remoteStations){const status=age(s.checked)>redwoodStaleAfter?'Stale':s.status;remoteCounts[status]=(remoteCounts[status]||0)+1;}
 $('#redwood-summary').textContent=remoteStations.length?Object.entries(remoteCounts).map(([status,count])=>`${count} ${status}`).join(' · '):'Waiting for first scan';
 }catch(e){$('#connection').textContent='Cannot refresh: '+e.message;}}
refresh();
// Connected/charging status should appear promptly; idle station lists can poll less often.
let lastFast=false;
async function adaptiveRefresh(){
  await refresh();
  const fast=!!document.querySelector('#priority .charging-priority,#priority .connected-card');
  if(fast!==lastFast){lastFast=fast;clearInterval(window.blinkPoll);window.blinkPoll=setInterval(adaptiveRefresh,fast?2000:5000);}
}
// Check quickly after page load too; adaptiveRefresh will relax to 5s when idle.
window.blinkPoll=setInterval(adaptiveRefresh,2000);
