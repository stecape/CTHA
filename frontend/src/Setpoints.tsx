// Le temperature si modificano sull'istanza che le sovrascrive.
//
// Un editor unico con un menù «scegli il punto della gerarchia» sarebbe più
// compatto, ma direbbe la cosa sbagliata: le sovrascritture *appartengono*
// all'elemento — due settimane tipo hanno temperature diverse perché sono due
// settimane tipo, non perché qualcuno ha cambiato voce in un menù. Quindi il
// pulsante sta accanto all'elemento, ovunque l'elemento compaia, e apre sempre
// questa stessa finestra.
//
// La finestra mostra tre cose per livello, e servono tutte: il valore proprio
// (vuoto = eredita), quello che erediterebbe e da chi, e quello che ne risulta.
// Con cinque livelli di gerarchia, un numero senza provenienza è inspiegabile.

import { useState } from "react";

import { api } from "./api";
import {
  LAYER_LABEL,
  formatTemp,
  inherited,
  levels,
  ownSetpointCount,
  setpointsOf,
} from "./model";
import type { Layer, Meta, Program, Run, Scope } from "./types";
import { Modal, NumberField } from "./ui";

/** Cosa significano le temperature scritte su ciascun tipo di elemento. */
const LAYER_HINT: Record<Layer, string> = {
  global: "È la radice della gerarchia: ogni livello deve avere un valore, e non può ereditare da nessuno.",
  scenario:
    "Valgono per tutte le zone di questo scenario che non dicono diversamente. Le sovrascrivono la zona, la settimana tipo e la giornata tipo.",
  zone: "Valgono per questa zona in tutti gli scenari. Le sovrascrivono la settimana tipo e la giornata tipo che la zona sta seguendo.",
  week_template:
    "Valgono per ogni zona che segue questa settimana tipo, in qualunque scenario. Le sovrascrive la giornata tipo del giorno.",
  day_template:
    "Valgono per ogni zona che in quel giorno segue questa giornata tipo. È il livello più specifico: batte tutti gli altri.",
  none: "",
};

/** Pulsante che apre le temperature di un elemento, col numero di quelle proprie. */
export function SetpointsButton({
  program,
  meta,
  scope,
  name,
  run,
  label = "Temperature",
}: {
  program: Program;
  meta: Meta;
  scope: Scope;
  name: string;
  run: Run;
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const own = ownSetpointCount(setpointsOf(program, scope));

  return (
    <>
      <button
        className="btn small"
        aria-pressed={own > 0}
        title={
          own > 0
            ? `${own} temperature proprie: sovrascrivono quelle ereditate`
            : "Nessuna temperatura propria: eredita tutto"
        }
        onClick={() => setOpen(true)}
      >
        {label}
        {own > 0 && <span className="badge">{own}</span>}
      </button>

      {open && (
        <SetpointsModal
          program={program}
          meta={meta}
          scope={scope}
          name={name}
          run={run}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}

export function SetpointsModal({
  program,
  meta,
  scope,
  name,
  run,
  onClose,
}: {
  program: Program;
  meta: Meta;
  scope: Scope;
  name: string;
  run: Run;
  onClose: () => void;
}) {
  const isRoot = scope.layer === "global";
  // Un template non ha un solo genitore: dipende da quale zona lo segue e in
  // quale scenario. La colonna «se eredita» mostra la catena dello scenario
  // attivo, ed è meglio dirlo che lasciarlo intuire.
  const ambiguous =
    scope.layer === "week_template" || scope.layer === "day_template";

  return (
    <Modal
      title={`Temperature — ${name}`}
      onClose={onClose}
      actions={
        <button className="btn primary" onClick={onClose}>
          Chiudi
        </button>
      }
    >
      <p className="hint">{LAYER_HINT[scope.layer]}</p>
      {!isRoot && (
        <p className="hint">
          Un campo vuoto eredita. Svuotarlo è il modo di tornare a ereditare.
        </p>
      )}

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
          {levels(program).map((level) => {
            const own = setpointsOf(program, scope)[level.id] ?? null;
            const from = inherited(program, scope, level.id);
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
                <td className={own === null ? "inherited" : undefined}>
                  <NumberField
                    value={own}
                    min={meta.min_temp}
                    max={meta.max_temp}
                    step={meta.temp_step}
                    placeholder={
                      from.value === undefined ? "—" : String(from.value)
                    }
                    title={
                      isRoot
                        ? "La radice della gerarchia: non può restare vuota"
                        : "Vuoto significa: eredita da chi sta sopra"
                    }
                    onCommit={(next) => {
                      if (next === null && isRoot) return;
                      void run((hass) =>
                        api.setSetpoint(hass, scope, level.id, next),
                      );
                    }}
                  />
                </td>
                <td className="hint">
                  {isRoot
                    ? "è la radice"
                    : from.value === undefined
                      ? "nessuno la definisce"
                      : `${formatTemp(from.value)} dal ${LAYER_LABEL[from.layer]} «${from.name}»`}
                </td>
                <td>
                  <strong>{formatTemp(own ?? from.value)}</strong>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {ambiguous && (
        <p className="hint">
          «Se eredita» segue la catena dello scenario attivo: un template usato
          da zone diverse eredita da ciascuna di esse.
        </p>
      )}
    </Modal>
  );
}
