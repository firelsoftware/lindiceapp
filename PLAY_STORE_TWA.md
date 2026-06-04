# Play Store com TWA

Este app pode ir para a Play Store usando Trusted Web Activity (TWA), reaproveitando a loja web/PWA atual.

## Base web ja preparada

- `accounts/static/accounts/site.webmanifest`
- `service-worker.js`
- pagina offline em `/offline/`
- `assetlinks.json` em `/.well-known/assetlinks.json`

## Variaveis de ambiente

Configure no ambiente publicado:

```text
ANDROID_APP_PACKAGE_ID=com.lindice.app
ANDROID_SHA256_CERT_FINGERPRINTS=AA:BB:CC:...,11:22:33:...
```

- `ANDROID_APP_PACKAGE_ID`: package do app Android.
- `ANDROID_SHA256_CERT_FINGERPRINTS`: uma ou mais fingerprints SHA-256 do certificado usado no app.

## Passo a passo

1. Garantir que o site final esta em HTTPS.
2. Fazer deploy da web com o manifest e service worker atualizados.
3. Configurar `ANDROID_APP_PACKAGE_ID` e `ANDROID_SHA256_CERT_FINGERPRINTS`.
4. Confirmar que `https://seu-dominio/.well-known/assetlinks.json` responde com o JSON do app.
5. Instalar o Bubblewrap:

```bash
npm install -g @bubblewrap/cli
```

6. Inicializar o projeto Android:

```bash
bubblewrap init --manifest https://seu-dominio/static/accounts/site.webmanifest
```

7. Gerar o app Android:

```bash
bubblewrap build
```

8. Gerar o Android App Bundle (`.aab`) para a Play Store.
9. Subir o `.aab` no Google Play Console.
10. Preencher politica de privacidade, Data safety, faixa etaria e dados de acesso para revisao.

## Checklist antes de publicar

- login e sessao funcionando no celular
- loja, carrinho e checkout responsivos
- politica de privacidade publica
- dominio final configurado
- `assetlinks.json` validado
- icones 192 e 512 prontos
- testes manuais em Android

## Observacao

As migracoes e deploy da web continuam separadas da publicacao Android. Primeiro a web precisa estar publicada e estavel; depois o wrapper Android aponta para ela.
