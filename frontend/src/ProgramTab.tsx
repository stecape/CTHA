// Asse temporale: quale livello vale in ogni mezz'ora della settimana.
//
// Il punto delicato non è dipingere, è che una giornata tipo può essere
// condivisa fra più giorni. Dipingere lunedì, quando lunedì usa lo stesso
// template di martedì e mercoledì, cambia anche quelli — silenziosamente, se
// nessuno lo dice. Qui la condivisione si vede prima (badge sulla riga) e si
// decide al momento della pennellata: modificare per tutti, oppure scollegare
// quel giorno su una copia.

import { useEffect, useState } from "react";

import { api } from "./api";
import {
  LEVELS,
  LEVEL_LABEL,
  WEEKDAYS,
  WEEKDAYS_SHORT,
  freeId,
  listDays,
  paintedSlots,
  sharedWith,
} from "./model";
import { Templates } from "./Templates";
import type { Level, Program, Run, Snapshot } from "./types";
import { Card, Modal } from "./ui";
import { WeekGrid } from "./WeekGrid";

interface Conflict {
  weekday: number;
  templateId: string;
  start: number;
  end: number;
  description: string;
}

export function ProgramTab({
  snapshot,
  run,
}: {
  snapshot: Snapshot;
  run: Run;
}) {
  const program = snapshot.program;
  const activeWeek = program.scenarios[program.active_scenario]?.week_template ?? "";

  const [weekId, setWeekId] = useState(activeWeek);
  const [brush, setBrush] = useState<Level | null>("comfort");
  const [pending, setPending] = useState<Record<string, string>>({});
  const [conflict, setConflict] = useState<Conflict | null>(null);

  // La settimana in modifica può sparire sotto i piedi: template eliminato da
  // un'altra scheda, o scenario cambiato.
  useEffect(() => {
    if (!program.week_templates[weekId]) setWeekId(activeWeek);
  }, [program, weekId, activeWeek]);

  // Un'anteprima ottimistica vive finché il backend non conferma lo stesso
  // valore. Da lì in poi la verità è di nuovo lo snapshot.
  useEffect(() => {
    setPending((current) => {
      const kept = Object.entries(current).filter(
        ([id, slots]) => program.day_templates[id]?.slots !== slots,
      );
      return kept.length === Object.keys(current).length
        ? current
        : Object.fromEntries(kept);
    });
  }, [program]);

  const slotsFor = (templateId: string): string =>
    pending[templateId] ?? program.day_templates[templateId]?.slots ?? "";

  const dropPending = (templateId: string) =>
    setPending(({ [templateId]: _dropped, ...rest }) => rest);

  const applyPaint = async (templateId: string, start: number, end: number) => {
    setPending((current) => ({
      ...current,
      [templateId]: paintedSlots(slotsFor(templateId), start, end, brush),
    }));
    const result = await run((hass) =>
      api.paintSlots(hass, templateId, start, end, brush),
    );
    if (!result.ok) dropPending(templateId);
  };

  const handlePaint = (weekday: number, start: number, end: number) => {
    const templateId = program.week_templates[weekId]?.days[String(weekday)];
    if (!templateId) return;

    const shared = sharedWith(program, weekId, weekday, templateId);
    if (shared.length === 0) {
      void applyPaint(templateId, start, end);
      return;
    }

    setConflict({
      weekday,
      templateId,
      start,
      end,
      description: shared
        .map((usage) => `${listDays(usage.days)} di «${usage.weekName}»`)
        .join("; "),
    });
  };

  const detachAndPaint = async (conflictToResolve: Conflict) => {
    const { weekday, templateId, start, end } = conflictToResolve;
    const source = program.day_templates[templateId];
    if (!source) return;

    const result = await run((hass) =>
      api.duplicateDayTemplate(hass, templateId, {
        newId: freeId(
          program.day_templates,
          `${templateId}_${WEEKDAYS_SHORT[weekday] ?? weekday}`,
        ),
        name: `${source.name} — ${WEEKDAYS[weekday]}`,
        weekTemplate: weekId,
        days: [weekday],
      }),
    );
    if (!result.ok) return;

    const copy = result.value;
    setPending((current) => ({
      ...current,
      [copy.template_id]: paintedSlots(copy.slots, start, end, brush),
    }));
    const painted = await run((hass) =>
      api.paintSlots(hass, copy.template_id, start, end, brush),
    );
    if (!painted.ok) dropPending(copy.template_id);
  };

  const week = program.week_templates[weekId];

  return (
    <>
      <Card
        title="Programma settimanale"
        hint="Scegli un pennello e trascina sulla riga di un giorno. Un trascinamento è un intervallo: dalle 07:00 alle 09:00 è un gesto solo."
        actions={
          <label className="field">
            Settimana tipo
            <select
              value={weekId}
              onChange={(event) => setWeekId(event.target.value)}
            >
              {Object.values(program.week_templates).map((template) => (
                <option key={template.id} value={template.id}>
                  {template.name}
                  {template.id === activeWeek ? " (in uso)" : ""}
                </option>
              ))}
            </select>
          </label>
        }
      >
        <div className="brushes">
          {LEVELS.map((level) => (
            <button
              key={level}
              className="brush"
              aria-pressed={brush === level}
              onClick={() => setBrush(level)}
            >
              <span className={`swatch ${level}`} />
              {LEVEL_LABEL[level]}
              <span className="badge plain">
                {program.global_setpoints[level]?.toFixed(1) ?? "—"} °C
              </span>
            </button>
          ))}
          <button
            className="brush"
            aria-pressed={brush === null}
            onClick={() => setBrush(null)}
            title="Lo slot non impone alcun livello: la zona resta all'ultimo setpoint"
          >
            <span className="swatch inherit" />
            Eredita
          </button>
        </div>

        {week ? (
          <>
            <WeekGrid
              program={program}
              weekId={weekId}
              slotsFor={slotsFor}
              brush={brush}
              sharedDays={(weekday, templateId) =>
                sharedWith(program, weekId, weekday, templateId).reduce(
                  (total, usage) => total + usage.days.length,
                  0,
                )
              }
              onPaint={handlePaint}
              onAssign={(weekday, templateId) =>
                void run((hass) =>
                  api.setWeekTemplate(hass, weekId, {
                    days: { [weekday]: templateId },
                  }),
                )
              }
            />
            <p className="legend">
              <span>
                <span className="swatch inherit" /> lo slot «eredita» non impone
                nulla: nessun setpoint viene scritto in quella mezz'ora
              </span>
            </p>
          </>
        ) : (
          <p className="hint">Nessuna settimana tipo da mostrare.</p>
        )}
      </Card>

      <Templates program={program} run={run} />

      {conflict && (
        <ConflictDialog
          conflict={conflict}
          program={program}
          brush={brush}
          onClose={() => setConflict(null)}
          onAll={() => {
            void applyPaint(conflict.templateId, conflict.start, conflict.end);
            setConflict(null);
          }}
          onDetach={() => {
            void detachAndPaint(conflict);
            setConflict(null);
          }}
        />
      )}
    </>
  );
}

function ConflictDialog({
  conflict,
  program,
  brush,
  onClose,
  onAll,
  onDetach,
}: {
  conflict: Conflict;
  program: Program;
  brush: Level | null;
  onClose: () => void;
  onAll: () => void;
  onDetach: () => void;
}) {
  const template = program.day_templates[conflict.templateId];
  const day = WEEKDAYS[conflict.weekday] ?? "";

  return (
    <Modal
      title="Questa giornata tipo è condivisa"
      onClose={onClose}
      actions={
        <>
          <button className="btn" onClick={onClose}>
            Annulla
          </button>
          <button className="btn" onClick={onAll}>
            Modifica per tutti
          </button>
          <button className="btn primary" onClick={onDetach}>
            Scollega {day}
          </button>
        </>
      }
    >
      <p className="hint">
        «{template?.name ?? conflict.templateId}» è usata anche da{" "}
        {conflict.description}. Modificarla qui cambia il programma anche lì.
      </p>
      <p className="hint">
        In alternativa {day} passa a una copia indipendente, e la pennellata
        {brush ? ` (${LEVEL_LABEL[brush].toLowerCase()})` : ""} resta solo su
        quel giorno.
      </p>
    </Modal>
  );
}
