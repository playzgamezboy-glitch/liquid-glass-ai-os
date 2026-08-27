import asyncio
import html
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote, urlparse

import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

app = FastAPI(title="Thanos OS Agent Orchestrator")

AI_MODELS_CATALOG = [
    {"id":"gemini-2.5-flash","name":"Google Gemini","provider":"Google AI Studio","specialty":"Vision and multimodal analysis","free_limit":"Free tier; limits shown in Google AI Studio","url":"https://aistudio.google.com/app/apikey","status":"available"},
    {"id":"groq-llama","name":"Groq / Llama","provider":"Groq","specialty":"Fast coding and reasoning","free_limit":"Free developer access; limits shown in Groq Console","url":"https://console.groq.com/keys","status":"available"},
    {"id":"openrouter-free","name":"OpenRouter Free Models","provider":"OpenRouter","specialty":"General fallback across free open models","free_limit":"Free models vary; check limits","url":"https://openrouter.ai/keys","status":"available"},
    {"id":"mistral","name":"Mistral AI","provider":"Mistral Studio","specialty":"Coding, documents, vision, JSON, and tools","free_limit":"Free mode; limits shown in Studio","url":"https://console.mistral.ai/api-keys","status":"available"},
    {"id":"cerebras","name":"Cerebras","provider":"Cerebras Cloud","specialty":"Fast reasoning and coding","free_limit":"Trial credits may apply","url":"https://cloud.cerebras.ai/","status":"available"},
    {"id":"fireworks","name":"Fireworks AI","provider":"Fireworks Dashboard","specialty":"Open models and structured output","free_limit":"Limited introductory credits","url":"https://app.fireworks.ai/settings/users/api-keys","status":"available"},
    {"id":"kimi","name":"Kimi / Moonshot AI","provider":"Kimi Platform","specialty":"Long-context coding and tools","free_limit":"Usually paid/top-up","url":"https://platform.kimi.ai/console/api-keys","status":"paid"},
    {"id":"deepseek","name":"DeepSeek","provider":"DeepSeek Platform","specialty":"Reasoning, mathematics, and coding","free_limit":"Check current account allowance","url":"https://platform.deepseek.com/api_keys","status":"available"},
    {"id":"anthropic","name":"Anthropic Claude","provider":"Anthropic Console","specialty":"Writing, reasoning, coding, and tools","free_limit":"API billing may be required","url":"https://console.anthropic.com/settings/keys","status":"paid"},
    {"id":"openai","name":"OpenAI","provider":"OpenAI Platform","specialty":"Structured extraction, vision, coding, and agents","free_limit":"API billing may be required","url":"https://platform.openai.com/api-keys","status":"paid"},
]

CHAT_ENDPOINTS = {
    "groq-llama": "https://api.groq.com/openai/v1/chat/completions",
    "openrouter-free": "https://openrouter.ai/api/v1/chat/completions",
    "mistral": "https://api.mistral.ai/v1/chat/completions",
    "cerebras": "https://api.cerebras.ai/v1/chat/completions",
    "fireworks": "https://api.fireworks.ai/inference/v1/chat/completions",
    "kimi": "https://api.moonshot.ai/v1/chat/completions",
    "deepseek": "https://api.deepseek.com/chat/completions",
    "openai": "https://api.openai.com/v1/chat/completions",
}
MODEL_PREFERENCES = {
    "groq-llama": "llama-3.1-8b-instant", "openrouter-free": "openrouter/auto", "mistral": "mistral-small-latest",
    "cerebras": "llama3.1-8b", "fireworks": "accounts/fireworks/models/llama-v3p1-8b-instruct",
    "kimi": "moonshot-v1-8k", "deepseek": "deepseek-chat", "openai": "gpt-4o-mini"
}
MODEL_ENDPOINTS = {k: v.replace("/chat/completions", "/models") for k, v in CHAT_ENDPOINTS.items()}
PENDING_ACTIONS: Dict[str, dict] = {}

class AgentRequest(BaseModel):
    prompt: str
    mode: str = "auto"
    team_strategy: str = "collaborative"
    target_directory: Optional[str] = None
    model_id: Optional[str] = None
    api_key: Optional[str] = None
    api_keys: Dict[str, str] = Field(default_factory=dict)
    history: List[dict] = Field(default_factory=list)

class KeyCheckRequest(BaseModel):
    model_id: str
    api_key: str

class ActionRequest(BaseModel):
    action: str
    target_directory: Optional[str] = None
    recipient: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None

class ApprovalRequest(BaseModel):
    action_id: str
    approved: bool

@app.get("/", response_class=HTMLResponse)
async def read_index():
    return FileResponse("static/index.html")

@app.get("/api/models")
async def get_models():
    return {"models": AI_MODELS_CATALOG}

async def provider_models(provider: str, key: str, client: httpx.AsyncClient) -> List[str]:
    if provider not in MODEL_ENDPOINTS:
        return []
    headers = {"Authorization": f"Bearer {key}"}
    response = await client.get(MODEL_ENDPOINTS[provider], headers=headers)
    if response.status_code != 200:
        return []
    data = response.json().get("data", [])
    return [x.get("id", "") for x in data if x.get("id")]

async def call_provider(provider: str, key: str, prompt: str, client: httpx.AsyncClient, history: Optional[List[dict]] = None) -> dict:
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    available = await provider_models(provider, key, client)
    usable = [x for x in available if not any(w in x.lower() for w in ("whisper", "embed", "moderation", "audio", "guard"))]
    preferred = MODEL_PREFERENCES.get(provider, "gpt-4o-mini")
    model = next((x for x in [preferred, "llama-3.1-8b-instant", "llama-3.3-70b-versatile", "mistral-small-latest"] if x in usable), usable[0] if usable else preferred)
    messages = [{"role": "system", "content": "You are one specialist on the Thanos team. Give concise, useful analysis. Use the conversation context when relevant. Do not claim to have performed actions you did not perform."}]
    messages.extend({"role": item.get("role", "user"), "content": str(item.get("content", ""))[:12000]} for item in (history or [])[-12:] if item.get("content"))
    messages.append({"role": "user", "content": prompt})
    payload = {"model": model, "messages": messages, "temperature": 0.25}
    response = await client.post(CHAT_ENDPOINTS[provider], headers=headers, json=payload)
    if response.status_code >= 400:
        return {"provider": provider, "model": model, "ok": False, "error": f"HTTP {response.status_code}: {response.text[:180]}"}
    content = response.json().get("choices", [{}])[0].get("message", {}).get("content", "")
    return {"provider": provider, "model": model, "ok": True, "content": content}

async def web_research(query: str) -> List[dict]:
    url = "https://html.duckduckgo.com/html/?q=" + quote(query)
    headers = {"User-Agent": "ThanosResearch/1.0"}
    async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=headers) as client:
        response = await client.get(url)
    if response.status_code != 200:
        return []
    results = []
    pattern = re.compile(r'<a rel="nofollow" class="result__a" href="(.*?)"[^>]*>(.*?)</a>', re.S)
    for index, match in enumerate(pattern.findall(response.text)[:6], 1):
        link, title = match
        title = re.sub(r"<.*?>", "", html.unescape(title)).strip()
        if link.startswith("//"): link = "https:" + link
        results.append({"id": index, "title": title, "url": link, "domain": urlparse(link).netloc})
    return results

@app.post("/api/validate-key")
async def validate_key(req: KeyCheckRequest):
    if not req.api_key.strip(): return {"valid": False, "message": "Paste an API key first."}
    if req.model_id == "gemini-2.5-flash":
        url, headers, params = "https://generativelanguage.googleapis.com/v1beta/models", {}, {"key": req.api_key.strip()}
    else:
        url = MODEL_ENDPOINTS.get(req.model_id)
        if not url: return {"valid": False, "message": "This provider cannot be checked automatically yet."}
        headers, params = {"Authorization": f"Bearer {req.api_key.strip()}"}, {}
    try:
        async with httpx.AsyncClient(timeout=12) as client: response = await client.get(url, headers=headers, params=params)
        if response.status_code in (200, 201): return {"valid": True, "message": "API key accepted by the provider."}
        if response.status_code == 429: return {"valid": True, "limited": True, "message": "Key accepted but currently rate-limited."}
        return {"valid": False, "message": f"Provider returned HTTP {response.status_code}."}
    except httpx.HTTPError as exc: return {"valid": False, "message": f"Provider check failed: {exc.__class__.__name__}."}

@app.post("/api/research")
async def research(req: AgentRequest):
    sources = await web_research(req.prompt)
    source_text = "\n".join(f"[{s['id']}] {s['title']} — {s['url']}" for s in sources)
    keys = {k: v for k, v in req.api_keys.items() if v and k in CHAT_ENDPOINTS}
    if req.api_key and req.model_id: keys[req.model_id] = req.api_key
    if not keys: return {"status": "success", "summary": "Research sources collected. Add a verified provider key to synthesize them.", "sources": sources, "steps": [{"phase":"research","agent":"Web Search","status":"Collected public search results","output":f"Found {len(sources)} sources."}]}
    prompt = f"Answer the user's research request using only the sources below. Cite claims inline as [1], [2], etc. Mention uncertainty and do not invent facts.\n\nUser request: {req.prompt}\n\nSources:\n{source_text}"
    async with httpx.AsyncClient(timeout=45) as client:
        result = await call_provider(next(iter(keys)), next(iter(keys.values())), prompt, client, req.history)
    return {"status":"success" if result.get("ok") else "error", "summary":result.get("content", result.get("error", "Research synthesis failed.")), "sources":sources, "steps":[{"phase":"research","agent":"Web Search","status":f"Collected {len(sources)} public sources.","output":source_text},{"phase":"synthesis","agent":result.get("model", "Provider"),"status":"Synthesized with citations.","output":result.get("provider", "")}]}

@app.post("/api/run-agent")
async def run_agent(req: AgentRequest):
    prompt_lower = req.prompt.lower()
    mode = req.mode if req.mode != "auto" else ("research" if any(x in prompt_lower for x in ["research", "sources", "latest", "compare", "find out"]) else ("code" if any(x in prompt_lower for x in ["code", "bug", "python", "javascript", "fix", "html", "react"]) else "agent"))
    keys = {k: v for k, v in req.api_keys.items() if v and k in CHAT_ENDPOINTS}
    if req.api_key and req.model_id and req.model_id in CHAT_ENDPOINTS: keys[req.model_id] = req.api_key
    if mode == "research": return await research(req)
    if not keys:
        return {"status":"error","inferred_mode":mode,"summary":"No verified live provider is active. Verify at least one provider key first.","steps":[]}
    providers = list(keys.items())
    async with httpx.AsyncClient(timeout=45) as client:
        if req.team_strategy == "single" or len(providers) == 1:
            results = [await call_provider(providers[0][0], providers[0][1], req.prompt, client, req.history)]
        else:
            specialist_prompt = f"Analyze this task independently as a specialist. Focus on your strongest contribution, risks, and a practical answer:\n\n{req.prompt}"
            results = await asyncio.gather(*(call_provider(p, k, specialist_prompt, client, req.history) for p, k in providers))
            good = [r for r in results if r.get("ok")]
            if len(good) > 1:
                synthesis = "\n\n".join(f"[{r['provider']} / {r['model']}]\n{r['content']}" for r in good)
                final_prompt = f"You are the lead. Combine these independent specialist reports into one accurate answer to the original request. Resolve disagreements explicitly and do not mention hidden reasoning.\nOriginal request: {req.prompt}\nReports:\n{synthesis}"
                lead = await call_provider(good[0]["provider"], good[0].get("provider") and keys[good[0]["provider"]], final_prompt, client, req.history)
                if lead.get("ok"): results.append({**lead, "provider":"Lead synthesis", "model":lead.get("model")})
    good = [r for r in results if r.get("ok")]
    if not good: return {"status":"error","inferred_mode":mode,"summary":"All selected providers failed: " + "; ".join(r.get("error", "unknown error") for r in results),"steps":[]}
    final = good[-1].get("content", "")
    steps = [{"phase":"thinking","agent":r.get("provider"),"status":"Specialist contributed to the shared task.","output":f"Model: {r.get('model')}"} for r in results]
    steps.append({"phase":"synthesis","agent":"Thanos Lead","status":"Combined provider reports into one answer.","output":f"Collaborators: {', '.join(r.get('provider','') for r in good)}"})
    return {"status":"success","inferred_mode":mode,"strategy":"multi-provider collaboration" if len(providers)>1 else "single provider","summary":final,"steps":steps}

@app.post("/api/action/plan")
async def plan_action(req: ActionRequest):
    if req.action not in {"organize_files", "gmail_draft"}:
        return {"status":"error","message":"Unknown action."}
    action_id = str(uuid.uuid4())
    item = req.model_dump()
    item["action_id"] = action_id
    item["status"] = "pending_approval"
    PENDING_ACTIONS[action_id] = item
    summary = (f"Organize files in {req.target_directory or 'the selected folder'}" if req.action == "organize_files" else f"Create a Gmail draft to {req.recipient or '(recipient missing)'} with subject {req.subject or '(no subject)'}")
    return {"status":"pending_approval","action_id":action_id,"summary":summary,"message":"Review the action details, then approve or reject. Nothing has changed or been sent."}

@app.post("/api/action/approve")
async def approve_action(req: ApprovalRequest):
    item = PENDING_ACTIONS.get(req.action_id)
    if not item: return {"status":"error","message":"Approval expired or action not found."}
    if not req.approved:
        item["status"] = "rejected"
        return {"status":"rejected","message":"Action rejected. Nothing changed."}
    if item["action"] == "gmail_draft":
        item["status"] = "approved_draft"
        compose = "https://mail.google.com/mail/?view=cm&fs=1&tf=1&to=" + quote(item.get("recipient") or "") + "&su=" + quote(item.get("subject") or "") + "&body=" + quote(item.get("body") or "")
        return {"status":"approved","message":"Gmail draft prepared. Open it, review it, and send it yourself.","compose_url":compose,"draft":item}
    directory = Path(item.get("target_directory") or "").expanduser()
    if not directory.is_dir(): return {"status":"error","message":"Folder does not exist; no files changed."}
    moves = []
    for path in directory.iterdir():
        if path.is_file() and path.suffix:
            destination = directory / path.suffix.lower().strip(".")
            destination.mkdir(exist_ok=True)
            target = destination / path.name
            if target != path and not target.exists():
                shutil.move(str(path), str(target)); moves.append({"from":str(path),"to":str(target)})
    item["status"] = "completed"
    return {"status":"approved","message":f"Moved {len(moves)} files after approval.","moves":moves}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
