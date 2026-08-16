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

// Il pannello mostra l'interruttore «Scorri / Dipingi» solo dove esiste un
// dito, e lo decide una volta sola quando il bundle viene valutato: la finta
// deve stare prima della `window.eval`.
Object.defineProperty(window.navigator, "maxTouchPoints", { value: 1 });

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

// --- Il dito: prima scorre, poi dipinge ------------------------------------

// Su un telefono la griglia è più larga dello schermo e lo stesso gesto
// servirebbe a due cose. Di base il dito scorre: toccare una riga non deve
// cambiare il programma.
const modes = query(".switch-option");
assert.deepEqual(
  modes.map((node) => node.textContent),
  ["Scorri", "Dipingi"],
  "l'interruttore deve offrire scorrimento e pennello",
);
assert.equal(
  modes[0].getAttribute("aria-pressed"),
  "true",
  "si parte da «Scorri»: una pennellata involontaria cambierebbe il programma",
);

const touch = (node, type) => {
  const event = new window.MouseEvent(type, {
    bubbles: true,
    clientX: 0,
    clientY: 0,
  });
  Object.defineProperty(event, "pointerType", { value: "touch" });
  node.dispatchEvent(event);
};

const before = calls.length;
touch(saturday, "pointerdown");
touch(saturday, "pointerup");
await settle();

assert.equal(calls.length, before, "in «Scorri» il dito non deve programmare");
assert.ok(
  !text().includes("Questa giornata tipo è condivisa"),
  "e non deve nemmeno aprire il dialogo della condivisione",
);

// Passando a «Dipingi» lo stesso gesto torna a essere una pennellata.
click(modes[1]);
await settle();
touch(saturday, "pointerdown");
touch(saturday, "pointerup");
await settle();

assert.ok(
  text().includes("Questa giornata tipo è condivisa"),
  "in «Dipingi» il dito deve programmare come il mouse",
);

const [cancel] = query(".dialog-actions .btn").filter(
  (node) => node.textContent === "Annulla",
);
click(cancel);
await settle();

// --- L'intervallo si legge, non si stima -----------------------------------

// Il righello dice l'ora solo finché lo si vede: scorrendo verso il fondo
// della settimana esce di campo, e una mezz'ora è troppo stretta perché
// l'occhio la conti. Durante il trascinamento l'intervallo va quindi scritto.
assert.equal(
  query(".paint-readout").length,
  0,
  "a riposo non deve esserci nessuna targhetta",
);

touch(saturday, "pointerdown");
await settle();

const [readout] = query(".paint-readout");
assert.ok(readout, "trascinando deve comparire l'intervallo in chiaro");
assert.ok(
  readout.textContent.includes("00:00 – 00:30"),
  `l'intervallo dev'essere leggibile: "${readout.textContent}"`,
);

// Un gesto annullato non lascia la targhetta appesa.
touch(saturday, "pointercancel");
await settle();
assert.equal(
  query(".paint-readout").length,
  0,
  "e sparire quando il gesto finisce",
);

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

// --- Le temperature si modificano sull'istanza -----------------------------

// Il pulsante sta accanto all'elemento, non in un editor centrale: qui, sullo
// scenario, e apre le temperature di *quello* scenario.
const scenarioTemps = query(".item.column .item-head .btn").find((node) =>
  node.textContent.startsWith("Temperature"),
);
assert.ok(scenarioTemps, "lo scenario deve avere il suo pulsante Temperature");
click(scenarioTemps);
await settle();

assert.ok(
  text().includes("Temperature — scenario «Normale»"),
  "la finestra deve dire di quale istanza sono le temperature",
);
assert.ok(
  text().includes("dal globale «Globale»"),
  "e da dove eredita ogni livello che non sovrascrive",
);

const [close] = query(".dialog-actions .btn").filter(
  (node) => node.textContent === "Chiudi",
);
click(close);
await settle();

// Ogni zona ha il proprio pulsante nella riga della tabella: le temperature di
// una zona sono della zona, non della settimana tipo che le è assegnata.
assert.ok(
  query(".item.column table .btn").some((node) =>
    node.textContent.startsWith("Temperature"),
  ),
  "ogni zona deve avere il suo pulsante Temperature",
);

// --- Temperature: livelli e sovrascritture ---------------------------------

await openTab("Temperature");

assert.ok(
  text().includes("Livelli di temperatura"),
  "la vista delle temperature deve mostrare i livelli",
);
assert.ok(text().includes("Antigelo"), "e tutti i livelli esistenti");

// L'elenco dice *dove* è stata scritta una temperatura: lo scenario Vacanza e
// la zona Soggiorno sovrascrivono «alta».
assert.ok(text().includes("Sovrascritture"), "e l'elenco delle sovrascritture");
for (const expected of ["Vacanza", "Soggiorno", "17.0 °C", "22.0 °C"]) {
  assert.ok(
    text().includes(expected),
    `l'elenco delle sovrascritture deve contenere "${expected}"`,
  );
}

console.log(
  "smoke: pannello montato, griglia disegnata, pennellata inoltrata, scenari e temperature per istanza",
);
