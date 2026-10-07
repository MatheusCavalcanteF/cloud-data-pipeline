# Guia de contribuição: Cloud Data Pipeline

## Visão Geral
Pipeline modular de dados utilizando Python, AWS S3 (Data Lake), PostgreSQL e Docker.
Arquitetura dividida em:
1. Extraction (Upload de arquivos locais brutos para o S3 via boto3)
2. Pipeline/ETL (Download do S3, limpeza/tratamento de nulos com Pandas)
3. Database (Carga dos dados tratados no PostgreSQL via SQLAlchemy/psycopg2)

## Comandos Principais
- Ativar ambiente virtual: `.\venv\Scripts\activate`
- Instalar dependências: `pip install -r requirements.txt`
- Subir container do PostgreSQL: `docker compose up -d`
- Parar container do PostgreSQL: `docker compose down`
- Executar testes unitários: `pytest`
- Executar o pipeline principal: `python main.py`

## Convenções de Código
- Padrão PEP 8 para nomes de variáveis e funções (snake_case).
- Uso estrito de variáveis de ambiente via `python-dotenv` (nunca expor chaves da AWS no código).
- Tratamento explícito de exceções e logs simples de execução.
- Funções modularizadas com responsabilidade única.