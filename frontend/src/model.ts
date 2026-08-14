// Funzioni pure sul modello: nessun React, nessun Home Assistant.
//
// Alcune duplicano ciò che fa il backend — le usanze di un template, il
// risultato di una pennellata, la catena di ereditarietà. La duplicazione è
// voluta e serve a una cosa sola: mostrare l'effetto di un'azione *prima* del
// giro attraverso il backend. La verità resta il backend, che rifiuta ciò che
// non è ammissibile; qui si disegna soltanto.

import type {
  DayTemplate,
  Layer,
  LevelId,
  Program,
  Scope,
  Setpoints,
  TemperatureLevel,
  WeekTemplate,
} from "./types";

export const INHERIT_CHAR = "-";

export const SLOTS_PER_DAY = 48;

export const LAYER_LABEL: Record<Layer, string> = {
  day_template: "giornata tipo",
  week_template: "settimana tipo",
  zone: "zona",
  scenario: "scenario",
  global: "globale",
  none: "nessuno",
};

export const WEEKDAYS = [
  "lunedì",
  "martedì",
  "mercoledì",
  "giovedì",
  "venerdì",
  "sabato",
  "domenica",
];

export const WEEKDAYS_SHORT = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"];

/** I livelli nell'ordine in cui sono stati creati: è l'ordine che l'utente ha scelto. */
export function levels(program: Program): TemperatureLevel[] {
  return Object.values(program.levels);
}

/** Livello dipinto in uno slot, o `null` se lo slot eredita. */
export function levelAt(
  program: Program,
  slots: string,
  slot: number,
): TemperatureLevel | null {
  const char = slots[slot];
  if (!char || char === INHERIT_CHAR) return null;
  return levels(program).find((level) => level.char === char) ?? null;
}

/** Ora d'inizio dello slot, in formato 24 ore. */
export function slotTime(slot: number): string {
  const minutes = slot * 30;
  const hh = String(Math.floor(minutes / 60)).padStart(2, "0");
  const mm = String(minutes % 60).padStart(2, "0");
  return `${hh}:${mm}`;
}

/** Intervallo orario coperto da uno slot, per i tooltip. */
export function slotRange(slot: number): string {
  return `${slotTime(slot)}–${slotTime((slot + 1) % SLOTS_PER_DAY)}`;
}

/** Risultato di una pennellata, senza toccare il modello: estremi inclusi. */
export function paintedSlots(
  slots: string,
  start: number,
  end: number,
  level: TemperatureLevel | null,
): string {
  const [from, to] = start <= end ? [start, end] : [end, start];
  const char = level === null ? INHERIT_CHAR : level.char;
  return slots.slice(0, from) + char.repeat(to - from + 1) + slots.slice(to + 1);
}

export interface DayUsage {
  weekId: string;
  weekName: string;
  days: number[];
}

/** Chi usa una giornata tipo, e in quali giorni: la vista delle dipendenze. */
export function dayTemplateUsages(
  program: Program,
  templateId: string,
): DayUsage[] {
  return Object.values(program.week_templates)
    .map((week) => ({
      weekId: week.id,
      weekName: week.name,
      days: Object.entries(week.days)
        .filter(([, id]) => id === templateId)
        .map(([day]) => Number(day))
        .sort((a, b) => a - b),
    }))
    .filter((usage) => usage.days.length > 0);
}

export interface WeekUsage {
  scenarioId: string;
  scenarioName: string;
  zones: string[];
}

/** Scenari che assegnano una settimana tipo, e a quali zone. */
export function weekTemplateUsages(
  program: Program,
  templateId: string,
): WeekUsage[] {
  return Object.values(program.scenarios)
    .map((scenario) => ({
      scenarioId: scenario.id,
      scenarioName: scenario.name,
      zones: Object.entries(scenario.zones)
        .filter(([, weekId]) => weekId === templateId)
        .map(([zoneId]) => program.zones[zoneId]?.name ?? zoneId),
    }))
    .filter((usage) => usage.zones.length > 0);
}

/** Giornate tipo che dipingono un livello, e in quanti slot. */
export function levelUsages(
  program: Program,
  levelId: LevelId,
): { id: string; name: string; slots: number }[] {
  const level = program.levels[levelId];
  if (!level) return [];
  return Object.values(program.day_templates)
    .map((template) => ({
      id: template.id,
      name: template.name,
      slots: [...template.slots].filter((char) => char === level.char).length,
    }))
    .filter((usage) => usage.slots > 0);
}

/**
 * Giorni che condividono la giornata tipo di un certo giorno, escluso quello.
 *
 * È la domanda che decide se una pennellata è innocua o se cambia il programma
 * anche altrove: se la risposta non è vuota, va chiesto all'utente cosa vuole.
 */
export function sharedWith(
  program: Program,
  weekId: string,
  weekday: number,
  templateId: string,
): DayUsage[] {
  return dayTemplateUsages(program, templateId)
    .map((usage) => ({
      ...usage,
      days:
        usage.weekId === weekId
          ? usage.days.filter((day) => day !== weekday)
          : usage.days,
    }))
    .filter((usage) => usage.days.length > 0);
}

/** Elenco leggibile di giorni: "lunedì, martedì e venerdì". */
export function listDays(days: number[]): string {
  const names = days.map((day) => WEEKDAYS[day] ?? String(day));
  if (names.length <= 1) return names.join("");
  return `${names.slice(0, -1).join(", ")} e ${names[names.length - 1]}`;
}

// --- Gerarchia dei setpoint -------------------------------------------------

export const GLOBAL_SCOPE: Scope = { layer: "global", id: "" };

interface Holder {
  layer: Layer;
  id: string;
  name: string;
  setpoints: Setpoints;
}

export interface Inherited {
  value: number | undefined;
  layer: Layer;
  name: string;
}

/**
 * Chi sta sopra a un punto della gerarchia, dal più vicino al globale.
 *
 * Un week template non ha un solo genitore: dipende da quale zona lo segue e
 * in quale scenario. Qui si mostra la catena *tipica* — quella dello scenario
 * attivo, e della prima zona che ci passa — perché è quella che l'utente sta
 * guardando mentre programma. La risoluzione vera la fa il backend, zona per
 * zona, e il pannello la rilegge dal runtime.
 */
export function ancestors(program: Program, scope: Scope): Holder[] {
  const globalHolder: Holder = {
    layer: "global",
    id: "",
    name: "Globale",
    setpoints: program.global_setpoints,
  };
  const active = program.scenarios[program.active_scenario];
  const scenarioHolder: Holder[] = active
    ? [
        {
          layer: "scenario",
          id: active.id,
          name: active.name,
          setpoints: active.setpoints,
        },
      ]
    : [];

  switch (scope.layer) {
    case "global":
      return [];
    case "scenario":
      return [globalHolder];
    case "zone":
      return [...scenarioHolder, globalHolder];
    case "week_template": {
      const zoneId = active
        ? Object.entries(active.zones).find(
            ([, weekId]) => weekId === scope.id,
          )?.[0]
        : undefined;
      const zone = zoneId ? program.zones[zoneId] : undefined;
      return zone
        ? [
            { layer: "zone", id: zone.id, name: zone.name, setpoints: zone.setpoints },
            ...scenarioHolder,
            globalHolder,
          ]
        : [...scenarioHolder, globalHolder];
    }
    case "day_template": {
      const week = Object.values(program.week_templates).find((candidate) =>
        Object.values(candidate.days).includes(scope.id),
      );
      if (!week) return [...scenarioHolder, globalHolder];
      return [
        {
          layer: "week_template",
          id: week.id,
          name: week.name,
          setpoints: week.setpoints,
        },
        ...ancestors(program, { layer: "week_template", id: week.id }),
      ];
    }
    default:
      return [globalHolder];
  }
}

/** Valore che un punto della gerarchia erediterebbe, e da chi. */
export function inherited(
  program: Program,
  scope: Scope,
  level: LevelId,
): Inherited {
  for (const holder of ancestors(program, scope)) {
    const value = holder.setpoints[level];
    if (value !== undefined) {
      return { value, layer: holder.layer, name: holder.name };
    }
  }
  return { value: undefined, layer: "none", name: "nessuno" };
}

/** Tabella di setpoint di un punto della gerarchia. */
export function setpointsOf(program: Program, scope: Scope): Setpoints {
  switch (scope.layer) {
    case "scenario":
      return program.scenarios[scope.id]?.setpoints ?? {};
    case "zone":
      return program.zones[scope.id]?.setpoints ?? {};
    case "week_template":
      return program.week_templates[scope.id]?.setpoints ?? {};
    case "day_template":
      return program.day_templates[scope.id]?.setpoints ?? {};
    default:
      return program.global_setpoints;
  }
}

/** Quanti setpoint propri dichiara un elemento: serve a segnalarlo negli elenchi. */
export function ownSetpointCount(setpoints: Setpoints): number {
  return Object.keys(setpoints).length;
}

/** Settimana tipo che una zona segue nello scenario attivo. */
export function weekTemplateForZone(
  program: Program,
  zoneId: string,
): string | null {
  return program.scenarios[program.active_scenario]?.zones[zoneId] ?? null;
}

// --- Formattazione ----------------------------------------------------------

/** Identificatore tecnico ricavato da un nome scritto a mano. */
export function slugify(name: string): string {
  const slug = name
    .normalize("NFD")
    // Toglie i segni diacritici, così "Città" diventa "citta" e non "citt_".
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return slug || "nuovo";
}

/** Primo id libero della forma `base`, `base_2`, `base_3`… */
export function freeId(existing: Record<string, unknown>, base: string): string {
  if (!(base in existing)) return base;
  let suffix = 2;
  while (`${base}_${suffix}` in existing) suffix += 1;
  return `${base}_${suffix}`;
}

export function formatTemp(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${value.toFixed(1)} °C`;
}

/** Giornate tipo in ordine alfabetico, per i menù. */
export function sortedDayTemplates(program: Program): DayTemplate[] {
  return Object.values(program.day_templates).sort((a, b) =>
    a.name.localeCompare(b.name, "it"),
  );
}

/** Settimane tipo in ordine alfabetico, per i menù. */
export function sortedWeekTemplates(program: Program): WeekTemplate[] {
  return Object.values(program.week_templates).sort((a, b) =>
    a.name.localeCompare(b.name, "it"),
  );
}
