import time
import threading
import random
import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify

app = Flask(__name__)

# Memória RAM do servidor
status_oficial_sefaz = {} # Guarda a cor real das bolinhas
banco_de_dados_app = {}   # Guarda o histórico do gráfico para o App
ultima_att = "--:--:--"

def scraper_oficial_sefaz():
    """Motor 1: Lê o site da SEFAZ a cada 3 minutos para não ser banido"""
    global status_oficial_sefaz, ultima_att
    url = "http://www.nfe.fazenda.gov.br/portal/disponibilidade.aspx"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0'}

    while True:
        try:
            req = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(req.text, 'html.parser')
            tabela = soup.find('table', {'class': 'tabelaListagemDados'})
            
            if tabela:
                linhas = tabela.find_all('tr')[1:] # Pula o cabeçalho
                for linha in linhas:
                    colunas = linha.find_all('td')
                    if len(colunas) >= 6:
                        autorizador = colunas[0].text.strip()
                        
                        # Pega todas as bolinhas da linha (Autorização, Consulta, etc)
                        bolinhas = [td.find('img')['src'] for td in colunas[1:] if td.find('img')]
                        
                        # Lógica implacável: Se tem uma vermelha, caiu. Se tem amarela, instável.
                        if any('vermelha' in b for b in bolinhas):
                            status = "FALHA"
                        elif any('amarela' in b for b in bolinhas):
                            status = "INSTÁVEL"
                        else:
                            status = "OPERACIONAL"
                            
                        status_oficial_sefaz[autorizador] = status
                
                ultima_att = time.strftime("%H:%M:%S")
                print(f"[{ultima_att}] SEFAZ Sincronizada com sucesso.")
        except Exception as e:
            print("Erro ao ler SEFAZ:", e)
            
        time.sleep(180) # Aguarda 3 minutos

def gerador_de_pulsos_fintech():
    """Motor 2: Roda a cada 10 segundos para dar vida ao gráfico do app"""
    global banco_de_dados_app
    while True:
        for autorizador, status in status_oficial_sefaz.items():
            if autorizador not in banco_de_dados_app:
                banco_de_dados_app[autorizador] = {"historico": []}
            
            # Gera a latência visual baseada na realidade
            if status == "OPERACIONAL":
                latencia = random.randint(15, 65)  # Gráfico baixo e saudável
            elif status == "INSTÁVEL":
                latencia = random.randint(150, 300) # Gráfico alto e nervoso
            else:
                latencia = random.randint(400, 600) # Gráfico estourado (Caiu)
            
            # Atualiza o histórico
            hist = banco_de_dados_app[autorizador]["historico"]
            hist.append(latencia)
            if len(hist) > 30: # Mantém só os últimos 30 pontos
                hist.pop(0)
            
            banco_de_dados_app[autorizador]["latencia_ms"] = latencia
            banco_de_dados_app[autorizador]["status_geral"] = status
            
        time.sleep(10) # Pulso a cada 10s

# Inicia os dois motores simultaneamente em background
threading.Thread(target=scraper_oficial_sefaz, daemon=True).start()
threading.Thread(target=gerador_de_pulsos_fintech, daemon=True).start()

@app.route('/api/status_v2', methods=['GET'])
def api_status():
    """Endpoint super rápido que o Android vai consumir"""
    dados_formatados = []
    for aut, info in banco_de_dados_app.items():
        dados_formatados.append({
            "autorizador": aut,
            "status_geral": info["status_geral"],
            "latencia_ms": info["latencia_ms"],
            "historico": info["historico"]
        })
    
    # Ordenar alfabeticamente igual ao site
    dados_formatados = sorted(dados_formatados, key=lambda x: x["autorizador"])
    
    return jsonify({
        "sucesso": len(dados_formatados) > 0,
        "timestamp": ultima_att,
        "dados": dados_formatados
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
