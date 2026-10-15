import logging
import os
from collections.abc import Sequence

from sqlalchemy import Table, create_engine, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import URL, Engine

from src.config import get_required_env, setup_logging

logger = logging.getLogger(__name__)

UPSERT_DIALECTS = {
    "postgresql": postgresql_insert,
    "sqlite": sqlite_insert,  # usado nos testes
}

DEFAULT_SSLMODE = "prefer"
VALID_SSLMODES = ("disable", "allow", "prefer", "require", "verify-ca", "verify-full")


def get_sslmode() -> str:
    """Lê DB_SSLMODE (libpq). 'prefer' serve o Docker local; banco remoto pede 'verify-full'."""
    sslmode = os.getenv("DB_SSLMODE") or DEFAULT_SSLMODE
    if sslmode not in VALID_SSLMODES:
        raise EnvironmentError(f"DB_SSLMODE inválido: {sslmode!r}. Use um de: {', '.join(VALID_SSLMODES)}.")
    return sslmode


def build_db_url() -> URL:
    """Monta a URL do PostgreSQL a partir do .env."""
    # URL.create escapa caracteres especiais da senha (ex: '@', ':', '/')
    return URL.create(
        drivername="postgresql+psycopg2",
        username=get_required_env("DB_USER"),
        password=get_required_env("DB_PASSWORD"),
        host=get_required_env("DB_HOST"),
        port=int(get_required_env("DB_PORT")),
        database=get_required_env("DB_NAME"),
        query={"sslmode": get_sslmode()},
    )


class DatabaseConnector:
    def __init__(self, engine: Engine | None = None):
        self.engine = engine or self._get_engine()

    def _get_engine(self) -> Engine:
        """Cria a engine do SQLAlchemy para o PostgreSQL a partir do .env."""
        db_url = build_db_url()
        try:
            # hide_parameters: erros do SQLAlchemy não incluem os valores das linhas (nomes, e-mails)
            engine = create_engine(db_url, pool_pre_ping=True, hide_parameters=True)
            logger.info("Engine SQLAlchemy criada com sucesso.")
            return engine
        except Exception as e:
            logger.error(f"Erro ao criar engine do banco de dados: {e}")
            raise

    def test_connection(self) -> bool:
        """Testa se a conexão com o PostgreSQL está ativa."""
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            logger.info("Conexão com o PostgreSQL estabelecida com sucesso!")
            return True
        except Exception as e:
            logger.error(f"Falha ao conectar no PostgreSQL: {e}")
            return False

    def upsert(self, table: Table, records: Sequence[dict], chunk_size: int = 1000) -> int:
        """Cria a tabela se necessário e faz INSERT ... ON CONFLICT (pk) DO UPDATE.

        Registros novos são anexados; registros com PK existente são atualizados.
        Tudo roda em uma única transação. Retorna o número de registros enviados.
        """
        if not records:
            logger.info(f"Nenhum registro para carregar em '{table.name}'.")
            return 0

        insert_fn = UPSERT_DIALECTS.get(self.engine.dialect.name)
        if insert_fn is None:
            raise NotImplementedError(f"Upsert não suportado para o dialeto {self.engine.dialect.name}")

        pk_columns = [column.name for column in table.primary_key.columns]
        if not pk_columns:
            raise ValueError(f"Tabela '{table.name}' precisa de chave primária para upsert.")

        stmt = insert_fn(table)
        update_columns = {
            column: stmt.excluded[column] for column in records[0] if column not in pk_columns
        }
        if update_columns:
            stmt = stmt.on_conflict_do_update(index_elements=pk_columns, set_=update_columns)
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=pk_columns)

        table.create(self.engine, checkfirst=True)
        with self.engine.begin() as connection:
            for start in range(0, len(records), chunk_size):
                connection.execute(stmt, list(records[start:start + chunk_size]))

        logger.info(f"{len(records)} registros upsert em '{table.name}'.")
        return len(records)


if __name__ == "__main__":
    setup_logging()
    DatabaseConnector().test_connection()
