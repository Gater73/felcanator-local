from google import genai
from openai import OpenAI
from anthropic import Anthropic
from groq import Groq
import os
import json
import re
from urllib.parse import urlparse
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

import logging

# Configure logger
logger = logging.getLogger("felcanator.classifier")
logger.setLevel(logging.INFO)

class ClassifierService:
    def __init__(self):
        self.provider = os.getenv("LLM_PROVIDER", "gemini").lower()
        logger.info(f"Iniciando ClassifierService. Provedor padrão: {self.provider.upper()}")
        
        # Initialize Gemini (v2 SDK)
        self.gemini_key = os.getenv("GEMINI_API_KEY")
        if self.gemini_key:
            self.gemini_client = genai.Client(api_key=self.gemini_key)
            logger.info("Cliente Gemini inicializado.")
        else:
            self.gemini_client = None
            logger.warning("Chave GEMINI_API_KEY ausente.")
        
        # Initialize OpenAI
        self.openai_key = os.getenv("OPENAI_API_KEY")
        self.openai_client = OpenAI(api_key=self.openai_key) if self.openai_key else None
        if self.openai_client: logger.info("Cliente OpenAI inicializado.")
        
        # Initialize Anthropic
        self.anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        self.anthropic_client = Anthropic(api_key=self.anthropic_key) if self.anthropic_key else None
        if self.anthropic_client: logger.info("Cliente Anthropic inicializado.")
        
        # Initialize Groq
        self.groq_key = os.getenv("GROQ_API_KEY")
        self.groq_client = Groq(api_key=self.groq_key) if self.groq_key else None
        if self.groq_client: logger.info("Cliente Groq inicializado.")

        # Initialize LM-Studio (OpenAI-compatible endpoint)
        self.lmstudio_base_url = self._normalize_openai_compatible_base_url(
            os.getenv("LMSTUDIO_BASE_URL")
        )
        self.lmstudio_api_key = os.getenv("LMSTUDIO_API_KEY")
        self.lmstudio_model = os.getenv("LMSTUDIO_MODEL")
        if self.lmstudio_base_url:
            # Many local OpenAI-compatible endpoints ignore api_key; still pass one to satisfy SDK.
            self.lmstudio_client = OpenAI(
                api_key=self.lmstudio_api_key or "lmstudio",
                base_url=self.lmstudio_base_url,
            )
            logger.info("Cliente LM-Studio inicializado.")
        else:
            self.lmstudio_client = None

        # Initialize Ollama (OpenAI-compatible endpoint)
        self.ollama_base_url = self._normalize_openai_compatible_base_url(
            os.getenv("OLLAMA_BASE_URL")
        )
        self.ollama_api_key = os.getenv("OLLAMA_API_KEY")
        self.ollama_model = os.getenv("OLLAMA_MODEL")
        if self.ollama_base_url:
            self.ollama_client = OpenAI(
                api_key=self.ollama_api_key or "ollama",
                base_url=self.ollama_base_url,
            )
            logger.info("Cliente Ollama inicializado.")
        else:
            self.ollama_client = None

    def classify_video(self, metadata, transcript, provider=None):
        """Classify video content using the specified or default provider."""
        active_provider = provider or self.provider
        logger.info(f"Iniciando classificação de vídeo usando provedor: {active_provider.upper()}")
        logger.info(f"Alvo: '{metadata.get('title')}'")
        
        # Prevent Token Limit Errors (TPM Rate Limits)
        # 1 token ~= 4 chars. Groq's Llama 3 on free tier has ~6k-12k tokens per min limit.
        # We cap transcripts at 25,000 characters (~6,250 tokens) to be safe.
        MAX_CHARS = 25000
        if transcript and len(transcript) > MAX_CHARS:
            logger.warning(f"Transcrição excedeu {MAX_CHARS} caracteres. Truncando para evitar limites de token (TPM).")
            # Get first 15k and last 10k to catch intro and outro
            transcript = transcript[:15000] + "\n\n... [TRUNCADO DEVIDO AO TAMANHO DO VÍDEO] ...\n\n" + transcript[-10000:]

        prompt = f"""
        # ANALISADOR DE CONTEÚDO FELCANATOR
        
        Sua missão é atuar como um auditor rigoroso de segurança de conteúdo digital para o público brasileiro, 
        baseando-se nas diretrizes de segurança infantil do Felcanator. Você deve analisar se o vídeo abaixo deve 
        ser classificado como "FLAG" (impróprio para menores) ou "SAFE" (seguro).

        ## CRITÉRIOS DE AUDITORIA:
        1. **VIOLÊNCIA EXTREMA/GORE**: Procure por menções a sangue, morte, armas, agressão física severa ou sofrimento. 
           Especialmente em jogos "indie" de terror ou shooters.
        2. **CONTEÚDO SENSUAL/ADULTO**: Analise se há linguagem de duplo sentido, referências sexuais, nudez ou temas 
           que incentivem a sexualização precoce.
        3. **LINGUAGEM INAPROPRIADA**: Conte palavrões, insultos pesados ou gírias obscenas.
        4. **TEMAS PERIGOSOS**: Incentivo a desafios arriscados, automutilação ou substâncias ilícitas.

        ## DADOS PARA ANÁLISE:
        Título: {metadata.get('title')}
        Descrição: {metadata.get('description')}
        Categorias: {metadata.get('categories')}
        
        Transcrição do Vídeo:
        ---
        {transcript if transcript else "[AVISO: Transcrição não disponível. Baseie-se APENAS nos metadados, mas atribua confidence < 0.7]"}
        ---

        ## INSTRUÇÕES DE RESPOSTA (OBRIGATÓRIO):
        - Sua análise deve ser baseada em **EVIDÊNCIAS** (palavras, frases, temas) extraídas da transcrição acima.
        - Se a transcrição estiver presente, você DEVE citar trechos ou termos que justificam a sua escolha.
        - Se a transcrição estiver ausente, baseie-se no título e descrição, mas atribua um "confidence" menor (máx 0.7) e explique que a falta de áudio limita a auditoria.
        - **IMPORTANTE**: Jogos como GTA, Roblox ou shooters indies são frequentemente violentos em áudio (palavrões, gritos, sons de tiro). Fique atento a isso na transcrição.
        
        Responda APENAS em formato JSON:
        {{
            "classification": "FLAG" ou "SAFE",
            "reasoning": "Sua justificativa técnica e rigorosa EM PORTUGUÊS (máximo 300 caracteres). Cite evidências se houver.",
            "confidence": 0.0 a 1.0
        }}
        """

        try:
            logger.debug("Prompt gerado. Enviando request para o LLM...")
            if active_provider == "gemini":
                result = self._call_gemini(prompt)
            elif active_provider == "openai":
                result = self._call_openai(prompt)
            elif active_provider == "anthropic":
                result = self._call_anthropic(prompt)
            elif active_provider == "groq":
                result = self._call_groq(prompt)
            elif active_provider == "lmstudio":
                result = self._call_lmstudio(prompt)
            elif active_provider == "ollama":
                result = self._call_ollama(prompt)
            else:
                logger.error(f"Provedor {active_provider} não suportado.")
                return {"error": f"Provider {active_provider} not supported."}
            
            if "error" not in result:
                logger.info(f"Classificação concluída: {result.get('classification')} (Confiança: {result.get('confidence')})")
            return result
        except Exception as e:
            logger.error(f"Erro fatal na classificação com {active_provider}: {str(e)}", exc_info=True)
            return {"error": str(e)}

    def _normalize_openai_compatible_base_url(self, base_url: Optional[str]) -> Optional[str]:
        """
        Normalize a base URL for OpenAI-compatible servers.
        Many expect `http://host:port/v1`.
        If the user sets `http://host:port`, append `/v1`.
        """
        if not base_url:
            return None

        base_url = base_url.strip().rstrip("/")
        parsed = urlparse(base_url)
        path = parsed.path or ""

        # If it already ends with `/v1`, keep it.
        if path == "/v1" or path.endswith("/v1"):
            return base_url

        # If path is empty or just `/`, append `/v1`.
        if path in ["", "/"]:
            return f"{base_url}/v1"

        # Otherwise, append `/v1` if it's not already present at the end.
        return f"{base_url}/v1"

    def _call_gemini(self, prompt):
        if not self.gemini_client: 
            logger.error("Tentativa de uso do Gemini falhou: Chave ausente.")
            return {"error": "Gemini client not initialized."}
        response = self.gemini_client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        logger.debug("Resposta do Gemini recebida com sucesso.")
        return self._parse_json(response.text)

    def _call_openai(self, prompt):
        if not self.openai_client: 
            logger.error("Tentativa de uso do OpenAI falhou: Chave ausente.")
            return {"error": "OpenAI API key missing."}
        response = self.openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        logger.debug("Resposta do OpenAI recebida com sucesso.")
        return json.loads(response.choices[0].message.content)

    def _call_anthropic(self, prompt):
        if not self.anthropic_client: 
            logger.error("Tentativa de uso da Anthropic falhou: Chave ausente.")
            return {"error": "Anthropic API key missing."}
        response = self.anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt + " Respond ONLY with the JSON object."}]
        )
        logger.debug("Resposta do Anthropic recebida com sucesso.")
        return self._parse_json(response.content[0].text)

    def _call_groq(self, prompt):
        if not self.groq_client: 
            logger.error("Tentativa de uso do Groq falhou: Chave ausente.")
            return {"error": "Groq API key missing."}
        response = self.groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        logger.debug("Resposta do Groq recebida com sucesso.")
        return json.loads(response.choices[0].message.content)

    def _call_lmstudio(self, prompt):
        if not self.lmstudio_client:
            logger.error("Tentativa de uso do LM-Studio falhou: base URL ausente.")
            return {"error": "LM-Studio base URL missing (LMSTUDIO_BASE_URL)."}
        if not self.lmstudio_model:
            logger.error("Tentativa de uso do LM-Studio falhou: modelo ausente.")
            return {"error": "LM-Studio model missing (LMSTUDIO_MODEL)."}

        messages = [{"role": "user", "content": prompt}]

        # Some OpenAI-compatible servers may not support `response_format`.
        try:
            response = self.lmstudio_client.chat.completions.create(
                model=self.lmstudio_model,
                messages=messages,
                response_format={"type": "json_object"},
            )
        except Exception as e:
            logger.warning(f"LM-Studio falhou com response_format, re-tentando sem. Erro: {str(e)}")
            response = self.lmstudio_client.chat.completions.create(
                model=self.lmstudio_model,
                messages=messages,
            )

        # Be defensive: if the endpoint is wrong/unexpected, `choices` can be None.
        content = None
        try:
            if getattr(response, "choices", None):
                content = response.choices[0].message.content
        except Exception:
            content = None

        if not content:
            logger.error(f"Resposta inesperada do LM-Studio (sem choices/message.content). Response={str(response)[:300]}")
            return {
                "error": (
                    "LM-Studio respondeu em formato inesperado. "
                    "Verifique se `LMSTUDIO_BASE_URL` aponta para um endpoint OpenAI-compatible "
                    "(ex.: http://localhost:1234/v1) e se o modelo em `LMSTUDIO_MODEL` existe."
                )
            }

        logger.debug("Resposta do LM-Studio recebida com sucesso.")
        return self._parse_json(content)

    def _call_ollama(self, prompt):
        if not self.ollama_client:
            logger.error("Tentativa de uso do Ollama falhou: base URL ausente.")
            return {"error": "Ollama base URL missing (OLLAMA_BASE_URL)."}
        if not self.ollama_model:
            logger.error("Tentativa de uso do Ollama falhou: modelo ausente.")
            return {"error": "Ollama model missing (OLLAMA_MODEL)."}

        messages = [{"role": "user", "content": prompt}]

        try:
            response = self.ollama_client.chat.completions.create(
                model=self.ollama_model,
                messages=messages,
                response_format={"type": "json_object"},
            )
        except Exception as e:
            logger.warning(f"Ollama falhou com response_format, re-tentando sem. Erro: {str(e)}")
            response = self.ollama_client.chat.completions.create(
                model=self.ollama_model,
                messages=messages,
            )

        content = None
        try:
            if getattr(response, "choices", None):
                content = response.choices[0].message.content
        except Exception:
            content = None

        if not content:
            logger.error(f"Resposta inesperada do Ollama (sem choices/message.content). Response={str(response)[:300]}")
            return {
                "error": (
                    "Ollama respondeu em formato inesperado. "
                    "Verifique se `OLLAMA_BASE_URL` aponta para um endpoint OpenAI-compatible "
                    "(ex.: http://localhost:11434/v1) e se o modelo em `OLLAMA_MODEL` existe."
                )
            }

        logger.debug("Resposta do Ollama recebida com sucesso.")
        return self._parse_json(content)

    def _parse_json(self, text):
        try:
            # Extract JSON if it's wrapped in triple backticks
            json_match = re.search(r'```json\n(.*?)\n```', text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(1))
            return json.loads(text)
        except Exception as e:
            logger.error(f"Falha ao executar parse do JSON da resposta do LLM: {str(e)}\nConteúdo recebido: {text[:200]}...")
            return {
                "classification": "UNKNOWN",
                "reasoning": f"Erro de parse JSON: {str(e)}",
                "confidence": 0
            }
