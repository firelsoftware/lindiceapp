// Testes determinísticos do motor real, sem bibliotecas nem temporizadores reais.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const elements = new Map();
function element() {
  return { style: {}, hidden: false, disabled: false, textContent: '', firstChild: { textContent: '' },
    classList: { toggle() {} }, addEventListener() {}, replaceChildren(...children) { this.children = children; },
    querySelector(selector) { return this[selector] ||= element(); } };
}
const context = vm.createContext({
  document: { getElementById(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); },
    createElement: element, querySelectorAll: () => [], addEventListener() {} },
  window: { addEventListener() {} }, setInterval: () => 1, clearInterval() {}, assert,
});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../accounts/private/snake_training/game.js'), 'utf8'), context);
vm.runInContext(`
  assert.equal(blocks.length, 4);
  assert.equal(new Set(blocks.map(b => b.text)).size, 4);
  executarAtividade();
  assert.equal(completed, false);
  assert.equal($('score').textContent, '0');
  // Percurso real de coleta: print -> ( -> mensagem -> ).
  function walk(name, steps) {
    escolherDirecao(name);
    for (let i = 0; i < steps; i++) movimentarSnake();
  }
  walk('up', 4); walk('right', 1);
  assert.equal(montarCodigo(), 'print');
  assert.equal(snake.length, 4);
  executarAtividade();
  assert.equal(running, false);
  assert.equal(completed, false);
  walk('right', 9); walk('down', 1);
  assert.equal(montarCodigo(), 'print(');
  walk('down', 5); walk('left', 1);
  assert.equal(collected.length, 3);
  walk('down', 1); walk('left', 8);
  assert.equal(validarCodigo(), true);
  assert.equal(snake.length, 7);
  assert.equal(running, false);
  executarAtividade(); executarAtividade();
  assert.equal($('output').textContent, 'Olá mundo');
  assert.equal($('score').textContent, '100');
  assert.equal($('progress').value, 3);
  assert.equal($('success').hidden, false);
  reiniciarFase();
  assert.equal(collected.length, 0);
  assert.equal($('score').textContent, '0');
  assert.equal($('success').hidden, true);
  // Ordem incorreta não executa nem revela a solução no feedback.
  walk('down', 3); walk('right', 1);
  assert.equal(montarCodigo(), ')');
  executarAtividade();
  assert.equal(completed, false);
  assert.equal($('feedback').textContent.includes('print'), false);
  // Parede reinicia a tentativa.
  reiniciarFase(); walk('up', 7);
  assert.equal(running, false);
  assert.equal(snake.length, 3);
  assert.equal(blocks.length, 4);
  assert.equal($('feedback').textContent.includes('colisão'), true);
  // Reversão rápida, cauda que se move e autocolisão.
  reiniciarFase(); escolherDirecao('up'); escolherDirecao('left');
  assert.equal(nextDirection, DIRECTIONS.up);
  snake = [{x:3,y:3},{x:3,y:4},{x:2,y:4},{x:2,y:3}];
  assert.equal(detectarColisoes({x:2,y:3}, false), false);
  assert.equal(detectarColisoes({x:2,y:3}, true), true);
  direction = DIRECTIONS.up; nextDirection = DIRECTIONS.down; running = true;
  movimentarSnake();
  assert.equal($('feedback').textContent.includes('colisão'), true);
  // Pausar impede movimentação; todos os trechos da mensagem são coletáveis.
  reiniciarFase(); continuarJogo(); pausarJogo();
  const before = JSON.stringify(snake); movimentarSnake();
  assert.equal(JSON.stringify(snake), before);
  for (let x = 9; x <= 12; x++) assert.equal(detectarColeta({x,y:8}), 2);
`, context);
console.log('Snake Training: coleta completa, execução, erro, reinício, colisões, pausa e metas OK.');
