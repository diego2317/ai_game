import { useEffect, useRef, useState } from 'react'
import { Clock3, RotateCcw, Users } from 'lucide-react'
import { api, requestId, type Session } from './api'
import { TeamWorkshop, type Economy } from './gameplay'
export type Timing = {elapsed_seconds:number;recommended_seconds:number|null;paused:boolean}

export function PhaseClock({timing}:{timing:Timing}){
  const [,tick]=useState(0)
  const stamp=useRef({timing,received:Date.now()})
  if(stamp.current.timing!==timing)stamp.current={timing,received:Date.now()}
  useEffect(()=>{const timer=setInterval(()=>tick(n=>n+1),1000);return()=>clearInterval(timer)},[])
  if(timing.recommended_seconds==null)return null
  const elapsed=timing.elapsed_seconds+(timing.paused?0:(Date.now()-stamp.current.received)/1000)
  const left=Math.ceil(timing.recommended_seconds-elapsed)
  const seconds=Math.abs(left)
  return <div className={`phase-clock ${left<0?'overtime':''}`}><Clock3 size={16}/><strong>{left<0?'+':''}{Math.floor(seconds/60)}:{String(seconds%60).padStart(2,'0')}</strong><span>{timing.paused?'Paused':left<0?'Past suggested time':'Suggested time left'} · instructor advances</span></div>
}

export function ClassroomTools({session,generation,demo,phase,teams,refresh}:{session:Session;generation:number;demo:boolean;phase:string;teams:{id:number;name:string;economy:Economy}[];refresh:()=>Promise<void>}){
  const [busy,setBusy]=useState(false)
  const [feedback,setFeedback]=useState('')
  const [team,setTeam]=useState(0)
  const active=useRef(false)
  const pendingReset=useRef<string|null>(null)
  async function act(fn:()=>Promise<string>){if(active.current)return;active.current=true;setBusy(true);setFeedback('');try{setFeedback(await fn());await refresh()}catch(e){setFeedback((e as Error).message)}finally{setBusy(false);active.current=false}}
  const selected=teams.find(t=>t.id===team)!
  return <>
  <div className="classroom-tools"><span className="fine">{demo?'DEMO · all participant labels and task times are simulated. Model training is real.':'Live room · participants stay connected after a reset.'}</span><button className="text-button reset-button" disabled={busy} onClick={()=>{
    const confirmation=prompt(`Reset this room? Labels, audits, purchases, and models will be cleared. Student sessions and room settings stay. ${demo?'Demo labels will be reloaded. ':''}Type ${session.code} to confirm.`)
    if(confirmation===null)return
    void act(async()=>{pendingReset.current ||= requestId();await api(`/rooms/${session.code}/reset`,session,{confirmation,generation,request_id:pendingReset.current});pendingReset.current=null;return 'Room reset. Everyone is back in the waiting room.'})
  }}><RotateCcw size={14}/>Reset room</button></div>{feedback&&<p className="tool-feedback" role="status">{feedback}</p>}
  {demo&&<section className="demo-banner"><div><Users size={21}/><div><strong>Demonstration room</strong><p>15 simulated annotators, scripted labels and task times. No human labor is claimed. Use the normal phase controls to train and compare real classifiers.</p></div></div>{['annotation','training'].includes(phase)&&<button className="secondary" disabled={busy} onClick={()=>void act(async()=>{const result=await api<{simulated_annotations:number}>(`/rooms/${session.code}/demo/annotate`,session,{});return `${result.simulated_annotations} additional scripted labels loaded.`})}>Simulate pending annotations</button>}</section>}
  {demo&&phase==='training'&&<details className="demo-controls"><summary>Demonstrate team investments & auditing</summary><label>Simulated company<select aria-label="Simulated company" value={team} onChange={e=>setTeam(Number(e.target.value))}>{teams.map(t=><option value={t.id} key={t.id}>{t.name}</option>)}</select></label><TeamWorkshop key={team} session={session} economy={selected.economy} refresh={refresh}/></details>}
  </>
}
