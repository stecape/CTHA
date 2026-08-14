// Prova di accensione del bundle: monta il pannello in jsdom con un Home
// Assistant finto e controlla che disegni davvero qualcosa.
//
// Non sostituisce la prova dentro Home Assistant — geometria, temi e bus non
// esistono qui. Serve a intercettare le rotture grosse: bundle che non parte,
// custom element non registrato, render che esplode, pennellata che non arriva
// al servizio, scenario che non mostra più la configurazione delle zone.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { JSDOM } from "jsdom";

const here = dirname(fileURLToPath(import.meta.url));
const bundle = readFileSync(
  join(here, "..", "..", "custom_components", "ctha", "frontend", "ctha-panel.js"),
  "utf8",
);

const SLOTS = 48;
const snapshot = {
  program: {
    levels: {
      alta: { id: "alta", name: "Alta", char: "a", color: "#e0703c" },
      media: { id: "media", name: "Media", char: "m", color: "#e0b13c" },
      bassa: { id: "bassa", name: "Bassa", char: "b", color: "#3f9d7c" },
      antigelo: { id: "antigelo", name: "Antigelo", char: "g", color: "#4a7fbf" },
    },
    global_setpoints: { alta: 21, media: 19, bassa: 17, antigelo: 7 },
    day_templates: {
      default: {
        id: "default",
        name: "Giornata tipo",
        slots:
          "b".repeat(12) + "a".repeat(5) + "m".repeat(17) + "a".repeat(11) + "b".repeat(3),
        setpoints: {},
      },
      weekend: {
        id: "weekend",
        name: "Weekend",
        slots: "a".repeat(SLOTS),
        setpoints: {},
      },
    },
    week_templates: {
      default: {
        id: "default",
        name: "Settimana tipo",
        days: { 0: "default", 1: "default", 2: "default", 3: "default", 4: "default", 5: "weekend", 6: "weekend" },
        setpoints: {},
      },
      estiva: {
        id: "estiva",
        name: "Settimana estiva",
        days: { 0: "weekend", 1: "weekend", 2: "weekend", 3: "weekend", 4: "weekend", 5: "weekend", 6: "weekend" },
        setpoints: {},
      },
    },
    scenarios: {
      default: {
        id: "default",
        name: "Normale",
        zones: { z1: "default" },
        setpoints: {},
      },
      vacanza: {
        id: "vacanza",
        name: "Vacanza",
        zones: { z1: "estiva" },
        setpoints: { alta: 17 },
      },
    },
    zones: {
      z1: { id: "z1", name: "Soggiorno", setpoints: { alta: 22 } },
    },
    overrides: {},
    active_scenario: "default",
  },
  runtime: {
    z1: {
      entity_id: "climate.soggiorno",
      level: "alta",
      source: "zone",
      scheduled: 22,
      target: 22,
      week_template: "default",
      day_template: "default",
      slot: 14,
      override: null,
    },
  },
  meta: {
    layers: ["day_template", "week_template", "zone", "scenario", "global"],
    policies: ["next_slot", "duration", "until_scenario_change", "sticky"],
    slots_per_day: SLOTS,
    slot_minutes: 30,
    inherit_char: "-",
    min_temp: 5,
    max_temp: 30,
    temp_step: 0.5,
  },
};

const dom = new JSDOM("<!doctype html><html><body></body></html>", {
  url: "http://localhost/ctha",
  pretendToBeVisual: true,
  // Serve a far girare `window.eval` dentro il contesto della finestra: senza,
  // il bundle verrebbe valutato in quello di Node, dove non esiste HTMLElement.
  runScripts: "outside-only",
});
const { window } = dom;

// jsdom non implementa la pointer capture: senza questi stub il primo
// pointerdown solleverebbe un errore invece di iniziare la pennellata.
window.Element.prototype.setPointerCapture = () => {};
window.Element.prototype.releasePointerCapture = () => {};

const calls = [];
const hass = {
  states: {
    "climate.soggiorno": {
      entity_id: "climate.soggiorno",
      state: "heat",
      attributes: { current_temperature: 20.4 },
    },
  },
  language: "it",
  callService: async (domain, service, data) => {
    calls.push({ domain, service, data });
    return {};
  },
  callWS: async () => snapshot,
  connection: {
    subscribeMessage: async (callback) => {
      callback(snapshot);
      return async () => {};
    },
  },
};

window.eval(bundle);

const panel = window.document.createElement("ctha-panel");
panel.hass = hass;
window.document.body.append(panel);

const settle = () => new Promise((resolve) => window.setTimeout(resolve, 50));

await new Promise((resolve) => window.setTimeout(resolve, 200));

const shadow = panel.shadowRoot;
assert.ok(shadow, "il pannello deve avere uno shadow root");

const query = (selector) => [...shadow.querySelectorAll(selector)];
const click = (node) =>
  node.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
const openTab = async (label) => {
  const tab = query(".tab").find((node) => node.textContent === label);
  assert.ok(tab, `manca la vista "${label}"`);
  click(tab);
  await settle();
};

assert.equal(query(".tab").length, 4, "quattro viste");
assert.equal(query(".row-cells").length, 7, "una riga per giorno");
assert.equal(
  query(".row-cells .cell").length,
  7 * SLOTS,
  "48 slot per ogni giorno",
);

const text = () => shadow.textContent ?? "";
for (const expected of ["lunedì", "domenica", "Giornata tipo", "Weekend", "Alta"]) {
  assert.ok(text().includes(expected), `manca "${expected}" nel pannello`);
}

// I pennelli sono i livelli del modello, non tre costanti nel codice.
assert.equal(query(".brush").length, 5, "un pennello per livello, più «eredita»");

// Il badge "condivisa" deve comparire: cinque giorni usano la stessa giornata.
assert.ok(
  query(".badge").some((node) => node.textContent === "condivisa"),
  "la condivisione fra giorni deve essere segnalata",
);

// Sabato e domenica condividono "Weekend": dipingere lì chiede conferma.
const saturday = query(".row-cells")[5];
const press = (type) =>
  saturday.dispatchEvent(
    new window.MouseEvent(type, { bubbles: true, clientX: 0, clientY: 0 }),
  );
press("pointerdown");
press("pointerup");

await settle();

assert.ok(
  text().includes("Questa giornata tipo è condivisa"),
  "una pennellata su un template condiviso deve chiedere cosa fare",
);
assert.equal(calls.length, 0, "e non deve scrivere nulla prima della risposta");

// Lunedì… venerdì condividono "Giornata tipo": stesso dialogo, e scegliendo
// "Modifica per tutti" parte la chiamata al servizio.
const [modifyAll] = query(".dialog-actions .btn").filter(
  (node) => node.textContent === "Modifica per tutti",
);
assert.ok(modifyAll, "il dialogo deve offrire di modificare per tutti");
click(modifyAll);

await settle();

assert.equal(calls.length, 1, "una pennellata, una chiamata");
// Il round-trip via JSON serve a confrontare i valori: gli oggetti nascono nel
// contesto di jsdom, quindi hanno un altro Object.prototype.
assert.deepEqual(JSON.parse(JSON.stringify(calls[0])), {
  domain: "ctha",
  service: "paint_slots",
  data: {
    template_id: "weekend",
    start_slot: 0,
    end_slot: 0,
    level: "alta",
  },
});

// --- Scenari: la configurazione delle zone ---------------------------------

await openTab("Scenari");

assert.ok(text().includes("Vacanza"), "gli scenari devono comparire tutti");
assert.ok(
  text().includes("Soggiorno"),
  "ogni scenario mostra la tabella delle sue zone",
);

// Riassegnare la settimana tipo di una zona dentro uno scenario passa dal
// servizio, con lo scenario esplicito: è il gesto che *è* lo scenario.
const assign = query(".item.column table select")[0];
assert.ok(assign, "ogni zona deve avere il menù della settimana tipo");
assign.value = "estiva";
assert.equal(assign.value, "estiva", "il menù deve elencare le settimane tipo");
assign.dispatchEvent(new window.Event("change", { bubbles: true }));

await settle();

assert.deepEqual(JSON.parse(JSON.stringify(calls[calls.length - 1])), {
  domain: "ctha",
  service: "set_zone_week_template",
  data: {
    zone_id: "z1",
    template_id: "estiva",
    scenario_id: "default",
  },
});

// --- Temperature: livelli e gerarchia --------------------------------------

await openTab("Temperature");

assert.ok(
  text().includes("Gerarchia delle temperature"),
  "la vista delle temperature deve mostrare la gerarchia",
);
assert.ok(text().includes("Antigelo"), "e tutti i livelli esistenti");

console.log(
  "smoke: pannello montato, griglia disegnata, pennellata inoltrata, scenari e gerarchia visibili",
);
