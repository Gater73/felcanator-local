from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from services.youtube import YouTubeService
from services.classifier import ClassifierService
import os
import json
import logging

from sse_starlette.sse import EventSourceResponse
import asyncio

# Configure global logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("felcanator.main")

app = FastAPI(title="Felcanator API")

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

youtube_service = YouTubeService()
classifier_service = ClassifierService()

class VideoRequest(BaseModel):
    url: str
    provider: Optional[str] = None
    limit: Optional[int] = 5

class VideoResult(BaseModel):
    id: str
    title: str
    url: str
    classification: str
    reasoning: str
    confidence: float

@app.get("/")
async def root():
    return {"message": "felcanator API is running."}

@app.get("/config")
async def get_config():
    """Return the default LLM provider."""
    return {"default_provider": classifier_service.provider}

@app.post("/classify/video", response_model=VideoResult)
async def classify_video(request: VideoRequest):
    logger.info(f"== Nova requisição de classificação de ÚNICO vídeo: URL={request.url} Provider={request.provider} ==")
    
    # 1. Reject Channel URLs from the Video endpoint
    if any(x in request.url for x in ["@", "/channel/", "/user/", "/c/"]):
        raise HTTPException(status_code=400, detail="Este é um link de canal. Por favor, clique no botão 'Analisar Canal' em vez de 'Analisar Vídeo'.")

    # 2. Extract Video ID
    video_info = youtube_service.get_video_id(request.url)
    if not video_info:
        logger.error(f"ID do vídeo não encontrado para a URL: {request.url}")
        raise HTTPException(status_code=400, detail="Link inválido do YouTube ou vídeo privado/deletado.")

    # 3. Bypass Trick: If it's age restricted, YouTube already flagged it! 
    if isinstance(video_info, dict) and video_info.get("age_restricted"):
        logger.warning(f"Vídeo {video_info['id']} restrito por idade. Classificando como FLAG automaticamente.")
        return {
            "id": video_info["id"],
            "title": "Vídeo Restrito (+18)",
            "url": request.url,
            "classification": "FLAG",
            "reasoning": "O YouTube já marcou este vídeo com restrição de idade (+18). Portanto, é sumariamente considerado inadequado pelo Felcanator.",
            "confidence": 1.0
        }

    video_id = video_info  # It's a string if successfully extracted

    logger.info(f"Buscando metadados e transcrição para o vídeo ID: {video_id}...")
    metadata = youtube_service.get_video_metadata(request.url)
    transcript = youtube_service.get_transcript(video_id)
    
    logger.info(f"Chamando classificador LLM (Provedor: {request.provider or 'padrão'})...")
    classification = classifier_service.classify_video(metadata, transcript, provider=request.provider)
    
    if "error" in classification:
        logger.error(f"Erro na classificação do LLM: {classification['error']}")
        raise HTTPException(status_code=500, detail=classification["error"])

    logger.info(f"Classificação concluída: {classification.get('classification')} com confiança de {classification.get('confidence')}")
    return {
        "id": video_id,
        "title": metadata.get('title'),
        "url": f"https://www.youtube.com/watch?v={video_id}",
        **classification
    }

@app.post("/classify/channel")
async def classify_channel(request: VideoRequest):
    logger.info(f"== Nova requisição de classificação de CANAL: URL={request.url} Limite={request.limit} ==")
    async def event_generator():
        yield {"event": "status", "data": f"Buscando vídeos do canal (limite: {request.limit})..."}
        videos = youtube_service.get_channel_videos(request.url, max_videos=request.limit)
        
        if not videos:
            logger.warning(f"Nenhum vídeo encontrado para o canal: {request.url}")
            yield {"event": "error", "data": "Canal não encontrado ou sem vídeos."}
            return

        logger.info(f"Encontrados {len(videos)} vídeos na playlist do canal. Processando 1 a 1...")
        yield {"event": "status", "data": f"{len(videos)} vídeos encontrados. Iniciando análise sequencial..."}
        
        for i, video in enumerate(videos):
            try:
                logger.info(f"Iteração [{i+1}/{len(videos)}] - Analisando vídeo: {video['id']} ({video['title']})")
                yield {"event": "status", "data": f"[{i+1}/{len(videos)}] Analisando: {video['title']}..."}
                
                metadata = youtube_service.get_video_metadata(video['url'])
                
                # Check for age restriction shortcut
                if isinstance(metadata, dict) and metadata.get("age_restricted"):
                    logger.warning(f"Vídeo {video['id']} restrito por idade. Classificando como FLAG.")
                    result = {
                        "id": video['id'],
                        "title": "Vídeo Restrito (+18)",
                        "url": video['url'],
                        "classification": "FLAG",
                        "reasoning": "Vídeo marcado com restrição de idade (+18) pelo YouTube. Inadequado para menores (Felcanator).",
                        "confidence": 1.0
                    }
                    yield {"event": "result", "data": json.dumps(result)}
                    continue

                if not metadata:
                    logger.warning(f"Metadados indisponíveis para o vídeo {video['id']}. Pulando.")
                    yield {"event": "log", "data": f"Vídeo {video['id']} está indisponível ou privado. Ignorando."}
                    continue
                    
                transcript = youtube_service.get_transcript(video['id'])
                classification = classifier_service.classify_video(metadata, transcript, provider=request.provider)
                
                if "error" in classification:
                    logger.error(f"Erro do LLM no vídeo {video['id']}: {classification['error']}")
                    yield {"event": "log", "data": f"Erro ao analisar vídeo {video['id']}: {classification['error']}"}
                    continue
                
                result = {
                    "id": video['id'],
                    "title": video['title'],
                    "url": video['url'],
                    **classification
                }
                logger.info(f"Resultado do vídeo {video['id']}: {classification.get('classification')}")
                yield {"event": "result", "data": json.dumps(result)}
                
            except Exception as e:
                logger.error(f"Erro inesperado processando vídeo {video['id']}: {str(e)}", exc_info=True)
                yield {"event": "log", "data": f"Erro inesperado no vídeo {video['id']}: {str(e)}"}
        
        logger.info("Análise do canal concluída com sucesso via SSE.")
        yield {"event": "done", "data": "Análise concluída!"}

    return EventSourceResponse(event_generator())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
