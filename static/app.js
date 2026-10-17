'use strict';
const $ = id => document.getElementById(id);
const state = {view:'feed', offset:0, total:0, jobs:[], overview:null, wasCollecting:false, expanded:new Set(), requestId:0};
const sourceState={offset:0,total:0,requestId:0};
const filterFields={'search':'search','status':'status-filter','sponsorship':'sponsorship','role':'role-filter',
  'work_model':'work-filter','found_days':'found-filter','experience':'experience-filter','graduate':'graduate-filter','sort':'sort-filter'};
const statuses = ['new','saved','applied','interview','offer','rejected','dismissed'];
const label = x => x.charAt(0).toUpperCase()+x.slice(1);
function el(tag, text, cls) { const e=document.createElement(tag); if(text!==undefined)e.textContent=text; if(cls)e.className=cls; return e; }
function message(text, error=false) { $('message').textContent=text; $('message').className=error?'error':''; $('message').hidden=!text; }
function date(value, full=false) { if(!value)return 'Not supplied'; const d=new Date(value); return Number.isNaN(d.getTime())?'Not supplied':d.toLocaleString(undefined,full?{dateStyle:'medium',timeStyle:'short'}:{month:'short',day:'numeric',year:'numeric'}); }
function ago(value) { if(!value)return 'Never'; const mins=Math.max(0,Math.floor((Date.now()-new Date(value).getTime())/60000)); return mins<1?'Just now':mins<60?`${mins}m ago`:mins<1440?`${Math.floor(mins/60)}h ago`:`${Math.floor(mins/1440)}d ago`; }
function link(text,url,cls) { const a=el('a',text,cls); a.href=url; a.target='_blank'; a.rel='noopener noreferrer'; return a; }
async function api(path, options={}) {
  const headers={'X-Tracker-Request':'1',...options.headers};
  if(options.body) headers['Content-Type']='application/json';
  const r=await fetch(path,{...options,headers});
  if(r.status===401 && path!='/api/login') { $('app').hidden=true; $('login').hidden=false; throw new Error('Sign in to your tracker.'); }
  const data=await r.json();
  if(!r.ok)throw new Error(typeof data.detail==='string'?data.detail:'Request could not be completed.');
  return data;
}
async function action(fn) { try { await fn(); } catch(e) { message(e.message,true); } }
function badge(job) {
  const names={supported:'Sponsorship mentioned',restricted:'Explicit restriction',unknown:'Needs verification',conflict:'Conflicting evidence'};
  return el('span',names[job.sponsorship]||'Needs verification','badge '+job.sponsorship);
}
function detailRow(job) {
  const row=el('tr'); row.id='detail-'+job.id;
  const cell=el('td',undefined,'detail-cell');cell.colSpan=5;
  const detail=el('div',undefined,'job-details');
  detail.append(el('h3','Eligibility evidence'));
  if(job.evidence.length) for(const evidence of job.evidence) detail.append(el('blockquote',evidence.quote));
  else detail.append(el('p','The posting does not give clear sponsorship evidence. Verify OPT acceptance and future sponsorship with the employer.'));
  for(const reason of job.scope_reasons||[])detail.append(el('p',reason));
  detail.append(el('p',`Original source locations: ${job.location||'Not supplied'}.`));
  detail.append(el('p',`Employer board last checked: ${job.verified_at?date(job.verified_at,true):'Not verified; discovered through a list or added manually'}. Availability: ${job.availability}.`));
  detail.append(el('p',`Source posting / publication date: ${date(job.posted_at)}. First found by this tracker: ${date(job.first_seen,true)}.`));
  const sources=el('p'); sources.textContent='Sources: '+job.sources.map(s=>`${s.name} (${s.last_error?'last refresh failed':s.misses?'absent from latest snapshot':'seen '+ago(s.last_seen)})`).join('; ');detail.append(sources);
  if(job.ai_review) {
    detail.append(el('h3','ChatGPT advice (advisory)'));
    detail.append(el('p',`${label(job.ai_review.sponsorship)}: ${job.ai_review.note}`));
    if(job.ai_review.quote)detail.append(el('blockquote',job.ai_review.quote));
    detail.append(el('p',`Reviewed ${date(job.ai_review.reviewed_at,true)} using ${job.ai_review.model}. ${job.ai_hash!==job.description_hash?'Posting changed since review. ':''}This advice does not change visibility.`));
  }
  const description=el('details'); description.append(el('summary','Read collected description'),el('div',job.description||'No employer description collected yet. Open the application link to review the full posting.','description'));detail.append(description);
  const notesLabel=el('label','Your notes'); const notes=el('textarea'); notes.value=job.notes; notes.maxLength=10000;notesLabel.append(notes);detail.append(notesLabel);
  const save=el('button','Save notes');save.type='button';save.addEventListener('click',()=>action(async()=>{save.disabled=true;try{await api('/api/jobs/'+job.id,{method:'PATCH',body:JSON.stringify({notes:notes.value})});job.notes=notes.value;message('Notes saved.');}finally{save.disabled=false;}}));detail.append(save);
  cell.append(detail);row.append(cell);return row;
}
function renderJobs() {
  $('jobs-body').replaceChildren();
  for(const job of state.jobs) {
    const row=el('tr');
    const role=el('button',job.title,'role');role.type='button';role.setAttribute('aria-expanded',String(state.expanded.has(job.id)));role.setAttribute('aria-controls','detail-'+job.id);
    role.addEventListener('click',()=>{state.expanded.has(job.id)?state.expanded.delete(job.id):state.expanded.add(job.id);renderJobs();document.querySelector(`[aria-controls="detail-${job.id}"]`)?.focus();});
    const name=el('td');name.append(role,el('div',job.company,'company'));name.append(el('div',`Found ${date(job.first_seen)} · ${job.min_years==null?'Experience not stated':`${job.min_years}+ years required`}`,'subtext'));row.append(name);
    const location=el('td',job.us_location||job.location||'Location not supplied','location');if(job.work_model!=='unknown')location.append(el('div',label(job.work_model),'subtext'));row.append(location);
    const eligibility=el('td');eligibility.append(badge(job));if(job.availability!=='open')eligibility.append(el('div',job.availability==='closed'?'Absent from two employer snapshots':'Employer posting not verified','subtext'));
    else if(Date.now()-new Date(job.verified_at).getTime()>36*3600000)eligibility.append(el('div','Verification is stale','subtext'));
    row.append(eligibility);
    const status=el('select',undefined,'status-select');status.setAttribute('aria-label','Application status for '+job.title+' at '+job.company);
    for(const value of statuses){const option=el('option',label(value));option.value=value;status.append(option);}status.value=job.status;
    status.addEventListener('change',()=>action(async()=>{status.disabled=true;try{await api('/api/jobs/'+job.id,{method:'PATCH',body:JSON.stringify({status:status.value})});await loadJobs();}catch(e){status.value=job.status;throw e;}finally{status.disabled=false;}}));const statusCell=el('td');statusCell.append(status);row.append(statusCell);
    const apply=el('td');apply.append(link('Apply ↗',job.apply_url,'apply'));row.append(apply);$('jobs-body').append(row);
    if(state.expanded.has(job.id))$('jobs-body').append(detailRow(job));
  }
  $('result-count').textContent=state.total.toLocaleString()+' '+(state.total===1?'job':'jobs');
  $('empty').hidden=!!state.jobs.length;
  if(!state.jobs.length) {
    const untouched=state.view==='feed'&&!state.overview?.runs?.length&&$('clear-filters').hidden;
    $('empty').querySelector('h2').textContent=untouched?'No jobs collected yet':state.view==='saved'?'No saved jobs match':'No jobs match these filters';
    $('empty').querySelector('p').textContent=untouched?'Refresh jobs to check the configured sources.':'Clear filters to see more US roles. Non-US and unconfirmed locations stay out of the main views.';
  }
  $('page-info').textContent=state.total?`${state.offset+1}–${Math.min(state.offset+100,state.total)} of ${state.total.toLocaleString()}`:'';
  $('previous').disabled=state.offset===0;$('next').disabled=state.offset+100>=state.total;
  $('view-note').textContent=['excluded','closed','all'].includes(state.view)?'Audit view: may contain non-US or unconfirmed locations.':state.view==='tracked'?'Your application history.':state.view==='saved'?'Your shortlist of US roles.':$('unapplied-filter').checked?'Unapplied US roles. Unclear sponsorship stays visible.':'US location required. Unclear sponsorship stays visible.';
  $('unapplied-label').hidden=state.view!=='feed';
}
function readFilters() {
  const query=new URLSearchParams({view:state.view,offset:String(state.offset)});
  for(const [key,id] of Object.entries(filterFields))query.set(key,$(id).value);
  query.set('verified',String($('verified-filter').checked));query.set('unapplied',String($('unapplied-filter').checked));
  return query;
}
function showFilterState() {
  const extra=['work-filter','experience-filter','graduate-filter','status-filter'].filter(id=>$(id).value).length+Number($('verified-filter').checked);
  $('filter-count').textContent=extra?`(${extra} active)`:'';
  const active=Object.entries(filterFields).some(([key,id])=>$(id).value && !['sort','found_days'].includes(key))||$('found-filter').value!=='0'||extra||$('sort-filter').value!=='recommended'||!$('unapplied-filter').checked;
  $('clear-filters').hidden=!active;
}
function restoreFilters() {
  const query=new URLSearchParams(location.search);
  if(['feed','saved','tracked','excluded','closed','all'].includes(query.get('view')))state.view=query.get('view');
  for(const [key,id] of Object.entries(filterFields)) {
    const value=query.get(key);if(value===null)continue;
    if($(id).tagName==='INPUT')$(id).value=value.slice(0,200);
    else if(Array.from($(id).options).some(o=>o.value===value))$(id).value=value;
  }
  $('verified-filter').checked=query.get('verified')==='true';$('unapplied-filter').checked=query.get('unapplied')!=='false';
  if(['work-filter','experience-filter','graduate-filter','status-filter'].some(id=>$(id).value)||$('verified-filter').checked)$('extra-filters').open=true;
  document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.view===state.view)));
}
async function clearFilters() {
  for(const [key,id] of Object.entries(filterFields))$(id).value=key==='sort'?'recommended':key==='found_days'?'0':'';
  $('verified-filter').checked=false;$('unapplied-filter').checked=true;state.offset=0;await loadJobs();
}
async function loadJobs() {
  const requestId=++state.requestId;
  const query=readFilters();showFilterState();history.replaceState(null,'','?'+query);
  const data=await api('/api/jobs?'+query);if(requestId!==state.requestId)return;state.jobs=data.jobs;state.total=data.total;renderJobs();
}
function renderOverview(o) {
  const latest=o.runs[0];
  let text;
  if(o.collecting)text=`Updating jobs · ${(latest?.success_count||0).toLocaleString()} sources checked. You can keep browsing.`;
  else if(!latest)text='Ready for your first refresh.';
  else text=`${latest.status==='interrupted'?'Refresh interrupted':latest.status==='failed'?'Refresh failed':'Updated '+ago(latest.finished_at||latest.started_at)}${o.failed_sources?' · Some sources unavailable. Details in Settings.':''}`;
  $('refresh-line').textContent=text;$('refresh-line').className='refresh-line'+(o.failed_sources||latest&&latest.status!=='success'?' warning':'');
  if(o.coverage){const c=o.coverage;$('coverage-line').textContent=`${c.enabled.toLocaleString()} enabled feeds · ${c.recent.toLocaleString()} checked successfully in the last 36 hours · ${c.pending.toLocaleString()} not checked yet · ${c.failed.toLocaleString()} need attention. Coverage is limited to these feeds.`;}
  $('refresh').disabled=o.collecting;$('refresh').textContent=o.collecting?'Refreshing…':'Refresh jobs';
  $('schedule-info').textContent=o.schedule_enabled?`Daily collection enabled. Next scheduled run: ${date(o.next_run,true)}. Missed runs catch up after restart.`:'Daily collection is disabled in this environment. Use Refresh jobs.';
  const p=o.plus;
  $('plus-status').textContent=p.connected?`Using ChatGPT plan · ${p.email||'Connected account'} · ${p.model||'Choose a model'} · up to ${p.daily_limit} requests per UTC day`:'Not connected. Daily collection does not require an AI subscription.';
  if(p.last_result)$('plus-status').textContent+=' · '+p.last_result.message;
  $('model-controls').hidden=!p.connected;
  $('run-history').replaceChildren();for(const run of o.runs){const row=el('div',undefined,'history-row');row.append(el('span',date(run.started_at,true)),el('strong',label(run.status)),el('span',`${run.success_count}/${run.source_count} sources · ${run.new_count} new`));if(run.error)row.append(el('span',run.error));$('run-history').append(row);}
}
async function loadOverview() {
  const previousRun=state.overview?.runs?.[0];const o=await api('/api/overview');
  const changed=state.wasCollecting&&!o.collecting || o.runs[0]?.finished_at!==previousRun?.finished_at;
  state.overview=o;renderOverview(o);state.wasCollecting=o.collecting;
  if(changed){await loadJobs();if(!$('settings').hidden)await loadSources();}
}
async function loadSources() {
  const requestId=++sourceState.requestId;
  const query=new URLSearchParams({search:$('source-search').value,health:$('source-health').value,offset:String(sourceState.offset),limit:'100'});
  const data=await api('/api/sources?'+query);if(requestId!==sourceState.requestId)return;$('sources-body').replaceChildren();
  sourceState.total=data.total;
  $('connect-command').textContent=`.venv/bin/python -m tracker.connect --host-id ${data.host_id}`;
  $('sources-summary').textContent=`Source health · ${data.summary.enabled.toLocaleString()} enabled · ${data.summary.failed.toLocaleString()} need attention`;
  $('source-page-info').textContent=data.total?`${sourceState.offset+1}–${Math.min(sourceState.offset+100,data.total)} of ${data.total.toLocaleString()} sources`:'No sources match';
  $('source-previous').disabled=sourceState.offset===0;$('source-next').disabled=sourceState.offset+100>=data.total;
  for(const s of data.sources) {
    const row=el('tr');const name=el('td');name.append(el('strong',s.name),el('div',`${s.provider} / ${s.slug}`,'subtext'));row.append(name,el('td',s.last_success?ago(s.last_success):'Never'),el('td',s.job_count==null?'—':String(s.job_count)),el('td',s.last_error||(!s.last_success?'Not checked':'OK'),s.last_error?'health-error':''));
    const check=el('input');check.type='checkbox';check.checked=!!s.enabled;check.setAttribute('aria-label','Enable '+s.name);check.addEventListener('change',()=>action(async()=>{try{await api('/api/sources/'+s.id,{method:'PATCH',body:JSON.stringify({enabled:check.checked})});await loadOverview();}catch(e){check.checked=!check.checked;throw e;}}));const cell=el('td');cell.append(check);row.append(cell);$('sources-body').append(row);
  }
  $('unsupported').replaceChildren();for(const s of data.unsupported)$('unsupported').append(el('p',`${s.name}: ${s.reason}`));
}
async function start() { const session=await api('/api/session');$('app').hidden=!session.authenticated;$('login').hidden=session.authenticated;if(session.authenticated){$('sign-out').hidden=!session.password_required;await loadOverview();await loadJobs();} }
$('login-form').addEventListener('submit',async event=>{event.preventDefault();$('login-error').textContent='';try{await api('/api/login',{method:'POST',body:JSON.stringify({password:$('password').value})});$('password').value='';await start();}catch(e){$('login-error').textContent=e.message;}});
$('refresh').addEventListener('click',()=>action(async()=>{$('refresh').disabled=true;try{await api('/api/refresh',{method:'POST'});message('Refresh started. You can keep browsing while sources are checked.');setTimeout(()=>action(loadOverview),500);}finally{setTimeout(()=>action(loadOverview),2000);}}));
$('settings-button').addEventListener('click',()=>action(async()=>{$('settings').hidden=!$('settings').hidden;$('settings-button').setAttribute('aria-expanded',String(!$('settings').hidden));if(!$('settings').hidden)await loadSources();}));
$('close-settings').addEventListener('click',()=>{$('settings').hidden=true;$('settings-button').setAttribute('aria-expanded','false');$('settings-button').focus();});
document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>action(async()=>{state.view=button.dataset.view;state.offset=0;$('status-filter').value='';document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));$('settings').hidden=true;$('settings-button').setAttribute('aria-expanded','false');await loadJobs();})));
let searchTimer; $('search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>action(async()=>{state.offset=0;await loadJobs();}),250);});
for(const id of Object.values(filterFields).filter(id=>id!=='search').concat(['verified-filter','unapplied-filter']))$(id).addEventListener('change',()=>action(async()=>{state.offset=0;await loadJobs();}));
for(const id of ['clear-filters','empty-clear'])$(id).addEventListener('click',()=>action(clearFilters));
$('previous').addEventListener('click',()=>action(async()=>{state.offset=Math.max(0,state.offset-100);await loadJobs();}));
$('next').addEventListener('click',()=>action(async()=>{state.offset+=100;await loadJobs();}));
$('source-form').addEventListener('submit',event=>{event.preventDefault();action(async()=>{await api('/api/sources',{method:'POST',body:JSON.stringify({provider:$('source-provider').value,slug:$('source-slug').value,name:$('source-name').value})});event.target.reset();await loadSources();await loadOverview();message('Source added. Refresh jobs to collect its listings.');});});
let sourceSearchTimer;$('source-search').addEventListener('input',()=>{clearTimeout(sourceSearchTimer);sourceSearchTimer=setTimeout(()=>action(async()=>{sourceState.offset=0;await loadSources();}),250);});
$('source-health').addEventListener('change',()=>action(async()=>{sourceState.offset=0;await loadSources();}));
$('source-previous').addEventListener('click',()=>action(async()=>{sourceState.offset=Math.max(0,sourceState.offset-100);await loadSources();}));
$('source-next').addEventListener('click',()=>action(async()=>{sourceState.offset+=100;await loadSources();}));
$('add-job-button').addEventListener('click',()=>{$('add-job').hidden=!$('add-job').hidden;$('add-job-button').setAttribute('aria-expanded',String(!$('add-job').hidden));if(!$('add-job').hidden)$('add-job').querySelector('input').focus();});
$('add-job').addEventListener('submit',event=>{event.preventDefault();action(async()=>{await api('/api/jobs',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(event.target)))});event.target.reset();$('add-job').hidden=true;$('add-job-button').setAttribute('aria-expanded','false');state.offset=0;await loadJobs();message('Job added as unverified. Recognized employer boards will be checked on the next refresh.');});});
$('sign-out').addEventListener('click',()=>action(async()=>{await api('/api/logout',{method:'POST'});await start();}));
$('import-plus').addEventListener('click',()=>action(async()=>{if(!$('plan-only').checked)throw new Error('Disable additional-credit fallback in ChatGPT settings, then confirm the checkbox.');const file=$('credential-file').files[0];if(!file||file.size>50000)throw new Error('Select the connection JSON file generated by the local helper.');const credentials=JSON.parse(await file.text());await api('/api/chatgpt/import',{method:'POST',body:JSON.stringify({credentials,plan_only_confirmed:true})});$('credential-file').value='';await loadOverview();message('ChatGPT connected. Load your available models and choose one. Delete the local transfer file.');}));
$('load-models').addEventListener('click',()=>action(async()=>{const data=await api('/api/chatgpt/models');$('model').replaceChildren();for(const m of data.models){const option=el('option',m.name);option.value=m.id;$('model').append(option);}if(!data.models.length)throw new Error('No eligible models were returned for this account. Collection remains available.');}));
$('save-model').addEventListener('click',()=>action(async()=>{await api('/api/chatgpt/model',{method:'POST',body:JSON.stringify({model:$('model').value})});await loadOverview();message('Model saved. Plus will review new unclear postings after daily collection.');}));
$('review').addEventListener('click',()=>action(async()=>{await api('/api/chatgpt/review',{method:'POST'});message('ChatGPT review started. Collection and application links remain available.');}));
$('disconnect').addEventListener('click',()=>action(async()=>{const data=await api('/api/chatgpt/disconnect',{method:'POST'});await loadOverview();message(data.message,!data.revoked);}));
async function poll(){if(!$('app').hidden)await action(loadOverview);setTimeout(poll,state.overview?.collecting?3000:30000);}
restoreFilters();action(start);setTimeout(poll,3000);
