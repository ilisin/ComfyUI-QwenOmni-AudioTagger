import asyncio

from aiohttp import web
from server import PromptServer

from .service import service


@PromptServer.instance.routes.get("/qwen-omni/status")
async def status(request):
    return web.json_response(await asyncio.to_thread(service.status))


@PromptServer.instance.routes.post("/qwen-omni/config")
async def configure(request):
    try:
        await asyncio.to_thread(service.save_config, await request.json())
        return web.json_response(await asyncio.to_thread(service.status))
    except (ValueError, OSError) as exc:
        return web.json_response({"error": str(exc)}, status=400)


@PromptServer.instance.routes.post("/qwen-omni/start")
async def start(request):
    try:
        await asyncio.to_thread(service.start)
        return web.json_response(await asyncio.to_thread(service.status))
    except (ValueError, OSError) as exc:
        return web.json_response({"error": str(exc)}, status=400)


@PromptServer.instance.routes.post("/qwen-omni/stop")
async def stop(request):
    try:
        await asyncio.to_thread(service.stop)
        return web.json_response(await asyncio.to_thread(service.status))
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=409)
