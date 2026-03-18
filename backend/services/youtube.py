import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi
import os

class YouTubeService:
    @staticmethod
    def get_video_id(url):
        """Extract video ID from URL."""
        ydl_opts = {'quiet': True, 'no_warnings': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
                return info.get('id')
            except Exception as e:
                error_msg = str(e)
                print(f"Error extracting video ID: {error_msg}")
                if "Sign in to confirm your age" in error_msg:
                    import re
                    match = re.search(r'\[youtube\] ([a-zA-Z0-9_-]{11}): Sign in', error_msg)
                    vid = match.group(1) if match else "age_restricted"
                    return {"id": vid, "age_restricted": True}
                return None

    @staticmethod
    def get_channel_videos(channel_url, max_videos=10):
        """Get a list of videos from a channel URL."""
        # Fix for YouTube channels returning tabs instead of videos
        if "@" in channel_url and not channel_url.endswith("/videos"):
            channel_url = channel_url.rstrip("/") + "/videos"
            
        ydl_opts = {
            'quiet': True,
            'extract_flat': 'in_playlist',
            'no_warnings': True,
            'playlist_items': f'1-{max_videos}'
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(channel_url, download=False)
                videos = []
                if 'entries' in info:
                    for entry in info['entries']:
                        if entry and entry.get('id'):
                            # Basic check to avoid channel IDs acting as video IDs
                            if len(entry.get('id')) == 11:
                                videos.append({
                                    'id': entry.get('id'),
                                    'title': entry.get('title'),
                                    'url': f"https://www.youtube.com/watch?v={entry.get('id')}"
                                })
                return videos
            except Exception as e:
                print(f"Error extracting channel videos: {e}")
                return []

    @staticmethod
    def get_transcript(video_id, languages=['pt', 'en']):
        """Fetch transcript for a given video ID with robust fallbacks."""
        print(f"\n--- Iniciando extração de transcrição para o vídeo: {video_id} ---")
        try:
            api = YouTubeTranscriptApi()
            transcript_list = api.list(video_id)
            
            # 1. Tentar encontrar transcrição nos idiomas preferidos
            try:
                transcript = transcript_list.find_transcript(languages)
                print(f"✓ Transcrição encontrada diretamente: {transcript.language_code}")
            except:
                # 2. Se não encontrar, tenta pegar a primeira disponível e traduzir
                print("! Idioma preferido não encontrado. Tentando tradução automática...")
                first_transcript = next(iter(transcript_list))
                transcript = first_transcript.translate('pt')
                print(f"✓ Transcrição traduzida de {first_transcript.language_code} para pt")
            
            data = transcript.fetch()
            # Handle both dict and object (FetchedTranscriptSnippet) formats
            texts = []
            for entry in data:
                if isinstance(entry, dict):
                    texts.append(entry.get('text', ''))
                else:
                    texts.append(getattr(entry, 'text', ''))
            
            full_text = " ".join(texts)
            print(f"✓ Sucesso! Conteúdo extraído: {len(full_text)} caracteres.\n")
            return full_text
        except Exception as e:
            print(f"✗ Erro ao buscar transcrição para {video_id}: {str(e)}\n")
            return None

    @staticmethod
    def get_video_metadata(video_url):
        """Get title, description, and tags for a video."""
        ydl_opts = {'quiet': True, 'no_warnings': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(video_url, download=False)
                return {
                    'title': info.get('title'),
                    'description': info.get('description'),
                    'tags': info.get('tags'),
                    'categories': info.get('categories')
                }
            except Exception as e:
                error_msg = str(e)
                print(f"Error extracting metadata: {error_msg}")
                if "Sign in to confirm your age" in error_msg:
                    return {"age_restricted": True}
                return None
