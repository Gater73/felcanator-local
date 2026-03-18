from google import genai
from openai import OpenAI
from anthropic import Anthropic
from groq import Groq
import os
import json
import re
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
            else:
                logger.error(f"Provedor {active_provider} não suportado.")
                return {"error": f"Provider {active_provider} not supported."}
            
            if "error" not in result:
                logger.info(f"Classificação concluída: {result.get('classification')} (Confiança: {result.get('confidence')})")
            return result
        except Exception as e:
            logger.error(f"Erro fatal na classificação com {active_provider}: {str(e)}", exc_info=True)
            return {"error": str(e)}

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
