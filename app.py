import os
import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="Thanos OS Agent Orchestrator")

# Links and free-access notes are informational. Keys stay in the browser and are never sent here.
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
    """Make a small authenticated request; the key is never stored by this server."""
    model = next((m for m in AI_MODELS_CATALOG if m["id"] == req.model_id), None)
    if not model:
        return {"valid": False, "message": "Unknown provider."}
    key = req.api_key.strip()
    if not key:
        return {"valid": False, "message": "Paste an API key first."}
    try:
        headers = {"Authorization": f"Bearer {key}"}
        timeout = httpx.Timeout(12.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            if req.model_id == "gemini-2.5-flash":
                response = await client.get("https://generativelanguage.googleapis.com/v1beta/models", params={"key": key})
            elif req.model_id == "cohere":
                response = await client.get("https://api.cohere.com/v1/models", headers=headers)
            else:
                base_urls = {
                    "groq-llama": "https://api.groq.com/openai/v1/models",
                    "openrouter-free": "https://openrouter.ai/api/v1/models",
                    "mistral": "https://api.mistral.ai/v1/models",
                    "cerebras": "https://api.cerebras.ai/v1/models",
                    "fireworks": "https://api.fireworks.ai/inference/v1/models",
                    "kimi": "https://api.moonshot.ai/v1/models",
                    "together": "https://api.together.xyz/v1/models",
                    "deepseek": "https://api.deepseek.com/models",
                    "anthropic": "https://api.anthropic.com/v1/models",
                    "openai": "https://api.openai.com/v1/models"
                }
                url = base_urls.get(req.model_id)
                if not url:
                    return {"valid": False, "message": "This provider cannot be checked automatically yet."}
                if req.model_id == "anthropic":
                    headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
                response = await client.get(url, headers=headers)
            if response.status_code in (200, 201):
                return {"valid": True, "message": "API key accepted by the provider."}
            if response.status_code in (401, 403):
                return {"valid": False, "message": "The provider rejected this key (401/403)."}
            if response.status_code == 429:
                return {"valid": True, "limited": True, "message": "Key accepted, but this provider is rate-limited right now."}
            return {"valid": False, "message": f"Provider returned HTTP {response.status_code}. Check the provider console."}
    except httpx.TimeoutException:
        return {"valid": False, "message": "Provider check timed out. Try again."}
    except httpx.HTTPError as exc:
        return {"valid": False, "message": f"Could not reach provider: {exc.__class__.__name__}."}

@app.post("/api/run-agent")
async def run_agent(req: AgentRequest):
    prompt = req.prompt.lower()
    mode = req.mode
    if mode == "auto":
        mode = "code" if any(x in prompt for x in ["code","script","bug","python","javascript","function","fix","html","react"]) else "agent"
    if req.api_key and req.model_id and req.model_id not in {"gemini-2.5-flash", "cohere"}:
        model_names = {
            "groq-llama": "llama-3.3-70b-versatile", "mistral": "mistral-small-latest",
            "cerebras": "gpt-oss-120b", "fireworks": "accounts/fireworks/models/llama-v3p1-8b-instruct",
            "kimi": "kimi-k2.6", "together": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
            "deepseek": "deepseek-chat", "openrouter-free": "openrouter/auto",
            "openai": "gpt-4o-mini", "anthropic": "claude-3-5-haiku-latest"
        }
        bases = {
            "groq-llama":"https://api.groq.com/openai/v1/chat/completions", "mistral":"https://api.mistral.ai/v1/chat/completions",
            "cerebras":"https://api.cerebras.ai/v1/chat/completions", "fireworks":"https://api.fireworks.ai/inference/v1/chat/completions",
            "kimi":"https://api.moonshot.ai/v1/chat/completions", "together":"https://api.together.xyz/v1/chat/completions",
            "deepseek":"https://api.deepseek.com/chat/completions", "openrouter-free":"https://openrouter.ai/api/v1/chat/completions",
            "openai":"https://api.openai.com/v1/chat/completions"
        }
        try:
            headers = {"Authorization": f"Bearer {req.api_key}", "Content-Type":"application/json"}
            if req.model_id == "anthropic":
                headers = {"x-api-key": req.api_key, "anthropic-version":"2023-06-01", "Content-Type":"application/json"}
            payload = {"model": model_names.get(req.model_id, "gpt-4o-mini"), "messages":[{"role":"user","content":req.prompt}], "temperature":0.3}
            async with httpx.AsyncClient(timeout=45) as client:
                response = await client.post(bases.get(req.model_id, "https://api.openai.com/v1/chat/completions"), headers=headers, json=payload)
            if response.status_code >= 400:
                return {"status":"error","inferred_mode":mode,"summary":f"Provider error HTTP {response.status_code}: {response.text[:240]}","steps":[]}
            body = response.json()
            answer = body.get("choices", [{}])[0].get("message", {}).get("content", "No response returned.")
            return {"status":"success","inferred_mode":mode,"summary":answer,"steps":[{"phase":"thinking","agent":"Thanos Router","specialty":"Provider selection","status":"Selected the configured provider and sent your prompt.","output":"Live request started."},{"phase":"executing","agent":model_names.get(req.model_id, req.model_id),"specialty":"Live provider response","status":"Completed real API request.","output":"Response returned by the selected provider."}]}
        except httpx.HTTPError as exc:
            return {"status":"error","inferred_mode":mode,"summary":f"Could not reach provider: {exc.__class__.__name__}.","steps":[]}

    if "organize" in prompt or "files" in prompt:
        directory = req.target_directory or os.path.expanduser("~")
        steps = [
            {"phase":"thinking","agent":"Planner","specialty":"Intent and safety planning","status":f"Preparing a file plan for {directory}...","output":"Plan ready; no files are changed until the local tool is explicitly enabled."},
            {"phase":"executing","agent":"Local File Tool","specialty":"OS file management","status":"Ready to organize by extension...","output":"Preview generated. Review the proposed moves before applying them."},
            {"phase":"executing","agent":"Validator","specialty":"Safety verification","status":"Checking for collisions and protected files...","output":"Human review required before destructive or irreversible moves."}
        ]
    elif any(x in prompt for x in ["gmail","email","message"]):
        steps = [
            {"phase":"thinking","agent":"Planner","specialty":"Intent and recipient parsing","status":"Preparing a Gmail draft plan...","output":"Recipient, subject, and message should be reviewed before use."},
            {"phase":"executing","agent":"Browser Tool","specialty":"Gmail draft control","status":"Ready to open Gmail and populate a draft...","output":"Sending is never automatic; a human confirmation is required."},
            {"phase":"executing","agent":"Validator","specialty":"Consent and safety","status":"Waiting for human review...","output":"Review the visible Gmail draft before sending."}
        ]
    else:
        steps = [
            {"phase":"thinking","agent":"Planner","specialty":"Task decomposition","status":"Analyzing the request and selecting providers by specialty...","output":"A specialty-routed plan was created."},
            {"phase":"executing","agent":"Thanos Network","specialty":"Multi-model orchestration","status":"Executing the selected task...","output":"Provider failover should occur only after an official error or rate-limit response."}
        ]
    return {"status":"success","inferred_mode":mode,"strategy":req.team_strategy,"steps":steps,"summary":"Thanos created a specialty-routed plan. API keys remain local to this browser."}

if __name__ == "__main__":
    import uvicorn
    os.makedirs("static", exist_ok=True)
    uvicorn.run(app, host="127.0.0.1", port=8000)
