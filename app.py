import os
import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="Thanos OS Agent Orchestrator")

AI_MODELS_CATALOG = [
    {"id":"gemini-2.5-flash","name":"Google Gemini","provider":"Google AI Studio","specialty":"Vision, image review, multimodal analysis","free_limit":"Free tier; limits shown in Google AI Studio","url":"https://aistudio.google.com/app/apikey","status":"available"},
    {"id":"groq-llama","name":"Groq / Llama","provider":"Groq","specialty":"Very fast coding, agents, and reasoning","free_limit":"Free developer access; limits shown in Groq Console","url":"https://console.groq.com/keys","status":"available"},
    {"id":"openrouter-free","name":"OpenRouter Free Models","provider":"OpenRouter","specialty":"General fallback across free open models","free_limit":"Free models vary; check model page and limits","url":"https://openrouter.ai/keys","status":"available"},
    {"id":"mistral","name":"Mistral AI","provider":"Mistral Studio","specialty":"Coding, documents/OCR, vision, JSON, and tools","free_limit":"Free mode; monthly and rate limits shown in Studio","url":"https://console.mistral.ai/api-keys","status":"available"},
    {"id":"cohere","name":"Cohere","provider":"Cohere Dashboard","specialty":"RAG, reranking, embeddings, multilingual agents","free_limit":"Trial key; rate-limited evaluation access","url":"https://dashboard.cohere.com/api-keys","status":"available"},
    {"id":"cerebras","name":"Cerebras","provider":"Cerebras Cloud","specialty":"Extremely fast reasoning and coding inference","free_limit":"Free trial credits after verified payment method; expires","url":"https://cloud.cerebras.ai/","status":"available"},
    {"id":"fireworks","name":"Fireworks AI","provider":"Fireworks Dashboard","specialty":"Fast open models, vision, tools, JSON, embeddings","free_limit":"Limited introductory credits; not unlimited","url":"https://app.fireworks.ai/settings/users/api-keys","status":"available"},
    {"id":"kimi","name":"Kimi / Moonshot AI","provider":"Kimi Platform","specialty":"Long-context coding, visual input, tools, complex workflows","free_limit":"No general free tier documented; usually paid/top-up","url":"https://platform.kimi.ai/console/api-keys","status":"paid"},
    {"id":"together","name":"Together AI","provider":"Together Projects","specialty":"Open models, image/video, audio, embeddings, fine-tuning","free_limit":"Prepaid API; no general free tier documented","url":"https://api.together.ai/settings/projects/~current/api-keys","status":"paid"},
    {"id":"anthropic","name":"Anthropic Claude","provider":"Anthropic Console","specialty":"Writing, careful reasoning, coding, and tool use","free_limit":"API billing/credits may be required; check account","url":"https://console.anthropic.com/settings/keys","status":"paid"},
    {"id":"openai","name":"OpenAI","provider":"OpenAI Platform","specialty":"Structured extraction, vision, coding, and agents","free_limit":"API billing/credits may be required; check account","url":"https://platform.openai.com/api-keys","status":"paid"},
    {"id":"deepseek","name":"DeepSeek","provider":"DeepSeek Platform","specialty":"Reasoning, mathematics, and coding","free_limit":"Check current official account allowance","url":"https://platform.deepseek.com/api_keys","status":"available"}
]

class AgentRequest(BaseModel):
    prompt: str
    mode: str = "auto"
    team_strategy: str = "collaborative"
    target_directory: Optional[str] = None
    model_id: Optional[str] = None
    api_key: Optional[str] = None

class KeyCheckRequest(BaseModel):
    model_id: str
    api_key: str

@app.get("/", response_class=HTMLResponse)
async def read_index():
    return FileResponse("static/index.html")

@app.get("/api/models")
async def get_models():
    return {"models": AI_MODELS_CATALOG}

@app.post("/api/validate-key")
async def validate_key(req: KeyCheckRequest):
    model = next((m for m in AI_MODELS_CATALOG if m["id"] == req.model_id), None)
    if not model or not req.api_key.strip():
        return {"valid": False, "message": "Unknown provider or empty key."}
    try:
        key = req.api_key.strip()
        headers = {"Authorization": f"Bearer {key}"}
        if req.model_id == "gemini-2.5-flash":
            async with httpx.AsyncClient(timeout=12) as client: response = await client.get("https://generativelanguage.googleapis.com/v1beta/models", params={"key":key})
        else:
            urls = {"groq-llama":"https://api.groq.com/openai/v1/models","openrouter-free":"https://openrouter.ai/api/v1/models","mistral":"https://api.mistral.ai/v1/models","cerebras":"https://api.cerebras.ai/v1/models","fireworks":"https://api.fireworks.ai/inference/v1/models","kimi":"https://api.moonshot.ai/v1/models","together":"https://api.together.xyz/v1/models","deepseek":"https://api.deepseek.com/models","anthropic":"https://api.anthropic.com/v1/models","openai":"https://api.openai.com/v1/models"}
            if req.model_id == "anthropic": headers = {"x-api-key":key,"anthropic-version":"2023-06-01"}
            async with httpx.AsyncClient(timeout=12) as client: response = await client.get(urls.get(req.model_id, "https://api.cohere.com/v1/models"), headers=headers)
        if response.status_code in (200,201): return {"valid":True,"message":"API key accepted by the provider."}
        if response.status_code == 429: return {"valid":True,"limited":True,"message":"Key accepted but currently rate-limited."}
        return {"valid":False,"message":f"Provider returned HTTP {response.status_code}."}
    except httpx.HTTPError as exc: return {"valid":False,"message":f"Provider check failed: {exc.__class__.__name__}."}

@app.post("/api/run-agent")
async def run_agent(req: AgentRequest):
    prompt_lower = req.prompt.lower()
    mode = req.mode if req.mode != "auto" else ("code" if any(x in prompt_lower for x in ["code","script","bug","python","javascript","function","fix","html","react"]) else "agent")
    if not req.api_key or not req.model_id or req.model_id in {"gemini-2.5-flash","cohere"}: return {"status":"error","inferred_mode":mode,"summary":"No supported verified live provider was supplied. Verify a Groq, Mistral, OpenRouter, Cerebras, Fireworks, Kimi, Together, DeepSeek, OpenAI, or Claude key first.","steps":[]}
    bases = {"groq-llama":"https://api.groq.com/openai/v1/chat/completions","mistral":"https://api.mistral.ai/v1/chat/completions","cerebras":"https://api.cerebras.ai/v1/chat/completions","fireworks":"https://api.fireworks.ai/inference/v1/chat/completions","kimi":"https://api.moonshot.ai/v1/chat/completions","together":"https://api.together.xyz/v1/chat/completions","deepseek":"https://api.deepseek.com/chat/completions","openrouter-free":"https://openrouter.ai/api/v1/chat/completions","openai":"https://api.openai.com/v1/chat/completions"}
    preferred = {"groq-llama":"llama-3.3-70b-versatile","mistral":"mistral-small-latest","cerebras":"gpt-oss-120b","fireworks":"accounts/fireworks/models/llama-v3p1-8b-instruct","kimi":"kimi-k2.6","together":"meta-llama/Llama-3.3-70B-Instruct-Turbo","deepseek":"deepseek-chat","openrouter-free":"openrouter/auto","openai":"gpt-4o-mini"}
    headers = {"Authorization":f"Bearer {req.api_key}","Content-Type":"application/json"}
    if req.model_id == "anthropic": headers = {"x-api-key":req.api_key,"anthropic-version":"2023-06-01","Content-Type":"application/json"}
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            selected = preferred.get(req.model_id, "gpt-4o-mini")
            models_url = bases.get(req.model_id,"").replace("/chat/completions","/models")
            if models_url:
                discovered = await client.get(models_url, headers=headers)
                if discovered.status_code == 200:
                    available = [x.get("id","") for x in discovered.json().get("data",[])]
                    usable = [x for x in available if not any(w in x.lower() for w in ["whisper","embed","moderation","audio","guard"])]
                    selected = next((x for x in [selected,"llama-3.1-8b-instant","llama-3.3-70b-versatile","openai/gpt-oss-20b","mistral-small-latest"] if x in usable), usable[0] if usable else selected)
            response = await client.post(bases.get(req.model_id,"https://api.openai.com/v1/chat/completions"), headers=headers, json={"model":selected,"messages":[{"role":"user","content":req.prompt}],"temperature":0.3})
        if response.status_code >= 400: return {"status":"error","inferred_mode":mode,"summary":f"Provider error HTTP {response.status_code}: {response.text[:240]}","steps":[]}
        answer = response.json().get("choices",[{}])[0].get("message",{}).get("content","No response returned.")
        return {"status":"success","inferred_mode":mode,"summary":answer,"steps":[{"phase":"thinking","agent":"Thanos Router","specialty":"Runtime model discovery","status":"Selected an available model for your key.","output":f"Using model: {selected}"},{"phase":"executing","agent":selected,"specialty":"Live provider response","status":"Completed real API request.","output":"Response returned by provider."}]}
    except httpx.HTTPError as exc: return {"status":"error","inferred_mode":mode,"summary":f"Could not reach provider: {exc.__class__.__name__}.","steps":[]}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
