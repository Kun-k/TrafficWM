"""Web-based real-time viewer for CityNDE interactive simulator.

Serves a browser UI and provides a thread-safe action queue consumed by the
simulation thread. Most actions are paused-only; rate editing and vehicle-id
 display toggle are available at any time.
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque

import cv2
import numpy as np
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

_HTML = r"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CityNDE Interactive UI</title>
<style>
:root{
  --bg:#0c141d;
  --bg2:#142435;
  --panel:#0f1e2c;
  --panel2:#15283a;
  --border:#2e4d67;
  --accent:#40d7ff;
  --accent2:#00ffbd;
  --warn:#ff7f50;
  --text:#e8f3ff;
  --muted:#97abc0;
}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Trebuchet MS','Segoe UI',sans-serif;color:var(--text);background:
  radial-gradient(1200px 700px at 20% -10%, #244663 0%, transparent 60%),
  radial-gradient(900px 500px at 100% 0%, #173655 0%, transparent 55%),
  linear-gradient(160deg, var(--bg) 0%, var(--bg2) 100%);
  min-height:100vh;overflow:hidden}
#topbar{position:fixed;top:0;left:0;right:0;height:56px;display:flex;align-items:center;gap:14px;
  padding:0 14px;border-bottom:1px solid var(--border);background:rgba(7,17,28,.92);backdrop-filter:blur(6px);z-index:30}
#title{font-weight:700;letter-spacing:.6px}
#status{font-size:13px;color:var(--muted);flex:1}
button,select,input{background:var(--panel2);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:7px 10px;font-size:12px}
button{cursor:pointer;transition:.2s border-color,.2s background,.2s transform}
button:hover{border-color:var(--accent);transform:translateY(-1px)}
button:active{transform:translateY(0);filter:brightness(.92)}
button:disabled,input:disabled,select:disabled{background:#23303d !important;color:#7f8d9c !important;border-color:#3a4652 !important;cursor:not-allowed !important;filter:none !important}
button:disabled:hover,input:disabled:hover,select:disabled:hover{transform:none !important;border-color:#3a4652 !important}
button.primary{background:linear-gradient(135deg,#1e5b7f,#208fa9);border-color:#46c4e8}
button.warn{background:linear-gradient(135deg,#663929,#9e4b2e);border-color:#d67b58}
button.on{background:linear-gradient(135deg,#1f5a49,#227d68);border-color:#52d8b3}
#layout{position:absolute;top:56px;left:0;right:0;bottom:0;display:flex}
#left{width:min(280px,30vw);border-right:1px solid var(--border);background:rgba(8,20,34,.82);overflow:auto;padding:14px 12px 18px}
#canvasWrap{position:relative;flex:1;overflow:hidden}
#vp{position:absolute;inset:0;overflow:hidden;cursor:grab}
#vp.drag{cursor:grabbing}
#im{position:absolute;transform-origin:0 0;user-select:none;opacity:0}
.panel{background:linear-gradient(155deg,var(--panel),#0b1a28);border:1px solid var(--border);border-radius:12px;padding:12px;margin-bottom:12px;box-shadow:0 10px 25px rgba(0,0,0,.25)}
.panel h3{font-size:14px;letter-spacing:.3px;margin-bottom:10px;color:#d9f4ff}
.row{display:flex;gap:8px;margin-bottom:8px;align-items:center}
.row:last-child{margin-bottom:0}
.row label{font-size:12px;color:var(--muted);min-width:72px}
.row input,.row select{flex:1;min-width:0}
.subsec{padding:4px 0}
.sep{border:none;border-top:1px solid var(--border);margin:10px 0}
.hint{font-size:11px;color:var(--muted);line-height:1.4}
#toast{position:fixed;right:16px;bottom:16px;max-width:48vw;background:rgba(8,16,24,.95);border:1px solid var(--border);padding:10px 12px;border-radius:10px;font-size:12px;color:var(--text);display:none;z-index:40}
#toast.ok{border-color:#2ebf9a}
#toast.err{border-color:#d2736d}
@media (max-width:720px){
  #layout{flex-direction:column}
  #left{width:100%;max-height:42%;border-right:none;border-bottom:1px solid var(--border)}
}
</style></head><body>
<div id="topbar">
  <div id="title">CityNDE Interactive Control</div>
  <div id="status">Step <b id="xStep">--</b> | Vehicles <b id="xVeh">--</b> | Zoom <b id="xZoom">100%</b></div>
  <button id="btnPause" class="primary">Pause</button>
  <button id="btnResume">Resume</button>
  <button id="btnReset">Reset View</button>
</div>
<div id="layout">
  <div id="left">
    <div class="panel">
      <h3>Map</h3>
      <div class="row"><label>Map File</label><select id="mapSel"></select></div>
      <div class="row"><button id="btnMap" class="primary">Switch Map</button></div>
      <div class="hint">Only maps under <code>assets/map/</code> are allowed.</div>
    </div>

    <div class="panel">
      <h3>Spawn / Remove</h3>
      <div class="subsec">
        <div class="row"><label>Spawn Mode</label>
          <select id="spawnMode"><option value="moving">Moving</option><option value="static">Static</option></select></div>
        <div class="row"><label>Speed</label><input id="spawnSpeed" type="number" min="0" step="0.1" value="2.0"></div>
        <div class="row"><label>X</label><input id="addX" type="number" step="0.1" placeholder="0.0"></div>
        <div class="row"><label>Y</label><input id="addY" type="number" step="0.1" placeholder="0.0"></div>
        <div class="row"><label>Heading</label><input id="addH" type="number" step="0.01" placeholder="0.0 rad"></div>
        <div class="row"><button id="btnAddManual" class="primary">Add By Coord</button></div>
      </div>
      <hr class="sep">
      <div class="subsec">
        <div class="row"><label>Vehicle ID</label><input id="rmId" placeholder="id"></div>
        <div class="row"><button id="btnRm" class="warn">Remove By ID</button></div>
      </div>
      <hr class="sep">
      <div class="subsec">
        <div class="row"><label>Click Mode</label>
          <select id="clickMode"><option value="none">None</option><option value="spawn">Spawn On Click</option><option value="delete">Delete On Click</option><option value="toggle_control">Toggle Static/Simulator</option></select></div>
      </div>
      <div class="hint">Click spawn snaps to nearest lane center point and heading. Click delete removes selected vehicle. Click toggle switches vehicle between static and simulator control.</div>
    </div>
    <div class="panel">
      <h3>Display</h3>
      <div class="row"><button id="btnToggleId" data-always-enabled="1">Toggle Vehicle ID</button></div>
    </div>

    <div class="panel">
      <h3>Arrival Rate</h3>
      <div class="row"><label>Lane ID</label><input id="laneId" data-always-enabled="1" placeholder="all or lane id"></div>
      <div class="row"><label>Prob</label><input id="laneProb" data-always-enabled="1" type="number" min="0" max="1" step="0.01" value="0.04"></div>
      <div class="row"><button id="btnRate" data-always-enabled="1" class="primary">Apply Rate</button></div>
    </div>

    <div class="panel">
      <h3>Vehicle Control</h3>
      <div class="row"><label>Vehicle ID</label><input id="toggleVid" placeholder="id"></div>
      <div class="row"><button id="btnToggleCtl" class="primary">Toggle Static/Simulator</button></div>
      <div class="hint">Switches vehicle between "keep static at current position" and "simulator-controlled" modes. You can also use Click Mode.</div>
    </div>

    <div class="panel">
      <h3>Advanced PKL</h3>
      <div class="row"><label>PKL Path</label><input id="pklPath" placeholder="relative to workspace, e.g. output/a.pkl"></div>
      <div class="row"><label>Vehicle ID</label><input id="ctlVid" placeholder="optional for add"></div>
      <div class="row"><label>Horizon</label><input id="ctlH" type="number" min="1" step="1" value="20"></div>
      <div class="row"><button id="btnPklAdd" class="primary">Add From PKL</button><button id="btnPklCtl">Control From PKL</button></div>
      <div class="hint">Supports existing scenario pkl and simplified <code>{"ops": [...]}</code> format.</div>
    </div>
  </div>

  <div id="canvasWrap">
    <div id="vp"><img id="im" src="" draggable="false"></div>
  </div>
</div>
<div id="toast"></div>
<script>
let s=1,tx=0,ty=0,drag=false,lastX=0,lastY=0,firstFit=false,resetViewPending=false;
let statusBusy=false, frameBusy=false;
let paused=false, pausePending=false, resumePending=false, pauseRequestedAtMs=0;

function applyEditAvailability(editAllowed){
  document.querySelectorAll('#left button, #left input, #left select').forEach(el=>{
    const alwaysEnabled=el.dataset.alwaysEnabled==='1';
    const locked=(!editAllowed && !alwaysEnabled);
    el.disabled=locked;
  });
  const btnPause=document.getElementById('btnPause');
  const btnResume=document.getElementById('btnResume');
  btnPause.disabled=!!editAllowed || pausePending || resumePending;
  btnResume.disabled=!editAllowed || pausePending || resumePending;
  syncSpawnModeUI();
}

function updatePauseButtons(){
  const btnPause=document.getElementById('btnPause');
  if(pausePending && !paused){
    btnPause.className='on';
    btnPause.textContent='Pausing...';
    return;
  }
  if(resumePending && paused){
    btnPause.className='';
    btnPause.textContent='Resuming...';
    return;
  }
  btnPause.className=paused?'on':'';
  btnPause.textContent=paused?'Paused':'Pause';
}
const vp=document.getElementById('vp');
const im=document.getElementById('im');

function setToast(msg, ok=true){
  const t=document.getElementById('toast');
  t.className=ok?'ok':'err';
  t.textContent=msg;
  t.style.display='block';
  setTimeout(()=>{t.style.display='none'},2200);
}

function updateTransform(){
  im.style.transform=`translate(${tx}px,${ty}px) scale(${s})`;
  document.getElementById('xZoom').textContent=`${Math.round(s*100)}%`;
}

function detectContentBounds(){
  const iw=im.naturalWidth||1024, ih=im.naturalHeight||1024;
  const c=document.createElement('canvas');
  c.width=iw; c.height=ih;
  const ctx=c.getContext('2d', {willReadFrequently:true});
  if(!ctx) return {x:0,y:0,w:iw,h:ih};
  ctx.drawImage(im,0,0,iw,ih);
  const img=ctx.getImageData(0,0,iw,ih).data;
  let minX=iw, minY=ih, maxX=-1, maxY=-1;
  const step=Math.max(1, Math.floor(Math.min(iw, ih)/512));
  for(let y=0;y<ih;y+=step){
    for(let x=0;x<iw;x+=step){
      const i=(y*iw+x)*4;
      // Treat near-black pixels as background.
      if((img[i] + img[i+1] + img[i+2]) > 18){
        if(x<minX) minX=x;
        if(y<minY) minY=y;
        if(x>maxX) maxX=x;
        if(y>maxY) maxY=y;
      }
    }
  }
  if(maxX < minX || maxY < minY) return {x:0,y:0,w:iw,h:ih};
  const pad=8;
  minX=Math.max(0, minX-pad);
  minY=Math.max(0, minY-pad);
  maxX=Math.min(iw-1, maxX+pad);
  maxY=Math.min(ih-1, maxY+pad);
  return {x:minX, y:minY, w:Math.max(1, maxX-minX+1), h:Math.max(1, maxY-minY+1)};
}

function getMinScale(bounds=null){
  const cw=vp.clientWidth, ch=vp.clientHeight;
  const iw=(bounds && bounds.w) ? bounds.w : (im.naturalWidth||1024);
  const ih=(bounds && bounds.h) ? bounds.h : (im.naturalHeight||1024);
  return Math.min(cw/iw, ch/ih);
}

function fitImage(){
  const cw=vp.clientWidth, ch=vp.clientHeight;
  const b=detectContentBounds();
  s=getMinScale(b);
  tx=(cw-b.w*s)/2 - b.x*s;
  ty=(ch-b.h*s)/2 - b.y*s;
  updateTransform();
}

function fitImageFull(){
  const cw=vp.clientWidth, ch=vp.clientHeight;
  const iw=im.naturalWidth||1024, ih=im.naturalHeight||1024;
  s=Math.min(cw/iw, ch/ih);
  tx=(cw-iw*s)/2;
  ty=(ch-ih*s)/2;
  updateTransform();
}

function resetView(){
  // If no frame is loaded yet, defer reset until image onload so one click is enough.
  if((im.naturalWidth||0)<=0 || (im.naturalHeight||0)<=0){
    resetViewPending=true;
    return;
  }
  resetViewPending=false;
  firstFit=false;
  fitImage();
  firstFit=true;
}

function handleViewportResize(){
  if(!firstFit) return;
  const oldW=window.__vpW||vp.clientWidth;
  const oldH=window.__vpH||vp.clientHeight;
  const newW=vp.clientWidth;
  const newH=vp.clientHeight;
  if(oldW<=0 || oldH<=0 || newW<=0 || newH<=0){
    window.__vpW=newW;
    window.__vpH=newH;
    return;
  }

  // Keep the same world point at viewport center after resize.
  const worldCx=(oldW*0.5 - tx)/s;
  const worldCy=(oldH*0.5 - ty)/s;
  const minScale=getMinScale();
  if(s<minScale) s=minScale;
  tx=newW*0.5 - worldCx*s;
  ty=newH*0.5 - worldCy*s;
  updateTransform();
  window.__vpW=newW;
  window.__vpH=newH;
}

im.onload=()=>{
  if(resetViewPending){
    resetView();
  }else if(!firstFit){
    fitImage();
    firstFit=true;
  }
  window.__vpW=vp.clientWidth;
  window.__vpH=vp.clientHeight;
  im.style.opacity='1';
};

vp.addEventListener('wheel',(e)=>{
  e.preventDefault();
  const r=vp.getBoundingClientRect();
  const mx=e.clientX-r.left,my=e.clientY-r.top;
  const os=s;
  s*=e.deltaY<0?1.12:1/1.12;
  const minScale=getMinScale();
  s=Math.max(minScale,Math.min(80,s));
  tx=mx-(mx-tx)*s/os;
  ty=my-(my-ty)*s/os;
  updateTransform();
},{passive:false});
vp.addEventListener('mousedown',(e)=>{drag=true;lastX=e.clientX;lastY=e.clientY;vp.classList.add('drag')});
window.addEventListener('mousemove',(e)=>{if(!drag)return;tx+=e.clientX-lastX;ty+=e.clientY-lastY;lastX=e.clientX;lastY=e.clientY;updateTransform();});
window.addEventListener('mouseup',()=>{drag=false;vp.classList.remove('drag')});
window.addEventListener('resize',handleViewportResize);

document.getElementById('btnReset').onclick=()=>{resetView()};

document.getElementById('btnPause').onclick=()=>{
  if(paused || pausePending) return;
  pausePending=true;
    pauseRequestedAtMs=Date.now();
  resumePending=false;
  updatePauseButtons();
  applyEditAvailability(false);
  postJson('/pause',{}).then(r=>{
    if(!r || r.ok===false){
      pausePending=false;
      pauseRequestedAtMs=0;
      updatePauseButtons();
      applyEditAvailability(paused);
      noticeResult(r);
      return;
    }
    noticeResult(r);
  });
};
document.getElementById('btnResume').onclick=()=>{
  if((!paused && !pausePending) || resumePending) return;
  const clickModeSel=document.getElementById('clickMode');
  if(clickModeSel) clickModeSel.value='none';
  syncSpawnModeUI();
  resumePending=true;
  pausePending=false;
    pauseRequestedAtMs=0;
  updatePauseButtons();
  applyEditAvailability(false);
  postJson('/resume',{}).then(r=>{
    if(!r || r.ok===false){
      resumePending=false;
      updatePauseButtons();
      applyEditAvailability(paused);
      noticeResult(r);
      return;
    }
    noticeResult(r);
  });
};

document.getElementById('btnMap').onclick=()=>{
  const sel=document.getElementById('mapSel');
  if(!window.confirm('Are you sure you want to switch map? This may remove off-road vehicles.')) return;
  postJson('/action',{type:'switch_map', map_path: sel.value}).then(r=>noticeResult(r));
};

document.getElementById('btnRate').onclick=()=>{
  const lane=(document.getElementById('laneId').value||'').trim();
  const prob=parseFloat(document.getElementById('laneProb').value);
  postJson('/action',{type:'set_rate', lane_id: lane===''?'all':lane, prob: prob}).then(r=>noticeResult(r));
};

document.getElementById('btnRm').onclick=()=>{
  const vid=(document.getElementById('rmId').value||'').trim();
  validateThenConfirm(
    {type:'remove_vehicle', vehicle_id: vid},
    'Are you sure you want to delete this vehicle by ID?'
  );
};

document.getElementById('btnToggleId').onclick=()=>postJson('/action',{type:'toggle_vehicle_id'}).then(r=>noticeResult(r));
document.getElementById('btnAddManual').onclick=()=>{
  const x=parseFloat(document.getElementById('addX').value);
  const y=parseFloat(document.getElementById('addY').value);
  const h=parseFloat(document.getElementById('addH').value);
  const spawnMode=document.getElementById('spawnMode').value;
  const speed=parseFloat(document.getElementById('spawnSpeed').value||'2.0');
  validateThenConfirm(
    {type:'add_vehicle_manual',x:x,y:y,heading:h,spawn_mode:spawnMode,speed:speed},
    'Are you sure you want to add a vehicle at this location?'
  );
};

document.getElementById('btnPklAdd').onclick=()=>{
  const p=(document.getElementById('pklPath').value||'').trim();
  const vid=(document.getElementById('ctlVid').value||'').trim();
  postJson('/action',{type:'advanced_add_from_pkl', pkl_path:p, vehicle_id: vid===''?null:vid}).then(r=>noticeResult(r));
};

document.getElementById('btnPklCtl').onclick=()=>{
  const p=(document.getElementById('pklPath').value||'').trim();
  const vid=(document.getElementById('ctlVid').value||'').trim();
  const hz=parseInt(document.getElementById('ctlH').value||'20');
  postJson('/action',{type:'advanced_control_from_pkl', pkl_path:p, vehicle_id: vid===''?null:vid, horizon: hz}).then(r=>noticeResult(r));
};



document.getElementById('btnToggleCtl').onclick=()=>{
  const vid=(document.getElementById('toggleVid').value||'').trim();
  validateThenConfirm(
    {type:'toggle_vehicle_control_mode', vehicle_id: vid},
    'Are you sure you want to toggle this vehicle between static and simulator control?'
  );
};

document.getElementById('spawnSpeed').addEventListener('change',()=>{
  const v=parseFloat(document.getElementById('spawnSpeed').value);
  postJson('/action',{type:'set_default_spawn_speed', speed:v}).then(()=>{});
});

function syncSpawnModeUI(){
  const spawnMode=document.getElementById('spawnMode').value;
  const clickMode=document.getElementById('clickMode').value;
  const spd=document.getElementById('spawnSpeed');
  const enableSpeed=(paused===true && clickMode==='spawn' && spawnMode==='moving');
  spd.disabled=!enableSpeed;
  if(!enableSpeed){
    spd.classList.add('is-static');
  }else{
    spd.classList.remove('is-static');
  }
}
  document.getElementById('spawnMode').addEventListener('change',syncSpawnModeUI);
  document.getElementById('clickMode').addEventListener('change',syncSpawnModeUI);

vp.addEventListener('click',(e)=>{
  if(drag) return;
  const mode=document.getElementById('clickMode').value;
  if(mode==='none') return;
  const rect=vp.getBoundingClientRect();
  const clickX=e.clientX-rect.left;
  const clickY=e.clientY-rect.top;
  const spawnMode=document.getElementById('spawnMode').value;
  const spd=parseFloat(document.getElementById('spawnSpeed').value||'2.0');
  const payload={
    type:'canvas_click',
    click_mode:mode,
    spawn_mode:spawnMode,
    click_x:clickX,
    click_y:clickY,
    scale:s,
    tx:tx,
    ty:ty,
    image_w:im.naturalWidth||1024,
    image_h:im.naturalHeight||1024,
    speed:spd,
  };
  const confirmMsg=(mode==='spawn')
    ? 'Are you sure you want to add a vehicle at this clicked location?'
    : (mode==='delete')
      ? 'Are you sure you want to delete the clicked vehicle?'
      : 'Are you sure you want to toggle static/simulator mode for the clicked vehicle?';
  validateThenConfirm(payload, confirmMsg);
});

function noticeResult(r){
  if(!r) return;
  if(r.ok===false){
        if((r.error||'')==='CLICK_OUT_OF_RANGE') return;
        setToast(r.error||'Failed', false);
        refreshStatus();
        return;
      }
  if(r.message && r.message !== 'Action queued'){ setToast(r.message, true); }
  refreshStatus();
  refreshFrame();
}

async function validateThenConfirm(actionPayload, confirmMessage){
  const checkPayload=Object.assign({}, actionPayload, {dry_run:true});
  const check=await postJson('/action', checkPayload);
  if(!check || check.ok===false){
      if(check && (check.error||'')==='CLICK_OUT_OF_RANGE') return;
      noticeResult(check);
      return;
    }
  if(!window.confirm(confirmMessage)) return;
  const execRes=await postJson('/action', actionPayload);
  noticeResult(execRes);
}

async function postJson(url,obj){
  try{
    const res=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(obj)});
    return await res.json();
  }catch(err){
    setToast('Network error',false);
    return {ok:false,error:String(err)};
  }
}

async function refreshStatus(){
  if(statusBusy) return;
  statusBusy=true;
  try{
    const d=await (await fetch('/status')).json();
    const serverPaused=!!d.paused;
    const serverPausePending=!!d.pause_pending && !serverPaused;

    paused=serverPaused;
    // Keep local pause pending latched until backend confirms paused.
    if(serverPaused){
      pausePending=false;
      pauseRequestedAtMs=0;
    }else{
      pausePending=!!pausePending || serverPausePending;
      // Only clear local pending when there is no active pause request anymore.
      if(!serverPausePending && pauseRequestedAtMs===0){
        pausePending=false;
      }
    }
    // Keep resumePending until backend actually leaves paused state.
    if(resumePending && !serverPaused){
      resumePending=false;
    }

    document.getElementById('xStep').textContent=d.step;
    document.getElementById('xVeh').textContent=d.vehicles;
    updatePauseButtons();
    const idBtn=document.getElementById("btnToggleId");
    if(d.show_vehicle_id){
      idBtn.classList.add("on");
      idBtn.textContent="Vehicle ID: ON";
    }else{
      idBtn.classList.remove("on");
      idBtn.textContent="Vehicle ID: OFF";
    }
    if(typeof d.default_spawn_speed==='number'){
      const inp=document.getElementById('spawnSpeed');
      if(document.activeElement!==inp) inp.value=String(d.default_spawn_speed);
    }
    if(d.last_error_nonce && d.last_error_nonce!==lastErrorNonce){
      lastErrorNonce=d.last_error_nonce;
      if(d.last_error){ window.alert(d.last_error); }
    }
    applyEditAvailability(serverPaused && !resumePending);
  }catch(err){}
  statusBusy=false;
}

async function refreshMaps(){
  try{
    const d=await (await fetch('/maps')).json();
    const sel=document.getElementById('mapSel');
    const cur=sel.value;
    sel.innerHTML='';
    (d.maps||[]).forEach(m=>{ const o=document.createElement('option'); o.value=m; o.textContent=m; sel.appendChild(o); });
    if(cur) sel.value=cur;
  }catch(err){}
}

function refreshFrame(){
  if(frameBusy) return;
  frameBusy=true;
  const ni=new Image();
  ni.onload=()=>{im.src=ni.src;frameBusy=false};
  ni.onerror=()=>{frameBusy=false};
  ni.src='/frame.jpg?'+Date.now();
}

setInterval(()=>{refreshStatus();refreshFrame();},300);
setInterval(()=>{refreshMaps();},3000);
syncSpawnModeUI();
applyEditAvailability(false);
refreshStatus();refreshFrame();refreshMaps();
</script></body></html>"""


class _FastThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128


class WebViewer:
    def __init__(self, mode: str, port: int = 8890):
        self.port = int(port)
        self._latest_jpg: bytes | None = None
        self._status = {
            "step": 0,
            "vehicles": 0,
            "mode": mode,
            "paused": False,
            "default_spawn_speed": 2.0,
            "pause_pending": False,
            "last_error": "",
            "last_error_nonce": 0,
        }
        self._pause_flag = False
        self._resume_flag = False
        self._action_queue: deque[dict] = deque()
        self._action_seq: int = 0
        self._action_results: dict[int, dict] = {}
        self._maps: list[str] = []
        self._state_lock = threading.Lock()
        self._action_cv = threading.Condition(self._state_lock)

        viewer = self

        class Handler(BaseHTTPRequestHandler):
            def _write_json(self, payload: dict, code: int = 200):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)

            def _read_json(self) -> dict:
                size = int(self.headers.get("Content-Length", "0"))
                if size <= 0:
                    return {}
                raw = self.rfile.read(size)
                if not raw:
                    return {}
                return json.loads(raw.decode("utf-8"))

            def do_GET(self):
                try:
                    if self.path in ("/", "/index.html"):
                        body = _HTML.encode("utf-8")
                        self.send_response(200)
                        self.send_header("Content-Type", "text/html; charset=utf-8")
                        self.send_header("Content-Length", str(len(body)))
                        self.send_header("Connection", "close")
                        self.end_headers()
                        self.wfile.write(body)
                        return

                    if self.path.startswith("/frame.jpg"):
                        with viewer._state_lock:
                            data = viewer._latest_jpg
                        if data is None:
                            self.send_response(204)
                            self.send_header("Connection", "close")
                            self.end_headers()
                            return
                        self.send_response(200)
                        self.send_header("Content-Type", "image/jpeg")
                        self.send_header("Content-Length", str(len(data)))
                        self.send_header("Cache-Control", "no-store")
                        self.send_header("Connection", "close")
                        self.end_headers()
                        self.wfile.write(data)
                        return

                    if self.path == "/status":
                        with viewer._state_lock:
                            status = dict(viewer._status)
                        self._write_json(status)
                        return

                    if self.path == "/maps":
                        with viewer._state_lock:
                            maps = list(viewer._maps)
                        self._write_json({"ok": True, "maps": maps})
                        return

                    self.send_response(404)
                    self.send_header("Connection", "close")
                    self.end_headers()
                except BrokenPipeError:
                    return
                except Exception as exc:
                    try:
                        self._write_json({"ok": False, "error": str(exc)}, code=500)
                    except Exception:
                        pass

            def do_POST(self):
                try:
                    if self.path == "/pause":
                        with viewer._state_lock:
                            viewer._pause_flag = True
                            viewer._resume_flag = False
                            viewer._status["pause_pending"] = True
                        self._write_json({"ok": True, "message": "Pause requested"})
                        return

                    if self.path == "/resume":
                        with viewer._state_lock:
                            # Clear any stale pause request regardless of current paused state.
                            viewer._pause_flag = False
                            viewer._status["pause_pending"] = False
                            if bool(viewer._status.get("paused", False)):
                                viewer._resume_flag = True
                                msg = "Resume requested"
                            else:
                                viewer._resume_flag = False
                                msg = "Already running"
                        self._write_json({"ok": True, "message": msg})
                        return

                    if self.path == "/action":
                        payload = self._read_json()
                        act_type = str(payload.get("type", "")).strip().lower()
                        allow_when_running = {"set_rate", "toggle_vehicle_id"}
                        with viewer._state_lock:
                            paused = bool(viewer._status.get("paused", False))
                            if (not paused) and act_type not in allow_when_running:
                                self._write_json(
                                    {
                                        "ok": False,
                                        "error": "This action is only available while paused",
                                    },
                                    code=400,
                                )
                                return
                            viewer._action_seq += 1
                            sync_id = viewer._action_seq
                            payload["_sync_id"] = sync_id
                            viewer._action_queue.append(payload)
                            deadline = time.time() + 4.0
                            result = None
                            while True:
                                result = viewer._action_results.pop(sync_id, None)
                                if result is not None:
                                    break
                                remaining = deadline - time.time()
                                if remaining <= 0:
                                    break
                                viewer._action_cv.wait(timeout=remaining)
                        if result is None:
                            self._write_json({"ok": True, "message": "Request accepted"})
                        else:
                            self._write_json(result)
                        return

                    self.send_response(404)
                    self.send_header("Connection", "close")
                    self.end_headers()
                except BrokenPipeError:
                    return
                except Exception as exc:
                    try:
                        self._write_json({"ok": False, "error": str(exc)}, code=500)
                    except Exception:
                        pass

            def log_message(self, format, *args):
                pass

        self._server = _FastThreadingHTTPServer(("0.0.0.0", self.port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

        print(f"\n{'=' * 60}")
        print("  [WebViewer] Interactive UI started")
        print(f"  Open in browser: http://localhost:{self.port}")
        print(f"{'=' * 60}\n")

    def update(
        self,
        frame: np.ndarray,
        step: int,
        vehicle_count: int,
        mode: str,
        paused: bool,
        extra_status: dict | None = None,
    ):
        _, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        with self._state_lock:
            self._latest_jpg = jpg.tobytes()
            self._status.update(
                {
                    "step": int(step),
                    "vehicles": int(vehicle_count),
                    "mode": str(mode),
                    "paused": bool(paused),
                }
            )
            if extra_status:
                self._status.update(extra_status)

    def set_maps(self, maps: list[str]):
        with self._state_lock:
            self._maps = list(maps)

    def set_status_fields(self, fields: dict):
        with self._state_lock:
            self._status.update(fields)

    @property
    def pause_requested(self) -> bool:
        with self._state_lock:
            if self._pause_flag:
                self._pause_flag = False
                return True
        return False

    @property
    def resume_requested(self) -> bool:
        with self._state_lock:
            if self._resume_flag:
                self._resume_flag = False
                return True
        return False

    def pop_action(self) -> dict | None:
        with self._state_lock:
            if self._action_queue:
                return self._action_queue.popleft()
        return None

    def set_action_result(self, sync_id: int | None, result: dict):
        if sync_id is None:
            return
        with self._action_cv:
            self._action_results[int(sync_id)] = dict(result)
            self._action_cv.notify_all()

    def set_paused(self, paused: bool):
        with self._state_lock:
            p = bool(paused)
            self._status["paused"] = p
            if p:
                self._status["pause_pending"] = False

    def close(self):
        self._server.shutdown()
        self._server.server_close()
        print("[WebViewer] Server stopped.")
