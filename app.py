import os
import urllib.parse
from flask import Flask, jsonify
import requests
from bs4 import BeautifulSoup
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
app = Flask(__name__)

def traduz_status(td_element):
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
    url_alvo = 'https://www.nfe.fazenda.gov.br/portal/disponibilidade.aspx'
    url_proxy = f"https://api.allorigins.win/get?url={urllib.parse.quote(url_alvo)}"
    headers = {'User-Agent': 'Mozilla/5.0'}

    try:
        # Usa o proxy só para ler a tabela sem tomar bloqueio
        res = requests.get(url_proxy, headers=headers, timeout=15)
        html = res.json().get('contents', '') if res.status_code == 200 else requests.get(url_alvo, verify=False, timeout=10).text

        soup = BeautifulSoup(html, 'html.parser')
        tabela = soup.find('table', class_='tabelaListagemDados')

        if not tabela:
            raise ValueError("Não foi possível carregar a tabela.")

        linhas = tabela.find_all('tr')[1:]
        dados = []

        for linha in linhas:
            cols = linha.find_all('td')
            if len(cols) < 6: continue

            autorizador = cols[0].text.strip()
            todos_status = [traduz_status(cols[i]) for i in range(1, 6)]
            status_geral = "INATIVO" if "Inativo" in todos_status else "INSTÁVEL" if "Instavel" in todos_status else "OPERACIONAL"

            dados.append({
                "autorizador": autorizador,
                "status_geral": status_geral,
                "latencia_local_ms": 0, # 🚨 Mandamos 0, porque o Celular é quem vai preencher isso!
                "servicos": {
                    "autorizacao": todos_status[0],
                    "retorno": todos_status[1],
                    "inutilizacao": todos_status[2],
                    "consulta": todos_status[3],
                    "status_servico": todos_status[4]
                }
            })

        return jsonify({"sucesso": True, "latencia_real_ms": 0, "dados": dados})

    except Exception as e:
        return jsonify({"sucesso": False, "mensagem": str(e), "dados": []}), 500

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 3000)))
