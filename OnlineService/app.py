"""Private optional AI helper. API credentials stay on the service."""
import os, time
from collections import defaultdict, deque
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import httpx

app=FastAPI(title="Trong Dung Studio AI + License",version="51.0.0")

# GitHub Pages is a static cross-origin Admin client. Restrict CORS to the
# explicitly configured trusted Admin origin(s) rather than enabling wildcard.
# E.g. ADMIN_ALLOWED_ORIGINS=https://example.github.io
allowed_admin_origins = [origin.strip().rstrip('/') for origin in
                         os.getenv('ADMIN_ALLOWED_ORIGINS','').split(',') if origin.strip()]
if allowed_admin_origins:
    from urllib.parse import urlsplit
    if any(urlsplit(origin).scheme != 'https' or not urlsplit(origin).hostname or urlsplit(origin).path not in ('','/') or
           urlsplit(origin).username or urlsplit(origin).password or urlsplit(origin).query or
           urlsplit(origin).fragment for origin in allowed_admin_origins):
        raise RuntimeError('ADMIN_ALLOWED_ORIGINS must list HTTPS origins only')
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_admin_origins,
        allow_credentials=False,
        allow_methods=['GET', 'POST', 'DELETE', 'OPTIONS'],
        allow_headers=['Authorization', 'Content-Type'],
        max_age=600
    )
hits=defaultdict(deque)
class Analyze(BaseModel):
    task:str=Field(min_length=3,max_length=12000)
    context:str=Field(default="",max_length=24000)
    sha256:str|None=Field(default=None,pattern=r"^[0-9a-fA-F]{64}$")

@app.get('/health')
async def health():
    return {"status":"ok","service":"aov-private-assistant","ai_configured":bool(os.getenv('OPENAI_API_KEY'))}

@app.middleware('http')
async def limit_requests(request:Request,call_next):
    # License users may share a proxy IP: never apply the old AI-only global throttle to them.
    if request.url.path.startswith(('/v1/license/', '/v1/admin/', '/admin')):
        return await call_next(request)
    key=request.client.host if request.client else 'unknown'; now=time.time(); q=hits[key]
    while q and now-q[0]>60:q.popleft()
    cap=30
    if len(q)>=cap: return JSONResponse(status_code=429,content={'detail':'Rate limit exceeded'})
    q.append(now); return await call_next(request)

@app.post('/v1/analyze')
async def analyze(body:Analyze,request:Request):
    secret=os.getenv('OPENAI_API_KEY'); model=os.getenv('OPENAI_MODEL','gpt-4.1-mini')
    if not secret: raise HTTPException(503,'AI backend is not configured')
    if request.headers.get('x-aov-client-token') != os.getenv('AOV_CLIENT_TOKEN','') or not os.getenv('AOV_CLIENT_TOKEN'):
        raise HTTPException(401,'Client token missing or invalid')
    prompt=('You assist with safe Arena of Valor MOD resource analysis. Do not claim game validation. '
            'Never infer encryption keys or recommend blind Unity/Wwise rewrites. Give actionable, bounded steps.\n'
            f"Task: {body.task}\nContext: {body.context}\nSource SHA256: {body.sha256 or 'not provided'}")
    async with httpx.AsyncClient(timeout=45) as client:
        response=await client.post('https://api.openai.com/v1/responses',headers={'Authorization':f'Bearer {secret}'},json={'model':model,'input':prompt,'max_output_tokens':1200})
    if response.status_code>=400: raise HTTPException(502,'AI provider request failed')
    data=response.json(); text='\n'.join(x.get('text','') for item in data.get('output',[]) for x in item.get('content',[]) if x.get('type')=='output_text')
    return {'answer':text,'model':model,'source_sha256':body.sha256,'runtime_verified':False}

# Build50 server-side licensing. Existing AI advisor remains available.
from license_service import router as license_router
app.include_router(license_router)
