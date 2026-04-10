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

# --- CONFIGURAÇÃO DE LOGS ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("SefazMonitor")

# --- MODELOS DE DADOS ---
class SefazStatusModel(BaseModel):
    autorizador: str
    status_geral: str
    latencia_ms: int
    historico: list[int]

class SefazResponseModel(BaseModel):
    sucesso: bool
    timestamp: str
    dados: list[SefazStatusModel]

# --- CACHE EM MEMÓRIA ---
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

# --- MOTORES DE FUNDO (WORKERS) ---
async def worker_scraper_sefaz():
    """Lê o site da SEFAZ a cada 3 minutos para não ser bloqueado"""
    url = "https://www.nfe.fazenda.gov.br/portal/disponibilidade.aspx"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'}
    
   timeout = httpx.Timeout(15.0)
    async with httpx.AsyncClient(verify=False, timeout=timeout, headers=headers, follow_redirects=True) as client:
        while True:
            try:
                response = await client.get(url)
                response.raise_for_status()
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
            except Exception as e:
                logger.error(f"Erro ao ler SEFAZ: {str(e)}")
            
            await asyncio.sleep(180) # Aguarda 3 minutos

async def worker_gerador_pulsos():
    """Gera o 'batimento cardíaco' do gráfico para o App Android a cada 10s"""
    while True:
        for autorizador, status in cache.official_status.items():
            if autorizador not in cache.app_data:
                cache.app_data[autorizador] = {"historico": []}
            
            if status == "OPERACIONAL": latencia = random.randint(15, 65)
            elif status == "INSTÁVEL": latencia = random.randint(150, 300)
            else: latencia = random.randint(400, 600)
            
            hist = cache.app_data[autorizador]["historico"]
            hist.append(latencia)
            if len(hist) > 30: hist.pop(0)
            
            cache.app_data[autorizador]["latencia_ms"] = latencia
            cache.app_data[autorizador]["status_geral"] = status
            
        await asyncio.sleep(10)

# --- INICIALIZAÇÃO DA API ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    task_scraper = asyncio.create_task(worker_scraper_sefaz())
    task_pulsos = asyncio.create_task(worker_gerador_pulsos())
    yield
    task_scraper.cancel()
    task_pulsos.cancel()

app = FastAPI(title="Sefaz Monitor API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/status", response_model=SefazResponseModel)
async def get_sefaz_status():
    dados_formatados = cache.get_formatted_data()
    return SefazResponseModel(
        sucesso=len(dados_formatados) > 0,
        timestamp=cache.last_update,
        dados=dados_formatados
    )
