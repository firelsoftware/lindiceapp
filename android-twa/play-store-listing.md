# Ficha da Play Store — Líndice

Textos prontos para colar no Google Play Console.

## Nome do app (máx. 30 caracteres)

```
Líndice
```

## Descrição curta (máx. 80 caracteres)

```
Calçados, bolsas e acessórios femininos com compra pelo app e entrega.
```

## Descrição completa (máx. 4000 caracteres)

```
A Líndice é a sua loja de calçados, bolsas e acessórios femininos no celular.

Navegue pelo catálogo, escolha seu número e finalize a compra direto pelo app,
com pagamento por cartão ou Pix. Quem preferir também pode solicitar crediário
e parcelar dentro do limite aprovado.

O que você encontra na Líndice:

• Catálogo completo de calçados femininos, bolsas, relógios e linha infantil
• Botas, rasteiras, tênis, saltos, anabelas, chinelos, scarpins e muito mais
• Compra rápida e segura pelo app, com pagamento por cartão ou Pix
• Opção de crediário digital para clientes cadastradas
• Acompanhamento do pedido, do pagamento até a entrega
• Entrega no seu endereço

Compre quando e onde quiser, com a comodidade de receber em casa.

Baixe agora e descubra as novidades da Líndice.
```

## Categoria sugerida

- Categoria: Compras (Shopping)
- Tags: moda, calçados, loja

## Recursos gráficos

- Ícone do app: 512x512 (use `accounts/static/accounts/lindice-icon-512.png`)
- Feature graphic: 1024x500 (`android-twa/feature-graphic.png`) — JÁ PRONTO
- Screenshots de celular: 2 a 8 imagens (mínimo 2). FALTA: tirar no Android.
  Sugestão de telas para print: loja (vitrine), página de um produto,
  carrinho e finalização da compra.

## Política de privacidade (URL)

```
https://app.lindice.com.br/privacidade/
```

## Exclusão de dados (URL)

```
https://app.lindice.com.br/privacidade/exclusao-de-dados/
```

## Passos que dependem de você (Play Console)

1. Subir o `app-release.aab` (em `android-twa/app/build/outputs/bundle/release/`).
2. Em "Assinatura de apps", copiar a impressão digital **SHA-256** do
   certificado de assinatura gerado pelo Google.
3. No Render, definir as variáveis de ambiente:
   - `ANDROID_APP_PACKAGE_ID=com.lindice.app`
   - `ANDROID_SHA256_CERT_FINGERPRINTS=<cole o SHA-256 aqui>`
4. Conferir que `https://app.lindice.com.br/.well-known/assetlinks.json`
   passa a mostrar o JSON com o package e a fingerprint.
5. Preencher Data safety, faixa etária e enviar para revisão.
6. Anexar feature graphic, ícone e screenshots.
```
