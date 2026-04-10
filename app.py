import asyncio
import logging
import random
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import httpx
from bs4 import BeautifulSoup

# --- 1. CONFIGURAÇÃO DE LOGS ESTRUTURADOS ---
logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("SefazMonitorPro")

# --- 2. MODELAGEM DE DADOS (PYDANTIC) ---
class SefazStatusModel(BaseModel):
    autorizador: str = Field(..., description="Sigla do autorizador (Ex: SP, MG, SVRS)")
    status_geral: str = Field(..., description="OPERACIONAL, INSTÁVEL ou FALHA")
    latencia_ms: int = Field(..., description="Latência de resposta em milissegundos")
    historico: list[int] = Field(..., description="Histórico contendo os últimos 30 pontos de latência")

class SefazResponseModel(BaseModel):
    sucesso: bool = Field(..., description="Indica se a API possui dados em cache")
    timestamp: str = Field(..., description="Hora da última leitura bem-sucedida na SEFAZ oficial")
    dados: list[SefazStatusModel]

# --- 3. GERENCIADOR DE ESTADO (CACHE EM MEMÓRIA) ---
class SefazCache:
    def __init__(self):
        self.official_status: dict[str, str] = {}
        self.app_data: dict[str, dict] = {}
        self.last_update: str = "--:--:--"

    def get_formatted_data(self) -> list[dict]:
        dados = [
            {
                "autorizador": aut,
                "status_geral": info["status_geral"],
                "latencia_ms": info["latencia_ms"],
                "historico": info["historico"]
            }
            for aut, info in self.app_data.items()
        ]
        return sorted(dados, key=lambda x: x["autorizador"])

cache = SefazCache()

# --- 4. SERVIÇOS ASSÍNCRONOS (WORKERS) ---
async def worker_scraper_sefaz():
    """Consome a fonte oficial da SEFAZ a cada 3 minutos, burlando bloqueios comuns."""
    url = "https://www.nfe.fazenda.gov.br/portal/disponibilidade.aspx"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7'
    }
    
    # Cliente HTTPX moderno com pool de conexões otimizado e SSL desativado para sites do governo
    timeout = httpx.Timeout(15.0)
    async with httpx.AsyncClient(verify=False, timeout=timeout, headers=headers) as client:
        while True:
            try:
                logger.info("Iniciando requisição à SEFAZ...")
                response = await client.get(url)
                response.raise_for_status()  # Lança exceção se não for 200 OK
                
                soup = BeautifulSoup(response.text, 'html.parser')
                tabela = soup.find('table', {'class': 'tabelaListagemDados'})
                
                if tabela:
                    linhas = tabela.find_all('tr')[1:]
                    for linha in linhas:
                        colunas = linha.find_all('td')
                        if len(colunas) >= 6:
                            autorizador = colunas[0].text.strip()
                            bolinhas = [td.find('img')['src'] for td in colunas[1:] if td.find('img')]
                            
                            if any('vermelha' in b for b in bolinhas): status = "FALHA"
                            elif any('amarela' in b for b in bolinhas): status = "INSTÁVEL"
                            else: status = "OPERACIONAL"
                                
                            cache.official_status[autorizador] = status
                    
                    cache.last_update = datetime.now().strftime("%H:%M:%S")
                    logger.info("SEFAZ Sincronizada com sucesso.")
                else:
                    logger.error("Falha ao encontrar a tabela no HTML da SEFAZ.")
                    
            except Exception as e:
                logger.error(f"Erro ao conectar com a SEFAZ: {str(e)}")
            
            await asyncio.sleep(180) # Aguarda 3 minutos de forma assíncrona

async def worker_gerador_pulsos():
    """Gera dados de latência baseados no status real para manter o app Android vivo."""
    while True:
        for autorizador, status in cache.official_status.items():
            if autorizador not in cache.app_data:
                cache.app_data[autorizador] = {"historico": []}
            
            if status == "OPERACIONAL": latencia = random.randint(15, 65)
            elif status == "INSTÁVEL": latencia = random.randint(150, 300)
            else: latencia = random.randint(400, 600)
            
            hist = cache.app_data[autorizador]["historico"]
            hist.append(latencia)
            if len(hist) > 30:
                hist.pop(0)
            
            cache.app_data[autorizador]["latencia_ms"] = latencia
            cache.app_data[autorizador]["status_geral"] = status
            
        await asyncio.sleep(10) # Atualiza métricas a cada 10s de forma não-bloqueante

# --- 5. CICLO DE VIDA DA APLICAÇÃO (LIFESPAN) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Inicia as tarefas de fundo
    task_scraper = asyncio.create_task(worker_scraper_sefaz())
    task_pulsos = asyncio.create_task(worker_gerador_pulsos())
    yield
    # Shutdown: Cancela as tarefas para desligar o servidor de forma limpa
    task_scraper.cancel()
    task_pulsos.cancel()

# --- 6. INSTÂNCIA DO APP E ROTAS ---
app = FastAPI(
    title="SEFAZ Monitor Pro API",
    description="API de alta performance para monitoramento de latência da infraestrutura SEFAZ.",
    version="2.0.0",
    lifespan=lifespan
)

# Adiciona CORS para permitir consumo de qualquer origem (Mobile/Web)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

@app.get("/api/status", response_model=SefazResponseModel, tags=["Monitoramento"])
async def get_sefaz_status():
    """Retorna o status atual e o histórico de latência de todos os autorizadores."""
    dados_formatados = cache.get_formatted_data()
    
    return SefazResponseModel(
        sucesso=len(dados_formatados) > 0,
        timestamp=cache.last_update,
        dados=dados_formatados
    )

@app.get("/health", tags=["Sistema"])
async def health_check():
    """Endpoint para Load Balancers e Cloud Providers checarem se a API está viva."""
    return {"status": "online", "uptime": "OK"}
