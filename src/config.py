import os
import logging

import boto3
from dotenv import load_dotenv

load_dotenv()

LOG_FORMAT = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
DEFAULT_MAX_RAW_FILE_MB = 100


def setup_logging(level: int = logging.INFO) -> None:
    """Configura o logging da aplicação (chamar apenas no entrypoint)."""
    logging.basicConfig(level=level, format=LOG_FORMAT)


def get_required_env(name: str) -> str:
    """Lê uma variável de ambiente obrigatória ou lança erro explícito."""
    value = os.getenv(name)
    if not value:
        raise EnvironmentError(f"Variável de ambiente obrigatória ausente: {name}")
    return value


def get_aws_static_credentials() -> dict:
    """Lê chaves AWS estáticas do ambiente, se houver.

    Sem nenhuma das duas, retorna {} e o boto3 usa a cadeia padrão
    (AWS_PROFILE/~/.aws, SSO, role de instância/container). Só uma das duas
    é configuração quebrada e gera erro explícito.
    """
    access_key = os.getenv("AWS_ACCESS_KEY_ID")
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    if not access_key and not secret_key:
        return {}
    if not (access_key and secret_key):
        raise EnvironmentError(
            "Defina AWS_ACCESS_KEY_ID e AWS_SECRET_ACCESS_KEY juntas, ou deixe as duas vazias "
            "para usar a cadeia padrão de credenciais do boto3 (perfil, SSO, role)."
        )
    credentials = {"aws_access_key_id": access_key, "aws_secret_access_key": secret_key}
    session_token = os.getenv("AWS_SESSION_TOKEN")
    if session_token:
        credentials["aws_session_token"] = session_token
    return credentials


def get_s3_client():
    """Cria um cliente boto3 S3 (chaves do .env, se houver; senão a cadeia padrão)."""
    return boto3.client(
        "s3",
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        **get_aws_static_credentials(),
    )


def get_bucket_name() -> str:
    return get_required_env("S3_BUCKET_NAME")


def get_max_raw_file_bytes() -> int:
    """Limite de tamanho de um arquivo bruto lido do S3 (MAX_RAW_FILE_MB, em MiB)."""
    raw_value = os.getenv("MAX_RAW_FILE_MB") or str(DEFAULT_MAX_RAW_FILE_MB)
    try:
        megabytes = int(raw_value)
    except ValueError:
        megabytes = 0
    if megabytes <= 0:
        raise EnvironmentError(f"MAX_RAW_FILE_MB deve ser um inteiro positivo (recebido: {raw_value!r}).")
    return megabytes * 1024 * 1024
