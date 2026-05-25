# Publicacao do Lindice

## Caminho recomendado

Este projeto esta preparado para subir no Render usando:

- Django em modo producao
- PostgreSQL gerenciado pelo Render
- WhiteNoise para arquivos estaticos
- Gunicorn como servidor WSGI
- HTTPS automatico do Render

## Passos

1. Crie um repositorio no GitHub para este projeto.
2. Suba os arquivos do projeto, sem `venv/`, `db.sqlite3` e `staticfiles/`.
3. No Render, crie um Blueprint a partir do repositorio.
4. O Render vai ler `render.yaml`, criar o banco PostgreSQL e o web service.
5. Depois do primeiro deploy, acesse a URL `.onrender.com`.
6. Crie o superusuario em um Shell do Render:

```bash
python manage.py createsuperuser
```

7. Adicione seu dominio personalizado no painel do Render.
8. No painel onde comprou o dominio, aponte o DNS para os registros informados pelo Render.
9. Atualize as variaveis:

```text
DJANGO_ALLOWED_HOSTS=.onrender.com,seu-dominio.com.br,www.seu-dominio.com.br
DJANGO_CSRF_TRUSTED_ORIGINS=https://seu-dominio.com.br,https://www.seu-dominio.com.br
```

## Observacoes importantes

O dominio sozinho nao hospeda o app. Ele apenas aponta para um servidor.

O banco local `db.sqlite3` nao deve ser enviado como banco de producao. O ideal e usar PostgreSQL online e, se necessario, migrar dados com fixtures.

Arquivos enviados por clientes, como comprovantes e fotos, ficam em `media/`. Para uso real com muitos clientes, o ideal e trocar para um armazenamento externo, como S3/R2. Para um MVP, da para comecar simples e evoluir depois.
