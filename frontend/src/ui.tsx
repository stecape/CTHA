// Mattoncini condivisi. Niente libreria di componenti: il pannello ne usa
// cinque, e una dipendenza in più andrebbe comunque impacchettata nel bundle.

import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";

export function Card({
  title,
  actions,
  hint,
  children,
}: {
  title?: string;
  actions?: ReactNode;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <section className="card">
      {(title || actions) && (
        <header className="card-head">
          <div>
            {title && <h2>{title}</h2>}
            {hint && <p className="hint">{hint}</p>}
          </div>
          {actions && <div className="item-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function Modal({
  title,
  children,
  actions,
  onClose,
}: {
  title: string;
  children: ReactNode;
  actions: ReactNode;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDivElement>(null);

  useEffect(() => {
    dialog.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    // Il listener sta sul document: il focus può essere ovunque nello shadow.
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="overlay" onPointerDown={onClose}>
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        ref={dialog}
        onPointerDown={(event) => event.stopPropagation()}
      >
        <h2>{title}</h2>
        {children}
        <div className="dialog-actions">{actions}</div>
      </div>
    </div>
  );
}

/**
 * Campo numerico che non combatte con chi digita.
 *
 * Il valore committato risale solo alla conferma o all'uscita dal campo: se
 * ogni tasto premuto chiamasse il servizio, "21" passerebbe per "2" e la
 * riscrittura delle zone partirebbe due volte.
 */
export function NumberField({
  value,
  onCommit,
  min,
  max,
  step,
  placeholder,
  title,
  className,
}: {
  value: number | null;
  onCommit: (value: number | null) => void;
  min?: number;
  max?: number;
  step?: number;
  placeholder?: string;
  title?: string;
  className?: string;
}) {
  const [draft, setDraft] = useState<string>(value === null ? "" : String(value));
  const committed = useRef(value);

  // Un valore che cambia dal backend (o da un'altra scheda) deve comparire,
  // ma non mentre l'utente sta scrivendo su quel campo.
  useEffect(() => {
    if (committed.current !== value) {
      committed.current = value;
      setDraft(value === null ? "" : String(value));
    }
  }, [value]);

  const commit = () => {
    const trimmed = draft.trim();
    const next = trimmed === "" ? null : Number(trimmed);
    if (next !== null && Number.isNaN(next)) {
      setDraft(value === null ? "" : String(value));
      return;
    }
    if (next === value) return;
    committed.current = next;
    onCommit(next);
  };

  return (
    <input
      type="number"
      className={className}
      value={draft}
      min={min}
      max={max}
      step={step}
      title={title}
      placeholder={placeholder}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") event.currentTarget.blur();
        if (event.key === "Escape") {
          setDraft(value === null ? "" : String(value));
          event.currentTarget.blur();
        }
      }}
    />
  );
}

/** Chiede un testo prima di eseguire: serve per "nuovo …" e "rinomina". */
export function PromptModal({
  title,
  label,
  initial,
  confirmLabel,
  onConfirm,
  onClose,
}: {
  title: string;
  label: string;
  initial?: string;
  confirmLabel: string;
  onConfirm: (value: string) => void;
  onClose: () => void;
}) {
  const [value, setValue] = useState(initial ?? "");
  return (
    <Modal
      title={title}
      onClose={onClose}
      actions={
        <>
          <button className="btn" onClick={onClose}>
            Annulla
          </button>
          <button
            className="btn primary"
            disabled={!value.trim()}
            onClick={() => {
              onConfirm(value.trim());
              onClose();
            }}
          >
            {confirmLabel}
          </button>
        </>
      }
    >
      <label className="field">
        {label}
        <input
          type="text"
          value={value}
          autoFocus
          onChange={(event) => setValue(event.target.value)}
        />
      </label>
    </Modal>
  );
}
