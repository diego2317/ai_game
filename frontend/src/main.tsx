import React, { useCallback, useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { QRCodeSVG } from 'qrcode.react'
import { ArrowRight, Check, X, Layers3, Radio, Users, Pause, Play, Copy, Monitor, LogOut, AlertCircle } from 'lucide-react'
import '@fontsource-variable/dm-sans'
import '@fontsource-variable/space-grotesk'
import './style.css'

import { api, type Session } from './api'
import { MaterialityReveal, type Reveal } from './reveal'
import { ClassroomTools, PhaseClock, type Timing } from './classroom'
import { Assumptions, PhaseControls, SettingsEditor, TeamWorkshop, TestingComparison, TrainingControls, defaultRules, type Economy, type Comparison } from './gameplay'

type Policy = {title: string; intro: string; rules: string[]}
type SharedState = {demo:boolean;generation:number;timing:Timing;reveal:Reveal|null}
type Student = SharedState & {code: string; phase: string; nickname: string; team: number; team_name: string; policy: Policy; completed: number; total: number; post: {assignment_id: number; text: string}|null; economy:Economy; comparison:Comparison|null}
type Team = {id: number; name: string; members: number; annotations: number; assigned: number; unique_posts: number; disagreements: number; allow: number; remove: number; labor_seconds: number; seconds_per_label: number|null; economy:Economy}
type Dashboard = SharedState & {code: string; phase: string; teams: Team[]; policy: Policy; participants: {id: number; nickname: string; team: number; online: boolean;simulated:boolean}[]; economy_rules:typeof defaultRules; comparison:Comparison|null}
const phaseName: Record<string,string> = {lobby:'Waiting room', annotation:'Annotation in progress', paused:'Annotation paused', complete:'Annotation complete', training:'Training & investment', testing:'Model comparison', reveal:'The hidden infrastructure'}
function App() {
  const [session, setSession] = useState<Session|null>(()=>{try{return JSON.parse(sessionStorage.getItem('true-cost-session')||'null')}catch{return null}})
  const [data, setData] = useState<Student|Dashboard|null>(null)
  const [error, setError] = useState('')
  const [connectionProblem, setConnectionProblem] = useState('')
  const currentSession = useRef(session)
  currentSession.current = session
  const refreshSequence = useRef(0)
  const appliedSequence = useRef(0)
  const [busy, setBusy] = useState(false)
  const [instructorMode, setInstructorMode] = useState(location.pathname === '/instructor')
  const [projector, setProjector] = useState(false)
  const [copied, setCopied] = useState(false)
  const [joinOrigin, setJoinOrigin] = useState(()=>localStorage.getItem('true-cost-join-origin') || location.origin)
  const [code, setCode] = useState(new URLSearchParams(location.search).get('room') || '')
  const [nickname, setNickname] = useState('')
  const [secret, setSecret] = useState('')
  const [economyRules, setEconomyRules] = useState(defaultRules)
  const [demoMode, setDemoMode] = useState(false)
  const lock = useRef(false)
  const refresh = useCallback(async()=> {
    if (!session) return
    const sequence = ++refreshSequence.current
    const result = await api<Student|Dashboard>(`/rooms/${session.code}/${session.role}`, session)
    if (currentSession.current?.token !== session.token || sequence < appliedSequence.current) return
    appliedSequence.current = sequence
    setData(current=>current?.code===result.code && current.generation>result.generation ? current : result)
  },[session])
  useEffect(()=>{if(!session)return; let active=true; const poll=async()=>{try{await refresh(); if(active)setConnectionProblem('')}catch(e){if(active)setConnectionProblem(`Connection interrupted. Retrying… ${(e as Error).message}`)}}; void poll(); const timer=setInterval(()=>void poll(),2000); return()=>{active=false;clearInterval(timer)}},[session,refresh])
  function save(next: Session){sessionStorage.setItem('true-cost-session',JSON.stringify(next));setSession(next);setData(null)}
  async function act(fn:()=>Promise<void>){if(lock.current)return;lock.current=true;setBusy(true);setError('');try{await fn()}catch(e){setError((e as Error).message)}finally{lock.current=false;setBusy(false)}}
  function leave(){sessionStorage.removeItem('true-cost-session');setSession(null);setData(null);setError('');setConnectionProblem('')}
  const student = session?.role==='student' ? data as Student|null : null
  const dashboard = session?.role==='instructor' ? data as Dashboard|null : null
  let joinUrl = ''
  let joinAddressError = ''
  try {
    const address = new URL(joinOrigin)
    if (!['http:', 'https:'].includes(address.protocol) || address.username || address.password) throw new Error()
    joinUrl = session ? `${address.origin}/?room=${session.code}` : ''
    const hostname = address.hostname.toLowerCase()
    if (hostname === 'localhost' || hostname.endsWith('.localhost') || hostname === '[::1]' || hostname === '0.0.0.0' || hostname.startsWith('127.')) {
      joinAddressError = 'Phones cannot reach localhost. Enter your computer’s Wi-Fi address (for example, http://192.168.1.20:8000), or your public Railway URL. Phones must be on the same Wi-Fi for a local address.'
    }
  } catch { joinAddressError = 'Enter a full address beginning with http:// or https://.' }
  async function copyJoinLink() {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(joinUrl)
    } else {
      const field = document.createElement('textarea')
      field.value = joinUrl
      document.body.appendChild(field)
      field.select()
      const ok = document.execCommand('copy')
      field.remove()
      if (!ok) throw new Error('Copy unavailable. Select and copy the displayed join link.')
    }
    setCopied(true)
    setTimeout(()=>setCopied(false),2500)
  }
  const totalLabels = dashboard?.teams.reduce((n,t)=>n+t.annotations,0)||0
  return <div className={projector?'app projector':'app'}>
    <header className="header"><a className="brand" href="/"><span className="brand-icon"><Layers3 size={23}/></span><span>THE TRUE COST <span className="muted">OF AI</span><small>A MEDIA STUDIES SIMULATION</small></span></a><div className="header-right"><span className="edition">CLASSROOM EDITION / 01</span>{session?.role==='instructor'&&<button className="secondary presentation-toggle" aria-label={projector?'Exit presentation':'Presentation'} onClick={()=>setProjector(!projector)}><Monitor size={17}/><span className="presentation-label">{projector?'Exit presentation':'Presentation'}</span></button>}{session && <button className="icon-button" aria-label="Leave session" title="Leave session (you will need a new nickname to rejoin)" onClick={leave}><LogOut size={19}/></button>}</div></header>
    <main data-phase={data?.phase || 'entry'}>
    {connectionProblem && <div role="status" className="connection-notice">{connectionProblem}</div>}
    {error && <div role="alert" className="error"><AlertCircle size={18}/>{error}</div>}
    {!session ? <div className="landing"><section className="intro"><div className="eyebrow"><span className="dot"/> BEHIND EVERY PREDICTION</div><h1>Artificial intelligence.<br/><em>Human work.</em></h1><p className="lede">Build an AI company. Make the calls.<br/>Discover what your model depends on.</p><div className="flow"><span>01 / LABEL</span><ArrowRight size={16}/><span>02 / BUILD</span><ArrowRight size={16}/><span>03 / RECKON</span></div><div className="intro-note">A live classroom investigation into data, labor, and the material world behind AI.</div></section><section className="panel entry"><span className="eyebrow">{instructorMode?'INSTRUCTOR ACCESS':'YOUR SHIFT STARTS HERE'}</span><h2>{instructorMode?'Open the classroom.':'Join your company.'}</h2><p className="muted">{instructorMode?'Create a private control room for your class, whatever the attendance.':'Enter the room code on the screen. No account needed.'}</p><form onSubmit={e=>{e.preventDefault();void act(async()=>{if(instructorMode){const s=await api<Omit<Session,'role'>>('/rooms',null,{secret,economy:economyRules,demo:demoMode});save({...s,role:'instructor'});setSecret('')}else{const s=await api<Omit<Session,'role'>>(`/rooms/${code.toUpperCase()}/join`,null,{nickname});save({...s,role:'student'})}})}}>{instructorMode?<><label>Instructor access key<input type="password" value={secret} onChange={e=>setSecret(e.target.value)} required autoComplete="current-password" minLength={8}/></label><label className="demo-option"><input type="checkbox" checked={demoMode} onChange={e=>setDemoMode(e.target.checked)}/><span>Demonstration room<small>15 simulated participants with preloaded labels. No student devices required.</small></span></label><SettingsEditor value={economyRules} onChange={setEconomyRules}/></>:<><label>Room code<input className="code-input" placeholder="ABC123" value={code} onChange={e=>setCode(e.target.value.toUpperCase())} required pattern="[A-Za-z0-9]{6}" maxLength={6} autoCapitalize="characters" autoComplete="off"/></label><label>Your nickname<input placeholder="e.g. Maya" value={nickname} onChange={e=>setNickname(e.target.value)} required maxLength={24} pattern="[\p{L}\p{N}_ .\-]+" autoComplete="nickname"/></label></>}<button className="primary" disabled={busy}>{busy?'Connecting…':instructorMode?'Create game room':'Enter the room'}<ArrowRight size={18}/></button></form><button className="text-button switch" onClick={()=>{setInstructorMode(!instructorMode);setError('')}}>{instructorMode?'← Student joining':'Leading the session? Instructor access →'}</button></section><div className="landing-foot"><span>3 COMPANIES</span><span>FLEXIBLE TEAM SIZES</span><span>ONE SHARED POLICY</span><span>~20 MINUTES</span></div></div> : !data ? <div className="empty">Connecting to your classroom…</div> : <>
    <div className="session-top"><div><div className="eyebrow">{session.role==='instructor'?'CONTROL ROOM':'ANNOTATOR WORKSPACE'} / {session.code}</div><h1>{dashboard?'The work behind the model.':student?.team_name}</h1></div><div className={`status ${data.phase==='annotation'?'live':''}`}><Radio size={16}/>{phaseName[data.phase]}</div></div>
    <nav className="phase-track" aria-label="Game progress"><span className={['lobby','annotation','paused','complete'].includes(data.phase)?'active':''}>01 <b>Human labor</b></span><span className={data.phase==='training'?'active':''}>02 <b>Training</b></span><span className={data.phase==='testing'?'active':''}>03 <b>Testing</b></span><span className={data.phase==='reveal'?'active':''}>04 <b>The reveal</b></span></nav>
    <PhaseClock timing={data.timing}/>
    {dashboard && <>
      <ClassroomTools key={dashboard.generation} session={session} generation={dashboard.generation} demo={dashboard.demo} phase={data.phase} teams={dashboard.teams} refresh={refresh}/>
      <div className={`instructor-layout ${dashboard.demo?'demonstration':''}`}><section className="panel room-card"><div className="eyebrow">INVITE YOUR CLASS</div><div className="room-code">{session.code}</div><label className="join-address">Student-accessible URL<input type="url" value={joinOrigin} placeholder="http://192.168.1.20:8000" onChange={e=>{setJoinOrigin(e.target.value);localStorage.setItem('true-cost-join-origin', e.target.value)}}/></label>{joinAddressError ? <p className="join-warning" role="status">{joinAddressError}</p> : <QRCodeSVG value={joinUrl} size={192} bgColor="#ffffff" fgColor="#111915" marginSize={4} title="Scan to join this classroom"/>}<p className="muted">Scan to join · {dashboard.participants.length} joined</p><a className="join-link" href={joinAddressError ? undefined : joinUrl} target="_blank" rel="noreferrer">{joinAddressError ? 'Set an address to enable joining by QR' : joinUrl}</a><button className="secondary" disabled={!!joinAddressError} onClick={()=>void act(copyJoinLink)}><Copy size={15}/>{copied?'Copied':'Copy join link'}</button></section><section className="panel control-card"><div className="eyebrow">INSTRUCTOR / PACE THE CLASSROOM</div><h2>{data.phase==='lobby'?'Your workforce is assembling.':data.phase==='complete'?'The dataset carries their decisions.':data.phase==='training'?'Turn their decisions into a model.':data.phase==='testing'?'Same test. Different learned decisions.':data.phase==='reveal'?'Bring the hidden system into view.':'Every label is a human decision.'}</h2><p className="muted">{data.phase==='lobby'?'Each new student joins the smallest team. Start with whoever is here; others can join during the shift.':'Students follow a shared policy, but interpret different, overlapping sets of posts. Shared examples expose disagreement.'}</p><div className="big-stats"><div><strong>{totalLabels}</strong><span>{dashboard.demo?'scripted labels':'labels contributed'}</span></div><div><strong>{dashboard.participants.filter(p=>p.online).length}<small> / {dashboard.participants.length}</small></strong><span>{dashboard.demo?'active human devices':'active in last 15 seconds'}</span></div><div><strong>{dashboard.teams.reduce((n,t)=>n+t.disagreements,0)}</strong><span>disputed posts</span></div></div><div className="actions">{['lobby','annotation','paused'].includes(data.phase) && <button className="primary" disabled={busy} onClick={()=>void act(async()=>{await api(`/rooms/${session.code}/phase`,session,{phase:data.phase==='annotation'?'paused':'annotation'});await refresh()})}>{data.phase==='annotation'?<Pause size={17}/>:<Play size={17}/>} {data.phase==='annotation'?'Pause shift':data.phase==='paused'?'Resume shift':'Start annotation'}</button>}{['annotation','paused'].includes(data.phase)&&<button className="secondary" disabled={busy} onClick={()=>{if(confirm('End this annotation shift? You can open Training afterward to continue work.'))void act(async()=>{await api(`/rooms/${session.code}/phase`,session,{phase:'complete'});await refresh()})}}>End annotation</button>}</div><p className="fine">Suggested pacing: 5 min labeling, 4 min investment and training, 5 min testing, 5 min reveal and discussion. The timer is a guide; you control every transition.</p></section></div><PhaseControls key={dashboard.generation} session={session} phase={data.phase} teams={dashboard.teams} refresh={refresh}/><Assumptions rules={dashboard.economy_rules}/>
      <div className="company-floor"><div className="section-heading"><h2>Company floor</h2><span className="muted">Updates every 2 seconds</span></div><div className="team-grid">{dashboard.teams.map(t=><section key={t.id} className={`panel team-card team-${t.id}`}><div className="team-title"><span className="team-mark">0{t.id+1}</span><h3>{t.name}</h3><span className="muted">{t.members} members</span></div><div className="annotation-count">{t.annotations}<span> / {t.assigned} labels</span></div><progress value={t.annotations} max={t.assigned||1} aria-label={`${t.name} labeling progress`}/><div className="metrics"><div><span>Allow / Remove</span><b>{t.allow} / {t.remove}</b></div><div><span>Distinct posts labeled</span><b>{t.unique_posts}</b></div><div><span>Disputed posts</span><b>{t.disagreements}</b></div><div><span>{dashboard.demo?'Scripted task time':'Recorded task time'}</span><b>{Math.round(t.labor_seconds)}s</b></div><div><span>Seconds per label</span><b>{t.seconds_per_label??'—'}</b></div></div><TrainingControls session={session} economy={t.economy} phase={data.phase} refresh={refresh}/><div className="members">{dashboard.participants.filter(p=>p.team===t.id).map(p=><div key={p.id} className="member"><span className={p.online?'presence online':'presence'}/><span>{p.nickname}{p.simulated?' · simulated':''}</span>{data.phase==='lobby'&&!dashboard.demo&&<select aria-label={`Assign ${p.nickname} to team`} value={p.team} disabled={busy} onChange={e=>void act(async()=>{await api(`/rooms/${session.code}/participants/${p.id}/team`,session,{team:Number(e.target.value)});await refresh()})}>{dashboard.teams.map(team=><option key={team.id} value={team.id}>{team.name}</option>)}</select>}</div>)}{!t.members&&<p className="muted">Waiting for annotators…</p>}</div></section>)}</div><p className="fine">{dashboard.demo?'Demo task counts and times are scripted, not actual human labor. Training time is measured.':'Recorded task time sums server-timed, submitted tasks (capped at 30 minutes each); it can include reading or idle time. Pausing discards unfinished task time.'} A disputed post has both labels within the same team. No labels are scored for correctness.</p></div>
    </>}
    {student && data.phase==='training' && <TeamWorkshop key={student.generation} session={session} economy={student.economy} refresh={refresh}/>}
    {data.phase==='reveal' && data.reveal && <MaterialityReveal reveal={data.reveal} comparison={data.comparison}/>}
    {data.phase==='testing' && data.comparison && <TestingComparison comparison={data.comparison} demo={data.demo}/>}
    {student && !['testing','reveal'].includes(data.phase) && <div id="annotation-queue" className={`student-layout team-${student.team}`}><section className="work-area"><div className="worker-bar"><span><Users size={17}/> {student.nickname}</span><span>{student.completed} / {student.total} submitted</span></div><progress value={student.completed} max={student.total} aria-label="Your annotation progress"/>{student.post?<section className="panel post-card"><div className="eyebrow">COMMON GROUND / MODERATION QUEUE</div><div className="post-meta"><span className="avatar">cg</span><span>Community post<small>Fictional classroom content</small></span></div><blockquote key={student.post.assignment_id}>{student.post.text}</blockquote><div className="decision-label">Apply the policy. What happens to this post?</div><div className="label-actions"><button className="allow" disabled={busy} onClick={()=>void act(async()=>{await api(`/rooms/${session.code}/labels`,session,{assignment_id:student.post!.assignment_id,label:'allow'});await refresh()})}><Check size={24}/>Allow</button><button className="remove" disabled={busy} onClick={()=>void act(async()=>{await api(`/rooms/${session.code}/labels`,session,{assignment_id:student.post!.assignment_id,label:'remove'});await refresh()})}><X size={24}/>Remove</button></div><p className="fine">{busy?'Saving your decision…':'Decisions are final for this shift. No correctness feedback.'}</p></section>:<section className="panel waiting"><Layers3 size={38}/><h2>{student.completed===student.total?'Your queue is complete.':student.phase==='complete'?'The annotation shift has ended.':student.phase==='paused'?'Take a breath. The shift is paused.':'You’re on the team.'}</h2><p className="muted">{student.phase==='complete'?'Your decisions are saved. Waiting for your instructor to open training.':student.completed===student.total?'Your work is saved. Other annotators may still be working.':student.phase==='paused'?'Your submitted labels are saved. Your instructor will resume the queue.':'Read the shared policy while your instructor prepares the shift.'}</p></section>}<p className="queue-note">You are creating training data. Another person may interpret the same post differently.</p></section><PolicyCard policy={student.policy}/></div>}
    </>}
    </main><footer><span>THE TRUE COST OF AI</span><span>Behind the interface, there is a world of work.</span><span>HUMAN LABOR · MATERIAL INFRASTRUCTURE</span></footer>
  </div>
}
function PolicyCard({policy}:{policy:Policy}){return <aside className="panel policy"><div className="eyebrow">THE SHARED STANDARD</div><h2>{policy.title}</h2><p className="muted">{policy.intro}</p><ol>{policy.rules.map(rule=><li key={rule}>{rule}</li>)}</ol><p className="fine">A moderation policy reflects choices and values. It is not a universal moral standard.</p></aside>}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>)
