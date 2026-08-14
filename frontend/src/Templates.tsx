// Chi usa cosa. È la vista che rende sicuro modificare un modello a
// riferimenti: prima di toccare o eliminare un template si vede dove finisce
// l'effetto. Le eliminazioni bloccate sono disattivate qui e rifiutate anche
// dal backend — questa è la spiegazione, non la difesa.

import { useState } from "react";

import { api } from "./api";
import {
  SLOTS_PER_DAY,
  dayTemplateUsages,
  freeId,
  levelAt,
  listDays,
  slugify,
  sortedDayTemplates,
  sortedWeekTemplates,
  weekTemplateUsages,
} from "./model";
import { SetpointsButton } from "./Setpoints";
import type { Meta, Program, Run } from "./types";
import { Card, PromptModal } from "./ui";

type Prompt =
  | { kind: "new-day" }
  | { kind: "new-week" }
  | { kind: "rename-day"; id: string; name: string }
  | { kind: "rename-week"; id: string; name: string };

export function Templates({
  program,
  meta,
  run,
}: {
  program: Program;
  meta: Meta;
  run: Run;
}) {
  const [prompt, setPrompt] = useState<Prompt | null>(null);

  const onPrompt = (value: string) => {
    if (!prompt) return;
    switch (prompt.kind) {
      case "new-day":
        void run((hass) =>
          api.setDayTemplate(
            hass,
            freeId(program.day_templates, slugify(value)),
            { name: value },
          ),
        );
        break;
      case "new-week":
        void run((hass) =>
          api.setWeekTemplate(
            hass,
            freeId(program.week_templates, slugify(value)),
            { name: value },
          ),
        );
        break;
      case "rename-day":
        void run((hass) => api.setDayTemplate(hass, prompt.id, { name: value }));
        break;
      case "rename-week":
        void run((hass) => api.setWeekTemplate(hass, prompt.id, { name: value }));
        break;
    }
  };

  return (
    <>
      <Card
        title="Giornate tipo"
        hint="Una giornata tipo è una striscia di 48 mezz'ore. Chi la usa la condivide: modificarla cambia il programma di tutti i giorni elencati."
        actions={
          <button className="btn" onClick={() => setPrompt({ kind: "new-day" })}>
            + Nuova
          </button>
        }
      >
        <div className="list">
          {sortedDayTemplates(program).map((template) => {
            const usages = dayTemplateUsages(program, template.id);
            const used = usages.length > 0;
            return (
              <div className="item" key={template.id}>
                <div className="item-main">
                  <strong>{template.name}</strong>
                  <span className="hint">
                    {used
                      ? usages
                          .map(
                            (usage) =>
                              `${listDays(usage.days)} di «${usage.weekName}»`,
                          )
                          .join("; ")
                      : "non usata da nessuna settimana tipo"}
                  </span>
                  <SlotsPreview program={program} slots={template.slots} />
                </div>
                <div className="item-actions">
                  <SetpointsButton
                    program={program}
                    meta={meta}
                    scope={{ layer: "day_template", id: template.id }}
                    name={`giornata tipo «${template.name}»`}
                    run={run}
                  />
                  <button
                    className="btn small"
                    onClick={() =>
                      setPrompt({
                        kind: "rename-day",
                        id: template.id,
                        name: template.name,
                      })
                    }
                  >
                    Rinomina
                  </button>
                  <button
                    className="btn small"
                    onClick={() =>
                      void run((hass) =>
                        api.duplicateDayTemplate(hass, template.id, {
                          newId: freeId(
                            program.day_templates,
                            `${template.id}_copy`,
                          ),
                        }),
                      )
                    }
                  >
                    Duplica
                  </button>
                  <button
                    className="btn small danger"
                    disabled={used}
                    title={
                      used
                        ? "Prima va tolta dalle settimane tipo che la usano"
                        : undefined
                    }
                    onClick={() =>
                      void run((hass) =>
                        api.deleteDayTemplate(hass, template.id),
                      )
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

      <Card
        title="Settimane tipo"
        hint="Una settimana tipo assegna una giornata a ciascun giorno. Sono gli scenari a darla alle zone."
        actions={
          <button className="btn" onClick={() => setPrompt({ kind: "new-week" })}>
            + Nuova
          </button>
        }
      >
        <div className="list">
          {sortedWeekTemplates(program).map((template) => {
            const usages = weekTemplateUsages(program, template.id);
            const used = usages.length > 0;
            return (
              <div className="item" key={template.id}>
                <div className="item-main">
                  <strong>{template.name}</strong>
                  <span className="hint">
                    {used
                      ? usages
                          .map(
                            (usage) =>
                              `${usage.zones.join(", ")} in «${usage.scenarioName}»`,
                          )
                          .join("; ")
                      : "nessuno scenario la assegna a una zona"}
                  </span>
                </div>
                <div className="item-actions">
                  <SetpointsButton
                    program={program}
                    meta={meta}
                    scope={{ layer: "week_template", id: template.id }}
                    name={`settimana tipo «${template.name}»`}
                    run={run}
                  />
                  <button
                    className="btn small"
                    onClick={() =>
                      setPrompt({
                        kind: "rename-week",
                        id: template.id,
                        name: template.name,
                      })
                    }
                  >
                    Rinomina
                  </button>
                  <button
                    className="btn small danger"
                    disabled={used}
                    title={
                      used
                        ? "Prima vanno spostate le zone degli scenari che la assegnano"
                        : undefined
                    }
                    onClick={() =>
                      void run((hass) =>
                        api.deleteWeekTemplate(hass, template.id),
                      )
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

      {prompt && (
        <PromptModal
          title={
            prompt.kind.startsWith("new")
              ? "Nuovo template"
              : "Rinomina template"
          }
          label="Nome"
          initial={"name" in prompt ? prompt.name : ""}
          confirmLabel={prompt.kind.startsWith("new") ? "Crea" : "Salva"}
          onConfirm={onPrompt}
          onClose={() => setPrompt(null)}
        />
      )}
    </>
  );
}

function SlotsPreview({ program, slots }: { program: Program; slots: string }) {
  return (
    <div className="preview" aria-hidden="true">
      {Array.from({ length: SLOTS_PER_DAY }, (_, slot) => {
        const level = levelAt(program, slots, slot);
        return (
          <div
            key={slot}
            className={level ? "cell" : "cell inherit"}
            style={level ? { background: level.color } : undefined}
          />
        );
      })}
    </div>
  );
}
