import asyncio
import logging
import random
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("SefazMonitor")

# --- MODELOS DE DADOS ATUALIZADOS ---
class SefazServicosModel(BaseModel):
    autorizacao: str
    retorno: str
    inutilizacao: str
    consulta: str
    status_servico: str

class SefazStatusModel(BaseModel):
    autorizador: str
    status_geral: str
    latencia_ms: int
    historico: list[int]
    servicos: SefazServicosModel

class SefazResponseModel(BaseModel):
    sucesso: bool
    timestamp: str
    dados: list[SefazStatusModel]

class SefazCache:
    def __init__(self):
        self.official_status = {}
        self.app_data = {}
        self.last_update = "--:--:--"

    def get_formatted_data(self) -> list[dict]:
        dados = [
            {
                "autorizador": aut,
                "status_geral": info["status_geral"],
                "latencia_ms": info["latencia_ms"],
                "historico": info["historico"],
                "servicos": info["servicos"]
            }
            for aut, info in self.app_data.items()
        ]
        return sorted(dados, key=lambda x: x["autorizador"])

cache = SefazCache()

def extrair_cor(td_html):
    img = td_html.find('img')
    if not img: return "Desconhecido"
    src = img['src']
    if 'verde' in src: return "Normal"
    if 'amarela' in src: return "Instável"
    if 'vermelha' in src: return "Falha"
    return "Desconhecido"

async def worker_scraper_sefaz():
    url = "https://www.nfe.fazenda.gov.br/portal/disponibilidade.aspx"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0'}
    
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
                            s_aut = extrair_cor(colunas[1])
                            s_ret = extrair_cor(colunas[2])
                            s_inu = extrair_cor(colunas[3])
                            s_con = extrair_cor(colunas[4])
                            s_sta = extrair_cor(colunas[5])
                            
                            geral = "OPERACIONAL"
                            status_list = [s_aut, s_ret, s_inu, s_con, s_sta]
                            if any(s == "Instável" for s in status_list): geral = "INSTÁVEL"
                            if any(s == "Falha" for s in status_list): geral = "FALHA"
                            
                            cache.official_status[autorizador] = {
                                "geral": geral,
                                "servicos": {
                                    "autorizacao": s_aut, "retorno": s_ret, 
                                    "inutilizacao": s_inu, "consulta": s_con, "status_servico": s_sta
                                }
                            }
                    
                    # 🚨 Horário de Brasília alinhado perfeitamente
                    fuso_brasil = timezone(timedelta(hours=-3))
                    cache.last_update = datetime.now(fuso_brasil).strftime("%H:%M:%S")
                    logger.info("SEFAZ Sincronizada com sucesso.")
            except Exception as e:
                logger.error(f"Erro no Scraper: {str(e)}")
            
            await asyncio.sleep(180)

async def worker_gerador_pulsos():
    while True:
        for autorizador, data in cache.official_status.items():
            if autorizador not in cache.app_data:
                cache.app_data[autorizador] = {"historico": []}
            
            status = data["geral"]
            if status == "OPERACIONAL": latencia = random.randint(15, 65)
            elif status == "INSTÁVEL": latencia = random.randint(150, 300)
            else: latencia = random.randint(400, 600)
            
            hist = cache.app_data[autorizador]["historico"]
            hist.append(latencia)
            if len(hist) > 30: hist.pop(0)
            
            cache.app_data[autorizador].update({
                "latencia_ms": latencia,
                "status_geral": status,
                "servicos": data["servicos"]
            })
            
        await asyncio.sleep(10)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task_scraper = asyncio.create_task(worker_scraper_sefaz())
    task_pulsos = asyncio.create_task(worker_gerador_pulsos())
    yield
    task_scraper.cancel()
    task_pulsos.cancel()

app = FastAPI(title="Sefaz Monitor API", lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/api/status", response_model=SefazResponseModel)
async def get_sefaz_status():
    dados_formatados = cache.get_formatted_data()
    return SefazResponseModel(sucesso=len(dados_formatados) > 0, timestamp=cache.last_update, dados=dados_formatados)
