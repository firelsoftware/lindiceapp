# Plano de site + app da Lindice

## Objetivo

Separar o site institucional do app de vendas sem pagar duas vezes pelo que nao precisa.

## Estrutura recomendada

### 1. App principal

- Dominio: `app.lindice.com.br`
- Tipo de servico: `Web Service` no Render
- Plano: `Starter`
- Responsabilidade:
  - login
  - cadastro
  - loja
  - carrinho
  - checkout
  - painel
  - gestao
  - webhooks

### 2. Site institucional

- Dominio: `lindice.com.br`
- Redirecionamento opcional: `www.lindice.com.br` -> `lindice.com.br`
- Tipo de servico: `Static Site` no Render
- Custo base: `US$ 0/mes`
- Responsabilidade:
  - homepage
  - sobre
  - como funciona
  - contato
  - politica comercial
  - campanhas e paginas de captacao

## Como as duas partes se conversam

O site institucional nao precisa compartilhar servidor com o app.

Os botoes do site apontam para o app:

- `Comprar agora` -> `https://app.lindice.com.br/loja/`
- `Entrar` -> `https://app.lindice.com.br/login/`
- `Criar conta` -> `https://app.lindice.com.br/cadastro/`
- `Pedir crediario` -> `https://app.lindice.com.br/cadastro/?intent=credit`
- `Acompanhar pedido` -> `https://app.lindice.com.br/login/`

## Desenho simples

```text
Visitante
   |
   +--> lindice.com.br -----------------> Static Site Render
   |                                         |
   |                                         +--> paginas institucionais
   |                                         +--> links para o app
   |
   +--> app.lindice.com.br ----------------> Django Web Service Render
                                             |
                                             +--> login, loja, checkout, gestao
                                             +--> PostgreSQL via DATABASE_URL
                                             +--> arquivos em Supabase Storage
```

## Por que esse desenho e o melhor para a Lindice

- elimina a sonolencia no que importa: o app
- deixa o site mais barato e rapido
- evita misturar checkout com pagina institucional
- facilita crescer depois sem refazer tudo
- segue o padrao de empresas maiores: site em camada estatica, produto em camada dinamica

## O que manter no app Django

- `app.lindice.com.br`
- `PUBLIC_SITE_URL=https://lindice.com.br`
- `DJANGO_ALLOWED_HOSTS=.onrender.com,app.lindice.com.br`
- `DJANGO_CSRF_TRUSTED_ORIGINS=https://*.onrender.com,https://app.lindice.com.br`

## O que colocar no site institucional

- marca
- proposta da loja
- destaques
- categorias
- vantagens
- botao para entrar no app
- botao para iniciar compra
- botao para cadastro de crediario

## Sequencia de implantacao

### Etapa 1. Resolver a sonolencia

Trocar o `lindice-app` de `free` para `starter`.

### Etapa 2. Publicar o site institucional

Criar um `Static Site` separado no Render para o site.

### Etapa 3. Configurar dominios

- `app.lindice.com.br` -> web service Django
- `lindice.com.br` -> static site
- `www.lindice.com.br` -> redirecionar para `lindice.com.br`

### Etapa 4. Ajustar links

Garantir que todo CTA do site leve para o app correto.

## Observacao sobre dominios no Render

O Render inclui uma quantidade limitada de custom domains por workspace e cobra valor pequeno por dominio adicional. Antes de fechar a configuracao final, vale conferir no dashboard se a combinacao `lindice.com.br`, `www.lindice.com.br` e `app.lindice.com.br` entra no limite atual do workspace.

Documentacao oficial:

- [Render Pricing](https://render.com/pricing)
- [Render Static Sites](https://render.com/docs/static-sites/)
- [Render Web Services](https://render.com/docs/web-services/)
- [Render Custom Domains](https://render.com/docs/custom-domains/)

## Caminho futuro quando crescer

Sem mudar a logica principal, depois voces podem adicionar:

- Cloudflare na frente do dominio
- analytics e pixel no site institucional
- landing pages de campanha no static site
- blog separado
- cache e protecao extra para o app

## Recomendacao final

Para a Lindice hoje:

- pagar `1` servico: o app Django no `Starter`
- hospedar `1` servico gratis: o site institucional no `Static Site`
- usar dominios separados para reduzir custo, melhorar desempenho e manter clareza operacional
