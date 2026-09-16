# Catálogos de setembro de 2026

Importação autorizada pelo administrador, começando por TÊNIS PREMIUM E ORIGINAL (1).pdf, recebido em 14/09/2026. As demais categorias serão publicadas em lotes separados. Relógios excluídos.

O manifesto em `accounts/seed/catalogos_202609/tenis/manifest.json` contém 115 produtos revisados e 348 fotos, recortadas conforme as máscaras do PDF, páginas de origem, faixa, preço base, preço final, cores e equivalências com os códigos antigos. Em 15/09/2026, a continuação incorporou o aceite do administrador para usar a maior faixa nos 12 grupos com preços conflitantes. Não restam grupos pendentes neste catálogo.

## Preços

Usar a coluna VAREJO: até R$200, acrescentar 10%; acima de R$200, acrescentar 5%. Arredondar para cima à dezena menos R$0,10. Exemplos: 159,90 → 179,90; 199,90 → 219,90; 209,90 → 229,90. Pix e crediário seguem as funções existentes do aplicativo; não houve alteração global de pagamentos.

O custo interno permanece a coluna de atacado de 30% de desconto, separado do preço final. Premium e Original seguem as seções do PDF, sem usar o preço para decidir a classificação. Não foram presumidos números de referência, tecnologias, materiais ou grades não confirmados. Fotos idênticas foram ligadas aos códigos do importador anterior quando possível.

## Publicação e reexecução

`python manage.py importar_catalogos_revisados --catalogo tenis --ensaio` valida manifesto, preços e SHA-256 das fotos sem gravar. O comando sem `--ensaio` importa; `build.sh` o executa após as migrações. Produtos com a mesma revisão são ignorados integralmente, preservando edições administrativas. Revisões posteriores comparam os valores anteriores antes de sobrescrever campos. Galerias e cores são adicionadas sem excluir as fotos manuais.

Quando uma revisão tira ou substitui uma foto que o próprio catálogo enviou (por exemplo, a versão sem a marca do fornecedor), o comando remove essa foto da galeria, troca a capa e a imagem da cor se apontavam para ela, retira a cor que só existia nessa foto e apaga o arquivo do storage depois do commit, desde que nenhum outro cadastro use o mesmo arquivo. Fotos enviadas manualmente pela loja não são tocadas.

Regra do administrador (15/09/2026): nenhuma foto publicada pode mostrar a marca Santa Fiori, fornecedora dos catálogos. O monograma "SF" com "SANTA FIORI" aparece principalmente nas palmilhas. A marca é apagada ou recortada; se o resultado não ficar natural, a foto sai do manifesto. Pessoas nas fotos são permitidas.

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

## Rasteiras, flatforms e papetes (15/09/2026)

O PDF `RASTEIRAS  PAPETES  FLATFORMS (2).pdf` tem 94 páginas e três seções. A revisão extraiu 260 fotos e gerou 96 produtos: 38 rasteiras, 21 flatforms e 37 papetes. Páginas com mais de uma faixa foram separadas conforme a posição do preço e revisadas visualmente. Cores do mesmo desenho na mesma página formam uma galeria; páginas e faixas diferentes permanecem separadas. Marcas só aparecem quando visíveis, como Gucci, Schutz, Dijean e Miu Miu; os demais nomes usam a seção e o número auditável da página.

O manifesto preserva 200 equivalências únicas com fotos idênticas do PDF antigo. O ensaio passou, a importação local criou 96 produtos e a repetição preservou os 96. Os nove testes passaram e todas as 96 fichas locais responderam HTTP 200, com preços e galerias conferidos.

## Ortopédicos, mocassins, sapatilhas e scarpins (16/09/2026)

O PDF `ORTOPÉDICOS  SCARPIN  MOCASSIM  SAPATILHA (1).pdf` tem 48 páginas: a capa, o índice e as aberturas das seções (páginas 1, 2, 13, 20 e 29) ficaram de fora. A revisão separou 141 recortes; 15 são pedaços do fundo decorativo, miniaturas da própria montagem ou fotos cortadas pela diagramação e foram descartados com o motivo registrado. O manifesto `accounts/seed/catalogos_202609/ortopedicos/manifest.json` reúne 61 produtos e 126 fotos.

A faixa vem do número impresso na página. Só as páginas 40, 41 e 48 trazem mais de uma faixa, e nelas a linha com ponto vermelho liga cada preço à sua foto. O scarpin preto de bico fino aparece na página 40 com faixa 20 e nas páginas 46 e 47 com faixa 23; como é o mesmo modelo em cores diferentes, o grupo usa a faixa maior, conforme a decisão do administrador para preços conflitantes. Marcas só aparecem quando legíveis na foto ou na caixa (Beira Rio, Modare, Vizzano, Moleca, Terra & Água). Fotos idênticas ao PDF antigo deram 73 equivalências únicas para reaproveitar cadastros.

Doze fotos mostravam o monograma "SF" da Santa Fiori impresso na palmilha. A marca foi apagada reconstruindo a palmilha a partir das bordas, e cada área foi conferida ampliada antes de entrar no manifesto; nenhuma foto precisou ser descartada por causa disso. O ensaio passou, a importação local criou os 61 produtos, a repetição preservou os 61 e as 61 fichas locais responderam com preço, nome e galeria corretos.
