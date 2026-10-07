import logging
import os
import sys

from src.config import setup_logging
from src.database.db_connector import DatabaseConnector
from src.database.schemas import TB_CLIENTES, TB_VENDAS
from src.extraction.s3_uploader import S3DataUploader
from src.pipeline.etl_process import DataETL

logger = logging.getLogger("pipeline")

RAW_FOLDER = "data/raw"

# nome do arquivo bruto -> tabela de destino (schema define PK e colunas obrigatórias)
PIPELINE_SOURCES = {
    "vendas.csv": TB_VENDAS,
    "clientes.json": TB_CLIENTES,
}


def run_pipeline() -> bool:
    logger.info("=== INICIANDO CLOUD DATA PIPELINE ===")

    db_connector = DatabaseConnector()
    if not db_connector.test_connection():
        logger.error("PostgreSQL indisponível. Rode 'docker compose up -d' e verifique o .env.")
        return False

    logger.info("Etapa 1: Ingestão de arquivos locais para o S3...")
    uploaded_keys = S3DataUploader().upload_raw_folder(RAW_FOLDER)
    if not uploaded_keys:
        logger.error(f"Nenhum arquivo enviado ao S3 a partir de '{RAW_FOLDER}'.")
        return False

    # Usa as chaves exatas retornadas pelo upload (já particionadas por data)
    keys_by_filename = {os.path.basename(key): key for key in uploaded_keys}

    logger.info("Etapa 2: ETL e carga no banco de dados...")
    etl = DataETL(db_connector=db_connector)
    failures = []
    for filename, table in PIPELINE_SOURCES.items():
        s3_key = keys_by_filename.get(filename)
        if s3_key is None:
            logger.warning(f"{filename} não foi enviado ao S3; pulando.")
            failures.append(filename)
            continue
        if not etl.process_and_load(s3_key, table):
            failures.append(filename)

    if failures:
        logger.error(f"=== PIPELINE FINALIZADO COM FALHAS: {failures} ===")
        return False

    logger.info("=== PIPELINE FINALIZADO COM SUCESSO ===")
    return True


if __name__ == "__main__":
    setup_logging()
    try:
        success = run_pipeline()
    except EnvironmentError as e:
        logger.error(e)
        success = False
    sys.exit(0 if success else 1)
