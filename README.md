# SEFAZ Monitor API

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![Status](https://img.shields.io/badge/status-em%20desenvolvimento-2563EB?style=for-the-badge)

API assíncrona para monitorar a disponibilidade dos serviços da **SEFAZ
Nacional**. O serviço consulta a página oficial de disponibilidade da NF-e,
interpreta o status de cada autorizador e disponibiliza os dados em um
endpoint JSON.

## Funcionalidades

- Consulta automática da disponibilidade dos autorizadores da SEFAZ.
- Classificação dos serviços como `OPERACIONAL`, `INSTÁVEL` ou `FALHA`.
- Monitoramento de autorização, retorno, inutilização, consulta e status.
- Histórico recente de latência por autorizador.
- Atualização periódica em background sem bloquear a API.
- Validação da resposta com modelos Pydantic.
- CORS configurado para integração com uma interface web.

## Endpoint

```text
GET /api/status
```

Exemplo de resposta:

```json
{
  "sucesso": true,
  "timestamp": "12:30:00",
  "dados": [
    {
      "autorizador": "SP",
      "status_geral": "OPERACIONAL",
      "latencia_ms": 42,
      "historico": [38, 42, 45],
      "servicos": {
        "autorizacao": "Normal",
        "retorno": "Normal",
        "inutilizacao": "Normal",
        "consulta": "Normal",
        "status_servico": "Normal"
      }
    }
  ]
}
```

## Tecnologias

- Python 3.10+
- FastAPI
- Uvicorn
- HTTPX
- BeautifulSoup
- Pydantic
- Docker

## Executando localmente

Instale as dependências:

```bash
python -m venv .venv
# Windows
.\.venv\Scripts\pip install -r requirements.txt
# Linux/macOS
# .venv/bin/pip install -r requirements.txt
```

Inicie a API:

```bash
uvicorn main:app --reload
```

Consulte:

- <http://127.0.0.1:8000/api/status>
- <http://127.0.0.1:8000/docs>

## Docker

```bash
docker build -t sefaz-monitor .
docker run --rm -p 8000:8000 -e PORT=8000 sefaz-monitor
```

## Como funciona

O scraper consulta a página oficial da NF-e a cada três minutos. Um segundo
processo atualiza os pulsos de latência a cada dez segundos, mantendo um
histórico curto para cada autorizador. A API lê o cache em memória e retorna
uma resposta pronta para dashboards e interfaces de monitoramento.

> Os dados são obtidos da página pública de disponibilidade da SEFAZ. O
> projeto não substitui os serviços oficiais nem deve ser usado como única
> fonte para decisões fiscais críticas.

## Licença

Consulte o arquivo `LICENSE` deste repositório.
