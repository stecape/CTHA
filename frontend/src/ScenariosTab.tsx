// Gli scenari: la configurazione delle zone.
//
// Uno scenario non è un'impostazione fra le altre, è *la* tabella zona →
// settimana tipo. Attivarne uno riprogramma tutto l'impianto in un gesto, ed è
// il motivo per cui questa vista mostra la tabella intera e non un riassunto:
// prima di attivare uno scenario si deve poter vedere cosa farà a ogni zona.

import { useState } from "react";

import { api } from "./api";
import {
  freeId,
  ownSetpointCount,
  slugify,
  sortedWeekTemplates,
} from "./model";
import type { Run, Snapshot } from "./types";
import { Card, PromptModal } from "./ui";

type Prompt = { kind: "new" } | { kind: "rename"; id: string; name: string };

export function ScenariosTab({
  snapshot,
  run,
}: {
  snapshot: Snapshot;
  run: Run;
}) {
  const { program } = snapshot;
  const [prompt, setPrompt] = useState<Prompt | null>(null);
  const zones = Object.values(program.zones);
  const weeks = sortedWeekTemplates(program);

  const onPrompt = (value: string) => {
    if (!prompt) return;
    if (prompt.kind === "new") {
      void run((hass) =>
        api.setScenario(hass, freeId(program.scenarios, slugify(value)), {
          name: value,
        }),
      );
    } else {
      void run((hass) => api.setScenario(hass, prompt.id, { name: value }));
    }
  };

  return (
    <>
      <Card
        title="Scenari"
        hint="Uno scenario dice, per ogni zona, quale settimana tipo seguire. Uno scenario nuovo parte dalla configurazione di quello attivo."
        actions={
          <button className="btn" onClick={() => setPrompt({ kind: "new" })}>
            + Nuovo
          </button>
        }
      >
        {zones.length === 0 && (
          <p className="hint">
            Nessuna zona configurata: aggiungine una da Impostazioni →
            Dispositivi e servizi, e comparirà in tutti gli scenari.
          </p>
        )}

        <div className="list">
          {Object.values(program.scenarios).map((scenario) => {
            const isActive = scenario.id === program.active_scenario;
            const own = ownSetpointCount(scenario.setpoints);
            return (
              <div className="item column" key={scenario.id}>
                <div className="item-head">
                  <div className="item-main">
                    <strong>
                      {scenario.name}{" "}
                      {isActive && <span className="badge">attivo</span>}
                      {own > 0 && (
                        <>
                          {" "}
                          <span
                            className="badge"
                            title="Sovrascrive le temperature globali"
                          >
                            {own} temperature proprie
                          </span>
                        </>
                      )}
                    </strong>
                  </div>
                  <div className="item-actions">
                    <button
                      className="btn small"
                      onClick={() =>
                        setPrompt({
                          kind: "rename",
                          id: scenario.id,
                          name: scenario.name,
                        })
                      }
                    >
                      Rinomina
                    </button>
                    <button
                      className="btn small"
                      disabled={isActive}
                      onClick={() =>
                        void run((hass) =>
                          api.activateScenario(hass, scenario.id),
                        )
                      }
                    >
                      Attiva
                    </button>
                    <button
                      className="btn small danger"
                      disabled={
                        isActive || Object.keys(program.scenarios).length === 1
                      }
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

                {zones.length > 0 && (
                  <table>
                    <thead>
                      <tr>
                        <th>Zona</th>
                        <th>Settimana tipo</th>
                      </tr>
                    </thead>
                    <tbody>
                      {zones.map((zone) => {
                        const assigned = scenario.zones[zone.id] ?? "";
                        return (
                          <tr key={zone.id}>
                            <td>{zone.name}</td>
                            <td className={assigned ? undefined : "inherited"}>
                              <select
                                value={assigned}
                                title={
                                  assigned
                                    ? undefined
                                    : "In questo scenario la zona non è programmata"
                                }
                                onChange={(event) =>
                                  void run((hass) =>
                                    api.setZoneWeekTemplate(
                                      hass,
                                      zone.id,
                                      event.target.value || null,
                                      scenario.id,
                                    ),
                                  )
                                }
                              >
                                <option value="">— non programmata —</option>
                                {weeks.map((week) => (
                                  <option key={week.id} value={week.id}>
                                    {week.name}
                                  </option>
                                ))}
                              </select>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                )}
              </div>
            );
          })}
        </div>
      </Card>

      {prompt && (
        <PromptModal
          title={prompt.kind === "new" ? "Nuovo scenario" : "Rinomina scenario"}
          label="Nome"
          initial={prompt.kind === "rename" ? prompt.name : ""}
          confirmLabel={prompt.kind === "new" ? "Crea" : "Salva"}
          onConfirm={onPrompt}
          onClose={() => setPrompt(null)}
        />
      )}
    </>
  );
}
