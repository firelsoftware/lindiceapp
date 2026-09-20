"use strict";

// Aula 1: os únicos objetos coletáveis são estas quatro partes do comando.
const LESSON = Object.freeze({ tokens: ["print", "(", '"Olá mundo"', ")"], output: "Olá mundo" });
const COLS = 18;
const ROWS = 12;
const STEP_MS = 240;
const DIRECTIONS = { up: { x: 0, y: -1 }, down: { x: 0, y: 1 }, left: { x: -1, y: 0 }, right: { x: 1, y: 0 } };
const $ = (id) => document.getElementById(id);
let snake, blocks, collected, direction, nextDirection, running, completed, timer;

function iniciarJogo() {
  $("execute").addEventListener("click", executarAtividade);
  $("clear").addEventListener("click", () => reiniciarFase("Tentativa limpa. Experimente uma nova sequência."));
  $("restart").addEventListener("click", () => reiniciarFase());
  $("pause").addEventListener("click", alternarPausa);
  document.querySelectorAll("[data-direction]").forEach((button) => {
    button.addEventListener("click", () => escolherDirecao(button.dataset.direction));
  });
  document.addEventListener("keydown", (event) => {
    const keyMap = { ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right" };
    // Espaço em um botão mantém o comportamento acessível de clicar nele.
    if (event.target.closest("input, textarea, select") || event.ctrlKey || event.metaKey || event.altKey) return;
    if (keyMap[event.key]) {
      event.preventDefault();
      escolherDirecao(keyMap[event.key]);
    } else if (event.code === "Space" && event.target.tagName !== "BUTTON") {
      event.preventDefault();
      if (!event.repeat) alternarPausa();
    }
  });
  window.addEventListener("blur", pausarJogo);
  document.addEventListener("visibilitychange", () => { if (document.hidden) pausarJogo(); });
  reiniciarFase();
}

function reiniciarFase(message = "Uma peça de cada vez. Você consegue!") {
  clearInterval(timer);
  snake = [{ x: 3, y: 6 }, { x: 2, y: 6 }, { x: 1, y: 6 }];
  // Blocos largos ocupam todas as células sob o rótulo, inclusive a mensagem.
  blocks = [
    { text: "print", x: 4, y: 2, width: 2, kind: "function" },
    { text: "(", x: 13, y: 3, width: 1, kind: "" },
    { text: '"Olá mundo"', x: 9, y: 8, width: 4, kind: "string" },
    { text: ")", x: 4, y: 9, width: 1, kind: "" }
  ];
  collected = [];
  direction = DIRECTIONS.right;
  nextDirection = direction;
  running = false;
  completed = false;
  $("output").textContent = "Aguardando execução…";
  $("success").hidden = true;
  $("pause").disabled = false;
  feedback(message);
  atualizarCodigo();
  desenharTabuleiro();
  mostrarPausa("Vamos começar?", "Use as setas para guiar a cobrinha.");
  $("pause").textContent = "Começar";
}

function desenharSnake() {
  $("snake").replaceChildren(...snake.map((part, index) => {
    const element = document.createElement("div");
    element.className = `segment${index === 0 ? " head" : ""}`;
    posicionar(element, part);
    return element;
  }));
}

function posicionar(element, item) {
  element.style.left = `${item.x / COLS * 100}%`;
  element.style.top = `${item.y / ROWS * 100}%`;
}

function desenharTabuleiro() {
  desenharSnake();
  $("pieces").replaceChildren(...blocks.map((block) => {
    const element = document.createElement("div");
    element.className = `token ${block.kind}`;
    element.textContent = block.text;
    element.style.width = `${block.width / COLS * 100}%`;
    posicionar(element, block);
    return element;
  }));
}

function escolherDirecao(name) {
  if (completed || blocks.length === 0) return;
  const candidate = DIRECTIONS[name];
  // Compara com o último movimento realizado: duas teclas no mesmo intervalo
  // nunca permitem inverter a direção e entrar no próprio pescoço.
  if (candidate.x === -direction.x && candidate.y === -direction.y) return;
  nextDirection = candidate;
  if (!running) continuarJogo();
}

function continuarJogo() {
  if (completed || blocks.length === 0) return;
  running = true;
  $("overlay").hidden = true;
  $("pause").textContent = "Pausar";
  clearInterval(timer);
  timer = setInterval(movimentarSnake, STEP_MS);
}

function mostrarPausa(title, subtitle) {
  $("overlay").hidden = false;
  $("overlay").querySelector("strong").textContent = title;
  $("overlay").querySelector("span").textContent = subtitle;
}

function pausarJogo() {
  if (!running) return;
  running = false;
  clearInterval(timer);
  mostrarPausa("Jogo pausado", "Continue quando estiver pronto.");
  $("pause").textContent = "Continuar";
}

function alternarPausa() { running ? pausarJogo() : continuarJogo(); }

function detectarColeta(head) {
  return blocks.findIndex((block) => head.y === block.y && head.x >= block.x && head.x < block.x + block.width);
}

function detectarColisoes(head, growing) {
  if (head.x < 0 || head.x >= COLS || head.y < 0 || head.y >= ROWS) return true;
  // A cauda sai da célula no mesmo passo, exceto quando a Snake cresce.
  const body = growing ? snake : snake.slice(0, -1);
  return body.some((part) => part.x === head.x && part.y === head.y);
}

function movimentarSnake() {
  if (!running) return;
  direction = nextDirection;
  const head = { x: snake[0].x + direction.x, y: snake[0].y + direction.y };
  const blockIndex = detectarColeta(head);
  if (detectarColisoes(head, blockIndex !== -1)) {
    reiniciarFase("Ops, uma colisão! Tente novamente. Use as setas para recomeçar.");
    return;
  }
  snake.unshift(head);
  if (blockIndex !== -1) armazenarSequencia(blockIndex);
  else snake.pop();
  desenharTabuleiro();
}

function armazenarSequencia(index) {
  collected.push(blocks.splice(index, 1)[0].text);
  atualizarCodigo();
  feedback("Bloco coletado. Observe como seu código está tomando forma.");
  // Ao coletar tudo, o jogo para: o aluno pode pensar e executar sem colisões.
  if (blocks.length === 0) {
    running = false;
    clearInterval(timer);
    $("pause").disabled = true;
    $("pause").textContent = "Coleta finalizada";
    feedback("Quatro blocos coletados. Pressione Executar para testar seu código.");
  }
}

function montarCodigo() { return collected.join(""); }
function validarCodigo() {
  return collected.length === LESSON.tokens.length && collected.every((token, index) => token === LESSON.tokens[index]);
}

function atualizarCodigo() {
  $("code").textContent = montarCodigo();
  $("placeholder").hidden = collected.length > 0;
  $("count").textContent = `${collected.length} / 4 blocos`;
  const formed = validarCodigo();
  marcarMeta("goal-code", formed);
  marcarMeta("goal-run", completed);
  marcarMeta("goal-output", completed);
  $("progress").value = completed ? 3 : formed ? 1 : 0;
  $("score").textContent = completed ? "100" : "0";
}

function marcarMeta(id, checked) {
  const item = $(id);
  item.firstChild.textContent = checked ? "✓ " : "○ ";
  item.classList.toggle("done", checked);
}

function feedback(message, error = false) {
  $("feedback").textContent = message;
  $("feedback").classList.toggle("error", error);
}

function executarAtividade() {
  pausarJogo();
  if (!validarCodigo()) {
    $("output").textContent = "Nenhuma saída. Revise seu código.";
    // Feedback orienta a reflexão sem mostrar a sequência correta.
    const validPrefix = collected.every((token, index) => token === LESSON.tokens[index]);
    feedback(collected.length === 0 ? "Colete os blocos antes de executar." : validPrefix ? "Ainda faltam elementos. Continue a coleta." : "Algo foi coletado antes da hora. Observe a ordem dos elementos de uma função. Tente novamente.", true);
    return;
  }
  // Simulação didática desta única instrução. Não usa eval nem executa código
  // arbitrário: o protótipo não inclui um interpretador Python.
  completed = true;
  $("output").textContent = LESSON.output;
  $("success").hidden = false;
  $("overlay").hidden = true;
  feedback("As três metas foram alcançadas. Seu primeiro programa está pronto!");
  atualizarCodigo();
}

iniciarJogo();
