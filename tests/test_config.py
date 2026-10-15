import pytest

import src.config as config

AWS_ENV_VARS = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_REGION")


@pytest.fixture(autouse=True)
def clean_aws_env(monkeypatch):
    # O import de src.config carrega o .env local; os testes não dependem dele
    for name in AWS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def captured_boto3_client(monkeypatch) -> dict:
    captured = {}

    def fake_client(service_name, **kwargs):
        captured.update(service_name=service_name, **kwargs)
        return object()

    monkeypatch.setattr(config.boto3, "client", fake_client)
    return captured


def test_sem_chaves_usa_cadeia_padrao_do_boto3(captured_boto3_client):
    config.get_s3_client()

    assert "aws_access_key_id" not in captured_boto3_client
    assert "aws_secret_access_key" not in captured_boto3_client
    assert captured_boto3_client["service_name"] == "s3"


def test_chaves_vazias_equivalem_a_ausentes(monkeypatch, captured_boto3_client):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "")

    config.get_s3_client()

    assert "aws_access_key_id" not in captured_boto3_client


def test_com_as_duas_chaves_usa_credenciais_estaticas(monkeypatch, captured_boto3_client):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAFAKE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "fake-secret")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "fake-token")

    config.get_s3_client()

    assert captured_boto3_client["aws_access_key_id"] == "AKIAFAKE"
    assert captured_boto3_client["aws_secret_access_key"] == "fake-secret"
    assert captured_boto3_client["aws_session_token"] == "fake-token"


@pytest.mark.parametrize("present", ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"])
def test_apenas_uma_chave_gera_erro_claro(monkeypatch, present):
    monkeypatch.setenv(present, "valor")

    with pytest.raises(EnvironmentError, match="juntas"):
        config.get_aws_static_credentials()


def test_limite_de_arquivo_padrao_e_100_mb(monkeypatch):
    monkeypatch.delenv("MAX_RAW_FILE_MB", raising=False)

    assert config.get_max_raw_file_bytes() == 100 * 1024 * 1024


def test_limite_de_arquivo_configuravel(monkeypatch):
    monkeypatch.setenv("MAX_RAW_FILE_MB", "5")

    assert config.get_max_raw_file_bytes() == 5 * 1024 * 1024


@pytest.mark.parametrize("value", ["0", "-1", "abc", "1.5"])
def test_limite_de_arquivo_invalido_gera_erro(monkeypatch, value):
    monkeypatch.setenv("MAX_RAW_FILE_MB", value)

    with pytest.raises(EnvironmentError, match="MAX_RAW_FILE_MB"):
        config.get_max_raw_file_bytes()
