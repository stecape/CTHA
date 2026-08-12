// Il pannello è un Web Component: è l'unico contratto che Home Assistant
// conosce. Dentro c'è React, montato su uno shadow root.
//
// Lo shadow root non è cosmetico: i temi di HA arrivano come variabili CSS
// ereditate (quindi funzionano lo stesso), mentre i fogli di stile globali del
// frontend non entrano — e il nostro non esce. Una griglia con centinaia di
// celle è esattamente il posto dove una regola CSS altrui farebbe danni.

import { createRoot, type Root } from "react-dom/client";

import { App } from "./App";
import styles from "./styles.css?inline";
import type { HomeAssistant } from "./types";

class CthaPanel extends HTMLElement {
  private root: Root | null = null;
  private hassValue: HomeAssistant | null = null;

  connectedCallback(): void {
    if (this.root) return;

    const shadow = this.shadowRoot ?? this.attachShadow({ mode: "open" });
    const sheet = document.createElement("style");
    sheet.textContent = styles;
    const mount = document.createElement("div");
    mount.className = "ctha-root";
    shadow.replaceChildren(sheet, mount);

    this.root = createRoot(mount);
    this.update();
  }

  disconnectedCallback(): void {
    // L'unmount è differito: HA sposta il pannello nel DOM quando cambia il
    // layout, e smontare durante lo stesso ciclo di rendering di React
    // stamperebbe un avviso senza motivo.
    const root = this.root;
    this.root = null;
    queueMicrotask(() => root?.unmount());
  }

  /** Home Assistant assegna questa proprietà a ogni cambio di stato. */
  set hass(value: HomeAssistant) {
    this.hassValue = value;
    this.update();
  }

  get hass(): HomeAssistant | null {
    return this.hassValue;
  }

  private update(): void {
    if (!this.root || !this.hassValue) return;
    this.root.render(<App hass={this.hassValue} />);
  }
}

if (!customElements.get("ctha-panel")) {
  customElements.define("ctha-panel", CthaPanel);
}
