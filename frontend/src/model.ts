// Funzioni pure sul modello: nessun React, nessun Home Assistant.
//
// Alcune duplicano ciò che fa `program.py` — le usanze di un template, il
// risultato di una pennellata. La duplicazione è voluta e serve a una cosa
// sola: mostrare l'effetto di un'azione *prima* del giro attraverso il
// backend. La verità resta il backend, che rifiuta ciò che non è ammissibile;
// qui si disegna soltanto.

import type { DayTemplate, Level, Program, Zone } from "./types";

export const LEVELS: Level[] = ["comfort", "eco", "antifreeze"];

export const LEVEL_LABEL: Record<Level, string> = {
  comfort: "Comfort",
  eco: "Eco",
  antifreeze: "Antigelo",
};

export const CHAR_BY_LEVEL: Record<Level, string> = {
  comfort: "c",
  eco: "e",
  antifreeze: "a",
};

export const INHERIT_CHAR = "-";

const LEVEL_BY_CHAR: Record<string, Level> = {
  c: "comfort",
  e: "eco",
  a: "antifreeze",
};

export const SLOTS_PER_DAY = 48;

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

/** Livello dello slot, o `null` se eredita dal globale. */
export function levelAt(slots: string, slot: number): Level | null {
  return LEVEL_BY_CHAR[slots[slot] ?? INHERIT_CHAR] ?? null;
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
  level: Level | null,
): string {
  const [from, to] = start <= end ? [start, end] : [end, start];
  const char = level === null ? INHERIT_CHAR : CHAR_BY_LEVEL[level];
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
  kind: "scenario" | "zone";
  id: string;
  name: string;
}

/** Scenari e zone che seguono una settimana tipo. */
export function weekTemplateUsages(
  program: Program,
  templateId: string,
): WeekUsage[] {
  return [
    ...Object.values(program.scenarios)
      .filter((scenario) => scenario.week_template === templateId)
      .map((scenario) => ({
        kind: "scenario" as const,
        id: scenario.id,
        name: scenario.name,
      })),
    ...Object.values(program.zones)
      .filter((zone) => zone.week_template === templateId)
      .map((zone) => ({ kind: "zone" as const, id: zone.id, name: zone.name })),
  ];
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

/** Setpoint effettivo di una zona per un livello, con la sua provenienza. */
export function effectiveSetpoint(
  program: Program,
  zone: Zone,
  level: Level,
): { value: number | undefined; inherited: boolean } {
  const own = zone.setpoints[level];
  if (own !== undefined && own !== null) {
    return { value: own, inherited: false };
  }
  return { value: program.global_setpoints[level], inherited: true };
}

/** Settimana tipo seguita dalla zona: la propria, altrimenti quella attiva. */
export function weekTemplateForZone(program: Program, zone: Zone): string | null {
  if (zone.week_template) return zone.week_template;
  return program.scenarios[program.active_scenario]?.week_template ?? null;
}

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

export function formatOffset(value: number): string {
  if (value === 0) return "0 °C";
  return `${value > 0 ? "+" : "−"}${Math.abs(value).toFixed(1)} °C`;
}

/** Giornate tipo in ordine alfabetico, per i menù. */
export function sortedTemplates(program: Program): DayTemplate[] {
  return Object.values(program.day_templates).sort((a, b) =>
    a.name.localeCompare(b.name, "it"),
  );
}
