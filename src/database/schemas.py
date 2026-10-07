"""Schemas explícitos das tabelas de destino.

IDs vêm da fonte (chave natural): autoincrement=False evita que o PostgreSQL
crie SERIAL/sequence nas PKs.

Fonte única de verdade para tipos, chave primária (usada na deduplicação e no
upsert) e colunas obrigatórias (nullable=False, usadas na limpeza).
"""
from sqlalchemy import BigInteger, Column, Date, Integer, MetaData, Numeric, Table, Text

metadata = MetaData()

TB_VENDAS = Table(
    "tb_vendas",
    metadata,
    Column("id_venda", BigInteger, primary_key=True, autoincrement=False),
    Column("id_cliente", BigInteger, nullable=False),
    Column("produto", Text),
    Column("quantidade", Integer),
    Column("valor", Numeric(12, 2), nullable=False),
    Column("data_venda", Date),
)

TB_CLIENTES = Table(
    "tb_clientes",
    metadata,
    Column("id_cliente", BigInteger, primary_key=True, autoincrement=False),
    Column("nome", Text, nullable=False),
    Column("email", Text),
    Column("cidade", Text),
)


def primary_key_columns(table: Table) -> list[str]:
    return [column.name for column in table.primary_key.columns]


def required_columns(table: Table) -> list[str]:
    return [column.name for column in table.columns if not column.nullable]
