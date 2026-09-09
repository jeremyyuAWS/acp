import React from 'react'
import { createRoot } from 'react-dom/client'
import RemediationAutoRelease from '../src/RemediationAutoRelease.jsx'
import '../src/styles.css'
const destination = {provider:'sharepoint',folder_id:'fixture-folder',folder_name:'Accessibility releases'}
const preview = {available:true,run_id:'fixture-execution',destination,destination_label:'SharePoint / Accessibility releases',authorization:null}
let state=preview
window.fixtureReleaseActions=[]
const client={
 get:async()=>state,
 enable:async(scan,intent)=>{window.fixtureReleaseActions.push({action:'enable',scan,intent});state={...preview,authorization:{id:'fixture-auth',status:'active',run_id:preview.run_id,files:intent.files,destination_label:preview.destination_label,progress:{published:1,pending:1,blocked:0,failed:0}}};return state},
 stop:async(scan,id)=>{window.fixtureReleaseActions.push({action:'stop',scan,id});state={...state,authorization:{...state.authorization,status:'stopped'}};return state},
}
createRoot(document.getElementById('root')).render(<main style={{maxWidth:900,margin:'20px auto',padding:12}}><RemediationAutoRelease scanId="fixture-scan" files={['report.docx','slides.pptx']} client={client}/></main>)
