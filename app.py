import os
from flask import Flask, jsonify
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
import urllib3

# Desativa os avisos de certificado inseguro do governo
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

# ---------------------------------------------------------
# CONFIGURAÇÃO DE RESILIÊNCIA (O "Coração" da estabilidade)
# ---------------------------------------------------------
estrategia_retry = Retry(
    total=5,                
    backoff_factor=1,       
    status_forcelist=[429, 500, 502, 503, 504], 
    allowed_methods=["GET"]
)

adaptador = HTTPAdapter(max_retries=estrategia_retry)
sessao = requests.Session()
sessao.mount("https://", adaptador)
sessao.mount("http://", adaptador)
# ---------------------------------------------------------

@app.route('/api/status', methods=['GET'])
def get_status_sefaz():
    url = 'https://www.nfe.fazenda.gov.br/portal/disponibilidade.aspx'
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Connection': 'keep-alive'
    }

    try:
        print("Buscando dados na SEFAZ de forma segura...")
        
        response = sessao.get(url, headers=headers, verify=False, timeout=20)
        response.raise_for_status() 

        soup = BeautifulSoup(response.text, 'html.parser')
        status_sefaz = []

        tabela = soup.find('table', class_='tabelaListagemDados')
        if not tabela:
            raise ValueError("Tabela de status não encontrada no HTML retornado.")

        linhas = tabela.find_all('tr')[1:] 

        for linha in linhas:
            colunas = linha.find_all('td')
            if len(colunas) < 2:
                continue

            autorizador = colunas[0].text.strip()
            
            img_tag = colunas[1].find('img')
            img_src = img_tag['src'] if img_tag else ''

            status = 'Desconhecido'
            if 'verde' in img_src:
                status = 'Normal'
            elif 'amarela' in img_src:
                status = 'Instabilidade'
            elif 'vermelha' in img_src:
                status = 'Inativo'
            elif 'bola_' in img_src:
                status = 'Pendente'

            status_sefaz.append({
                "autorizador": autorizador,
                "autorizacao4": status
            })

        return jsonify({
            "sucesso": True,
            "ultima_atualizacao": response.headers.get('Date', 'Data não informada'),
            "total_estados": len(status_sefaz),
            "dados": status_sefaz
        })

    except requests.exceptions.RetryError:
        return jsonify({"sucesso": False, "erro": "SEFAZ está fora do ar ou recusou conexão após 5 tentativas."}), 503
    except requests.exceptions.ReadTimeout:
        return jsonify({"sucesso": False, "erro": "Tempo limite esgotado. A SEFAZ demorou mais de 20 segundos para responder."}), 504
    except Exception as e:
        print(f"Erro inesperado: {e}")
        return jsonify({"sucesso": False, "erro": "Falha ao buscar dados", "detalhe": str(e)}), 500

# ==========================================
# 👇 MUDANÇAS CRÍTICAS PARA O RENDER AQUI 👇
# ==========================================
if __name__ == '__main__':
    # O Render injeta uma porta dinâmica através do "os.environ"
    # Se não achar (rodando local), ele usa a 3000 como backup
    port = int(os.environ.get("PORT", 3000))
    
    # O host "0.0.0.0" diz ao Python para liberar o acesso para a internet externa
    # O debug=False é obrigatório em produção por segurança
    print(f"✅ Iniciando servidor na porta {port}...")
    app.run(host="0.0.0.0", port=port, debug=False)
