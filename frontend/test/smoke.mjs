// Prova di accensione del bundle: monta il pannello in jsdom con un Home
// Assistant finto e controlla che disegni davvero qualcosa.
//
// Non sostituisce la prova dentro Home Assistant — geometria, temi e bus non
// esistono qui. Serve a intercettare le rotture grosse: bundle che non parte,
// custom element non registrato, render che esplode, pennellata che non arriva
// al servizio.

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
    global_setpoints: { comfort: 21, eco: 18, antifreeze: 7 },
    day_templates: {
      default: {
        id: "default",
        name: "Giornata tipo",
        slots: "e".repeat(12) + "c".repeat(5) + "e".repeat(17) + "c".repeat(11) + "e".repeat(3),
      },
      weekend: { id: "weekend", name: "Weekend", slots: "c".repeat(SLOTS) },
    },
    week_templates: {
      default: {
        id: "default",
        name: "Settimana tipo",
        days: { 0: "default", 1: "default", 2: "default", 3: "default", 4: "default", 5: "weekend", 6: "weekend" },
      },
    },
    scenarios: {
      default: {
        id: "default",
        name: "Normale",
        week_template: "default",
        offset: 0,
        zone_offsets: {},
      },
    },
    zones: {
      z1: { id: "z1", name: "Soggiorno", setpoints: { comfort: 22 }, week_template: null },
    },
    overrides: {},
    active_scenario: "default",
  },
  runtime: {
    z1: {
      entity_id: "climate.soggiorno",
      level: "comfort",
      base: 22,
      source: "zone",
      offset: 0,
      scheduled: 22,
      target: 22,
      override: null,
    },
  },
  meta: {
    levels: ["comfort", "eco", "antifreeze"],
    policies: ["next_slot", "duration", "until_scenario_change", "sticky"],
    slots_per_day: SLOTS,
    slot_minutes: 30,
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

await new Promise((resolve) => window.setTimeout(resolve, 200));

const shadow = panel.shadowRoot;
assert.ok(shadow, "il pannello deve avere uno shadow root");

const query = (selector) => [...shadow.querySelectorAll(selector)];

assert.equal(query(".tab").length, 3, "tre viste");
assert.equal(query(".row-cells").length, 7, "una riga per giorno");
assert.equal(
  query(".row-cells .cell").length,
  7 * SLOTS,
  "48 slot per ogni giorno",
);

const text = shadow.textContent ?? "";
for (const expected of ["lunedì", "domenica", "Giornata tipo", "Weekend", "Comfort"]) {
  assert.ok(text.includes(expected), `manca "${expected}" nel pannello`);
}

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

await new Promise((resolve) => window.setTimeout(resolve, 50));

assert.ok(
  (shadow.textContent ?? "").includes("Questa giornata tipo è condivisa"),
  "una pennellata su un template condiviso deve chiedere cosa fare",
);
assert.equal(calls.length, 0, "e non deve scrivere nulla prima della risposta");

// Lunedì… venerdì condividono "Giornata tipo": stesso dialogo, e scegliendo
// "Modifica per tutti" parte la chiamata al servizio.
const [modifyAll] = query(".dialog-actions .btn").filter(
  (node) => node.textContent === "Modifica per tutti",
);
assert.ok(modifyAll, "il dialogo deve offrire di modificare per tutti");
modifyAll.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));

await new Promise((resolve) => window.setTimeout(resolve, 50));

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
    level: "comfort",
  },
});

console.log("smoke: pannello montato, griglia disegnata, pennellata inoltrata");
