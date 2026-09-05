# Publicacao do Lindice

## Caminho recomendado

Este projeto esta preparado para subir no Render usando:

- Django em modo producao
- PostgreSQL externo por `DATABASE_URL`
- WhiteNoise para arquivos estaticos
- Gunicorn como servidor WSGI
- HTTPS automatico do Render

## Modelo recomendado de repositorio

Este repositorio pode servir duas publicacoes diferentes:

- app Django em `app.lindice.com.br`
- site institucional estatico na pasta `site/`

Isso nao afeta a Play Store se o app Android/TWA continuar apontando para `app.lindice.com.br`.

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

## Site institucional no mesmo repositorio

Se quiser publicar tambem o site institucional no mesmo Git:

1. Crie um novo servico `Static Site` no Render.
2. Aponte o `Root directory` para `site`.
3. Deixe `Build command` vazio.
4. Use `Publish directory` como `.`.
5. Configure o dominio principal, por exemplo `lindice.com.br`.
6. Mantenha o app Django em `app.lindice.com.br`.

Assim:

- `lindice.com.br` -> site institucional
- `app.lindice.com.br` -> app Django
- Play Store/TWA -> continua usando `app.lindice.com.br`

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

### Bucket publico das fotos da loja

O bucket acima e privado porque guarda documento de cliente. Link privado sai
assinado e vence em uma hora, o que atrapalha foto de produto: o navegador nao
guarda em cache e nenhum site de fora abre a imagem. Por isso as fotos da loja
ficam num segundo bucket, publico.

1. No Supabase, em Storage, crie um bucket chamado `lindice-publico` e marque
   a opcao **Public bucket**.
2. Na Render, adicione a variavel:

```text
SUPABASE_PUBLIC_BUCKET=lindice-publico
```

3. Depois do redeploy, entre em `/gestao/fotos-publicas/` e clique em
   "Copiar as fotos que faltam". Pode clicar de novo sem medo: o que ja foi
   copiado nao vai duas vezes.

Nao e preciso gerar chave nova: o bucket publico usa as mesmas credenciais S3.
Sem a variavel, tudo continua funcionando como antes, no bucket privado.

Depois do redeploy, novos uploads vao para o Supabase Storage. Arquivos antigos que estavam no disco do Render nao migram sozinhos; se uma foto antiga aparecer quebrada, reenvie a foto pelo app.
