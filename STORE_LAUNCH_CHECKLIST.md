# Checklist de lancamento da loja Lindice

## Antes de vender

- Configurar `MERCADO_PAGO_ACCESS_TOKEN` no Render.
- Configurar `PUBLIC_SITE_URL` com o dominio publico da loja.
- Configurar `SHOE_SUPPLIER_CATALOG_URL` no Render.
- Atualizar catalogo do fornecedor no painel de gestao.
- Marcar manualmente quais produtos ficam visiveis na loja.
- Conferir preco de venda, custo dropshipping e margem de cada produto visivel.
- Fazer uma compra de teste com valor baixo.
- Confirmar que o webhook do Mercado Pago marca o pedido como pago.
- Confirmar que o painel mostra o pedido em `Pago - comprar no fornecedor`.
- Fazer o pedido manual no fornecedor e marcar como comprado no painel.
- Testar adicionar codigo de rastreio.

## Seguranca e operacao

- Nunca salvar token do Mercado Pago no GitHub.
- Usar HTTPS no dominio publico.
- Manter acesso ao Render, GitHub e Mercado Pago com senha forte e 2FA.
- Criar rotina de backup do banco antes de cadastrar clientes reais em volume.
- Publicar termos simples e politica de privacidade antes de trafego pago.
- Revisar dados coletados no checkout: nome, email, telefone e endereco.
- Conferir se os produtos visiveis ainda possuem estoque no fornecedor antes de divulgar.

## Lancamento gradual

- Testar primeiro com voce.
- Testar com uma pessoa de confianca.
- Fazer uma primeira venda real controlada.
- Corrigir qualquer problema antes de divulgar para mais pessoas.
- So depois considerar trafego pago.
