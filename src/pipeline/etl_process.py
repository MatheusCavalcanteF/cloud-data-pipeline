import io
import logging
from collections.abc import Sequence

import pandas as pd
from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import Date, Table
from sqlalchemy.exc import SQLAlchemyError

from src.config import get_bucket_name, get_max_raw_file_bytes, get_s3_client, setup_logging
from src.database.db_connector import DatabaseConnector
from src.database.schemas import TB_VENDAS, primary_key_columns, required_columns

logger = logging.getLogger(__name__)


class RawFileTooLargeError(ValueError):
    """Objeto do S3 maior que o limite configurado em MAX_RAW_FILE_MB."""


def _strip_value(value):
    """Remove espaços das strings; strings vazias viram nulo."""
    if isinstance(value, str):
        value = value.strip()
        return value if value else None
    return value


def _as_list(columns: str | Sequence[str] | None) -> list[str]:
    if columns is None:
        return []
    if isinstance(columns, str):
        return [columns]
    return list(columns)


def clean_data(
    df: pd.DataFrame,
    required_columns: Sequence[str] | None = None,
    primary_key: str | Sequence[str] | None = None,
) -> pd.DataFrame:
    """Limpa um DataFrame bruto sem alterar o original.

    1. Remove espaços nas bordas de strings e converte strings vazias em nulo.
    2. Remove linhas totalmente nulas.
    3. Remove linhas com nulo em `required_columns` + `primary_key`
       (se ambos vazios, em qualquer coluna).
    4. Deduplica: com `primary_key`, mantém a ÚLTIMA ocorrência de cada chave;
       sem ela, remove apenas linhas idênticas.
    5. Converte para tipos nullable do pandas (ex: IDs float -> Int64).
    """
    pk_columns = _as_list(primary_key)
    not_null_columns = list(dict.fromkeys(_as_list(required_columns) + pk_columns))

    missing = set(not_null_columns) - set(df.columns)
    if missing:
        raise KeyError(f"Colunas obrigatórias ausentes no DataFrame: {sorted(missing)}")

    initial_count = len(df)
    df_cleaned = df.copy()

    text_columns = df_cleaned.select_dtypes(include=["object", "string"]).columns
    for column in text_columns:
        df_cleaned[column] = df_cleaned[column].map(_strip_value)

    df_cleaned = df_cleaned.dropna(how="all")
    df_cleaned = df_cleaned.dropna(subset=not_null_columns or None)

    if pk_columns:
        df_cleaned = df_cleaned.drop_duplicates(subset=pk_columns, keep="last")
    else:
        df_cleaned = df_cleaned.drop_duplicates()

    df_cleaned = df_cleaned.reset_index(drop=True)
    # Restaura inteiros que o pandas leu como float por causa dos nulos removidos
    df_cleaned = df_cleaned.convert_dtypes()

    logger.info(
        f"Limpeza concluída: {initial_count - len(df_cleaned)} de {initial_count} linhas removidas."
    )
    return df_cleaned


def _to_db_value(value):
    """Converte escalares pandas/numpy em tipos Python nativos aceitos pelo driver."""
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def prepare_records(df: pd.DataFrame, table: Table) -> list[dict]:
    """Alinha o DataFrame ao schema da tabela e gera registros para o upsert."""
    extra_columns = set(df.columns) - set(table.columns.keys())
    if extra_columns:
        logger.warning(f"Colunas ignoradas (fora do schema de '{table.name}'): {sorted(extra_columns)}")

    columns = [name for name in table.columns.keys() if name in df.columns]
    df_aligned = df[columns].copy()

    for name in columns:
        if isinstance(table.columns[name].type, Date):
            # errors="raise": data inválida falha a carga em vez de virar nulo silenciosamente
            try:
                df_aligned[name] = pd.to_datetime(df_aligned[name], errors="raise").dt.date
            except (ValueError, TypeError):
                # A mensagem do pandas cita o valor da célula; o erro leva só a coluna
                raise ValueError(f"Coluna '{name}' contém data inválida.") from None

    return [
        {name: _to_db_value(value) for name, value in row.items()}
        for row in df_aligned.astype(object).to_dict("records")
    ]


def describe_db_error(error: SQLAlchemyError) -> str:
    """Resume um erro de banco sem a mensagem do driver.

    A mensagem do PostgreSQL pode citar valores das linhas
    (ex: DETAIL: Key (email)=(...) already exists), então o log leva só a
    classe do erro e o SQLSTATE.
    """
    sqlstate = getattr(getattr(error, "orig", None), "pgcode", None)
    name = type(error).__name__
    return f"{name} (SQLSTATE {sqlstate})" if sqlstate else name


def read_raw_content(content: bytes, s3_key: str) -> pd.DataFrame:
    """Converte o conteúdo bruto (CSV ou JSON em lista de registros) em DataFrame."""
    key = s3_key.lower()
    if key.endswith(".csv"):
        return pd.read_csv(io.BytesIO(content))
    if key.endswith(".json"):
        return pd.read_json(io.BytesIO(content), orient="records")
    raise ValueError(f"Formato não suportado: {s3_key}")


class DataETL:
    def __init__(
        self,
        s3_client=None,
        bucket_name: str | None = None,
        db_connector=None,
        max_raw_file_bytes: int | None = None,
    ):
        self.bucket_name = bucket_name or get_bucket_name()
        self.s3_client = s3_client or get_s3_client()
        self.db_connector = db_connector or DatabaseConnector()
        self.max_raw_file_bytes = max_raw_file_bytes or get_max_raw_file_bytes()

    def clean_data(
        self,
        df: pd.DataFrame,
        required_columns: Sequence[str] | None = None,
        primary_key: str | Sequence[str] | None = None,
    ) -> pd.DataFrame:
        return clean_data(df, required_columns, primary_key)

    def extract(self, s3_key: str) -> pd.DataFrame:
        """Baixa o arquivo bruto do S3 e retorna como DataFrame."""
        logger.info(f"Lendo s3://{self.bucket_name}/{s3_key}...")
        response = self.s3_client.get_object(Bucket=self.bucket_name, Key=s3_key)
        body = response["Body"]
        limit = self.max_raw_file_bytes
        try:
            # Recusa antes de baixar quando o S3 já informa o tamanho
            content_length = response.get("ContentLength")
            if content_length is not None and content_length > limit:
                raise RawFileTooLargeError(
                    f"{s3_key} tem {content_length} bytes; limite é {limit} (MAX_RAW_FILE_MB)."
                )
            # Lê no máximo limite + 1 byte: protege mesmo sem ContentLength confiável
            content = body.read(limit + 1)
            if len(content) > limit:
                raise RawFileTooLargeError(f"{s3_key} excede o limite de {limit} bytes (MAX_RAW_FILE_MB).")
        finally:
            body.close()
        return read_raw_content(content, s3_key)

    def load(self, df: pd.DataFrame, table: Table) -> int:
        """Anexa/atualiza os dados na tabela via upsert, respeitando o schema."""
        return self.db_connector.upsert(table, prepare_records(df, table))

    def process_and_load(self, s3_key: str, table: Table) -> bool:
        """Executa extract -> clean -> load. Retorna True em caso de sucesso."""
        try:
            df = self.extract(s3_key)
            df_clean = self.clean_data(
                df,
                required_columns=required_columns(table),
                primary_key=primary_key_columns(table),
            )
            self.load(df_clean, table)
            return True
        except (BotoCoreError, ClientError) as e:
            logger.error(f"Erro de S3 ao processar {s3_key}: {e}")
        except SQLAlchemyError as e:
            logger.error(f"Erro de banco ao carregar {s3_key} em '{table.name}': {describe_db_error(e)}")
        except (ValueError, KeyError) as e:
            logger.error(f"Dados inválidos em {s3_key}: {e}")
        return False


if __name__ == "__main__":
    setup_logging()
    DataETL().process_and_load("raw/2026-01-01/vendas.csv", TB_VENDAS)
