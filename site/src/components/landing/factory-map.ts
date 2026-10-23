import { ApiUnavailable, getProgress, isApiError, isLocalHost } from "../../lib/api";
import { markStatus } from "../../lib/landing";

class FactoryMap extends HTMLElement {
  connectedCallback() {
    for (const el of this.querySelectorAll<SVGElement>("[data-module]")) {
      const show = () => this.show(el.dataset.module!);
      el.addEventListener("mouseenter", show);
      el.addEventListener("focus", show);
    }
    this.show(this.dataset.initial ?? "");
    void this.colourMarks();
  }

  private show(id: string) {
    for (const el of this.querySelectorAll<SVGElement>("[data-module]")) {
      el.classList.toggle("is-active", el.dataset.module === id);
    }
    for (const panel of this.querySelectorAll<HTMLElement>("[data-panel]")) {
      panel.hidden = panel.dataset.panel !== id;
    }
  }

  private async colourMarks() {
    if (!isLocalHost(location.hostname)) return;
    try {
      const progress = await getProgress();
      if (isApiError(progress)) return;
      for (const mark of this.querySelectorAll<SVGElement>(".mark[data-exercise][data-stage]")) {
        mark.dataset.status = markStatus(progress, mark.dataset.exercise!, mark.dataset.stage!);
      }
    } catch (err) {
      if (!(err instanceof ApiUnavailable)) throw err;
      this.querySelector(".api-note")?.removeAttribute("hidden");
    }
  }
}

customElements.define("miubais-factory-map", FactoryMap);
