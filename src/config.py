import os
import logging

import boto3
from dotenv import load_dotenv

load_dotenv()

LOG_FORMAT = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    """Configura o logging da aplicação (chamar apenas no entrypoint)."""
    logging.basicConfig(level=level, format=LOG_FORMAT)


def get_required_env(name: str) -> str:
    """Lê uma variável de ambiente obrigatória ou lança erro explícito."""
    value = os.getenv(name)
    if not value:
        raise EnvironmentError(f"Variável de ambiente obrigatória ausente: {name}")
    return value


def get_s3_client():
    """Cria um cliente boto3 S3 a partir das variáveis de ambiente."""
    return boto3.client(
        "s3",
        aws_access_key_id=get_required_env("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=get_required_env("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_REGION", "us-east-1"),
    )


def get_bucket_name() -> str:
    return get_required_env("S3_BUCKET_NAME")
