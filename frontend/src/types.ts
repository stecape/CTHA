// Specchio TypeScript del modello di `models.py` e dello snapshot di
// `websocket.py`. Le chiavi dei dizionari passano da JSON, quindi i giorni
// della settimana arrivano come stringhe ("0"…"6") anche se nel modello Python
// sono interi.
//
// I livelli di temperatura non sono più un'unione chiusa: si creano e si
// eliminano dal pannello, quindi qui sono id opachi e il loro elenco arriva
// col programma.

export type LevelId = string;

/** I cinque punti della gerarchia dei setpoint, più «nessuno». */
export type Layer =
  | "day_template"
  | "week_template"
  | "zone"
  | "scenario"
  | "global"
  | "none";

export type OverrideSource = "ha" | "external" | "hardware";
export type Policy =
  | "next_slot"
  | "duration"
  | "until_scenario_change"
  | "sticky";

/** Livello → °C. Un livello assente eredita da chi sta sopra. */
export type Setpoints = Record<LevelId, number>;

/** Un punto della gerarchia: il livello e, se non è il globale, quale elemento. */
export interface Scope {
  layer: Layer;
  id: string;
}

export interface TemperatureLevel {
  id: LevelId;
  name: string;
  /** Carattere che rappresenta il livello dentro i day template. */
  char: string;
  color: string;
}

export interface DayTemplate {
  id: string;
  name: string;
  /** 48 caratteri: quello di un livello, oppure "-" per ereditare. */
  slots: string;
  setpoints: Setpoints;
}

export interface WeekTemplate {
  id: string;
  name: string;
  /** giorno ("0" = lunedì) → id della giornata tipo. */
  days: Record<string, string>;
  setpoints: Setpoints;
}

export interface Scenario {
  id: string;
  name: string;
  /** zona → settimana tipo che segue in questo scenario. */
  zones: Record<string, string>;
  setpoints: Setpoints;
}

export interface Zone {
  id: string;
  name: string;
  setpoints: Setpoints;
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
  levels: Record<LevelId, TemperatureLevel>;
  global_setpoints: Setpoints;
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
  level: LevelId | null;
  source: Layer;
  scheduled: number | null;
  target: number | null;
  week_template: string | null;
  day_template: string | null;
  slot: number;
  override: Override | null;
}

export interface Meta {
  /** Gerarchia dal più specifico al più generale, come in `resolve.py`. */
  layers: Layer[];
  policies: Policy[];
  slots_per_day: number;
  slot_minutes: number;
  inherit_char: string;
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
