# Catálogos de setembro de 2026

Importação autorizada pelo administrador, começando por TÊNIS PREMIUM E ORIGINAL (1).pdf, recebido em 14/09/2026. As demais categorias serão publicadas em lotes separados. Relógios excluídos.

O manifesto em `accounts/seed/catalogos_202609/tenis/manifest.json` contém 115 produtos revisados e 348 fotos, recortadas conforme as máscaras do PDF, páginas de origem, faixa, preço base, preço final, cores e equivalências com os códigos antigos. Em 15/09/2026, a continuação incorporou o aceite do administrador para usar a maior faixa nos 12 grupos com preços conflitantes. Não restam grupos pendentes neste catálogo.

## Preços

Usar a coluna VAREJO: até R$200, acrescentar 10%; acima de R$200, acrescentar 5%. Arredondar para cima à dezena menos R$0,10. Exemplos: 159,90 → 179,90; 199,90 → 219,90; 209,90 → 229,90. Pix e crediário seguem as funções existentes do aplicativo; não houve alteração global de pagamentos.

O custo interno permanece a coluna de atacado de 30% de desconto, separado do preço final. Premium e Original seguem as seções do PDF, sem usar o preço para decidir a classificação. Não foram presumidos números de referência, tecnologias, materiais ou grades não confirmados. Fotos idênticas foram ligadas aos códigos do importador anterior quando possível.

## Publicação e reexecução

`python manage.py importar_catalogos_revisados --catalogo tenis --ensaio` valida manifesto, preços e SHA-256 das fotos sem gravar. O comando sem `--ensaio` importa; `build.sh` o executa após as migrações. Produtos com a mesma revisão são ignorados integralmente, preservando edições administrativas. Revisões posteriores comparam os valores anteriores antes de sobrescrever campos. Galerias e cores são adicionadas sem excluir as fotos manuais.

As fotos usam o storage configurado para a vitrine, sem HeadObject, pois esse serviço pode bloquear consulta prévia. Os caminhos efetivamente gravados são registrados no produto. A transação é por produto; uma falha pode ser retomada sem reimportar os produtos já concluídos. As fotos enviadas antes de uma falha de banco podem ficar órfãs no bucket.

Produtos antigos identificados pela mesma foto são reaproveitados, mantendo seus IDs e os pedidos vinculados. Duplicatas com identidade confirmada são ocultadas. Produtos antigos não identificados e produtos pendentes não são excluídos. A importação mantém a convenção de disponibilidade sob consulta deste fornecedor; a numeração exige confirmação.

## Validação

`python manage.py test accounts.test_catalog_import --noinput` cobre margem, arredondamento, arquivos alterados, execução de ensaio, isolamento de outros fornecedores, equivalência com entradas antigas, reexecução e preservação de edições administrativas. `python manage.py check` também passou.

## Identificação

Foram comparadas fotos e nomes visíveis no PDF com páginas das marcas. Nomes sem confirmação de modelo permanecem descritivos; a comparação não comprova autenticidade do item fornecido.

- https://www.adidas.com.br/tenis-samba-og/IH3119.html
- https://www.nike.com.br/nav/marca/nike/modelos/dunk
- https://www.newbalance.com/pd/530/U530SCW-D-09.html
- https://www.vans.com.br/c/estilo/knuskool
- https://www.westcoast.com.br/produtos
- https://www.actvitta.com.br/
- https://www.ferracini.com/colecao/

## Linha infantil (15/09/2026)

O PDF `LINHA INFANTIL (2).pdf` tem 44 páginas. A revisão visual separou 150 recortes; cinco elementos decorativos, duplicados ou montagens sem preço claro foram excluídos. O manifesto `accounts/seed/catalogos_202609/infantil/manifest.json` reúne 113 produtos e 145 fotos. Preços seguem a mesma coluna VAREJO e a regra de 10%/5% com arredondamento para cima. A faixa 9 tem varejo de R$49,90; as faixas 10 a 24 seguem R$59,90 e incrementos de R$10. A faixa mais alta do mesmo modelo foi usada apenas quando fotos de cores do mesmo desenho aparecem com valores diferentes.

Marcas foram atribuídas quando a foto ou embalagem as mostra; os demais nomes descrevem o desenho visível sem presumir código de referência, autenticidade ou material. Algumas páginas informam numeração 17–25 ou 26–36, mas a disponibilidade continua sob consulta. Fotos idênticas ao PDF infantil antigo fornecem 120 equivalências únicas para reaproveitar cadastros sem tocar pedidos anteriores.

A importação local criou 113 produtos, e a segunda execução ignorou os 113. Os nove testes do importador passaram; as 113 fichas locais responderam HTTP 200 com preços e galerias conferidos. Verificar o deploy e as imagens públicas após o envio.
