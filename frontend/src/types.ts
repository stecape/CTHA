// Specchio TypeScript del modello di `models.py` e dello snapshot di
// `websocket.py`. Le chiavi dei dizionari passano da JSON, quindi i giorni
// della settimana arrivano come stringhe ("0"…"6") anche se nel modello Python
// sono interi.

export type Level = "comfort" | "eco" | "antifreeze";
export type SetpointSource = "zone" | "global" | "none";
export type OverrideSource = "ha" | "external" | "hardware";
export type Policy =
  | "next_slot"
  | "duration"
  | "until_scenario_change"
  | "sticky";

export interface DayTemplate {
  id: string;
  name: string;
  /** 48 caratteri: c, e, a, oppure "-" per ereditare. */
  slots: string;
}

export interface WeekTemplate {
  id: string;
  name: string;
  /** giorno ("0" = lunedì) → id della giornata tipo. */
  days: Record<string, string>;
}

export interface Scenario {
  id: string;
  name: string;
  week_template: string;
  offset: number;
  zone_offsets: Record<string, number>;
}

export interface Zone {
  id: string;
  name: string;
  /** livello → temperatura; assente o null significa "eredita". */
  setpoints: Partial<Record<Level, number | null>>;
  week_template: string | null;
}

export interface Override {
  zone_id: string;
  temperature: number;
  source: OverrideSource;
  policy: Policy;
  created_at: string | null;
  expires_at: string | null;
  scenario_id: string | null;
}

export interface Program {
  global_setpoints: Record<Level, number>;
  day_templates: Record<string, DayTemplate>;
  week_templates: Record<string, WeekTemplate>;
  scenarios: Record<string, Scenario>;
  zones: Record<string, Zone>;
  overrides: Record<string, Override>;
  active_scenario: string;
}

/** Risoluzione corrente di una zona: non è deducibile dal solo modello. */
export interface ZoneRuntime {
  entity_id: string | null;
  level: Level | null;
  base: number | null;
  source: SetpointSource;
  offset: number;
  scheduled: number | null;
  target: number | null;
  override: Override | null;
}

export interface Meta {
  levels: Level[];
  policies: Policy[];
  slots_per_day: number;
  slot_minutes: number;
  min_temp: number;
  max_temp: number;
  temp_step: number;
}

export interface Snapshot {
  program: Program;
  runtime: Record<string, ZoneRuntime>;
  meta: Meta;
}

/**
 * Esegue una scrittura mostrando l'eventuale errore in cima al pannello.
 *
 * L'esito è esplicito invece che dedotto da un valore nullo: chi chiama deve
 * poter distinguere "riuscito, senza risposta" da "fallito", per esempio per
 * togliere un'anteprima ottimistica che non si avvererà mai.
 */
export type Run = <T>(
  action: (hass: HomeAssistant) => Promise<T>,
) => Promise<{ ok: true; value: T } | { ok: false }>;

// --- Superficie di Home Assistant effettivamente usata dal pannello ---------

export interface HassEntity {
  entity_id: string;
  state: string;
  attributes: Record<string, unknown>;
}

export interface ServiceCallResponse {
  response?: unknown;
}

export interface HomeAssistant {
  states: Record<string, HassEntity>;
  language: string;
  callService(
    domain: string,
    service: string,
    serviceData?: Record<string, unknown>,
    target?: Record<string, unknown>,
    notifyOnError?: boolean,
    returnResponse?: boolean,
  ): Promise<ServiceCallResponse>;
  callWS<T>(msg: Record<string, unknown>): Promise<T>;
  connection: {
    subscribeMessage<T>(
      callback: (message: T) => void,
      subscribeMessage: Record<string, unknown>,
    ): Promise<() => Promise<void>>;
  };
}
