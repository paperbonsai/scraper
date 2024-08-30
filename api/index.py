from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from .scraper import process_url

app = FastAPI()


class UrlRequest(BaseModel):
    url: str


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        data = await websocket.receive_json()
        url = data.get("url")
        if url:
            await process_url(url, websocket)
        else:
            await websocket.send_json({"error": "No URL provided"})
    except WebSocketDisconnect:
        print("WebSocket disconnected")
