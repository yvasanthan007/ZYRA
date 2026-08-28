"""
FastAPI Backend Server for ZYRA AI Assistant
Serves the desktop dashboard and provides API/WebSocket endpoints for Zyra
"""
import os
import sys
import json
import asyncio
import threading
import webbrowser
from typing import Optional, Dict, Any
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

# Add parent directory to path for importing Zyra modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.zyra_bridge import (
    process_chat,
    process_command,
    process_voice_command,
    process_message,
    speak_text,
)
from backend.link_security import (
    analyze_url_security,
    format_security_report,
    extract_url,
)
from system_monitor import (
    get_system_metrics,
    format_system_monitor_text,
    get_voice_summary,
    is_system_monitor_intent,
    start_system_monitor,
)

app = FastAPI(
    title="ZYRA AI Assistant API",
    description="Backend API for ZYRA - Your AI Desktop Assistant",
    version="1.0.0",
)

# CORS middleware - allow all origins for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dashboard directory
DASHBOARD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "desktop-dashboard")

# WebSocket connection manager
class ConnectionManager:
    """Manages WebSocket connections for real-time communication"""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: Dict[str, Any]):
        """Send a message to all connected clients"""
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

    async def send_personal(self, message: Dict[str, Any], websocket: WebSocket):
        """Send a message to a specific client"""
        try:
            await websocket.send_json(message)
        except Exception:
            pass

manager = ConnectionManager()

# Event loop reference for thread-safe cross-thread broadcasting
_server_loop: Optional[asyncio.AbstractEventLoop] = None


@app.on_event("startup")
async def on_startup():
    global _server_loop
    _server_loop = asyncio.get_running_loop()


def broadcast_message_sync(message: Dict[str, Any]) -> None:
    """Thread-safe helper to broadcast a message to all connected clients."""
    global _server_loop
    if _server_loop and _server_loop.is_running():
        try:
            asyncio.run_coroutine_threadsafe(manager.broadcast(message), _server_loop)
        except Exception:
            pass


def broadcast_system_monitor_trigger(metrics: Optional[Dict[str, Any]] = None) -> None:
    """Broadcast system monitor activation to all connected clients."""
    if metrics is None:
        metrics = get_system_metrics()
    broadcast_message_sync({
        "type": "show_system_monitor",
        "data": metrics,
        "formatted": format_system_monitor_text(metrics),
    })


# ========== REST API Endpoints ==========

@app.get("/")
async def get_dashboard():
    """Serve the main dashboard HTML page"""
    index_path = os.path.join(DASHBOARD_DIR, "index.html")
    if not os.path.exists(index_path):
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return FileResponse(index_path)


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "ok",
        "zyra": "running",
        "version": "1.0.0"
    }


@app.post("/api/chat")
async def chat_endpoint(data: Dict[str, Any]):
    """
    Send a chat message to Zyra

    Request body:
    {
        "message": "Hello Zyra, how are you?"
    }

    Response:
    {
        "success": true,
        "response": "I'm doing great! How can I help you today?"
    }
    """
    message = data.get("message", "")
    if not message:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "Message is required"}
        )

    try:
        response = process_chat(message)
        return {"success": True, "response": response}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.post("/api/command")
async def command_endpoint(data: Dict[str, Any]):
    """
    Execute a Zyra command

    Request body:
    {
        "command": "open_chrome",
        "params": {}
    }

    Response:
    {
        "success": true,
        "data": "Executed open_chrome"
    }
    """
    command = data.get("command", "")
    params = data.get("params", {})

    if not command:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "Command is required"}
        )

    try:
        result = process_command(command, params)
        return result
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.post("/api/voice")
async def voice_endpoint(data: Dict[str, Any]):
    """
    Process a voice command (transcribed text)

    Request body:
    {
        "text": "open chrome"
    }

    Response:
    {
        "success": true,
        "data": {
            "response": "Opening Chrome",
            "action": "open_chrome"
        }
    }
    """
    text = data.get("text", "")
    if not text:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "Text is required"}
        )

    try:
        result = process_voice_command(text)
        return {"success": True, "data": result}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.post("/api/speak")
async def speak_endpoint(data: Dict[str, Any]):
    """
    Make Zyra speak text through TTS

    Request body:
    {
        "text": "Hello, I am Zyra"
    }

    Response:
    {
        "success": true,
        "data": "Speaking"
    }
    """
    text = data.get("text", "")
    if not text:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "Text is required"}
        )

    try:
        speak_text(text)
        return {"success": True, "data": "Speaking"}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.post("/api/analyze-link")
async def analyze_link_endpoint(data: Dict[str, Any]):
    """
    Backend-only link security analysis.
    Inspects a URL for phishing, malicious intent, or suspicious attributes.
    Never modifies the frontend dashboard UI — returns a text-only report.

    Request body (provide either field):
        {"url": "http://example.com/login"}
        {"text": "Analyse the link http://example.com/login"}

    Response:
        {"success": true, "report": "...", "analysis": {...}}
    """
    url = (data.get("url") or "").strip()
    text = (data.get("text") or "").strip()
    target = url or (extract_url(text) if text else "")
    if not target:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "Provide 'url' or 'text' containing a URL"}
        )
    try:
        analysis = analyze_url_security(target)
        report = format_security_report(analysis)
        return {"success": True, "report": report, "analysis": analysis}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.get("/api/system/metrics")
@app.get("/api/system-metrics")
async def system_metrics_endpoint():
    """Get real-time system monitoring metrics."""
    try:
        metrics = get_system_metrics()
        return {"success": True, "data": metrics, "formatted": format_system_monitor_text(metrics)}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.post("/api/system/monitor")
async def system_monitor_trigger_endpoint():
    """Trigger and activate System Monitor."""
    try:
        metrics = get_system_metrics()
        formatted = format_system_monitor_text(metrics)
        await manager.broadcast({
            "type": "show_system_monitor",
            "data": metrics,
            "formatted": formatted,
        })
        return {"success": True, "data": metrics, "formatted": formatted}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.get("/api/commands")
async def list_commands():
    """List all available Zyra commands"""
    from backend.zyra_bridge import COMMAND_MAP
    commands = list(COMMAND_MAP.keys())
    return {
        "success": True,
        "commands": commands,
        "count": len(commands)
    }


# ========== WebSocket Endpoint ==========

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time communication with Zyra

    Message format (JSON):
    {
        "type": "chat|command|voice|speak|remember|recall",
        "data": "..."
    }

    Response format:
    {
        "type": "response",
        "success": true,
        "data": "..."
    }
    """
    await manager.connect(websocket)
    try:
        while True:
            # Receive message from client
            raw_data = await websocket.receive_text()

            try:
                data = json.loads(raw_data)
            except json.JSONDecodeError:
                await manager.send_personal(
                    {"type": "error", "success": False, "error": "Invalid JSON"},
                    websocket
                )
                continue

            msg_type = data.get("type", "")
            msg_data = data.get("data")

            # Process the message through Zyra bridge
            try:
                result = process_message(msg_type, msg_data)

                # Send response back to the client
                response = {
                    "type": "response",
                    "success": result.get("success", False),
                    "data": result.get("data", result.get("response")),
                }
                if "error" in result:
                    response["error"] = result["error"]

                await manager.send_personal(response, websocket)

                # If it's a system monitor intent or action, broadcast card trigger
                if result.get("action") == "system_monitor":
                    metrics = result.get("metrics") or get_system_metrics()
                    await manager.broadcast({
                        "type": "show_system_monitor",
                        "data": metrics,
                        "formatted": format_system_monitor_text(metrics),
                    })

                # If it's a voice command with a response, also broadcast to all
                if msg_type == "voice" and result.get("success"):
                    voice_data = result.get("data", {})
                    if isinstance(voice_data, dict) and voice_data.get("response"):
                        await manager.broadcast({
                            "type": "voice_response",
                            "data": voice_data["response"]
                        })

            except Exception as e:
                await manager.send_personal(
                    {"type": "error", "success": False, "error": str(e)},
                    websocket
                )

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")
        manager.disconnect(websocket)


# ========== Server Runner ==========

def run_server(host: str = "127.0.0.1", port: int = 8080, open_browser: bool = False):
    """
    Run the FastAPI server

    Args:
        host: Host address to bind to
        port: Port to listen on
        open_browser: Whether to open the dashboard in browser
    """
    if open_browser:
        url = f"http://{host}:{port}"
        print(f"\n🌐 Opening dashboard at {url}")
        webbrowser.open(url)

    print(f"\n🚀 ZYRA Backend Server running at http://{host}:{port}")
    print(f"📡 WebSocket endpoint: ws://{host}:{port}/ws")
    print(f"📋 API docs: http://{host}:{port}/docs")
    print(f"🔍 Health check: http://{host}:{port}/api/health\n")

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
    )


def start_server_thread(host: str = "127.0.0.1", port: int = 8080, open_browser: bool = False):
    """
    Start the FastAPI server in a background thread.
    Used when running from main.py alongside the voice assistant.
    """
    server_thread = threading.Thread(
        target=run_server,
        args=(host, port, open_browser),
        daemon=True,
        name="ZYRA-Server"
    )
    server_thread.start()
    return server_thread


if __name__ == "__main__":
    # When run directly, start server and open browser
    run_server(open_browser=True)
