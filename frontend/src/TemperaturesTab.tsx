// Asse termico: quanti gradi vale un livello, e in quale punto della gerarchia.
//
// Due cose che questa vista deve rendere visibili, e sono la ragione per cui è
// fatta così:
//
// * i livelli sono dati, non tre costanti — si creano, si rinominano, si
//   ricolorano, si eliminano quando nessuna giornata tipo li dipinge più;
// * un campo vuoto non è "zero gradi": è "eredita", e accanto mostra il valore
//   che eredita e da chi. Svuotarlo è il modo di tornare a ereditare.

import { useState } from "react";

import { api } from "./api";
import {
  GLOBAL_SCOPE,
  LAYER_LABEL,
  formatTemp,
  freeId,
  inherited,
  levelUsages,
  levels,
  setpointsOf,
  slugify,
  sortedDayTemplates,
  sortedWeekTemplates,
} from "./model";
import type { Layer, Program, Run, Scope, Snapshot } from "./types";
import { Card, NumberField, PromptModal } from "./ui";

// Dal più generale al più specifico: è l'ordine in cui la gerarchia si legge,
// anche se `resolve.py` la percorre al contrario.
const SCOPE_LAYERS: Layer[] = [
  "global",
  "scenario",
  "zone",
  "week_template",
  "day_template",
];

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
  const [scope, setScope] = useState<Scope>(GLOBAL_SCOPE);

  const palette = levels(program);
  const choices = scopeChoices(program, scope.layer);
  // L'elemento scelto può sparire: template eliminato, zona rimossa.
  const current: Scope =
    scope.layer === "global" || choices.some((choice) => choice.id === scope.id)
      ? scope
      : { layer: scope.layer, id: choices[0]?.id ?? "" };
  const editable = current.layer === "global" || current.id !== "";
  const own = editable ? setpointsOf(program, current) : {};

  return (
    <>
      <Card
        title="Livelli di temperatura"
        hint="Alta, media, bassa e antigelo sono solo quelli di partenza: se ne creano quanti servono. Il colore è quello con cui il livello compare nella griglia."
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
        title="Gerarchia delle temperature"
        hint="Globale → scenario → zona → settimana tipo → giornata tipo. Chi sta più in basso sovrascrive; chi non dice nulla eredita da chi sta sopra."
        actions={
          <>
            <label className="field">
              Punto della gerarchia
              <select
                value={current.layer}
                onChange={(event) => {
                  const layer = event.target.value as Layer;
                  setScope({
                    layer,
                    id: scopeChoices(program, layer)[0]?.id ?? "",
                  });
                }}
              >
                {SCOPE_LAYERS.map((layer) => (
                  <option key={layer} value={layer}>
                    {LAYER_LABEL[layer]}
                  </option>
                ))}
              </select>
            </label>
            {current.layer !== "global" && (
              <label className="field">
                Elemento
                <select
                  value={current.id}
                  onChange={(event) =>
                    setScope({ layer: current.layer, id: event.target.value })
                  }
                >
                  {choices.length === 0 && <option value="">— nessuno —</option>}
                  {choices.map((choice) => (
                    <option key={choice.id} value={choice.id}>
                      {choice.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </>
        }
      >
        {!editable ? (
          <p className="hint">
            Non c'è nessun elemento di tipo «{LAYER_LABEL[current.layer]}» su cui
            scrivere temperature.
          </p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Livello</th>
                <th>Temperatura</th>
                <th>Se eredita</th>
                <th>In vigore</th>
              </tr>
            </thead>
            <tbody>
              {palette.map((level) => {
                const value = own[level.id] ?? null;
                const from = inherited(program, current, level.id);
                return (
                  <tr key={level.id}>
                    <td>
                      <div className="cell-stack">
                        <span
                          className="swatch"
                          style={{ background: level.color }}
                        />
                        {level.name}
                      </div>
                    </td>
                    <td className={value === null ? "inherited" : undefined}>
                      <NumberField
                        value={value}
                        min={meta.min_temp}
                        max={meta.max_temp}
                        step={meta.temp_step}
                        placeholder={
                          from.value === undefined ? "—" : String(from.value)
                        }
                        title={
                          current.layer === "global"
                            ? "La radice della gerarchia: non può restare vuota"
                            : "Vuoto significa: eredita da chi sta sopra"
                        }
                        onCommit={(next) => {
                          if (next === null && current.layer === "global") return;
                          void run((hass) =>
                            api.setSetpoint(hass, current, level.id, next),
                          );
                        }}
                      />
                    </td>
                    <td className="hint">
                      {current.layer === "global"
                        ? "è la radice"
                        : from.value === undefined
                          ? "nessuno la definisce"
                          : `${formatTemp(from.value)} dal ${LAYER_LABEL[from.layer]} «${from.name}»`}
                    </td>
                    <td>
                      <strong>{formatTemp(value ?? from.value)}</strong>
                    </td>
                  </tr>
                );
              })}
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

/** Elementi su cui si possono scrivere temperature, per ciascun tipo. */
function scopeChoices(
  program: Program,
  layer: Layer,
): { id: string; name: string }[] {
  switch (layer) {
    case "scenario":
      return Object.values(program.scenarios).map((item) => ({
        id: item.id,
        name: item.name,
      }));
    case "zone":
      return Object.values(program.zones).map((item) => ({
        id: item.id,
        name: item.name,
      }));
    case "week_template":
      return sortedWeekTemplates(program).map((item) => ({
        id: item.id,
        name: item.name,
      }));
    case "day_template":
      return sortedDayTemplates(program).map((item) => ({
        id: item.id,
        name: item.name,
      }));
    default:
      return [];
  }
}
