import React, { useState } from 'react'
import { createRoot } from 'react-dom/client'
import Choices from '../src/RemediationPlanChoices.jsx'
import PlanRelease from '../src/RemediationReleasePlan.jsx'
import LiveRelease from '../src/RemediationAutoRelease.jsx'
import { authorizeAcceptedRelease } from '../src/releasePlanIntent.js'
import '../src/styles.css'
import '../src/remediation-impact-card.css'
const destination={provider:'sharepoint',folder_id:'fixture',folder_name:'Accessibility releases'}
const planning={available:true,files:['report.docx'],source_revision:'source',destination,destination_label:'SharePoint / Accessibility releases'}
let state={available:false,run_id:null,planning,authorization:null}
window.releasePlanActions=[]
const client={get:async()=>state,enable:async(scan,request)=>{window.releasePlanActions.push({action:'release',request});state={...state,authorization:{id:'auth',status:'active',run_id:request.run_id,request_id:request.request_id,source_revision:'source',files:request.files,destination_label:planning.destination_label,progress:{pending:1}}};return state.authorization},stop:async()=>{window.releasePlanActions.push({action:'stop'});state={...state,authorization:{...state.authorization,status:'stopped'}}}}
function Fixture(){
 const [intent,setIntent]=useState(null),[started,setStarted]=useState(false),[notice,setNotice]=useState('')
 const [policy,setPolicy]=useState({rule_based:2,ai:0})
 async function start(){window.releasePlanActions.push({action:'remediate'});const selected=intent;setIntent(null);setNotice(await authorizeAcceptedRelease('scan',['report.docx'],{scan_id:'scan',enqueued:1,batch_id:'accepted',snapshot_id:'source'},selected,client));setStarted(true)}
 return <main style={{maxWidth:620,margin:'20px auto',padding:12}}><h1>{started?'Live':'Plan'}</h1>{!started?<><Choices policy={policy} onChange={(key,value)=>setPolicy({...policy,[key]:value})}/><PlanRelease scanId="scan" files={['report.docx']} intent={intent} onChange={setIntent} read={client.get}/><button onClick={start}>Approve plan and start</button></>:<><p role="status">{notice}</p><LiveRelease scanId="scan" files={['report.docx']} client={client}/></>}</main>
}
createRoot(document.getElementById('root')).render(<Fixture/> )
