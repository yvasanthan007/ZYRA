import inspect, sys
sys.path.insert(0, 'backend')
import server as s
src = s.__doc__
print(src[:400])
import asyncio
async def show():
    from fastapi import FastAPI
    app = FastAPI()
    @app.post("/api/test")
    async def test():
        return {"ok": True}
    import uvicorn
    config = uvicorn.Config(app=app, port=0, log_level="error")
    server = uvicorn.Server(config)
    await server.serve()
asyncio.run(show())