import os
import time
import concurrent.futures
import urllib.parse
from flask import Flask, jsonify
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
import urllib3

# Desativa avisos de SSL se algum servidor do governo estiver com certificado vencido
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
app = Flask(__name__)

@app.route('/healthcheck', methods=['GET'])
def healthcheck():
    return "OK", 200

estrategia_retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
adaptador = HTTPAdapter(max_retries=estrategia_retry)
sessao = requests.Session()
sessao.mount("https://", adaptador)

# 🚨 GAVETA DE MEMÓRIA GLOBAL (Cache Lazy)
CACHE = {
    "dados": None,
    "ultima_atualizacao": 0
}

URLS_SEFAZ = {
    "AM": "https://sistemas.sefaz.am.gov.br", "BA": "https://nfe.sefaz.ba.gov.br",
    "CE": "https://nfe.sefaz.ce.gov.br", "GO": "https://nfe.sefaz.go.gov.br",
    "MG": "https://nfe.fazenda.mg.gov.br", "MS": "https://nfe.fazenda.ms.gov.br",
    "MT": "https://nfe.sefaz.mt.gov.br", "PE": "https://nfe.sefaz.pe.gov.br",
    "PR": "https://nfe.sefa.pr.gov.br", "RS": "https://nfe.sefazrs.rs.gov.br",
    "SP": "https://nfe.fazenda.sp.gov.br", "SVAN": "https://www.sefaz.virtual.sistemas.gov.br",
    "SVRS": "https://nfe.svrs.rs.gov.br", "SVC-AN": "https://www.svc.fazenda.gov.br",
    "SVC-RS": "https://nfe.svrs.rs.gov.br"
}

def ping_estado(autorizador):
    url = URLS_SEFAZ.get(autorizador)
    if not url: return autorizador, 0
    try:
        inicio = time.time()
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

# 🚨 ROTA PRINCIPAL: Ela mesma gerencia a busca e o Cache
@app.route('/api/status', methods=['GET'])
def get_status_sefaz():
    global CACHE
    agora = time.time()

    # Se os dados estão frescos (menos de 30 segundos), devolve a gaveta instantaneamente
    if CACHE["dados"] is not None and (agora - CACHE["ultima_atualizacao"]) < 30:
        return jsonify(CACHE["dados"])

    # Se a gaveta tá velha ou vazia, busca os dados!
    url_alvo = 'https://www.nfe.fazenda.gov.br/portal/disponibilidade.aspx'
    url_proxy = f"https://api.allorigins.win/get?url={urllib.parse.quote(url_alvo)}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    try:
        inicio_global = time.time()
        
        # Tenta buscar usando a ponte (Proxy) para evitar o bloqueio do Render
        res = sessao.get(url_proxy, headers=headers, timeout=15)
        
        # Fallback de Segurança: Se o proxy der erro, tenta bater direto na SEFAZ
        if res.status_code != 200:
            res = sessao.get(url_alvo, headers=headers, timeout=15, verify=False)
            html_governo = res.text
        else:
            html_governo = res.json().get('contents', '')

        latencia_global_ms = int((time.time() - inicio_global) * 1000)

        soup = BeautifulSoup(html_governo, 'html.parser')
        tabela = soup.find('table', class_='tabelaListagemDados')
        
        if not tabela:
            raise ValueError("O layout da SEFAZ mudou ou fomos bloqueados.")

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

        # Dispara os pings locais em paralelo
        latencias_locais = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            resultados = executor.map(ping_estado, autorizadores_encontrados)
            for estado, latencia in resultados:
                latencias_locais[estado] = latencia

        status_sefaz_final = []
        for dado in dados_brutos:
            ping_do_estado = latencias_locais.get(dado["autorizador"], 0)
            if ping_do_estado == 0: ping_do_estado = latencia_global_ms
            dado["latencia_local_ms"] = ping_do_estado
            status_sefaz_final.append(dado)

        # Monta a resposta final
        resultado_final = {
            "sucesso": True,
            "latencia_real_ms": latencia_global_ms,
            "total_estados": len(status_sefaz_final),
            "dados": status_sefaz_final
        }

        # Salva na memória global e atualiza o relógio
        CACHE["dados"] = resultado_final
        CACHE["ultima_atualizacao"] = agora

        return jsonify(resultado_final)

    except Exception as e:
        # 🚨 SISTEMA DE EMERGÊNCIA: Se der erro, mas tiver dados velhos na memória, entrega os velhos!
        if CACHE["dados"] is not None:
            return jsonify(CACHE["dados"])
        
        # Se der erro e a memória estiver vazia, aí sim cospe o erro
        return jsonify({
            "sucesso": False,
            "latencia_real_ms": 0,
            "mensagem": f"Erro de comunicação: {str(e)}",
            "dados": []
        }), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port, debug=False)
