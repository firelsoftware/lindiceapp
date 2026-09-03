# Regras de negócio — CRM, Pontos de Bônus, Score, Crediário e Benefícios

> Especificação a ser seguida quando retomarmos o app Líndice. Este documento é a
> fonte da verdade das regras; o código deve refletir exatamente o que está aqui.
> Ainda **não implementado** — ver "Pontos de contato com o que já existe" e
> "Decisões em aberto" no fim.

## Contexto e objetivo

O sistema atua como motor de regras, CRM e inteligência de uma loja de varejo de
calçados, joias e smartwatches. Ele gerencia o perfil dos clientes, registra
assinaturas, calcula **Pontos de Bônus** (vindos de compras) e monitora o
**Score de Relacionamento** (comportamento de pagamento), garantindo a aplicação
correta de descontos e selos de fidelidade.

## 1. Regra de ouro: cadastro obrigatório

Nenhum cliente acumula pontos de bônus, sobe no pódio de Score (VIP, Premium, Lin.)
ou recebe benefícios sem cadastro formalizado no App da loja.

- O cliente **não** precisa ter o app instalado no celular no momento da compra.
- Mas o cadastro sistêmico vinculado ao App **deve existir e estar ativo**.

## 2. Pontos de Bônus × Score de Relacionamento

| | Pontos de Bônus | Score de Relacionamento |
|---|---|---|
| O que é | A "moeda de troca" | A "reputação" do cliente |
| De onde vem | Só de transações (compras) | Histórico de pagamentos (adimplência), relacionamento e tempo de casa |
| Para que serve | Resgatar descontos financeiros | Conceder selos de pódio (VIP, Premium, Lin.) |

- As regras e benefícios dos selos de pódio serão definidos em um **módulo futuro**.

## 3. Aquisição de Pontos de Bônus

Pontuação cumulativa, **limite máximo de 200 pontos**. Hierarquia por método de pagamento:

- **À Vista / Pix** — maior pontuação possível.
- **Cartão de crédito/débito** — pontuação intermediária (melhor que crediário, menor que Pix).
- **Crediário (recorrência)** — menor pontuação, e os pontos **só são validados e
  computados se o cliente pagar as parcelas estritamente em dia**.

**Bônus de quitação (calçados/geral):** compra no crediário quitada até o fim
**sem nenhum dia de atraso** → injeção de pontos extras como prêmio por fechar o
carnê perfeitamente.

## 4. Descontos e resgate máximo

### Desconto padrão (imediato)
Pagamentos **À Vista ou Pix** recebem automaticamente **15% de desconto** no ato da
compra, **independentemente** do saldo de pontos.

### Prêmio máximo (200 pontos)
O cliente pode usar frações de pontos a qualquer momento. Ao acumular **200 pontos**,
conquista um super bônus: **20% de desconto adicional**.

- **Condição de uso:** só pode ser resgatado numa compra **À Vista / Pix**.
- **Matemática cumulativa:** acumula com o desconto padrão do Pix. Aplica-se primeiro
  os 15% do Pix, depois os 20% dos 200 pontos sobre o valor já reduzido.
  - Exemplo: produto de R$ 100 → 15% de Pix → R$ 85 → 20% sobre R$ 85 → **R$ 68**.
- **Gatilho de urgência (expiração):** ao atingir 200 pontos, começa um **cronômetro
  de 90 dias**. Se o benefício não for usado no prazo, os pontos **expiram e o saldo
  é zerado**.

## 5. Crediário e segurança jurídica

- **Assinatura gov.br:** toda nova venda no **crediário** exige assinatura digital
  autenticada via **gov.br**.
- Assinaturas e contratos vinculados são **armazenados automaticamente no cadastro
  do cliente**.
- O sistema compila esses dados para gerar:
  1. **Relatórios de comportamento:** histórico de datas de vencimento × datas de pagamento.
  2. **Reflexos do cliente:** dossiê rápido da confiabilidade do cliente, para aprovar
     novos limites e alimentar o cálculo do Score de Relacionamento (pódio).

## 6. Painel de balcão / caixa — saída obrigatória

Sempre que a ficha de um cliente for aberta no balcão ou caixa, o painel principal
deve exibir **obrigatoriamente**:

1. **Status do cadastro no App** (Ativo / Inativo).
2. **Saldo atual de Pontos de Bônus** e **quanto falta para a meta de 200**.
3. **Classificação atual do Score** (ex.: Em construção, VIP, Premium, Lin.).
4. **Alertas visuais (vermelho / amarelo)** se houver parcelas de crediário em aberto,
   e **links rápidos** para os contratos assinados via gov.br.
5. **Alerta crítico:** se o cliente tiver 200 pontos, exibir um **contador regressivo
   bem grande** com os dias restantes dos 90 de prazo para uso.

---

## Pontos de contato com o que já existe (a resolver antes de codar)

O Líndice **já tem** um programa de fidelidade em produção. Estas regras novas
**colidem ou se sobrepõem** com ele; precisamos decidir conscientemente como conciliar:

1. **Pontos (máx. 200) × Cashback em dinheiro.** Hoje existe `CashbackTransaction`
   (ganho/resgate/ajuste/indicação) com saldo em **reais**, `StoreSettings`
   (`cashback_percent` = 5%, `cashback_max_redeem_percent` = 25%, `referral_bonus` = R$20)
   e `award_purchase_cashback`. A spec nova é um sistema de **pontos** (inteiro, teto 200),
   não de dinheiro. → **Substituir o cashback por pontos, rodar os dois em paralelo, ou
   traduzir um no outro?**
2. **Desconto de 15% no Pix.** Verificar se já há desconto de Pix / `welcome_discount_amount`
   em `CreditSale` para não aplicar duas vezes.
3. **Teto de resgate.** Hoje o resgate é limitado a 25% da compra; a spec fala em
   +20% ao bater 200 pontos, com matemática própria. Mecânicas diferentes de desconto.
4. **Crediário sem gov.br.** `CreditSale` existe, mas **não** há assinatura gov.br hoje.
   A spec exige gov.br em toda venda no crediário — integração nova (jurídica/regulatória),
   com armazenamento de contrato e relatórios de comportamento.
5. **Score de Relacionamento (VIP/Premium/Lin.).** Conceito novo, marcado como módulo
   futuro pela própria spec.
6. **Painel de balcão / caixa.** Tela administrativa/PDV nova, com os 5 itens obrigatórios.
7. **`is_staff` não pontua.** O cashback atual já exclui staff; manter para os pontos.

## Refinamentos confirmados com o dono (ago/2026)

Estas regras **fecham** as decisões em aberto do PDF e são as que valem para o código:

1. **Pontos substituem o cashback.** O `CashbackTransaction`/`StoreSettings` em dinheiro
   sai; entra o sistema de pontos (inteiro, teto 200). Os saldos de cashback existentes
   são **convertidos em pontos** na migração (taxa a definir na hora; provavelmente pouco
   saldo real).
2. **Resgate: cada 100 pontos = 10% de desconto.** Proporcional, frações liberadas. Como
   o teto é 200, o desconto máximo por pontos é **20%** (bate com o PDF). **Só resgata em
   pagamento à vista / Pix.** **Acumula** com os 15% do à vista/Pix (aplica 15% primeiro,
   depois o % dos pontos sobre o valor já reduzido).
3. **Indicação (pontos) = 100 pontos** por cliente indicado que se cadastra (substitui os
   R$20 antigos). Uma indicação vale 10% de desconto.
4. **Ganho por compra por método:** Pix > cartão > crediário (crediário só valida os
   pontos se pagar em dia). **Bônus de quitação** ao fechar o carnê sem atraso. Os valores
   exatos ficam **ajustáveis no admin** (chute inicial: Pix 10 / cartão 6 / crediário 3;
   quitação +20). `is_staff` não pontua.
5. **gov.br: upload manual** do contrato assinado, anexado no cadastro do cliente (sem
   integração de API).
6. **Teto 200 + expiração:** ao atingir 200 pontos, começa o contador de 90 dias; se não
   usar, zera. (Mantido do PDF, confirmado.)

### Indicação responsável (Premium avaliza um conhecido no crediário) — depende do Score

- Um **cliente Premium** (selo do Score) pode **indicar/avalizar um conhecido** para o
  crediário.
- **Se o avalizado não pagar**, o cliente Premium **perde o seu desconto** e o **seu
  próprio crediário volta ao valor normal** (sem o benefício).
- **Atenção:** isso é uma indicação diferente da indicação-por-pontos (item 3). É um
  **aval/fiança** com consequência. **Depende do módulo de Score (Premium)** — que o PDF
  deixou para o futuro — e de rastrear inadimplência do avalizado. Portanto entra numa
  **fase posterior**, não na fundação dos pontos.

## Fases de implementação

1. **Fundação dos pontos** — ledger de pontos (substitui o cashback em dinheiro), ganho
   por método (ajustável), indicação = 100 pts, teto 200, cadastro-ativo obrigatório,
   migração dos saldos. *(Fase atual.)*
2. **Descontos e expiração** — resgate 100pts=10% (só à vista/Pix, cumulativo com 15%),
   contador de 90 dias.
3. **Crediário + gov.br** — anexar contrato assinado, relatório de comportamento
   (vencimento × pagamento), dossiê do cliente.
4. **Score de Relacionamento** — selos VIP/Premium/Lin. + a **indicação responsável** acima.
5. **Painel de balcão** — os 5 itens obrigatórios, alertas e contador dos 90 dias.

## Mapa do que existe hoje no código (para o refactor)

- `models.py`: `CashbackTransaction` (EARN/REDEEM/REFERRAL/ADJUST), `cashback_balance()`,
  `award_purchase_cashback()`, `redeem_cashback_for_order()`, `award_referral_bonus()`,
  `resolve_referrer()`, `StoreSettings` (linha única). `ClientProfile.referral_bonus_awarded`.
- Ganho disparado em `StoreOrder.mark_paid()` (linha ~500) e `CreditSale` (~1020).
- Resgate/preview no checkout do carrinho (`views.py` ~1774–1931).
- Exibição em `dashboard.html`, `base.html`, `cart_checkout.html`, `register.html`,
  `staff_loyalty_settings.html`. Testes em `tests.py` (EARN/REFERRAL/REDEEM).
