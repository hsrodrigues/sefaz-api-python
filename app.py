import os
import time
import concurrent.futures # 🚨 NOVO: Para disparar pings simultâneos
from flask import Flask, jsonify
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
app = Flask(__name__)

@app.route('/healthcheck', methods=['GET'])
def healthcheck():
    return "OK", 200

estrategia_retry = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
adaptador = HTTPAdapter(max_retries=estrategia_retry)
sessao = requests.Session()
sessao.mount("https://", adaptador)

# 🚨 MAPEAMENTO DOS SERVIDORES REAIS DE CADA ESTADO
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
    """Bate no servidor do estado e mede os milissegundos."""
    url = URLS_SEFAZ.get(autorizador)
    if not url: return autorizador, 0
    try:
        inicio = time.time()
        # Usamos HEAD em vez de GET para não baixar o site todo, apenas testar a rede
        sessao.head(url, verify=False, timeout=3.0) 
        return autorizador, int((time.time() - inicio) * 1000)
    except:
        return autorizador, 0 # Se o servidor do estado recusar a conexão, retorna 0

def traduz_status(td_element):
    """Lê a imagem da coluna e traduz para texto."""
    if not td_element: return "Pendente"
    img_tag = td_element.find('img')
    if not img_tag: return "Pendente"
    
    src = img_tag.get('src', '')
    if 'verde' in src: return "Normal"
    if 'amarela' in src: return "Instavel"
    if 'vermelha' in src: return "Inativo"
    return "Pendente"

@app.route('/api/status', methods=['GET'])
def get_status_sefaz():
    url_nacional = 'https://www.nfe.fazenda.gov.br/portal/disponibilidade.aspx'
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36'}

    try:
        # PING GLOBAL (Portal Nacional)
        inicio_ping_global = time.time()
        response = sessao.get(url_nacional, headers=headers, verify=False, timeout=20)
        response.raise_for_status() 
        latencia_global_ms = int((time.time() - inicio_ping_global) * 1000)

        soup = BeautifulSoup(response.text, 'html.parser')
        tabela = soup.find('table', class_='tabelaListagemDados')
        linhas = tabela.find_all('tr')[1:] 

        dados_brutos = []
        autorizadores_encontrados = []

        # 1. Lê a tabela e pega os status visuais
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
            if "Inativo" in todos_status:
                status_geral = "INATIVO"
            elif "Instavel" in todos_status:
                status_geral = "INSTÁVEL"
            else:
                status_geral = "OPERACIONAL"

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

        # 2. 🚨 DISPARA O PING SIMULTÂNEO PARA TODOS OS ESTADOS (Multithreading)
        latencias_locais = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            resultados = executor.map(ping_estado, autorizadores_encontrados)
            for estado, latencia in resultados:
                latencias_locais[estado] = latencia

        # 3. Junta tudo: Status Visual + Ping Local do Estado
        status_sefaz_final = []
        for dado in dados_brutos:
            ping_do_estado = latencias_locais.get(dado["autorizador"], 0)
            
            # Se o ping local falhar, usa o global como plano B para não quebrar o gráfico
            if ping_do_estado == 0:
                ping_do_estado = latencia_global_ms
                
            dado["latencia_local_ms"] = ping_do_estado
            status_sefaz_final.append(dado)

        return jsonify({
            "sucesso": True,
            "latencia_real_ms": latencia_global_ms,
            "total_estados": len(status_sefaz_final),
            "dados": status_sefaz_final
        })

    except Exception as e:
        return jsonify({"sucesso": False, "erro": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port, debug=False)
