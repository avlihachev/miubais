import { ApiUnavailable, getHint, getProgress, isApiError, isLocalHost, runCheck, type Progress } from "../lib/api";

interface StageInfo {
  id: string;
  title: string;
}

class ExercisePanel extends HTMLElement {
  private rows = new Map<string, HTMLElement>();
  private output!: HTMLElement;

  async connectedCallback() {
    if (!isLocalHost(location.hostname)) return;
    const exercise = this.getAttribute("exercise") ?? "";
    const stages: StageInfo[] = JSON.parse(this.dataset.stages ?? "[]");
    try {
      const progress = await getProgress();
      if (isApiError(progress)) return this.fail(progress.detail);
      this.render(exercise, stages, progress[exercise] ?? {});
    } catch (err) {
      if (err instanceof ApiUnavailable) return this.unavailable();
      throw err;
    }
  }

  private unavailable() {
    const note = document.createElement("p");
    note.textContent = "local API not running";
    this.append(note);
  }

  private fail(message: string) {
    const note = document.createElement("p");
    note.textContent = message;
    this.append(note);
  }

  private setStatus(id: string, status: string) {
    const badge = this.rows.get(id)?.querySelector(".status");
    if (badge) {
      badge.textContent = status;
      badge.setAttribute("data-status", status);
    }
  }

  private render(exercise: string, stages: StageInfo[], done: Progress[string]) {
    this.replaceChildren();
    const list = document.createElement("ul");
    for (const stage of stages) {
      const row = document.createElement("li");
      row.innerHTML = `<code></code> <span class="status"></span>`;
      row.querySelector("code")!.textContent = stage.id;
      list.append(row);
      this.rows.set(stage.id, row);
      this.setStatus(stage.id, done[stage.id]?.status ?? "pending");
    }
    this.output = document.createElement("p");
    this.output.setAttribute("aria-live", "polite");
    const check = this.button("Run check", () => this.check(exercise));
    const hint = this.button("Hint", () => this.hint(exercise));
    this.append(list, check, hint, this.output);
  }

  private button(label: string, onClick: () => void) {
    const el = document.createElement("button");
    el.type = "button";
    el.textContent = label;
    el.addEventListener("click", onClick);
    return el;
  }

  private async guard(work: () => Promise<void>) {
    try {
      await work();
    } catch (err) {
      this.output.textContent = err instanceof ApiUnavailable ? "local API not running: start it with `uv run miubais serve`" : String(err);
    }
  }

  private check(exercise: string) {
    return this.guard(async () => {
      this.output.textContent = "running";
      const error = await runCheck(exercise, (name, data) => {
        if (name === "stage") this.setStatus(data.stage, data.status);
        if (name === "error") this.output.textContent = data.message;
        if (name === "done") this.output.textContent = data.failed ? `failed at ${data.failed}` : "all stages passed";
      });
      if (error) this.output.textContent = error.detail;
    });
  }

  private hint(exercise: string) {
    return this.guard(async () => {
      const result = await getHint(exercise);
      this.output.textContent = isApiError(result) ? result.detail : `${result.text} (source: ${result.source})`;
    });
  }
}

customElements.define("miubais-exercise-panel", ExercisePanel);

class ProgressTable extends HTMLElement {
  async connectedCallback() {
    if (!isLocalHost(location.hostname)) return;
    try {
      const progress = await getProgress();
      if (isApiError(progress)) return;
      this.querySelector(".api-note")?.setAttribute("hidden", "");
      for (const cell of this.querySelectorAll<HTMLElement>("[data-exercise][data-stage]")) {
        const status = progress[cell.dataset.exercise!]?.[cell.dataset.stage!]?.status;
        if (status) cell.textContent = status;
      }
    } catch (err) {
      if (!(err instanceof ApiUnavailable)) throw err;
    }
  }
}

customElements.define("miubais-progress-table", ProgressTable);
