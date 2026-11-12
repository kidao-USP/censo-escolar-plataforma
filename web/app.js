"use strict";
const $ = (id) => document.getElementById(id);
const CATEGORIA = { matriculas: "matricula", docentes: "docente", turmas: "turma" };
let ultimaConsulta = null; // URL (sem formato) da ultima consulta, para o CSV

function setStatus(texto, erro = false) {
  const el = $("status");
  el.textContent = texto;
  el.className = erro ? "erro" : "";
}

async function api(caminho, params = {}) {
  const url = new URL(caminho, window.location.origin);
  for (const [k, v] of Object.entries(params)) {
    if (v !== "" && v !== null && v !== undefined) url.searchParams.set(k, v);
  }
  const r = await fetch(url);
  if (!r.ok) {
    let msg = `Erro ${r.status}`;
    try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch (_) {}
    throw new Error(msg);
  }
  return r;
}

async function carregarAnos() {
  const anos = await (await api("/api/anos")).json();
  const sel = $("ano");
  sel.replaceChildren();
  for (const a of anos) {
    const o = document.createElement("option");
    o.value = a.ano; o.textContent = a.ano;
    sel.appendChild(o);
  }
  if (!anos.length) setStatus("Nenhum ano carregado na base ainda (rode o ETL).", true);
}

async function carregarVariaveis() {
  const recurso = $("recurso").value;
  const box = $("lista-variaveis");
  const ehAgregado = recurso in CATEGORIA;
  $("fs-variaveis").hidden = !ehAgregado;
  $("lbl-agrupar").hidden = !ehAgregado;
  $("lbl-nome").hidden = ehAgregado;
  if (!ehAgregado) return;
  const vars = await (await api("/api/metadados/variaveis",
    { categoria: CATEGORIA[recurso], busca: $("busca-var").value.trim() })).json();
  box.replaceChildren();
  for (const v of vars.slice(0, 400)) {
    const lbl = document.createElement("label");
    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.value = v.no_variavel;
    const txt = document.createElement("span");
    const code = document.createElement("code");
    code.textContent = v.no_variavel;
    txt.append(code, v.descricao ? " – " + v.descricao : "");
    lbl.append(cb, txt);
    box.appendChild(lbl);
  }
  if (!vars.length) box.textContent = "Nenhuma variável encontrada.";
}

// ---- Municipio: lista de sugestoes (envia o codigo IBGE do escolhido)
const SUG = { timer: null, seq: 0 };

function esconderSugestoes() {
  const ul = $("sugestoes-municipio");
  ul.hidden = true;
  ul.replaceChildren();
  $("municipio").setAttribute("aria-expanded", "false");
}

function escolherMunicipio(m) {
  const campo = $("municipio");
  campo.value = m.rotulo;
  campo.dataset.codigo = m.co_municipio;
  esconderSugestoes();
  campo.focus();
}

async function buscarMunicipios() {
  const texto = $("municipio").value.trim();
  const seq = ++SUG.seq;
  if (texto.length < 2 || /^\d+$/.test(texto)) { esconderSugestoes(); return; }
  try {
    const lista = await (await api("/api/municipios",
      { busca: texto, uf: $("uf").value.trim(), ano: $("ano").value })).json();
    if (seq !== SUG.seq) return; // resposta antiga: o usuario ja digitou outra coisa
    const ul = $("sugestoes-municipio");
    ul.replaceChildren();
    for (const m of lista) {
      const li = document.createElement("li");
      const b = document.createElement("button");
      b.type = "button";
      b.setAttribute("role", "option");
      b.textContent = `${m.rotulo} · IBGE ${m.co_municipio}`;
      b.addEventListener("click", () => escolherMunicipio(m));
      li.appendChild(b);
      ul.appendChild(li);
    }
    if (!lista.length) {
      const li = document.createElement("li");
      li.className = "vazio";
      li.textContent = "Nenhum município encontrado.";
      ul.appendChild(li);
    }
    ul.hidden = false;
    $("municipio").setAttribute("aria-expanded", "true");
  } catch (_) {
    esconderSugestoes(); // a consulta continua valendo com o texto digitado
  }
}

$("municipio").addEventListener("input", () => {
  delete $("municipio").dataset.codigo; // editou o texto: deixa de valer o codigo escolhido
  clearTimeout(SUG.timer);
  SUG.timer = setTimeout(buscarMunicipios, 250);
});
$("municipio").addEventListener("keydown", (ev) => {
  const ul = $("sugestoes-municipio");
  if (ev.key === "Escape") esconderSugestoes();
  else if (ev.key === "ArrowDown" && !ul.hidden) {
    ev.preventDefault();
    const primeiro = ul.querySelector("button");
    if (primeiro) primeiro.focus();
  }
});
$("sugestoes-municipio").addEventListener("keydown", (ev) => {
  const botoes = [...$("sugestoes-municipio").querySelectorAll("button")];
  const i = botoes.indexOf(document.activeElement);
  if (ev.key === "ArrowDown") { ev.preventDefault(); if (botoes[i + 1]) botoes[i + 1].focus(); }
  else if (ev.key === "ArrowUp") { ev.preventDefault(); (botoes[i - 1] || $("municipio")).focus(); }
  else if (ev.key === "Escape") { esconderSugestoes(); $("municipio").focus(); }
});
document.addEventListener("click", (ev) => {
  if (!ev.target.closest(".campo-sugestoes")) esconderSugestoes();
});

function parametros() {
  const recurso = $("recurso").value;
  const campoMun = $("municipio");
  const p = {
    ano: $("ano").value, uf: $("uf").value.trim(),
    municipio: campoMun.dataset.codigo || campoMun.value.trim(),
    rede: $("rede").value, localizacao: $("localizacao").value,
  };
  if (recurso in CATEGORIA) {
    p.agrupar_por = $("agrupar").value;
    const marcadas = [...document.querySelectorAll("#lista-variaveis input:checked")].map((c) => c.value);
    if (marcadas.length) p.variaveis = marcadas.join(",");
  } else {
    p.nome = $("nome").value.trim();
    p.limite = 1000;
  }
  return p;
}

function desenharTabela(linhas) {
  const t = $("tabela");
  t.replaceChildren();
  if (!linhas.length) return;
  const colunas = Object.keys(linhas[0]);
  const thead = t.createTHead().insertRow();
  for (const c of colunas) {
    const th = document.createElement("th");
    th.textContent = c;
    thead.appendChild(th);
  }
  const tbody = t.createTBody();
  for (const l of linhas) {
    const tr = tbody.insertRow();
    for (const c of colunas) {
      const td = tr.insertCell();
      const v = l[c];
      td.textContent = v === null || v === undefined ? "" : (typeof v === "number" && c === "total" ? v.toLocaleString("pt-BR") : v);
      if (c === "total") td.className = "num";
    }
  }
}

$("form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  setStatus("Consultando…");
  $("baixar").disabled = true;
  const recurso = $("recurso").value;
  try {
    const params = parametros();
    const dados = await (await api(`/api/${recurso}`, params)).json();
    desenharTabela(dados.dados);
    ultimaConsulta = { recurso, params };
    $("baixar").disabled = false;
    $("resumo").textContent = recurso === "escolas"
      ? `${dados.total.toLocaleString("pt-BR")} escolas encontradas (mostrando ${dados.quantidade}).`
      : `${dados.quantidade} linha(s).` + (dados.aviso ? " " + dados.aviso : "");
    setStatus("");
  } catch (e) {
    setStatus(e.message, true);
  }
});

$("baixar").addEventListener("click", () => {
  if (!ultimaConsulta) return;
  const url = new URL(`/api/${ultimaConsulta.recurso}`, window.location.origin);
  for (const [k, v] of Object.entries(ultimaConsulta.params)) if (v !== "") url.searchParams.set(k, v);
  url.searchParams.set("formato", "csv");
  if (ultimaConsulta.recurso === "escolas") url.searchParams.set("limite", 100000);
  window.location.href = url;
});

$("recurso").addEventListener("change", () => carregarVariaveis().catch((e) => setStatus(e.message, true)));
let timer;
$("busca-var").addEventListener("input", () => {
  clearTimeout(timer);
  timer = setTimeout(() => carregarVariaveis().catch((e) => setStatus(e.message, true)), 300);
});

(async () => {
  try { await carregarAnos(); await carregarVariaveis(); }
  catch (e) { setStatus("Não foi possível conectar à API: " + e.message, true); }
})();
