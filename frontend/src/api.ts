// Ponte verso Home Assistant: lettura via websocket, scrittura via servizi.
//
// I servizi esistono già, validano e fanno rispettare l'integrità
// referenziale: il pannello li chiama invece di avere comandi websocket
// propri, così la logica di scrittura resta in un posto solo.

import type { HomeAssistant, Level, Policy, Snapshot } from "./types";

const DOMAIN = "ctha";

/** Risposta di `duplicate_day_template`: le chiavi sono quelle del servizio. */
export interface DuplicateResponse {
  template_id: string;
  name: string;
  slots: string;
}

/** Si iscrive allo snapshot; il primo arriva subito dopo l'ack. */
export function subscribe(
  hass: HomeAssistant,
  onSnapshot: (snapshot: Snapshot) => void,
): Promise<() => Promise<void>> {
  return hass.connection.subscribeMessage<Snapshot>(onSnapshot, {
    type: `${DOMAIN}/subscribe`,
  });
}

function call(
  hass: HomeAssistant,
  service: string,
  data: Record<string, unknown>,
): Promise<unknown> {
  // I valori assenti si omettono: sugli schemi voluptuous "campo mancante" e
  // "campo a null" non significano la stessa cosa.
  const payload = Object.fromEntries(
    Object.entries(data).filter(([, value]) => value !== undefined),
  );
  return hass.callService(DOMAIN, service, payload);
}

export const api = {
  setOverride(
    hass: HomeAssistant,
    zoneId: string,
    temperature: number,
    policy: Policy = "next_slot",
    duration?: string,
  ) {
    return call(hass, "set_override", {
      zone_id: zoneId,
      temperature,
      policy,
      duration,
    });
  },

  clearOverride(hass: HomeAssistant, zoneId: string) {
    return call(hass, "clear_override", { zone_id: zoneId });
  },

  setDayTemplate(
    hass: HomeAssistant,
    templateId: string,
    fields: { name?: string; slots?: string },
  ) {
    return call(hass, "set_day_template", {
      template_id: templateId,
      ...fields,
    });
  },

  paintSlots(
    hass: HomeAssistant,
    templateId: string,
    start: number,
    end: number,
    level: Level | null,
  ) {
    return call(hass, "paint_slots", {
      template_id: templateId,
      start_slot: start,
      end_slot: end,
      // Livello assente = "torna a ereditare": è la semantica dello schema.
      level: level ?? undefined,
    });
  },

  /** Duplica una giornata tipo; la risposta serve per sapere l'id della copia. */
  async duplicateDayTemplate(
    hass: HomeAssistant,
    templateId: string,
    options: { newId?: string; name?: string; weekTemplate?: string; days?: number[] },
  ): Promise<DuplicateResponse> {
    const result = await hass.callService(
      DOMAIN,
      "duplicate_day_template",
      {
        template_id: templateId,
        ...(options.newId !== undefined ? { new_id: options.newId } : {}),
        ...(options.name !== undefined ? { name: options.name } : {}),
        ...(options.weekTemplate !== undefined
          ? { week_template: options.weekTemplate }
          : {}),
        ...(options.days !== undefined ? { days: options.days } : {}),
      },
      undefined,
      true,
      true,
    );
    return result.response as DuplicateResponse;
  },

  deleteDayTemplate(hass: HomeAssistant, templateId: string) {
    return call(hass, "delete_day_template", { template_id: templateId });
  },

  setWeekTemplate(
    hass: HomeAssistant,
    templateId: string,
    fields: { name?: string; days?: Record<number, string | null> },
  ) {
    return call(hass, "set_week_template", {
      template_id: templateId,
      ...fields,
    });
  },

  deleteWeekTemplate(hass: HomeAssistant, templateId: string) {
    return call(hass, "delete_week_template", { template_id: templateId });
  },

  setScenario(
    hass: HomeAssistant,
    scenarioId: string,
    fields: {
      name?: string;
      week_template?: string;
      offset?: number;
      zone_offsets?: Record<string, number | null>;
    },
  ) {
    return call(hass, "set_scenario", { scenario_id: scenarioId, ...fields });
  },

  deleteScenario(hass: HomeAssistant, scenarioId: string) {
    return call(hass, "delete_scenario", { scenario_id: scenarioId });
  },

  activateScenario(hass: HomeAssistant, scenarioId: string) {
    return call(hass, "activate_scenario", { scenario_id: scenarioId });
  },

  setSetpoint(
    hass: HomeAssistant,
    level: Level,
    temperature: number | null,
    zoneId?: string,
  ) {
    return call(hass, "set_setpoint", {
      level,
      // null è esplicito: sulla zona significa "torna a ereditare".
      temperature,
      zone_id: zoneId,
    });
  },

  setZoneWeekTemplate(
    hass: HomeAssistant,
    zoneId: string,
    templateId: string | null,
  ) {
    return call(hass, "set_zone_week_template", {
      zone_id: zoneId,
      template_id: templateId,
    });
  },
};

/** Messaggio leggibile da un errore di chiamata a servizio. */
export function errorMessage(error: unknown): string {
  if (typeof error === "string") return error;
  if (error && typeof error === "object") {
    const record = error as Record<string, unknown>;
    for (const key of ["message", "error"]) {
      if (typeof record[key] === "string") return record[key] as string;
    }
  }
  return "Operazione non riuscita";
}
