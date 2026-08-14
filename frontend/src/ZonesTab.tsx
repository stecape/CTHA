// Cosa sta succedendo adesso, zona per zona.
//
// La riga che conta è "target": dice se la zona sta seguendo il programma o un
// override, e da quale livello della gerarchia esce il numero. Un setpoint che
// non si sa da dove viene è la cosa che rende impossibile fidarsi di un
// cronotermostato — e con cinque livelli di ereditarietà lo diventerebbe in
// fretta, se non fosse scritto.

import { useState } from "react";

import { api } from "./api";
import { LAYER_LABEL, formatTemp, sortedWeekTemplates } from "./model";
import { SetpointsButton } from "./Setpoints";
import type { HomeAssistant, Override, Policy, Run, Snapshot } from "./types";
import { Card, NumberField } from "./ui";

const POLICY_LABEL: Record<Policy, string> = {
  next_slot: "fine della mezz'ora",
  duration: "un'ora",
  until_scenario_change: "cambio scenario",
  sticky: "finché non lo tolgo",
};

const OVERRIDE_SOURCE_LABEL: Record<string, string> = {
  ha: "impostato da Home Assistant",
  external: "arrivato da app o centralina",
  hardware: "manopola del termostato",
};

export function ZonesTab({
  snapshot,
  hass,
  run,
}: {
  snapshot: Snapshot;
  hass: HomeAssistant;
  run: Run;
}) {
  const { program, runtime, meta } = snapshot;
  const zones = Object.values(program.zones);
  const scenario = program.scenarios[program.active_scenario];
  const weeks = sortedWeekTemplates(program);

  if (zones.length === 0) {
    return (
      <Card title="Zone">
        <p className="hint">
          Nessuna zona: aggiungine una da Impostazioni → Dispositivi e servizi.
        </p>
      </Card>
    );
  }

  return (
    <Card
      title="Zone"
      hint="Temperatura misurata, setpoint applicato e da quale livello della gerarchia arriva. Un override scavalca il programma finché non scade."
    >
      <div className="zones">
        {zones.map((zone) => {
          const state = runtime[zone.id];
          const entity = state?.entity_id
            ? hass.states[state.entity_id]
            : undefined;
          const current = entity?.attributes["current_temperature"];
          const level = state?.level ? program.levels[state.level] : undefined;

          return (
            <div className="zone" key={zone.id}>
              <div className="zone-head">
                <strong>{zone.name}</strong>
                <span className="reading">
                  {typeof current === "number" ? formatTemp(current) : "—"}
                </span>
              </div>

              <div className="rows">
                <div className="row">
                  <span className="k">Target</span>
                  <span>{formatTemp(state?.target)}</span>
                </div>
                <div className="row">
                  <span className="k">Livello</span>
                  <span>
                    {level ? (
                      <span className="cell-stack">
                        <span
                          className="swatch"
                          style={{ background: level.color }}
                        />
                        {level.name}
                      </span>
                    ) : (
                      "—"
                    )}
                  </span>
                </div>
                {state?.source && state.source !== "none" && (
                  <div className="row">
                    <span className="k">Temperatura da</span>
                    <span className="badge plain">
                      {LAYER_LABEL[state.source]}
                    </span>
                  </div>
                )}
                <div className="row">
                  <span className="k">Programma</span>
                  <span>
                    {state?.week_template
                      ? (program.week_templates[state.week_template]?.name ??
                        state.week_template)
                      : "non programmata"}
                    {state?.day_template && (
                      <>
                        {" · oggi "}
                        {program.day_templates[state.day_template]?.name ??
                          state.day_template}
                      </>
                    )}
                  </span>
                </div>
              </div>

              {state?.override ? (
                <OverrideRow
                  override={state.override}
                  onClear={() =>
                    void run((hass) => api.clearOverride(hass, zone.id))
                  }
                />
              ) : (
                <SetOverride
                  suggested={state?.target ?? meta.min_temp}
                  min={meta.min_temp}
                  max={meta.max_temp}
                  step={meta.temp_step}
                  onSet={(temperature, policy) =>
                    void run((hass) =>
                      api.setOverride(hass, zone.id, temperature, policy),
                    )
                  }
                />
              )}

              <div className="item-actions">
                <SetpointsButton
                  program={program}
                  meta={meta}
                  scope={{ layer: "zone", id: zone.id }}
                  name={`zona «${zone.name}»`}
                  run={run}
                />
              </div>

              <label className="field">
                Settimana tipo in «{scenario?.name ?? program.active_scenario}»
                <select
                  value={scenario?.zones[zone.id] ?? ""}
                  onChange={(event) =>
                    void run((hass) =>
                      api.setZoneWeekTemplate(
                        hass,
                        zone.id,
                        event.target.value || null,
                      ),
                    )
                  }
                >
                  <option value="">— non programmata —</option>
                  {weeks.map((template) => (
                    <option key={template.id} value={template.id}>
                      {template.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function OverrideRow({
  override,
  onClear,
}: {
  override: Override;
  onClear: () => void;
}) {
  const expires = override.expires_at
    ? new Date(override.expires_at).toLocaleString("it-IT", {
        weekday: "short",
        hour: "2-digit",
        minute: "2-digit",
      })
    : null;

  return (
    <div className="rows">
      <div className="row">
        <span className="k">Override</span>
        <span>
          {formatTemp(override.temperature)}{" "}
          <span className="badge">
            {OVERRIDE_SOURCE_LABEL[override.source] ?? override.source}
          </span>
        </span>
      </div>
      <div className="row">
        <span className="k">Scade</span>
        <span>
          {override.source === "hardware"
            ? "mai: va tolto dalla manopola"
            : (expires ?? POLICY_LABEL[override.policy])}
        </span>
      </div>
      <div className="item-actions">
        <button
          className="btn small"
          disabled={override.source === "hardware"}
          title={
            override.source === "hardware"
              ? "Nessun comando software può annullare la manopola fisica"
              : undefined
          }
          onClick={onClear}
        >
          Torna al programma
        </button>
      </div>
    </div>
  );
}

function SetOverride({
  suggested,
  min,
  max,
  step,
  onSet,
}: {
  suggested: number;
  min: number;
  max: number;
  step: number;
  onSet: (temperature: number, policy: Policy) => void;
}) {
  const [temperature, setTemperature] = useState<number | null>(suggested);
  const [policy, setPolicy] = useState<Policy>("next_slot");

  return (
    <div className="item-actions">
      <NumberField
        value={temperature}
        min={min}
        max={max}
        step={step}
        onCommit={setTemperature}
      />
      <select
        value={policy}
        onChange={(event) => setPolicy(event.target.value as Policy)}
      >
        {(Object.keys(POLICY_LABEL) as Policy[]).map((option) => (
          <option key={option} value={option}>
            {POLICY_LABEL[option]}
          </option>
        ))}
      </select>
      <button
        className="btn small"
        disabled={temperature === null}
        onClick={() => temperature !== null && onSet(temperature, policy)}
      >
        Forza
      </button>
    </div>
  );
}
