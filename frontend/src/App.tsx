// Guscio del pannello: sottoscrizione, scelta della vista, errori.
//
// Le due viste principali ricalcano i due assi dell'architettura, e non è una
// coincidenza estetica: "Programma" è l'asse temporale (quale livello, quando),
// "Temperature" è l'asse termico (quanti gradi vale un livello, per chi).
// Tenerli separati nell'interfaccia è ciò che permette di cambiare le
// temperature senza rimettere mano al programma, e viceversa.

import { useCallback, useEffect, useRef, useState } from "react";

import { api, errorMessage, subscribe } from "./api";
import { ProgramTab } from "./ProgramTab";
import { TemperaturesTab } from "./TemperaturesTab";
import type { HomeAssistant, Run, Snapshot } from "./types";
import { ZonesTab } from "./ZonesTab";

const TABS = [
  { id: "programma", label: "Programma" },
  { id: "temperature", label: "Temperature" },
  { id: "zone", label: "Zone" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export function App({ hass }: { hass: HomeAssistant }) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabId>("programma");

  // `hass` cambia identità a ogni aggiornamento di stato in tutta la casa; la
  // connessione no. Passa da una ref, così la sottoscrizione si apre una volta
  // sola invece di chiudersi e riaprirsi di continuo.
  const hassRef = useRef(hass);
  hassRef.current = hass;

  useEffect(() => {
    let cancelled = false;
    let unsubscribe: (() => Promise<void>) | undefined;

    subscribe(hassRef.current, setSnapshot)
      .then((off) => {
        if (cancelled) void off();
        else unsubscribe = off;
      })
      .catch((cause: unknown) => setError(errorMessage(cause)));

    return () => {
      cancelled = true;
      void unsubscribe?.();
    };
  }, []);

  const run = useCallback<Run>(async (action) => {
    try {
      const value = await action(hassRef.current);
      setError(null);
      return { ok: true, value };
    } catch (cause: unknown) {
      setError(errorMessage(cause));
      return { ok: false };
    }
  }, []);

  if (!snapshot) {
    return (
      <div className="layout">
        {error && <ErrorBar message={error} onDismiss={() => setError(null)} />}
        <p className="loading">Caricamento del programma…</p>
      </div>
    );
  }

  const { program } = snapshot;
  const active = program.scenarios[program.active_scenario];

  return (
    <div className="layout">
      <div className="topbar">
        <div className="tabs" role="tablist">
          {TABS.map((entry) => (
            <button
              key={entry.id}
              className="tab"
              role="tab"
              aria-selected={tab === entry.id}
              onClick={() => setTab(entry.id)}
            >
              {entry.label}
            </button>
          ))}
        </div>

        <div className="scenario-bar">
          <label className="field">
            Scenario attivo
            <select
              value={program.active_scenario}
              onChange={(event) =>
                void run((hass) => api.activateScenario(hass, event.target.value))
              }
            >
              {Object.values(program.scenarios).map((scenario) => (
                <option key={scenario.id} value={scenario.id}>
                  {scenario.name}
                </option>
              ))}
            </select>
          </label>
          {active && active.offset !== 0 && (
            <span className="badge">
              {active.offset > 0 ? "+" : "−"}
              {Math.abs(active.offset).toFixed(1)} °C su tutto
            </span>
          )}
        </div>
      </div>

      {error && <ErrorBar message={error} onDismiss={() => setError(null)} />}

      {tab === "programma" && <ProgramTab snapshot={snapshot} run={run} />}
      {tab === "temperature" && (
        <TemperaturesTab snapshot={snapshot} run={run} />
      )}
      {tab === "zone" && <ZonesTab snapshot={snapshot} hass={hass} run={run} />}
    </div>
  );
}

function ErrorBar({
  message,
  onDismiss,
}: {
  message: string;
  onDismiss: () => void;
}) {
  return (
    <div className="error" role="alert">
      <span>{message}</span>
      <button className="btn small" onClick={onDismiss}>
        Ho capito
      </button>
    </div>
  );
}
