import os
import time
from flask import Flask, jsonify
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
app = Flask(__name__)

estrategia_retry = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
adaptador = HTTPAdapter(max_retries=estrategia_retry)
sessao = requests.Session()
sessao.mount("https://", adaptador)

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
    url = 'https://www.nfe.fazenda.gov.br/portal/disponibilidade.aspx'
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36'}

    try:
        # Marca o tempo exato antes de bater na SEFAZ (Início do PING)
        inicio_ping = time.time()
        
        response = sessao.get(url, headers=headers, verify=False, timeout=20)
        response.raise_for_status() 

        # Calcula a latência real em milissegundos
        latencia_ms = int((time.time() - inicio_ping) * 1000)

        soup = BeautifulSoup(response.text, 'html.parser')
        status_sefaz = []
        
        tabela = soup.find('table', class_='tabelaListagemDados')
        linhas = tabela.find_all('tr')[1:] 

        for linha in linhas:
            colunas = linha.find_all('td')
            if len(colunas) < 6: continue # Garante que tem todas as colunas

            # Lê TODAS as colunas do painel
            autorizador = colunas[0].text.strip()
            autorizacao = traduz_status(colunas[1])
            retorno = traduz_status(colunas[2])
            inutilizacao = traduz_status(colunas[3])
            consulta = traduz_status(colunas[4])
            status_servico = traduz_status(colunas[5])

            # Define o status geral (Se algum estiver inativo, o estado fica alerta)
            todos_status = [autorizacao, retorno, inutilizacao, consulta, status_servico]
            if "Inativo" in todos_status:
                status_geral = "INATIVO"
            elif "Instavel" in todos_status:
                status_geral = "INSTÁVEL"
            else:
                status_geral = "OPERACIONAL"

            status_sefaz.append({
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

        return jsonify({
            "sucesso": True,
            "latencia_real_ms": latencia_ms,
            "total_estados": len(status_sefaz),
            "dados": status_sefaz
        })

    except Exception as e:
        return jsonify({"sucesso": False, "erro": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port, debug=False)
