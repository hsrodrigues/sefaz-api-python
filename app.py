import time
import threading
import random
import requests
import urllib3 # 🚨 ADICIONE ESTA LINHA NO TOPO
from bs4 import BeautifulSoup
from flask import Flask, jsonify

# 🚨 DESATIVA OS AVISOS DE SEGURANÇA CHATOS DO PYTHON PARA SITES DO GOVERNO
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

status_oficial_sefaz = {}
banco_de_dados_app = {}
ultima_att = "--:--:--"

def scraper_oficial_sefaz():
    global status_oficial_sefaz, ultima_att
    url = "https://www.nfe.fazenda.gov.br/portal/disponibilidade.aspx" # Mudei para HTTPS
    
    # Disfarce reforçado de navegador
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7'
    }

    while True:
        try:
            print("Tentando acessar o site da SEFAZ...")
            
            # 🚨 verify=False É O SEGREDO PARA PASSAR PELO SSL DO GOVERNO
            req = requests.get(url, headers=headers, timeout=15, verify=False)
            
            # Verifica se a SEFAZ bloqueou nosso IP (Render)
            if req.status_code != 200:
                print(f"🚨 SEFAZ bloqueou a conexão! Código de erro: {req.status_code}")
            else:
                soup = BeautifulSoup(req.text, 'html.parser')
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
                                
                            status_oficial_sefaz[autorizador] = status
                    
                    ultima_att = time.strftime("%H:%M:%S")
                    print(f"[{ultima_att}] ✅ Dados puxados da SEFAZ com sucesso!")
                else:
                    print("🚨 Tabela não encontrada no HTML. A SEFAZ pode ter mudado o layout.")
                    
        except Exception as e:
            # AGORA O ERRO VAI APARECER NO LOG DO RENDER
            print(f"🚨 ERRO FATAL AO LER SEFAZ: {e}")
            
        time.sleep(180)
