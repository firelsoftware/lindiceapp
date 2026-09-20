# Snake Training — Aula 1

Protótipo do TCC, integrado ao Lindice em `/gestao/snake-training/`. O link está no painel de gestão e só aparece para superusuários. Usa a sessão existente: não cria login, tabelas, ranking, IA nem outras aulas. Pontuação e progresso pertencem à tentativa atual e são apagados ao limpar, reiniciar ou recarregar.

## Arquivos

- `accounts/private/snake_training/index.html`: interface e conteúdo pedagógico.
- `accounts/private/snake_training/style.css`: aparência, grade e adaptação para telas menores.
- `accounts/private/snake_training/game.js`: motor da Snake e atividade, em JavaScript puro, comentado em português.
- `accounts/snake_views.py`: serve os três arquivos após verificar superusuário ativo.
- `accounts/urls.py`: rotas da página e dos arquivos protegidos.
- `accounts/templates/accounts/management_dashboard.html`: entrada no painel administrativo.
- `accounts/templates/accounts/service-worker.js`: impede cache da área privada.

Os três arquivos do jogo estão fora de `static` para não serem publicados como recursos públicos. Não copie essa pasta para hospedagem estática: a restrição depende da view Django. Superusuários ativos têm acesso; funcionários comuns e clientes recebem 403; visitantes são encaminhados ao login existente. Se houver outros superusuários, eles também terão acesso.

## Executar localmente

Para apenas testar a mecânica, abra `accounts/private/snake_training/index.html` no navegador. Não exige instalação nem conexão; o link da marca para o painel só funciona dentro do Lindice. Essa abertura local não tem controle de acesso.

Para testar integrado, na pasta do aplicativo `tmp/crediario-app`, com as dependências e o ambiente habitual do Lindice preparados:

```powershell
python manage.py runserver 127.0.0.1:8000
```

Acesse `http://127.0.0.1:8000/gestao/snake-training/` e use sua conta de superusuário existente. Não há migrações novas para o jogo. A integração precisa ser publicada junto com o aplicativo para aparecer no site online; os arquivos locais por si só não alteram a produção.

## Funcionamento

`iniciarJogo()` registra os controles. `desenharSnake()` desenha os segmentos; `movimentarSnake()` avança uma célula a cada 240 ms; `detectarColisoes()` verifica paredes e corpo; `detectarColeta()` verifica a célula ocupada pelo bloco. A mensagem ocupa quatro células e pode ser coletada em qualquer uma delas. `armazenarSequencia()` registra a ordem e aumenta a Snake.

Setas iniciam e controlam a Snake; espaço ou o botão pausam. Sair da janela também pausa. Colisões reiniciam a tentativa sem retomar automaticamente. Limpar remove o código, a saída e as metas e repõe os quatro blocos. Ao terminar a coleta, o movimento para automaticamente.

A lógica pedagógica fica em `LESSON`, `montarCodigo()`, `validarCodigo()` e `executarAtividade()`. Somente a sequência exata aceita produz `Olá mundo`. Executar uma sequência incompleta ou errada mostra orientação sem preencher a solução. A meta de formar o comando é marcada quando a sequência está correta; as demais, após executar. A execução correta vale 100 pontos por tentativa, sem acumular em cliques repetidos.

A saída é uma simulação didática específica de `print("Olá mundo")`, não um interpretador Python. Não há `eval`, chamadas de API ou envio dos dados do jogador.

## Testes

```powershell
node tools/test_snake_training.cjs
python manage.py test accounts.test_snake_training
```

O teste JavaScript percorre o tabuleiro usando o motor real com DOM mínimo e relógio controlado, verifica coleta/growth, execução correta/incompleta/incorreta, pontuação idempotente, limpeza, pausa, colisões e reversão de direção. O teste Django verifica acesso aos três arquivos para visitante, cliente, funcionário, superusuário ativo/inativo e rejeita arquivos não permitidos, sem acessar banco.

## Como acrescentar a Aula 2 futuramente

Primeiro definir seu objetivo pedagógico e a sequência esperada. Depois extrair `LESSON` e a distribuição de blocos de `reiniciarFase()` para uma configuração por aula; usar essa configuração na validação, nos textos e nas metas. Manter o motor de movimento reutilizável. Só então acrescentar uma seleção de aula e os testes do novo objetivo. Nada disso foi implementado neste protótipo: o texto “Aula 1 de 10” indica a proposta do curso, e a barra mede as três metas apenas da Aula 1.
