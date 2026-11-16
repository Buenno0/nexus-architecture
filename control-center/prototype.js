const stages = [
  { category: "ENTRADA / API", title: "Repetir a chamada não duplica o registro.", description: "Se a resposta se perder na rede, o cliente pode tentar de novo com a mesma chave de idempotência. A API devolve a resposta armazenada para aquela operação.", from: "CLIENTE", fromValue: "POST", to: "API", toValue: "CHAVE", caption: "mesma operação → resposta armazenada", link: "https://github.com/Buenno0/nexus-architecture/blob/main/docs/adr/ADR-002-identidade-e-idempotencia.md" },
  { category: "PERSISTÊNCIA / OUTBOX", title: "O evento fica salvo antes da publicação.", description: "Registro e evento pendente são gravados na mesma transação. Se a publicação falhar, o despachante ainda encontra o evento no outbox.", from: "API", fromValue: "GRAVA", to: "DYNAMODB", toValue: "OUTBOX", caption: "registro + evento em uma transação", link: "https://github.com/Buenno0/nexus-architecture/blob/main/docs/adr/ADR-003-transactional-outbox.md" },
  { category: "ESPERA / FILA", title: "Após três tentativas sem sucesso, a mensagem vai para a DLQ.", description: "O worker tenta novamente com espera crescente. Esgotado o limite, a mensagem fica na DLQ até ser examinada ou devolvida por redrive.", from: "FILA", fromValue: "3 TENT.", to: "DLQ", toValue: "REDRIVE", caption: "tentativas esgotadas → mensagem visível", link: "https://github.com/Buenno0/nexus-architecture/blob/main/docs/adr/ADR-004-fila-local-sqlite.md" },
  { category: "DECISÃO / RESOLUÇÃO", title: "Par incerto fica para revisão humana.", description: "O score produz três saídas: fundir, pedir revisão ou não associar. A faixa intermediária não funde registros automaticamente.", from: "PAR", fromValue: "SCORE", to: "REVISÃO", toValue: "PENDENTE", caption: "faixa intermediária → revisão", link: "https://github.com/Buenno0/nexus-architecture/blob/main/docs/adr/ADR-006-entity-resolution.md" },
  { category: "TRILHA / OBSERVABILIDADE", title: "API e worker registram marcos da mesma jornada.", description: "A trilha junta eventos emitidos pelos dois processos e permite localizar a espera na fila. É best-effort: pode ter lacunas e não substitui uma auditoria.", from: "API", fromValue: "MARCO", to: "WORKER", toValue: "MARCO", caption: "marcos emitidos durante o percurso", link: "https://github.com/Buenno0/nexus-architecture/blob/main/docs/adr/ADR-010-observabilidade.md" },
];

const tabs = [...document.querySelectorAll(".journey-step")];
const panel = document.querySelector("#stage-panel");
let current = 0;

function selectStage(index, focus = false) {
  current = Math.max(0, Math.min(stages.length - 1, index));
  const stage = stages[current];
  tabs.forEach((tab, i) => {
    const selected = i === current;
    tab.classList.toggle("active", selected);
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
  });
  panel.setAttribute("aria-labelledby", `stage-tab-${current}`);
  document.querySelector("#stage-label").textContent = `ETAPA 0${current + 1} / 05`;
  document.querySelector("#stage-category").textContent = stage.category;
  document.querySelector("#stage-title").textContent = stage.title;
  document.querySelector("#stage-description").textContent = stage.description;
  document.querySelector("#diagram-caption").textContent = stage.caption;
  document.querySelector("#stage-link").href = stage.link;
  document.querySelector("#stage-link").firstChild.textContent = `Ler o ADR-${["002", "003", "004", "006", "010"][current]} `;
  document.querySelector(".diagram-source span").textContent = stage.from;
  document.querySelector(".diagram-source b").textContent = stage.fromValue;
  document.querySelector(".diagram-target span").textContent = stage.to;
  document.querySelector(".diagram-target b").textContent = stage.toValue;
  document.querySelector("#step-prev").disabled = current === 0;
  document.querySelector("#step-next").disabled = current === stages.length - 1;
  if (focus) tabs[current].focus();
}

tabs.forEach((tab, index) => {
  tab.addEventListener("click", () => selectStage(index));
  tab.addEventListener("keydown", (event) => {
    if (!["ArrowRight", "ArrowLeft", "ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === "Home" ? 0 : event.key === "End" ? stages.length - 1 : index + (["ArrowRight", "ArrowDown"].includes(event.key) ? 1 : -1);
    selectStage((next + stages.length) % stages.length, true);
  });
});
document.querySelector("#step-prev").addEventListener("click", () => selectStage(current - 1));
document.querySelector("#step-next").addEventListener("click", () => selectStage(current + 1));
