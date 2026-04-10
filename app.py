import os
import time
import concurrent.futures
import threading
import urllib.parse
from flask import Flask, jsonify
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
import urllib3

# Desativa avisos de certificados SSL do governo
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
app = Flask(__name__)

# 🚨 A NOSSA GAVETA DE MEMÓRIA (CACHE)
CACHE_SEFAZ = {
    "sucesso": False,
    "latencia_real_ms": 0,
    "mensagem": "Servidor aquecendo a turbina anti-bloqueio... tente em 5 segundos.",
    "dados": []
}

@app.route('/healthcheck', methods=['GET'])
def healthcheck():
    return "OK", 200

# Configuração de conexão com tentativas automáticas
estrategia_retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
adaptador = HTTPAdapter(max_retries=estrategia_retry)
sessao = requests.Session()
sessao.mount("https://", adaptador)

# URLs diretas para tentar o ping local de cada estado
URLS_SEFAZ = {
    "AM": "https://sistemas.sefaz.am.gov.br",
    "BA": "https://nfe.sefaz.ba.gov.br",
    "CE": "https://nfe.sefaz.ce.gov.br",
    "GO": "https://nfe.sefaz.go.gov.br",
    "MG": "https://nfe.fazenda.mg.gov.br",
    "MS": "https://nfe.fazenda.ms.gov.br",
    "MT": "https://nfe.sefaz.mt.gov.br",
    "PE": "https://nfe.sefaz.pe.gov.br",
    "PR": "https://nfe.sefa.pr.gov.br",
    "RS": "https://nfe.sefazrs.rs.gov.br",
    "SP": "https://nfe.fazenda.sp.gov.br",
    "SVAN": "https://www.sefaz.virtual.sistemas.gov.br",
    "SVRS": "https://nfe.svrs.rs.gov.br",
    "SVC-AN": "https://www.svc.fazenda.gov.br",
    "SVC-RS": "https://nfe.svrs.rs.gov.br"
}

def ping_estado(autorizador):
    url = URLS_SEFAZ.get(autorizador)
    if not url: return autorizador, 0
    try:
        inicio = time.time()
        # Bate na porta do estado bem rápido (1.5s). Se enrolar, retorna 0.
        sessao.head(url, verify=False, timeout=1.5) 
        return autorizador, int((time.time() - inicio) * 1000)
    except:
        return autorizador, 0

def traduz_status(td_element):
    if not td_element: return "Pendente"
    img_tag = td_element.find('img')
    if not img_tag: return "Pendente"
    src = img_tag.get('src', '')
    if 'verde' in src: return "Normal"
    if 'amarela' in src: return "Instavel"
    if 'vermelha' in src: return "Inativo"
    return "Pendente"

# 🚨 MOTOR QUE RODA EM SEGUNDO PLANO SEM PARAR (ANTI-BLOQUEIO)
def trabalhador_de_fundo():
    global CACHE_SEFAZ
    
    url_alvo = 'https://www.nfe.fazenda.gov.br/portal/disponibilidade.aspx'
    # Usando o Proxy AllOrigins para a SEFAZ não bloquear o IP do Render
    url_proxy = f"https://api.allorigins.win/get?url={urllib.parse.quote(url_alvo)}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    while True:
        try:
            inicio_ping_global = time.time()
            
            # Pede pro Proxy buscar o HTML da SEFAZ
            response = sessao.get(url_proxy, headers=headers, timeout=20)
            response.raise_for_status() 
            
            # O proxy devolve um JSON. O HTML do governo fica dentro de "contents"
            dados_proxy = response.json()
            html_governo = dados_proxy.get('contents', '')
            
            latencia_global_ms = int((time.time() - inicio_ping_global) * 1000)

            soup = BeautifulSoup(html_governo, 'html.parser')
            tabela = soup.find('table', class_='tabelaListagemDados')
            
            if not tabela:
                raise ValueError("O Proxy não conseguiu ler a tabela da SEFAZ")

            linhas = tabela.find_all('tr')[1:] 
            dados_brutos = []
            autorizadores_encontrados = []

            for linha in linhas:
                colunas = linha.find_all('td')
                if len(colunas) < 6: continue 

                autorizador = colunas[0].text.strip()
                autorizadores_encontrados.append(autorizador)

                autorizacao = traduz_status(colunas[1])
                retorno = traduz_status(colunas[2])
                inutilizacao = traduz_status(colunas[3])
                consulta = traduz_status(colunas[4])
                status_servico = traduz_status(colunas[5])

                todos_status = [autorizacao, retorno, inutilizacao, consulta, status_servico]
                if "Inativo" in todos_status: status_geral = "INATIVO"
                elif "Instavel" in todos_status: status_geral = "INSTÁVEL"
                else: status_geral = "OPERACIONAL"

                dados_brutos.append({
                    "autorizador": autorizador,
                    "status_geral": status_geral,
                    "servicos": {
                        "autorizacao": autorizacao,
                        "retorno": retorno,
                        "inutilizacao": inutilizacao,
                        "consulta": consulta,
                        "status_servico": status_servico
                    }
                })

            # Dispara os pings locais (reduzi de 20 para 5 trabalhadores para não irritar os servidores locais)
            latencias_locais = {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                resultados = executor.map(ping_estado, autorizadores_encontrados)
                for estado, latencia in resultados:
                    latencias_locais[estado] = latencia

            status_sefaz_final = []
            for dado in dados_brutos:
                ping_do_estado = latencias_locais.get(dado["autorizador"], 0)
                # Se o estado não responder ao ping direto, usa a latência do proxy como base
                if ping_do_estado == 0: ping_do_estado = latencia_global_ms
                dado["latencia_local_ms"] = ping_do_estado
                status_sefaz_final.append(dado)

            # 🚨 ATUALIZA A GAVETA COM OS DADOS PRONTOS
            CACHE_SEFAZ = {
                "sucesso": True,
                "latencia_real_ms": latencia_global_ms,
                "total_estados": len(status_sefaz_final),
                "dados": status_sefaz_final
            }

        except Exception as e:
            # Se a SEFAZ ou o Proxy falharem, avisa na gaveta
            CACHE_SEFAZ = {
                "sucesso": False,
                "latencia_real_ms": 0,
                "mensagem": f"Aguardando Governo/Proxy: {str(e)}",
                "dados": []
            }
        
        # Pausa de 30 segundos entre as varreduras (pra não levar ban do Proxy)
        time.sleep(30)

# Inicia o motor de fundo assim que o servidor liga
thread_fundo = threading.Thread(target=trabalhador_de_fundo, daemon=True)
thread_fundo.start()

# 🚨 A ROTA DA SUA API: Agora ela só entrega o que está na gaveta (Instantâneo)
@app.route('/api/status', methods=['GET'])
def get_status_sefaz():
    return jsonify(CACHE_SEFAZ)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port, debug=False)
