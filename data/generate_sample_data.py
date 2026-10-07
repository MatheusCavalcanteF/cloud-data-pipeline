"""Gera dados fictícios em data/raw/ com nulos e duplicados para testar a limpeza.

Uso: python data/generate_sample_data.py
"""
import json
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

RAW_DIR = Path(__file__).resolve().parent / "raw"


def build_vendas() -> pd.DataFrame:
    rows = [
        {"id_venda": 1, "id_cliente": 101, "produto": "Notebook", "quantidade": 1, "valor": 4500.00, "data_venda": "2026-09-01"},
        {"id_venda": 2, "id_cliente": 102, "produto": "Mouse", "quantidade": 2, "valor": 150.00, "data_venda": "2026-09-02"},
        {"id_venda": 3, "id_cliente": 103, "produto": "Teclado", "quantidade": 1, "valor": 320.50, "data_venda": "2026-09-03"},
        {"id_venda": 4, "id_cliente": 101, "produto": "Monitor", "quantidade": 2, "valor": 1899.90, "data_venda": "2026-09-04"},
        {"id_venda": 5, "id_cliente": 104, "produto": "Headset", "quantidade": 1, "valor": None, "data_venda": "2026-09-05"},  # valor nulo
        {"id_venda": 6, "id_cliente": None, "produto": "Webcam", "quantidade": 1, "valor": 280.00, "data_venda": "2026-09-06"},  # cliente nulo
        {"id_venda": 7, "id_cliente": 105, "produto": None, "quantidade": 3, "valor": 90.00, "data_venda": "2026-09-07"},  # nulo não crítico
        {"id_venda": 2, "id_cliente": 102, "produto": "Mouse", "quantidade": 2, "valor": 150.00, "data_venda": "2026-09-02"},  # duplicado
        {"id_venda": 4, "id_cliente": 101, "produto": "Monitor", "quantidade": 2, "valor": 1899.90, "data_venda": "2026-09-04"},  # duplicado
        {"id_venda": 3, "id_cliente": 103, "produto": "Teclado", "quantidade": 1, "valor": 299.90, "data_venda": "2026-09-08"},  # mesmo ID, valor corrigido (deve prevalecer)
        {"id_venda": None, "id_cliente": None, "produto": None, "quantidade": None, "valor": None, "data_venda": None},  # totalmente nulo
    ]
    # Int64 (nullable) evita que IDs com nulos sejam gravados como float (ex: 101.0)
    return pd.DataFrame(rows).astype({"id_venda": "Int64", "id_cliente": "Int64", "quantidade": "Int64"})


def build_clientes() -> list[dict]:
    return [
        {"id_cliente": 101, "nome": "Ana Souza", "email": "ana.souza@example.com", "cidade": "São Paulo"},
        {"id_cliente": 102, "nome": "Bruno Lima", "email": "bruno.lima@example.com", "cidade": "Recife"},
        {"id_cliente": 103, "nome": "Carla Mendes", "email": None, "cidade": "Curitiba"},  # nulo não crítico
        {"id_cliente": 104, "nome": None, "email": "sem.nome@example.com", "cidade": "Belo Horizonte"},  # nome nulo
        {"id_cliente": 105, "nome": "  Diego Alves  ", "email": "diego.alves@example.com", "cidade": "Porto Alegre"},  # espaços
        {"id_cliente": 102, "nome": "Bruno Lima", "email": "bruno.lima@example.com", "cidade": "Recife"},  # duplicado
        {"id_cliente": 105, "nome": "Diego Alves", "email": "diego.alves@example.com", "cidade": "Porto Alegre"},  # duplicado após strip
        {"id_cliente": 101, "nome": "Ana Souza", "email": "ana.souza@example.com", "cidade": "Campinas"},  # mesmo ID, cidade atualizada (deve prevalecer)
        {"id_cliente": None, "nome": "", "email": None, "cidade": None},  # vazio
    ]


def generate(raw_dir: Path = RAW_DIR) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)

    vendas_path = raw_dir / "vendas.csv"
    build_vendas().to_csv(vendas_path, index=False)
    logger.info(f"Arquivo gerado: {vendas_path}")

    clientes_path = raw_dir / "clientes.json"
    with clientes_path.open("w", encoding="utf-8") as f:
        json.dump(build_clientes(), f, ensure_ascii=False, indent=2)
    logger.info(f"Arquivo gerado: {clientes_path}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    generate()
