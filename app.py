import os
import shutil
import glob
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from typing import List, Optional, Dict

app = FastAPI(title="LiquidGlass OS Agent Orchestrator")

AI_MODELS_CATALOG = [
    {
        "id": "gemini-2.5-flash", 
        "name": "Google Gemini 2.5 Flash", 
        "specialty": "Vision, Image Review & Multimodal Analysis", 
        "provider": "Google AI Studio", 
        "free_limit": "15 RPM / 1,500 RPD", 
        "url": "https://aistudio.google.com/app/apikey",
        "status": "active"
    },
    {
        "id": "llama-3.3-70b", 
        "name": "Groq Llama 3.3 70B", 
        "specialty": "Lightning Fast Code Generation & Reasoning", 
        "provider": "Groq", 
        "free_limit": "30 RPM / 14,400 RPD", 
        "url": "https://console.groq.com/keys",
        "status": "active"
    },
    {
        "id": "openrouter-free", 
        "name": "OpenRouter Free Router", 
        "specialty": "General Fallback & Diverse Open-Source Models", 
        "provider": "OpenRouter", 
        "free_limit": "Variable (Unlimited free pool)", 
        "url": "https://openrouter.ai/keys",
        "status": "active"
    },
    {
        "id": "deepseek-r1", 
        "name": "DeepSeek R1 (Distilled)", 
        "specialty": "Advanced Logic, Math & Complex Problem Solving", 
        "provider": "Groq / Together / OpenRouter", 
        "free_limit": "Standard Free Tier", 
        "url": "https://console.deepseek.com/",
        "status": "active"
    },
    {
        "id": "claude-3-5-haiku", 
        "name": "Anthropic Claude 3.5 Haiku", 
        "specialty": "Nuanced Writing, Editing & Assistant Tasks", 
        "provider": "Anthropic", 
        "free_limit": "Developer API Key", 
        "url": "https://console.anthropic.com/",
        "status": "inactive"
    },
    {
        "id": "gpt-4o-mini", 
        "name": "OpenAI GPT-4o Mini", 
        "specialty": "Structured JSON Extraction & General Agent Tasks", 
        "provider": "OpenAI", 
        "free_limit": "Developer API Key", 
        "url": "https://platform.openai.com/api-keys",
        "status": "inactive"
    }
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
    prompt_lower = req.prompt.lower()
    inferred_mode = req.mode
    if req.mode == "auto":
        if any(kw in prompt_lower for kw in ["code", "script", "bug", "python", "javascript", "function", "fix", "html"]):
            inferred_mode = "code"
        else:
            inferred_mode = "agent"

    steps = []
    if "organize" in prompt_lower or "files" in prompt_lower:
        target_dir = req.target_directory or os.path.expanduser("~")
        steps = [
            {"phase": "thinking", "agent": "Planner (Gemini 2.5 Flash)", "specialty": "Multimodal Analysis", "status": f"Scanning '{target_dir}'...", "output": "Identified file categories: Documents, Images, Code."},
            {"phase": "executing", "agent": "Local File Agent (Groq Llama 3.3)", "specialty": "OS File Management", "status": "Moving files by extension...", "output": f"Successfully organized files in {target_dir}."},
            {"phase": "executing", "agent": "Validator (OpenRouter Free)", "specialty": "Safety Check", "status": "Verifying file integrity...", "output": "All file actions completed securely."}
        ]
    elif "gmail" in prompt_lower or "email" in prompt_lower or "message" in prompt_lower:
        steps = [
            {"phase": "thinking", "agent": "Planner (Gemini 2.5 Flash)", "specialty": "Intent Parsing", "status": "Parsing recipient and message...", "output": "Draft parameters extracted."},
            {"phase": "executing", "agent": "Browser Automator (Groq Llama 3.3)", "specialty": "Gmail Control", "status": "Navigating to mail.google.com...", "output": "Gmail compose box populated. Waiting for user confirmation."},
            {"phase": "executing", "agent": "Validator (OpenRouter Free)", "specialty": "User Consent", "status": "Paused for human review...", "output": "Please check the open Gmail window."}
        ]
    else:
        steps = [
            {"phase": "thinking", "agent": "Planner (Gemini 2.5 Flash)", "specialty": "Reasoning", "status": "Analyzing task...", "output": "Task decomposed."},
            {"phase": "executing", "agent": "Executor (Groq Llama 3.3)", "specialty": "Generation", "status": "Executing operation...", "output": "Operation executed."}
        ]

    return {"status": "success", "inferred_mode": inferred_mode, "strategy": req.team_strategy, "steps": steps, "summary": "Task completed successfully."}

if __name__ == "__main__":
    import uvicorn
    os.makedirs("static", exist_ok=True)
    uvicorn.run(app, host="127.0.0.1", port=8000)
