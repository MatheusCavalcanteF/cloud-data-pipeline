import io
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy import BigInteger, Date, Integer, Numeric, create_engine, inspect, select

from src.database.db_connector import DatabaseConnector
from src.database.schemas import TB_CLIENTES, TB_VENDAS
from src.extraction.s3_uploader import S3DataUploader, build_partition_key
from src.pipeline.etl_process import DataETL, clean_data, prepare_records, read_raw_content


class FakeS3Client:
    """Simula o boto3: registra uploads e serve objetos em memória."""

    def __init__(self, objects: dict[str, bytes] | None = None):
        self.objects = objects or {}
        self.uploaded: list[tuple[str, str, str]] = []
        self.upload_extra_args: list[dict | None] = []

    def upload_file(self, local_path, bucket, key, ExtraArgs=None):
        self.uploaded.append((local_path, bucket, key))
        self.upload_extra_args.append(ExtraArgs)

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[Key])}


@pytest.fixture
def sqlite_connector() -> DatabaseConnector:
    return DatabaseConnector(engine=create_engine("sqlite://"))


def _fetch_all(connector: DatabaseConnector, table) -> list[dict]:
    pk = list(table.primary_key.columns)[0]
    with connector.engine.connect() as connection:
        rows = connection.execute(select(table).order_by(pk)).mappings().all()
    return [dict(row) for row in rows]


@pytest.fixture
def raw_vendas() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id_venda": [1, 2, 2, 3, 4, None],
            "id_cliente": [10, 20, 20, None, 40, None],
            "produto": ["Mouse", "Teclado", "Teclado", "Monitor", None, None],
            "valor": [100.0, 200.0, 200.0, 300.0, 400.0, None],
        }
    )


def test_clean_data_remove_nulos_e_duplicados_por_padrao(raw_vendas):
    result = clean_data(raw_vendas)

    assert result["id_venda"].tolist() == [1, 2]
    assert not result.isna().any().any()
    assert not result.duplicated().any()


def test_clean_data_com_required_columns_preserva_nulos_nao_criticos(raw_vendas):
    result = clean_data(raw_vendas, required_columns=["id_venda", "id_cliente"])

    # id 3 sai (id_cliente nulo); id 4 fica mesmo sem produto
    assert result["id_venda"].tolist() == [1, 2, 4]
    assert pd.isna(result.loc[result["id_venda"] == 4, "produto"].iloc[0])


def test_clean_data_remove_linhas_totalmente_nulas():
    df = pd.DataFrame({"a": [1, None], "b": ["x", None]})

    result = clean_data(df, required_columns=["a"])

    assert len(result) == 1


def test_clean_data_strip_e_string_vazia_vira_nulo():
    df = pd.DataFrame(
        {
            "id": [1, 2, 3],
            "nome": ["  Ana  ", "Ana", "   "],
        }
    )

    result = clean_data(df, required_columns=["id", "nome"])

    # "  Ana  " e "Ana" não são duplicatas (ids diferentes), mas ambos são normalizados
    assert result["nome"].tolist() == ["Ana", "Ana"]
    # "   " virou nulo e a linha foi descartada por ser coluna obrigatória
    assert 3 not in result["id"].tolist()


def test_clean_data_deduplica_apos_normalizar_espacos():
    df = pd.DataFrame({"id": [1, 1], "nome": ["Ana", " Ana "]})

    assert len(clean_data(df)) == 1


def test_clean_data_restaura_inteiros_lidos_como_float(raw_vendas):
    result = clean_data(raw_vendas, required_columns=["id_venda"])

    assert pd.api.types.is_integer_dtype(result["id_venda"])


def test_clean_data_nao_altera_dataframe_original(raw_vendas):
    snapshot = raw_vendas.copy()

    clean_data(raw_vendas)

    pd.testing.assert_frame_equal(raw_vendas, snapshot)


def test_clean_data_reseta_indice(raw_vendas):
    result = clean_data(raw_vendas)

    assert result.index.tolist() == list(range(len(result)))


def test_clean_data_dataframe_vazio():
    df = pd.DataFrame({"id": pd.Series([], dtype="Int64")})

    result = clean_data(df)

    assert result.empty


def test_clean_data_coluna_obrigatoria_inexistente_lanca_erro(raw_vendas):
    with pytest.raises(KeyError, match="coluna_fantasma"):
        clean_data(raw_vendas, required_columns=["coluna_fantasma"])


def test_read_raw_content_csv_e_json():
    csv_df = read_raw_content(b"id,nome\n1,Ana\n", "raw/x.csv")
    json_df = read_raw_content(b'[{"id": 1, "nome": "Ana"}]', "raw/x.json")

    assert csv_df.to_dict("records") == json_df.to_dict("records") == [{"id": 1, "nome": "Ana"}]


def test_read_raw_content_formato_nao_suportado():
    with pytest.raises(ValueError):
        read_raw_content(b"", "raw/x.parquet")


# --- Particionamento por data no S3 ---


def test_build_partition_key_formato_yyyy_mm_dd():
    assert build_partition_key("vendas.csv", date(2026, 3, 7)) == "raw/2026-03-07/vendas.csv"


def test_build_partition_key_usa_apenas_nome_do_arquivo():
    assert build_partition_key("data/raw/clientes.json", date(2026, 10, 3)) == "raw/2026-10-03/clientes.json"


def test_upload_raw_folder_envia_para_particao_da_data(tmp_path):
    (tmp_path / "vendas.csv").write_text("id_venda\n1\n")
    (tmp_path / "clientes.json").write_text("[]")
    (tmp_path / "notas.txt").write_text("ignorar")
    s3 = FakeS3Client()

    keys = S3DataUploader(s3_client=s3, bucket_name="bucket").upload_raw_folder(
        str(tmp_path), run_date=date(2026, 10, 3)
    )

    assert keys == ["raw/2026-10-03/clientes.json", "raw/2026-10-03/vendas.csv"]
    assert [key for _, _, key in s3.uploaded] == keys


def test_upload_raw_folder_sem_data_usa_data_utc_atual(tmp_path, monkeypatch):
    (tmp_path / "vendas.csv").write_text("id_venda\n1\n")
    monkeypatch.setattr(
        "src.extraction.s3_uploader.current_partition_date", lambda: date(2030, 1, 31)
    )

    keys = S3DataUploader(s3_client=FakeS3Client(), bucket_name="bucket").upload_raw_folder(str(tmp_path))

    assert keys == ["raw/2030-01-31/vendas.csv"]


def test_upload_pede_criptografia_sse_s3(tmp_path):
    (tmp_path / "vendas.csv").write_text("id_venda\n1\n")
    s3 = FakeS3Client()

    S3DataUploader(s3_client=s3, bucket_name="bucket").upload_raw_folder(str(tmp_path))

    assert s3.upload_extra_args == [{"ServerSideEncryption": "AES256"}]


# --- Deduplicação por chave primária ---


def test_clean_data_dedup_por_pk_mantem_ultima_ocorrencia():
    df = pd.DataFrame(
        {
            "id_venda": [1, 2, 1, 3, 1],
            "valor": [10.0, 20.0, 11.0, 30.0, 12.0],
        }
    )

    result = clean_data(df, primary_key="id_venda")

    assert sorted(result["id_venda"].tolist()) == [1, 2, 3]
    assert result.loc[result["id_venda"] == 1, "valor"].item() == 12.0


def test_clean_data_dedup_por_pk_composta():
    df = pd.DataFrame(
        {
            "id_pedido": [1, 1, 1],
            "item": [1, 2, 1],
            "qtd": [5, 1, 9],
        }
    )

    result = clean_data(df, primary_key=["id_pedido", "item"])

    assert len(result) == 2
    assert result.loc[result["item"] == 1, "qtd"].item() == 9


def test_clean_data_pk_nula_e_descartada_mesmo_sem_required_columns():
    df = pd.DataFrame({"id_cliente": [1, None], "nome": ["Ana", "Sem ID"]})

    result = clean_data(df, primary_key="id_cliente")

    assert result["nome"].tolist() == ["Ana"]


def test_clean_data_dedup_por_pk_considera_strip_antes_de_comparar_ultima():
    df = pd.DataFrame({"id_cliente": [5, 5], "nome": ["Diego", "  Diego Alves  "]})

    result = clean_data(df, primary_key="id_cliente")

    assert result["nome"].tolist() == ["Diego Alves"]


def test_clean_data_pk_inexistente_lanca_erro():
    with pytest.raises(KeyError, match="id_fantasma"):
        clean_data(pd.DataFrame({"id": [1]}), primary_key="id_fantasma")


# --- Carga com append/upsert preservando tipos ---


def _vendas_df(rows: list[dict]) -> pd.DataFrame:
    return clean_data(pd.DataFrame(rows), primary_key="id_venda", required_columns=["id_cliente", "valor"])


def test_prepare_records_converte_tipos_e_ignora_colunas_extras():
    df = _vendas_df(
        [{"id_venda": 1, "id_cliente": 10, "produto": None, "quantidade": 2,
          "valor": 9.5, "data_venda": "2026-09-01", "coluna_extra": "x"}]
    )

    [record] = prepare_records(df, TB_VENDAS)

    assert "coluna_extra" not in record
    assert record["data_venda"] == date(2026, 9, 1)
    assert type(record["id_venda"]) is int
    assert record["produto"] is None


def test_prepare_records_data_invalida_lanca_erro():
    df = _vendas_df([{"id_venda": 1, "id_cliente": 10, "valor": 1.0, "data_venda": "nao-e-data"}])

    with pytest.raises(ValueError):
        prepare_records(df, TB_VENDAS)


def test_load_cria_tabela_com_tipos_do_schema(sqlite_connector):
    etl = DataETL(s3_client=FakeS3Client(), bucket_name="b", db_connector=sqlite_connector)

    etl.load(_vendas_df([{"id_venda": 1, "id_cliente": 10, "produto": "Mouse", "quantidade": 1,
                          "valor": 10.0, "data_venda": "2026-09-01"}]), TB_VENDAS)

    columns = {c["name"]: c for c in inspect(sqlite_connector.engine).get_columns("tb_vendas")}
    assert isinstance(columns["id_venda"]["type"], BigInteger)
    assert isinstance(columns["quantidade"]["type"], Integer)
    assert isinstance(columns["valor"]["type"], Numeric)
    assert isinstance(columns["data_venda"]["type"], Date)
    assert inspect(sqlite_connector.engine).get_pk_constraint("tb_vendas")["constrained_columns"] == ["id_venda"]


def test_load_append_adiciona_novos_e_atualiza_ids_existentes(sqlite_connector):
    etl = DataETL(s3_client=FakeS3Client(), bucket_name="b", db_connector=sqlite_connector)
    etl.load(_vendas_df([
        {"id_venda": 1, "id_cliente": 10, "valor": 100.0, "data_venda": "2026-09-01"},
        {"id_venda": 2, "id_cliente": 20, "valor": 200.0, "data_venda": "2026-09-02"},
    ]), TB_VENDAS)

    etl.load(_vendas_df([
        {"id_venda": 2, "id_cliente": 20, "valor": 250.0, "data_venda": "2026-09-03"},
        {"id_venda": 3, "id_cliente": 30, "valor": 300.0, "data_venda": "2026-09-03"},
    ]), TB_VENDAS)

    rows = _fetch_all(sqlite_connector, TB_VENDAS)
    assert [row["id_venda"] for row in rows] == [1, 2, 3]
    assert rows[1]["valor"] == Decimal("250.00")
    assert rows[1]["data_venda"] == date(2026, 9, 3)


def test_load_e_idempotente_ao_reprocessar_mesmo_arquivo(sqlite_connector):
    etl = DataETL(s3_client=FakeS3Client(), bucket_name="b", db_connector=sqlite_connector)
    df = _vendas_df([{"id_venda": 1, "id_cliente": 10, "valor": 100.0, "data_venda": "2026-09-01"}])

    etl.load(df, TB_VENDAS)
    etl.load(df, TB_VENDAS)

    assert len(_fetch_all(sqlite_connector, TB_VENDAS)) == 1


def test_process_and_load_fim_a_fim_com_particao(sqlite_connector):
    s3_key = build_partition_key("clientes.json", date(2026, 10, 3))
    raw_json = (
        b'[{"id_cliente": 101, "nome": "Ana", "email": null, "cidade": "Sao Paulo"},'
        b' {"id_cliente": 102, "nome": null, "email": null, "cidade": "Recife"},'
        b' {"id_cliente": 101, "nome": "Ana", "email": null, "cidade": "Campinas"}]'
    )
    etl = DataETL(s3_client=FakeS3Client({s3_key: raw_json}), bucket_name="b", db_connector=sqlite_connector)

    assert etl.process_and_load(s3_key, TB_CLIENTES) is True

    rows = _fetch_all(sqlite_connector, TB_CLIENTES)
    assert rows == [{"id_cliente": 101, "nome": "Ana", "email": None, "cidade": "Campinas"}]


def test_process_and_load_retorna_false_para_arquivo_sem_coluna_obrigatoria(sqlite_connector):
    s3_key = "raw/2026-10-03/clientes.json"
    etl = DataETL(
        s3_client=FakeS3Client({s3_key: b'[{"id_cliente": 1}]'}), bucket_name="b", db_connector=sqlite_connector
    )

    assert etl.process_and_load(s3_key, TB_CLIENTES) is False


@pytest.mark.parametrize("table", [TB_VENDAS, TB_CLIENTES])
def test_schema_pk_natural_sem_autoincrement(table):
    # IDs vêm da fonte; SERIAL/sequence no Postgres colidiria com eles
    assert all(column.autoincrement is False for column in table.primary_key.columns)
