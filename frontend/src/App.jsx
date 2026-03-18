import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Search, ExternalLink, AlertTriangle, CheckCircle, Youtube, Loader2, PlayCircle, Settings } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

const API_BASE = "http://localhost:8000";

function App() {
  const [url, setUrl] = useState('');
  const [provider, setProvider] = useState('gemini');
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState([]);
  const [error, setError] = useState('');
  const [statusMessage, setStatusMessage] = useState('');
  const [maxVideos, setMaxVideos] = useState(5);

  // Auto-detect default provider on mount
  useEffect(() => {
    const fetchConfig = async () => {
      try {
        const response = await axios.get(`${API_BASE}/config`);
        if (response.data.default_provider) {
          setProvider(response.data.default_provider);
        }
      } catch (err) {
        console.error("Erro ao carregar configuração inicial:", err);
      }
    };
    fetchConfig();
  }, []);

  const handleClassifyVideo = async () => {
    if (!url) return;
    setLoading(true);
    setError('');
    setResults([]);
    setStatusMessage('Iniciando análise do vídeo...');

    try {
      setStatusMessage('Extraindo metadados e transcrição...');
      const response = await axios.post(`${API_BASE}/classify/video`, {
        url,
        provider: provider
      });
      setResults([response.data]);
      setStatusMessage('Análise concluída!');
    } catch (err) {
      setError(err.response?.data?.detail || "Erro ao processar o vídeo. Certifique-se que o backend está online.");
      setStatusMessage('');
    } finally {
      setLoading(false);
    }
  };

  const handleClassifyChannel = async () => {
    if (!url) return;
    setLoading(true);
    setError('');
    setResults([]);
    setStatusMessage('Conectando ao canal...');

    try {
      const response = await fetch(`${API_BASE}/classify/channel`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, provider, limit: maxVideos })
      });

      if (!response.ok) throw new Error("Falha ao iniciar análise do canal.");

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      try {
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          
          // SSE format requires double newlines to terminate an event block
          const parts = buffer.split(/\r?\n\r?\n/);
          buffer = parts.pop() || "";

          for (const part of parts) {
            const lines = part.split(/\r?\n/);
            let event = "";
            let data = "";
            
            for (const line of lines) {
              if (line.startsWith('event: ')) event = line.replace('event: ', '').trim();
              if (line.startsWith('data: ')) data = line.replace('data: ', '').trim();
            }

            if (event === 'status') setStatusMessage(data);
            if (event === 'error') {
              setError(data);
              setLoading(false);
            }
            if (event === 'result') {
              const videoResult = JSON.parse(data);
              setResults(prev => [...prev, videoResult]);
            }
            if (event === 'done') {
              setStatusMessage('Análise do canal finalizada!');
              setLoading(false);
            }
          }
        }
      } finally {
        setLoading(false);
        if (statusMessage && !statusMessage.includes('finalizada') && !error) {
           setStatusMessage('Streaming concluído ou interrompido.');
        }
      }
    } catch (err) {
      setError(err.message || "Erro de conexão com o servidor.");
      setLoading(false);
    }
  };

  return (
    <div className="container">
      <header className="header">
        <motion.div
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
        >
          <h1>Felcanator</h1>
          <p>Vigiar e punir gostoso demais</p>
        </motion.div>
      </header>

      <div className="controls-row">
        <div className="control-group">
          <label><Settings size={14} /> Provedor IA</label>
          <select
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            className="provider-select"
          >
            <option value="gemini">Google Gemini</option>
            <option value="openai">OpenAI (GPT-4o mini)</option>
            <option value="anthropic">Anthropic (Claude Haiku)</option>
            <option value="groq">Groq (Llama 3)</option>
          </select>
        </div>

        <div className="control-group">
          <label><PlayCircle size={14} /> Limite de Vídeos (Canal)</label>
          <input 
            type="number" 
            min="1" 
            max="50" 
            value={maxVideos} 
            onChange={(e) => setMaxVideos(parseInt(e.target.value))}
            className="limit-input"
          />
        </div>
      </div>

      <motion.div
        className="search-container"
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.4, delay: 0.2 }}
      >
        <div className="input-wrapper">
          <Youtube color="#94a3b8" />
          <input
            type="text"
            placeholder="Cole o link do vídeo ou canal do YouTube..."
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
        </div>
        <div className="button-group">
          <button 
            className={`btn-main ${loading ? 'btn-loading' : ''}`} 
            onClick={handleClassifyVideo} 
            disabled={loading}
          >
            {loading ? <Loader2 className="animate-spin" /> : 'Analisar Vídeo'}
          </button>
          <button 
            className={`btn-secondary ${loading ? 'btn-loading' : ''}`} 
            onClick={handleClassifyChannel} 
            disabled={loading}
          >
            {loading ? <Loader2 className="animate-spin" /> : 'Analisar Canal'}
          </button>
        </div>
      </motion.div>

      <AnimatePresence>
        {statusMessage && (
          <motion.div 
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="status-banner"
          >
            <Loader2 size={16} className="animate-spin" /> {statusMessage}
          </motion.div>
        )}
      </AnimatePresence>

      {error && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="error-message"
        >
          <AlertTriangle size={18} /> {error}
        </motion.div>
      )}

      <div className="results-grid">
        <AnimatePresence>
          {results.map((result, index) => (
            <motion.div
              key={result.id + index}
              className="result-card"
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, scale: 0.95 }}
              transition={{ duration: 0.4 }}
            >
              <div className="result-header">
                <span className={`badge ${result.classification === 'FLAG' ? 'badge-flag' : 'badge-safe'}`}>
                  {result.classification === 'FLAG' ? (
                    <span style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                      <AlertTriangle size={14} /> FLAG (Conteúdo Adulto)
                    </span>
                  ) : (
                    <span style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                      <CheckCircle size={14} /> SAFE (Livre)
                    </span>
                  )}
                </span>
                <span className="confidence-label">
                  {(result.confidence * 100).toFixed(0)}% certeza
                </span>
              </div>
              <h3 className="video-title">{result.title}</h3>
              <p className="reasoning">{result.reasoning}</p>
              <a href={result.url} target="_blank" rel="noopener noreferrer" className="video-link">
                Ver no YouTube <ExternalLink size={14} />
              </a>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
}

export default App;
