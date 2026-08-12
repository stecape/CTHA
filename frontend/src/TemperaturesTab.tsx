// Asse termico: quanti gradi vale un livello, e per chi.
//
// L'ereditarietà è la cosa che questa vista deve rendere visibile. Un campo
// vuoto non è "zero gradi": è "eredita", e mostra in grigio il valore che
// eredita. Svuotarlo è il modo di tornare a ereditare.

import { useState } from "react";

import { api } from "./api";
import { LEVELS, LEVEL_LABEL, formatOffset, freeId, slugify } from "./model";
import type { Run, Snapshot } from "./types";
import { Card, NumberField, PromptModal } from "./ui";

export function TemperaturesTab({
  snapshot,
  run,
}: {
  snapshot: Snapshot;
  run: Run;
}) {
  const { program, meta } = snapshot;
  const [newScenario, setNewScenario] = useState(false);
  const zones = Object.values(program.zones);
  const active = program.scenarios[program.active_scenario];

  return (
    <>
      <Card
        title="Setpoint globali"
        hint="La radice dell'ereditarietà: valgono per ogni zona che non dice diversamente."
      >
        <div className="item-actions">
          {LEVELS.map((level) => (
            <label className="field" key={level}>
              {LEVEL_LABEL[level]}
              <NumberField
                value={program.global_setpoints[level] ?? null}
                min={meta.min_temp}
                max={meta.max_temp}
                step={meta.temp_step}
                onCommit={(value) => {
                  if (value === null) return; // il globale non può ereditare
                  void run((hass) => api.setSetpoint(hass, level, value));
                }}
              />
            </label>
          ))}
        </div>
      </Card>

      <Card
        title="Setpoint per zona"
        hint="Un campo vuoto eredita dal globale, e mostra in grigio il valore ereditato. Svuotarlo è il modo di tornare a ereditare."
      >
        {zones.length === 0 ? (
          <p className="hint">Nessuna zona configurata.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Zona</th>
                {LEVELS.map((level) => (
                  <th key={level}>{LEVEL_LABEL[level]}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {zones.map((zone) => (
                <tr key={zone.id}>
                  <td>{zone.name}</td>
                  {LEVELS.map((level) => {
                    const own = zone.setpoints[level] ?? null;
                    return (
                      <td
                        key={level}
                        className={own === null ? "inherited" : undefined}
                      >
                        <NumberField
                          value={own}
                          min={meta.min_temp}
                          max={meta.max_temp}
                          step={meta.temp_step}
                          placeholder={String(program.global_setpoints[level])}
                          title={
                            own === null
                              ? "Ereditato dal setpoint globale"
                              : "Valore proprio della zona"
                          }
                          onCommit={(value) =>
                            void run((hass) =>
                              api.setSetpoint(hass, level, value, zone.id),
                            )
                          }
                        />
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Card
        title="Scenari"
        hint="Uno scenario non cambia i livelli del programma: sposta le temperature che ne derivano."
        actions={
          <button className="btn" onClick={() => setNewScenario(true)}>
            + Nuovo
          </button>
        }
      >
        <div className="list">
          {Object.values(program.scenarios).map((scenario) => {
            const isActive = scenario.id === program.active_scenario;
            return (
              <div className="item" key={scenario.id}>
                <div className="item-main">
                  <strong>
                    {scenario.name}{" "}
                    {isActive && <span className="badge">attivo</span>}
                  </strong>
                  <span className="hint">
                    segue «
                    {program.week_templates[scenario.week_template]?.name ??
                      scenario.week_template}
                    » · offset {formatOffset(scenario.offset)}
                  </span>
                </div>
                <div className="item-actions">
                  <label className="field">
                    Settimana
                    <select
                      value={scenario.week_template}
                      onChange={(event) =>
                        void run((hass) =>
                          api.setScenario(hass, scenario.id, {
                            week_template: event.target.value,
                          }),
                        )
                      }
                    >
                      {Object.values(program.week_templates).map((template) => (
                        <option key={template.id} value={template.id}>
                          {template.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="field">
                    Offset
                    <NumberField
                      value={scenario.offset}
                      step={0.5}
                      min={-15}
                      max={15}
                      onCommit={(value) =>
                        void run((hass) =>
                          api.setScenario(hass, scenario.id, {
                            offset: value ?? 0,
                          }),
                        )
                      }
                    />
                  </label>
                  <button
                    className="btn small"
                    disabled={isActive}
                    onClick={() =>
                      void run((hass) => api.activateScenario(hass, scenario.id))
                    }
                  >
                    Attiva
                  </button>
                  <button
                    className="btn small danger"
                    disabled={isActive || Object.keys(program.scenarios).length === 1}
                    title={
                      isActive
                        ? "Attiva prima un altro scenario"
                        : "Deve restare almeno uno scenario"
                    }
                    onClick={() =>
                      void run((hass) => api.deleteScenario(hass, scenario.id))
                    }
                  >
                    Elimina
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </Card>

      {active && zones.length > 0 && (
        <Card
          title={`Eccezioni di zona — ${active.name}`}
          hint="Una zona con un offset proprio ignora quello generale dello scenario. Campo vuoto: segue il generale."
        >
          <table>
            <thead>
              <tr>
                <th>Zona</th>
                <th>Offset</th>
                <th>Applicato</th>
              </tr>
            </thead>
            <tbody>
              {zones.map((zone) => {
                const own = active.zone_offsets[zone.id];
                return (
                  <tr key={zone.id}>
                    <td>{zone.name}</td>
                    <td className={own === undefined ? "inherited" : undefined}>
                      <NumberField
                        value={own ?? null}
                        step={0.5}
                        min={-15}
                        max={15}
                        placeholder={String(active.offset)}
                        onCommit={(value) =>
                          void run((hass) =>
                            api.setScenario(hass, active.id, {
                              zone_offsets: { [zone.id]: value },
                            }),
                          )
                        }
                      />
                    </td>
                    <td>{formatOffset(own ?? active.offset)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}

      {newScenario && (
        <PromptModal
          title="Nuovo scenario"
          label="Nome"
          confirmLabel="Crea"
          onClose={() => setNewScenario(false)}
          onConfirm={(name) =>
            void run((hass) =>
              api.setScenario(
                hass,
                freeId(program.scenarios, slugify(name)),
                { name },
              ),
            )
          }
        />
      )}
    </>
  );
}
