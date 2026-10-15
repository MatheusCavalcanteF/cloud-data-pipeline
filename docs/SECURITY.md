# Segurança

## Reportar uma vulnerabilidade

Não abra issue pública para falhas de segurança. Use o **reporte privado de vulnerabilidades** do GitHub: aba **Security** → **Report a vulnerability** ([link direto](https://github.com/MatheusCavalcanteF/cloud-data-pipeline/security/advisories/new)).

Inclua, se possível:

- o que é afetado (arquivo, função, configuração);
- passos para reproduzir;
- impacto esperado.

É um projeto pessoal: a resposta vem assim que possível, sem prazo garantido. Correções são publicadas no `main` e o advisory é divulgado depois da correção, com crédito a quem reportou (se desejar).

## Permissões AWS (menor privilégio)

O pipeline só lê e grava objetos sob `raw/` em um único bucket. A identidade usada (usuário IAM, role ou perfil SSO) não precisa de mais nada:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "LerEGravarObjetosRaw",
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject"],
      "Resource": "arn:aws:s3:::<bucket>/raw/*"
    },
    {
      "Sid": "ListarSomentePrefixoRaw",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::<bucket>",
      "Condition": {
        "StringLike": { "s3:prefix": ["raw/*"] }
      }
    }
  ]
}
```

Troque `<bucket>` pelo nome do bucket. Observações:

- `s3:ListBucket` não é usado pelo código hoje, mas sem ele um `GetObject` de chave inexistente retorna `403` em vez de `404`, o que confunde o diagnóstico.
- Não há `s3:DeleteObject` nem permissões de bucket (`s3:CreateBucket`, `s3:PutBucketPolicy`): o pipeline não apaga dados nem altera a configuração do bucket.
- Prefira credenciais temporárias (SSO, role) a chaves estáticas de usuário IAM. Se usar chaves, rotacione-as e nunca as coloque fora do `.env`.

## Configuração do bucket

Recomendações para o bucket do data lake, aplicadas uma vez por quem administra a conta:

**Block Public Access** ligado nas quatro opções:

```bash
aws s3api put-public-access-block --bucket <bucket> \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
```

**Versionamento** ligado, para recuperar versões sobrescritas quando o pipeline roda mais de uma vez no mesmo dia (a chave `raw/AAAA-MM-DD/arquivo` é a mesma):

```bash
aws s3api put-bucket-versioning --bucket <bucket> \
  --versioning-configuration Status=Enabled
```

Com versionamento, vale uma regra de lifecycle que expire versões antigas (`NoncurrentVersionExpiration`) para o custo não crescer sem limite.

**Criptografia em repouso:** todo upload do pipeline pede SSE-S3 (`ServerSideEncryption: AES256`), e buckets novos já usam SSE-S3 por padrão.

**Somente TLS (opcional):** uma bucket policy que negue requisições sem HTTPS:

```json
{
  "Sid": "NegarSemTLS",
  "Effect": "Deny",
  "Principal": "*",
  "Action": "s3:*",
  "Resource": ["arn:aws:s3:::<bucket>", "arn:aws:s3:::<bucket>/*"],
  "Condition": { "Bool": { "aws:SecureTransport": "false" } }
}
```

## Banco de dados

- No ambiente local, o `docker compose` publica o PostgreSQL só em `127.0.0.1`.
- Em banco remoto, use `DB_SSLMODE=verify-full` (valida certificado e hostname) e um usuário com permissão apenas no schema das tabelas de destino.
- Os erros de banco são registrados sem os valores das linhas: `hide_parameters=True` na engine e log com classe do erro + SQLSTATE.

## Dependências

- `requirements.txt` fixa versões exatas; `pip-audit -r requirements.txt` roda no CI.
- O Dependabot abre PRs semanais para pip, a imagem do PostgreSQL e as GitHub Actions.
