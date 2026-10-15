import os
import logging
from datetime import date, datetime, timezone

from botocore.exceptions import BotoCoreError, ClientError

from src.config import get_bucket_name, get_s3_client, setup_logging

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = (".csv", ".json")
RAW_PREFIX = "raw"
# SSE-S3: o objeto fica criptografado em repouso mesmo se a criptografia padrão do bucket mudar
UPLOAD_EXTRA_ARGS = {"ServerSideEncryption": "AES256"}


def current_partition_date() -> date:
    """Data da partição em UTC, para não depender do fuso da máquina."""
    return datetime.now(timezone.utc).date()


def build_partition_key(filename: str, run_date: date) -> str:
    """Monta a chave S3 particionada: raw/YYYY-MM-DD/nome_do_arquivo."""
    return f"{RAW_PREFIX}/{run_date.isoformat()}/{os.path.basename(filename)}"


class S3DataUploader:
    def __init__(self, s3_client=None, bucket_name: str | None = None):
        self.bucket_name = bucket_name or get_bucket_name()
        self.s3_client = s3_client or get_s3_client()

    def upload_file(self, local_path: str, s3_key: str) -> bool:
        """Envia um arquivo local para o bucket S3."""
        try:
            self.s3_client.upload_file(local_path, self.bucket_name, s3_key, ExtraArgs=UPLOAD_EXTRA_ARGS)
            logger.info(f"Upload concluído: {local_path} -> s3://{self.bucket_name}/{s3_key}")
            return True
        except (BotoCoreError, ClientError, OSError) as e:
            logger.error(f"Erro ao enviar {local_path} para o S3: {e}")
            return False

    def upload_raw_folder(self, raw_folder_path: str = "data/raw", run_date: date | None = None) -> list[str]:
        """Envia os CSV/JSON da pasta local para raw/YYYY-MM-DD/ no S3.

        Retorna a lista de chaves S3 enviadas com sucesso.
        """
        if not os.path.isdir(raw_folder_path):
            logger.warning(f"Diretório {raw_folder_path} não encontrado.")
            return []

        run_date = run_date or current_partition_date()
        uploaded_keys = []
        for filename in sorted(os.listdir(raw_folder_path)):
            if not filename.lower().endswith(SUPPORTED_EXTENSIONS):
                continue

            local_file_path = os.path.join(raw_folder_path, filename)
            s3_key = build_partition_key(filename, run_date)
            logger.info(f"Iniciando upload de: {filename}")
            if self.upload_file(local_file_path, s3_key):
                uploaded_keys.append(s3_key)

        return uploaded_keys


if __name__ == "__main__":
    setup_logging()
    S3DataUploader().upload_raw_folder()
