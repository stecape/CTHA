// La griglia settimanale: sette giorni per 48 slot da mezz'ora.
//
// Il trascinamento non ascolta le singole celle ma la riga: la posizione del
// puntatore diventa un indice di slot con un calcolo sulla larghezza. Così
// funziona uguale con mouse e con dito, non serve un listener per cella, e
// soprattutto un trascinamento resta *un* intervallo — che è esattamente ciò
// che il servizio `paint_slots` si aspetta.
//
// I colori arrivano dal modello e non dal foglio di stile: i livelli si creano
// dal pannello, quindi una classe CSS per livello non esisterebbe.

import { useRef, useState } from "react";

import { SLOTS_PER_DAY, WEEKDAYS, levelAt, slotRange, sortedDayTemplates } from "./model";
import type { Program, TemperatureLevel } from "./types";

interface Drag {
  weekday: number;
  anchor: number;
  head: number;
}

export function WeekGrid({
  program,
  weekId,
  slotsFor,
  brush,
  sharedDays,
  onPaint,
  onAssign,
}: {
  program: Program;
  weekId: string;
  slotsFor: (templateId: string) => string;
  brush: TemperatureLevel | null;
  sharedDays: (weekday: number, templateId: string) => number;
  onPaint: (weekday: number, start: number, end: number) => void;
  onAssign: (weekday: number, templateId: string | null) => void;
}) {
  // Il trascinamento vive due volte: nello stato, che serve a ridisegnare
  // l'anteprima, e in una ref, che serve a leggerlo al rilascio. Solo la ref è
  // affidabile lì: il rilascio può arrivare prima che React abbia applicato lo
  // stato della pressione, e una chiusura vecchia perderebbe la pennellata.
  const [drag, setDrag] = useState<Drag | null>(null);
  const dragRef = useRef<Drag | null>(null);

  const week = program.week_templates[weekId];
  if (!week) return null;

  const startDrag = (weekday: number, slot: number) => {
    dragRef.current = { weekday, anchor: slot, head: slot };
    setDrag(dragRef.current);
  };

  const moveDrag = (weekday: number, slot: number) => {
    const current = dragRef.current;
    if (!current || current.weekday !== weekday || current.head === slot) return;
    dragRef.current = { ...current, head: slot };
    setDrag(dragRef.current);
  };

  const endDrag = (weekday: number) => {
    const current = dragRef.current;
    dragRef.current = null;
    setDrag(null);
    if (!current || current.weekday !== weekday) return;
    onPaint(
      weekday,
      Math.min(current.anchor, current.head),
      Math.max(current.anchor, current.head),
    );
  };

  const templates = sortedDayTemplates(program);

  const slotAt = (element: HTMLElement, clientX: number): number => {
    const rect = element.getBoundingClientRect();
    // Una riga larga zero non ha slot su cui ragionare: succede solo mentre il
    // pannello è nascosto, e senza guardia il calcolo darebbe NaN.
    if (rect.width <= 0) return 0;
    const ratio = (clientX - rect.left) / rect.width;
    return Math.min(SLOTS_PER_DAY - 1, Math.max(0, Math.floor(ratio * SLOTS_PER_DAY)));
  };

  return (
    <div className="grid-scroll">
      <div className="grid">
        <div />
        <div className="hours">
          {Array.from({ length: 8 }, (_, index) => (
            <span key={index}>{String(index * 3).padStart(2, "0")}</span>
          ))}
        </div>

        {WEEKDAYS.map((name, weekday) => {
          const templateId = week.days[String(weekday)];
          const template = templateId
            ? program.day_templates[templateId]
            : undefined;
          const slots = template ? slotsFor(template.id) : "";
          const shared = template ? sharedDays(weekday, template.id) : 0;

          return (
            <Row
              key={weekday}
              program={program}
              name={name}
              weekday={weekday}
              slots={slots}
              shared={shared}
              templateId={template?.id ?? ""}
              templates={templates.map((item) => ({ id: item.id, name: item.name }))}
              brush={brush}
              drag={drag?.weekday === weekday ? drag : null}
              onAssign={onAssign}
              onDragStart={(slot) => startDrag(weekday, slot)}
              onDragMove={(slot) => moveDrag(weekday, slot)}
              onDragEnd={() => endDrag(weekday)}
              slotAt={slotAt}
            />
          );
        })}
      </div>
    </div>
  );
}

function Row({
  program,
  name,
  weekday,
  slots,
  shared,
  templateId,
  templates,
  brush,
  drag,
  onAssign,
  onDragStart,
  onDragMove,
  onDragEnd,
  slotAt,
}: {
  program: Program;
  name: string;
  weekday: number;
  slots: string;
  shared: number;
  templateId: string;
  templates: { id: string; name: string }[];
  brush: TemperatureLevel | null;
  drag: Drag | null;
  onAssign: (weekday: number, templateId: string | null) => void;
  onDragStart: (slot: number) => void;
  onDragMove: (slot: number) => void;
  onDragEnd: () => void;
  slotAt: (element: HTMLElement, clientX: number) => number;
}) {
  const painting = drag
    ? { from: Math.min(drag.anchor, drag.head), to: Math.max(drag.anchor, drag.head) }
    : null;

  return (
    <>
      <div className="day-label">
        <span className="day">
          {name}
          {shared > 0 && (
            <>
              {" "}
              <span className="badge" title={`Condivisa con altri ${shared} giorni`}>
                condivisa
              </span>
            </>
          )}
        </span>
        <select
          className="template"
          value={templateId}
          onChange={(event) => onAssign(weekday, event.target.value || null)}
          title="Giornata tipo assegnata a questo giorno"
        >
          <option value="">— scoperto —</option>
          {templates.map((template) => (
            <option key={template.id} value={template.id}>
              {template.name}
            </option>
          ))}
        </select>
      </div>

      {templateId ? (
        <div
          className="row-cells"
          role="group"
          aria-label={`Programma di ${name}`}
          onPointerDown={(event) => {
            if (event.button !== 0 && event.pointerType === "mouse") return;
            event.currentTarget.setPointerCapture(event.pointerId);
            onDragStart(slotAt(event.currentTarget, event.clientX));
          }}
          onPointerMove={(event) =>
            onDragMove(slotAt(event.currentTarget, event.clientX))
          }
          onPointerUp={onDragEnd}
          onPointerCancel={onDragEnd}
        >
          {Array.from({ length: SLOTS_PER_DAY }, (_, slot) => {
            const inPaint =
              painting !== null && slot >= painting.from && slot <= painting.to;
            const level = inPaint ? brush : levelAt(program, slots, slot);
            return (
              <div
                key={slot}
                className={[
                  "cell",
                  level ? "" : "inherit",
                  slot % 2 === 1 ? "hour" : "",
                  inPaint ? "painting" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                style={level ? { background: level.color } : undefined}
                title={`${slotRange(slot)} · ${level ? level.name : "eredita"}`}
              />
            );
          })}
        </div>
      ) : (
        <div className="row-cells empty" title="Nessuna giornata tipo assegnata" />
      )}
    </>
  );
}
