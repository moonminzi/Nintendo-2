import base64, hmac, json, math, os, re
import urllib.parse, urllib.request
import boto3
from botocore.config import Config

BUCKET = os.environ["BUCKET"]
TOKEN = os.environ["TOKEN"]
PREFIX = "uploads/"
s3 = boto3.client("s3", region_name="us-east-1",
                  config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}))


def resp(code, body, ctype="application/json"):
    if ctype == "application/json":
        body = json.dumps(body, ensure_ascii=False)
    return {"statusCode": code, "headers": {"Content-Type": ctype + "; charset=utf-8",
            "Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}, "body": body}


def clean(name):
    name = os.path.basename(str(name)).strip()
    name = re.sub(r'[\x00-\x1f/\\]', "_", name)
    if not name or name in (".", ".."):
        raise ValueError("bad name")
    return name[:200]


def handler(event, context):
    http = event.get("requestContext", {}).get("http", {})
    method, path = http.get("method", "GET"), event.get("rawPath", "/")
    if method == "GET" and path == "/":
        return resp(200, PAGE, "text/html")
    if method != "POST" or not path.startswith("/api/"):
        return resp(404, {"error": "not found"})
    tok = (event.get("headers") or {}).get("x-token", "")
    if not hmac.compare_digest(tok.encode(), TOKEN.encode()):
        return resp(401, {"error": "비밀번호가 틀렸어요"})
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode()
    try:
        b = json.loads(raw)
        return resp(200, ACTIONS[path[5:]](b))
    except KeyError:
        return resp(404, {"error": "unknown action"})
    except Exception as e:
        return resp(400, {"error": str(e)[:300]})


def a_list(b):
    out = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=PREFIX):
        for o in page.get("Contents", []):
            f = {"name": o["Key"][len(PREFIX):], "size": o["Size"],
                 "time": o["LastModified"].isoformat()}
            if f["name"].endswith(LINK_EXT):
                f["link"] = True
                try:
                    m = s3.head_object(Bucket=BUCKET, Key=o["Key"]).get("Metadata", {})
                    f["size"] = int(m.get("size") or -1)
                    f["host"] = m.get("host", "")
                except Exception:
                    f["size"] = -1
            out.append(f)
    return {"files": out}


LINK_EXT = ".url"
GAME_EXTS = (".nsp", ".xci", ".nsz", ".xcz", ".zip")


def fix_share_link(url):
    """공유 페이지 링크를 직접 다운로드 링크로 바꿈 (Google Drive, Dropbox)."""
    u = urllib.parse.urlparse(url)
    host = u.netloc.lower()
    if host in ("drive.google.com", "docs.google.com"):
        m = re.search(r"/d/([\w-]{10,})", u.path)
        fid = m.group(1) if m else urllib.parse.parse_qs(u.query).get("id", [None])[0]
        if fid:
            return f"https://drive.usercontent.google.com/download?id={fid}&export=download&confirm=t"
    if host.endswith("dropbox.com"):
        q = urllib.parse.parse_qs(u.query)
        q["dl"] = ["1"]
        return urllib.parse.urlunparse(u._replace(query=urllib.parse.urlencode(q, doseq=True)))
    return url


def probe(url):
    """링크를 잠깐 열어 크기와 파일 이름을 알아냄. 실패해도 괜찮음."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Range": "bytes=0-0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            h = r.headers
            size = -1
            cr = h.get("Content-Range", "")
            if "/" in cr and cr.rsplit("/", 1)[1].isdigit():
                size = int(cr.rsplit("/", 1)[1])
            elif r.status == 200 and (h.get("Content-Length") or "").isdigit():
                size = int(h["Content-Length"])
            name = ""
            cd = h.get("Content-Disposition", "")
            m = re.search(r"filename\*=(?:UTF-8'')?([^;]+)", cd, re.I) or re.search(r'filename="?([^";]+)"?', cd, re.I)
            if m:
                name = urllib.parse.unquote(m.group(1).strip())
            return size, name, (h.get("Content-Type") or "").lower(), r.geturl()
    except Exception as e:
        return -1, "", "", str(e)[:200]


def a_link(b):
    url = str(b.get("url", "")).strip()
    u = urllib.parse.urlparse(url)
    if u.scheme not in ("http", "https") or not u.netloc:
        raise ValueError("http(s):// 로 시작하는 링크를 넣어 주세요")
    url = fix_share_link(url)
    size, cd_name, ctype, _ = probe(url)
    if ctype.startswith("text/html") and 0 <= size < (1 << 20):
        raise ValueError("링크가 파일이 아니라 웹페이지예요. 직접 다운로드 링크를 넣어 주세요")
    name = str(b.get("name") or "").strip() or cd_name or \
        urllib.parse.unquote(os.path.basename(urllib.parse.urlparse(url).path)) or "game"
    name = clean(name)
    if name.endswith(LINK_EXT):
        name = name[:-len(LINK_EXT)]
    key = PREFIX + clean(name + LINK_EXT)
    s3.put_object(Bucket=BUCKET, Key=key, Body=(url + "\n").encode(), ContentType="text/plain",
                  Metadata={"size": str(size), "host": u.netloc[:100]})
    return {"ok": True, "name": name, "size": size,
            "warn": "" if name.lower().endswith(GAME_EXTS) else "파일 이름에 확장자가 없어요. 빌드할 때 내용을 보고 정해요."}


def a_start(b):
    name, size = clean(b["name"]), int(b["size"])
    part = max(64 << 20, math.ceil(size / 9000))
    r = s3.create_multipart_upload(Bucket=BUCKET, Key=PREFIX + name)
    return {"key": PREFIX + name, "uploadId": r["UploadId"], "partSize": part}


def _key(b):
    k = str(b["key"])
    if not k.startswith(PREFIX) or ".." in k:
        raise ValueError("bad key")
    return k


def a_parts(b):
    done, kw = [], {}
    while True:
        r = s3.list_parts(Bucket=BUCKET, Key=_key(b), UploadId=b["uploadId"], **kw)
        done += [{"n": p["PartNumber"], "etag": p["ETag"], "size": p["Size"]} for p in r.get("Parts", [])]
        if not r.get("IsTruncated"):
            return {"parts": done}
        kw = {"PartNumberMarker": r["NextPartNumberMarker"]}


def a_sign(b):
    k = _key(b)
    urls = {}
    for n in b["parts"][:50]:
        urls[str(int(n))] = s3.generate_presigned_url("upload_part", ExpiresIn=3600, Params={
            "Bucket": BUCKET, "Key": k, "UploadId": b["uploadId"], "PartNumber": int(n)})
    return {"urls": urls}


def a_complete(b):
    parts = sorted(({"PartNumber": int(p["n"]), "ETag": p["etag"]} for p in b["parts"]),
                   key=lambda p: p["PartNumber"])
    s3.complete_multipart_upload(Bucket=BUCKET, Key=_key(b), UploadId=b["uploadId"],
                                 MultipartUpload={"Parts": parts})
    return {"ok": True}


def a_abort(b):
    s3.abort_multipart_upload(Bucket=BUCKET, Key=_key(b), UploadId=b["uploadId"])
    return {"ok": True}


def a_delete(b):
    s3.delete_object(Bucket=BUCKET, Key=PREFIX + clean(b["name"]))
    return {"ok": True}


ACTIONS = {"list": a_list, "link": a_link, "start": a_start, "parts": a_parts, "sign": a_sign,
           "complete": a_complete, "abort": a_abort, "delete": a_delete}

PAGE = r"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>게임 업로드</title>
<style>
:root{color-scheme:light dark;--bg:#f5f5f7;--card:#fff;--fg:#1d1d1f;--mut:#6e6e73;--acc:#e60012;--line:#d2d2d7}
@media(prefers-color-scheme:dark){:root{--bg:#000;--card:#1c1c1e;--fg:#f5f5f7;--mut:#98989d;--line:#38383a}}
*{box-sizing:border-box}body{margin:0;font:17px/1.45 -apple-system,system-ui,sans-serif;background:var(--bg);color:var(--fg)}
main{max-width:640px;margin:0 auto;padding:24px 16px 48px}h1{font-size:28px;margin:8px 0 4px}
p.sub{color:var(--mut);margin:0 0 20px}.card{background:var(--card);border-radius:16px;padding:18px;margin-bottom:16px}
h2{font-size:15px;color:var(--mut);font-weight:600;margin:0 0 12px;text-transform:uppercase;letter-spacing:.04em}
label.pick{display:block;border:2px dashed var(--line);border-radius:12px;padding:28px 12px;text-align:center;cursor:pointer}
label.pick b{color:var(--acc)}input[type=file]{display:none}
button{font:inherit;border:0;border-radius:12px;padding:12px 18px;background:var(--acc);color:#fff;font-weight:600;cursor:pointer}
button.sec{background:transparent;color:var(--acc);padding:6px 8px}button:disabled{opacity:.4}
.row{display:flex;align-items:center;gap:10px;padding:10px 0;border-top:1px solid var(--line)}.row:first-child{border-top:0}
.row .n{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.row .s{color:var(--mut);font-size:14px;white-space:nowrap}
.bar{height:8px;background:var(--line);border-radius:4px;overflow:hidden;margin:6px 0}.bar i{display:block;height:100%;width:0;background:var(--acc);transition:width .3s}
.st{font-size:14px;color:var(--mut)}.err{color:var(--acc)}.empty{color:var(--mut)}
input[type=password],input[type=url],input[type=text]{font:inherit;width:100%;padding:12px;border-radius:12px;border:1px solid var(--line);background:var(--bg);color:var(--fg);margin-bottom:10px}
</style></head><body><main>
<h1>게임 업로드</h1><p class="sub">여기 올린 파일로 GitHub Actions가 IPA를 빌드해요.</p>
<div id="login" class="card" hidden><h2>비밀번호</h2><input id="pw" type="password" placeholder="비밀번호"><button id="go">들어가기</button></div>
<div id="app" hidden>
<div class="card"><h2>파일 올리기</h2>
<label class="pick"><input id="file" type="file" multiple><b>파일 선택</b><br><span class="st">.nsp .xci .nsz .xcz 또는 .zip · 본편 + 업데이트 + DLC</span></label>
<div id="jobs"></div>
<p class="st">올리는 동안 이 화면을 켜 두세요. 끊기면 같은 파일을 다시 고르면 이어서 올라가요.</p></div>
<div class="card"><h2>링크로 추가</h2>
<input id="url" type="url" inputmode="url" autocomplete="off" placeholder="https://… 직접 다운로드 링크">
<input id="lname" type="text" autocomplete="off" placeholder="파일 이름 (비우면 자동, 예: game.nsp)">
<button id="addlink">링크 추가</button><div id="linkst" class="st"></div>
<p class="st">파일을 폰에 받지 않고 링크만 저장해요. 빌드할 때 GitHub 러너가 직접 받아요. Google Drive·Dropbox 공유 링크도 돼요 (링크가 있는 모든 사용자 공개).</p></div>
<div class="card"><h2>버킷에 있는 파일</h2><div id="list" class="empty">불러오는 중…</div>
<p class="st">빌드는 여기 있는 파일을 전부 받아요. 다른 게임 파일은 지워 두세요. 14일 뒤 자동 삭제돼요.</p></div>
</div>
<script>
const $=s=>document.querySelector(s);
let token=localStorage.getItem('tok')||'';
const h=new URLSearchParams(location.hash.slice(1)).get('k');
if(h){token=h;localStorage.setItem('tok',h);history.replaceState(null,'',location.pathname)}
async function api(a,b={}){const r=await fetch('/api/'+a,{method:'POST',headers:{'Content-Type':'application/json','x-token':token},body:JSON.stringify(b)});
 const j=await r.json().catch(()=>({error:'HTTP '+r.status}));if(!r.ok)throw Object.assign(new Error(j.error||r.status),{status:r.status});return j}
const fmt=n=>n>=1<<30?(n/(1<<30)).toFixed(2)+' GB':n>=1<<20?(n/(1<<20)).toFixed(1)+' MB':(n/1024).toFixed(0)+' KB';
const esc=s=>s.replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
async function refresh(){try{const {files}=await api('list');const el=$('#list');
 if(!files.length){el.className='empty';el.textContent='아직 없어요';return}
 el.className='';el.innerHTML=files.map(f=>`<div class="row"><span class="n">${f.link?'🔗 ':''}${esc(f.link?f.name.slice(0,-4):f.name)}</span><span class="s">${f.link?(f.size>=0?'링크 · '+fmt(f.size):'링크'):fmt(f.size)}</span><button class="sec" data-n="${esc(f.name)}">삭제</button></div>`).join('');
 el.querySelectorAll('button').forEach(b=>b.onclick=async()=>{if(!confirm(b.dataset.n+' 을(를) 지울까요?'))return;await api('delete',{name:b.dataset.n});refresh()})
}catch(e){if(e.status===401)showLogin();else $('#list').textContent=e.message}}
function showLogin(){$('#app').hidden=true;$('#login').hidden=false}
function showApp(){$('#login').hidden=true;$('#app').hidden=false;refresh()}
$('#go').onclick=()=>{token=$('#pw').value.trim();localStorage.setItem('tok',token);showApp()};
let wake=null;async function lock(on){try{if(on&&!wake&&navigator.wakeLock){wake=await navigator.wakeLock.request('screen');wake.onrelease=()=>wake=null}else if(!on&&wake){await wake.release();wake=null}}catch(e){}}
let active=0;
async function upload(file){
 const row=document.createElement('div');row.innerHTML=`<div class="row"><span class="n">${esc(file.name)}</span><span class="s">${fmt(file.size)}</span></div><div class="bar"><i></i></div><div class="st">준비 중…</div>`;
 $('#jobs').appendChild(row);const bar=row.querySelector('i'),st=row.querySelector('.st');
 const sk='up:'+file.name+':'+file.size+':'+file.lastModified;let job=JSON.parse(localStorage.getItem(sk)||'null');
 active++;lock(true);
 try{
  let done=new Map();
  if(job){try{(await api('parts',job)).parts.forEach(p=>done.set(p.n,p.etag))}catch(e){job=null}}
  if(!job){job=await api('start',{name:file.name,size:file.size});localStorage.setItem(sk,JSON.stringify(job))}
  const total=Math.max(1,Math.ceil(file.size/job.partSize));const todo=[];for(let n=1;n<=total;n++)if(!done.has(n))todo.push(n);
  const t0=Date.now();let sent=done.size*job.partSize,base=sent;const prog={};
  const show=()=>{const cur=Math.min(file.size,sent+Object.values(prog).reduce((a,b)=>a+b,0));bar.style.width=(cur/file.size*100)+'%';
   const sp=(cur-base)/Math.max(1,(Date.now()-t0)/1000);st.textContent=`${fmt(cur)} / ${fmt(file.size)} · ${fmt(sp)}/s`+(sp>0?` · 남은 시간 약 ${Math.ceil((file.size-cur)/sp/60)}분`:'')};
  show();let urls={};
  const getUrl=async n=>{if(!urls[n]){const i=todo.indexOf(n);Object.assign(urls,(await api('sign',{...job,parts:todo.slice(i,i+50)})).urls)}return urls[n]};
  const putPart=n=>new Promise((res,rej)=>{getUrl(n).then(u=>{const x=new XMLHttpRequest();x.open('PUT',u);
   x.upload.onprogress=e=>{prog[n]=e.loaded;show()};x.onload=()=>{delete prog[n];if(x.status==200){const et=x.getResponseHeader('ETag');if(!et)return rej(new Error('ETag 없음'));res(et)}else{delete urls[n];rej(new Error('S3 '+x.status))}};
   x.onerror=()=>{delete prog[n];delete urls[n];rej(new Error('네트워크 오류'))};
   x.send(file.slice((n-1)*job.partSize,Math.min(file.size,n*job.partSize)))},rej)});
  let q=0;const worker=async()=>{while(q<todo.length){const n=todo[q++];let tries=0;
   for(;;){try{const et=await putPart(n);done.set(n,et);sent+=Math.min(job.partSize,file.size-(n-1)*job.partSize);show();break}
   catch(e){if(++tries>=6)throw e;st.textContent=`재시도 중 (${e.message})…`;await new Promise(r=>setTimeout(r,2000*tries))}}}};
  await Promise.all([worker(),worker(),worker(),worker()]);
  st.textContent='마무리 중…';
  await api('complete',{...job,parts:[...done].map(([n,etag])=>({n,etag}))});
  localStorage.removeItem(sk);bar.style.width='100%';st.textContent='완료 ✓';refresh();
 }catch(e){st.innerHTML=`<span class="err">실패: ${esc(e.message)}</span> — 같은 파일을 다시 고르면 이어서 올라가요.`}
 finally{if(--active===0)lock(false)}}
$('#addlink').onclick=async()=>{const st=$('#linkst'),btn=$('#addlink');const url=$('#url').value.trim();if(!url)return;
 btn.disabled=true;st.textContent='링크 확인 중…';
 try{const r=await api('link',{url,name:$('#lname').value.trim()});st.textContent=`추가됨 ✓ ${r.name}`+(r.size>=0?` (${fmt(r.size)})`:'')+(r.warn?' · '+r.warn:'');
  $('#url').value='';$('#lname').value='';refresh()}
 catch(e){if(e.status===401)showLogin();st.innerHTML=`<span class="err">실패: ${esc(e.message)}</span>`}finally{btn.disabled=false}};
$('#file').onchange=e=>{for(const f of e.target.files)upload(f);e.target.value=''};
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible'&&active)lock(true)});
token?showApp():showLogin();
</script></main></body></html>"""
