import os
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

@app.get("/", response_class=HTMLResponse)
async def read_index():
    return FileResponse("static/index.html")

@app.get("/api/models")
async def get_models():
    return {"models": AI_MODELS_CATALOG}

@app.post("/api/run-agent")
async def run_agent(req: AgentRequest):
    prompt = req.prompt.lower()
    mode = req.mode
    if mode == "auto":
        mode = "code" if any(x in prompt for x in ["code","script","bug","python","javascript","function","fix","html","react"]) else "agent"
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
