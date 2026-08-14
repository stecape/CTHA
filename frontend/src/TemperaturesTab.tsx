// I livelli di temperatura e la radice della gerarchia.
//
// Le sovrascritture *non* si modificano da qui: appartengono all'elemento che
// le dichiara — una settimana tipo, una zona, uno scenario — e si toccano lì,
// col pulsante «Temperature» accanto all'elemento. Qui restano le due cose che
// non appartengono a nessun elemento in particolare: quali livelli esistono, e
// quanto valgono alla radice.
//
// L'elenco in fondo è di sola lettura per la parte informativa — dice *dove*
// qualcuno ha scritto una temperatura, che altrimenti si scoprirebbe solo
// aprendo gli elementi uno per uno — ma i pulsanti portano allo stesso editor
// che si apre dall'elemento, perché è lo stesso dato.

import { useState } from "react";

import { api } from "./api";
import {
  GLOBAL_SCOPE,
  LAYER_LABEL,
  formatTemp,
  freeId,
  levelUsages,
  levels,
  slugify,
  writtenSetpoints,
} from "./model";
import { SetpointsButton } from "./Setpoints";
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
  const [newLevel, setNewLevel] = useState(false);
  const [rename, setRename] = useState<{ id: string; name: string } | null>(null);

  const palette = levels(program);
  const written = writtenSetpoints(program);

  return (
    <>
      <Card
        title="Livelli di temperatura"
        hint="Alta, media, bassa e antigelo sono solo quelli di partenza: se ne creano quanti servono. Il setpoint globale è la radice della gerarchia — vale per chiunque non dica diversamente, e non può restare vuoto."
        actions={
          <button className="btn" onClick={() => setNewLevel(true)}>
            + Nuovo
          </button>
        }
      >
        <table>
          <thead>
            <tr>
              <th>Livello</th>
              <th>Carattere</th>
              <th>Setpoint globale</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {palette.map((level) => {
              const usages = levelUsages(program, level.id);
              const painted = usages.reduce(
                (total, usage) => total + usage.slots,
                0,
              );
              return (
                <tr key={level.id}>
                  <td>
                    <div className="cell-stack">
                      <input
                        type="color"
                        className="color"
                        defaultValue={level.color}
                        title="Colore del livello nella griglia"
                        onBlur={(event) =>
                          void run((hass) =>
                            api.setLevel(hass, level.id, {
                              color: event.target.value,
                            }),
                          )
                        }
                      />
                      <span>{level.name}</span>
                    </div>
                  </td>
                  <td>
                    <span className="badge plain" title="Carattere nei day template">
                      {level.char}
                    </span>
                  </td>
                  <td>
                    <NumberField
                      value={program.global_setpoints[level.id] ?? null}
                      min={meta.min_temp}
                      max={meta.max_temp}
                      step={meta.temp_step}
                      title="La radice della gerarchia: non può restare vuota"
                      onCommit={(value) => {
                        if (value === null) return;
                        void run((hass) =>
                          api.setSetpoint(hass, GLOBAL_SCOPE, level.id, value),
                        );
                      }}
                    />
                  </td>
                  <td>
                    <div className="item-actions">
                      <button
                        className="btn small"
                        onClick={() =>
                          setRename({ id: level.id, name: level.name })
                        }
                      >
                        Rinomina
                      </button>
                      <button
                        className="btn small danger"
                        disabled={painted > 0 || palette.length === 1}
                        title={
                          painted > 0
                            ? `Dipinto in ${usages
                                .map((usage) => `«${usage.name}» (${usage.slots} slot)`)
                                .join(", ")}`
                            : palette.length === 1
                              ? "Deve restare almeno un livello"
                              : undefined
                        }
                        onClick={() =>
                          void run((hass) => api.deleteLevel(hass, level.id))
                        }
                      >
                        Elimina
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>

      <Card
        title="Sovrascritture"
        hint="Le temperature si scrivono sull'elemento che le sovrascrive, col pulsante «Temperature» accanto a esso: su uno scenario in Scenari, su una zona nella tabella dello scenario o nella sua scheda, su una settimana o una giornata tipo in Programma. Qui si vede solo dove sono state scritte."
      >
        <p className="hierarchy">
          <span className="badge plain">globale</span> →{" "}
          <span className="badge plain">scenario</span> →{" "}
          <span className="badge plain">zona</span> →{" "}
          <span className="badge plain">settimana tipo</span> →{" "}
          <span className="badge plain">giornata tipo</span>
          <span className="hint"> · chi sta più a destra vince</span>
        </p>

        {written.length === 0 ? (
          <p className="hint">
            Nessuna sovrascrittura: ogni zona segue i setpoint globali.
          </p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Dove</th>
                <th>Elemento</th>
                <th>Temperature</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {written.map((entry) => (
                <tr key={`${entry.scope.layer}:${entry.scope.id}`}>
                  <td>
                    <span className="badge plain">
                      {LAYER_LABEL[entry.scope.layer]}
                    </span>
                  </td>
                  <td>{entry.name}</td>
                  <td>
                    {Object.entries(entry.setpoints)
                      .map(
                        ([levelId, value]) =>
                          `${program.levels[levelId]?.name ?? levelId} ${formatTemp(value)}`,
                      )
                      .join(" · ")}
                  </td>
                  <td>
                    <SetpointsButton
                      program={program}
                      meta={meta}
                      scope={entry.scope}
                      name={`${LAYER_LABEL[entry.scope.layer]} «${entry.name}»`}
                      run={run}
                      label="Modifica"
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {newLevel && (
        <PromptModal
          title="Nuovo livello di temperatura"
          label="Nome"
          confirmLabel="Crea"
          onClose={() => setNewLevel(false)}
          onConfirm={(name) =>
            void run((hass) =>
              api.setLevel(hass, freeId(program.levels, slugify(name)), { name }),
            )
          }
        />
      )}

      {rename && (
        <PromptModal
          title="Rinomina livello"
          label="Nome"
          initial={rename.name}
          confirmLabel="Salva"
          onClose={() => setRename(null)}
          onConfirm={(name) =>
            void run((hass) => api.setLevel(hass, rename.id, { name }))
          }
        />
      )}
    </>
  );
}
