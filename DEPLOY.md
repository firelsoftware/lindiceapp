# Publicacao do Lindice

## Caminho recomendado

Este projeto esta preparado para subir no Render usando:

- Django em modo producao
- PostgreSQL externo por `DATABASE_URL`
- WhiteNoise para arquivos estaticos
- Gunicorn como servidor WSGI
- HTTPS automatico do Render

## Passos

1. Crie um repositorio no GitHub para este projeto.
2. Suba os arquivos do projeto, sem `venv/`, `db.sqlite3` e `staticfiles/`.
3. Crie um banco PostgreSQL no Supabase.
4. No Supabase, copie a connection string do banco. Para o Render, use `Session pooler` em formato URI.
5. No Render, configure `DATABASE_URL` com a connection string do Supabase e `?sslmode=require` no final.
6. No Render, crie um Blueprint a partir do repositorio.
7. O Render vai ler `render.yaml` e criar o web service.
8. Depois do primeiro deploy, acesse a URL `.onrender.com`.
9. Crie o superusuario em um Shell do Render ou configure as variaveis `DJANGO_SUPERUSER_*`:

```bash
python manage.py createsuperuser
```

10. Adicione seu dominio personalizado no painel do Render.
11. No painel onde comprou o dominio, aponte o DNS para os registros informados pelo Render.
12. Atualize as variaveis:

```text
DJANGO_ALLOWED_HOSTS=.onrender.com,seu-dominio.com.br,www.seu-dominio.com.br
DJANGO_CSRF_TRUSTED_ORIGINS=https://seu-dominio.com.br,https://www.seu-dominio.com.br
PUBLIC_SITE_URL=https://seu-dominio.com.br
STORE_CONTACT_EMAIL=contato@seu-dominio.com.br
STORE_RESPONSIBLE_NAME=Nome completo do responsavel
STORE_PIX_KEY=chave-pix-da-loja
MERCADO_PAGO_ACCESS_TOKEN=...
CARD_PAYMENT_ENABLED=true
SHOE_SUPPLIER_CATALOG_URL=...
PHONE_VERIFICATION_REQUIRED=false
```

Use `PHONE_VERIFICATION_REQUIRED=false` apenas enquanto nao houver envio real de codigo por SMS ou WhatsApp. Nesse modo, o cadastro segue direto para analise manual do administrador.

## Observacoes importantes

O dominio sozinho nao hospeda o app. Ele apenas aponta para um servidor.

O banco local `db.sqlite3` nao deve ser enviado como banco de producao. O ideal e usar PostgreSQL online e, se necessario, migrar dados com fixtures.

Ao trocar o banco de producao para Supabase, confirme que o deploy rodou as migracoes antes de remover qualquer banco antigo.

Arquivos enviados por clientes, como comprovantes e fotos de produtos, devem ficar no Supabase Storage. Crie um bucket privado, por exemplo `lindice-media`, gere credenciais S3 no Supabase e configure no Render:

```text
SUPABASE_STORAGE_BUCKET=lindice-media
SUPABASE_STORAGE_ENDPOINT_URL=https://SEU_PROJECT_REF.storage.supabase.co/storage/v1/s3
SUPABASE_STORAGE_REGION=REGIAO_DO_PROJETO
SUPABASE_S3_ACCESS_KEY_ID=...
SUPABASE_S3_SECRET_ACCESS_KEY=...
```

As credenciais S3 sao de uso exclusivo no servidor. Nao coloque esses valores no GitHub.

Depois do redeploy, novos uploads vao para o Supabase Storage. Arquivos antigos que estavam no disco do Render nao migram sozinhos; se uma foto antiga aparecer quebrada, reenvie a foto pelo app.
