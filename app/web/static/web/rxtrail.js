// Icons, copy-to-clipboard and timestamps. Alpine.js handles the rest.
document.addEventListener("DOMContentLoaded", () => {
  window.lucide?.createIcons();
});

// An empty date field shows its format (mm/dd/yyyy) like a placeholder: faint.
// CSS cannot tell an empty date input apart, so mark the filled ones.
const markDate = (input) => input.toggleAttribute("data-filled", input.value !== "");
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll('input[type="date"]').forEach(markDate);
});
document.addEventListener("input", (event) => {
  if (event.target.matches?.('input[type="date"]')) markDate(event.target);
});

window.rxCopy = async (text, button) => {
  await navigator.clipboard.writeText(text);
  const label = button.querySelector("[data-label]");
  if (!label) return;
  const before = label.textContent;
  label.textContent = "Copied";
  setTimeout(() => (label.textContent = before), 1400);
};

// The medication picker of the prescription form. Results are server-rendered
// HTML (catalog/search/); choosing one fills the form. Limits only warn: the
// prescriber decides, and the program does not know them.
window.rxMedicationPicker = (chosenScript, searchUrl, locked, quantity, days) => ({
  open: false,
  busy: false,
  loading: false,
  q: "",
  html: "",
  chosen: JSON.parse(document.getElementById(chosenScript).textContent),
  locked: locked || "",
  quantity: quantity === "" ? null : Number(quantity),
  days: Number(days) || 30,

  openPicker() {
    this.open = true;
    this.search();
    this.$nextTick(() => this.$refs.search.focus());
  },

  async search() {
    this.loading = true;
    try {
      const response = await fetch(`${searchUrl}?q=${encodeURIComponent(this.q)}`);
      this.html = response.ok
        ? await response.text()
        : `<p class="p-4 text-sm text-danger">Search failed (${response.status}).</p>`;
    } catch {
      this.html = '<p class="p-4 text-sm text-danger">Search failed: no connection.</p>';
    } finally {
      this.loading = false;
    }
    this.$nextTick(() => window.lucide?.createIcons());
  },

  choose(medication) {
    this.chosen = medication;
    this.locked = "";
    this.open = false;
  },

  // Arrow keys walk the results; Enter on a focused result chooses it.
  move(step) {
    const items = [...this.$refs.results.querySelectorAll("[data-medication]:not([disabled])")];
    const at = items.indexOf(document.activeElement);
    if (at === 0 && step < 0) return this.$refs.search.focus();
    const next = at < 0 ? 0 : Math.min(Math.max(at + step, 0), items.length - 1);
    items[next]?.focus();
  },

  get lockedProduct() {
    return this.chosen?.products.find((p) => p.id === this.locked) ?? null;
  },

  get warnings() {
    const m = this.chosen;
    if (!m || !this.quantity) return [];
    const found = [];
    if (m.max_quantity && this.quantity > m.max_quantity)
      found.push(`Above the regulatory limit of ${m.max_quantity} ${m.unit}s per prescription.`);
    if (m.max_validity_days && this.days > m.max_validity_days)
      found.push(`Above the regulatory validity of ${m.max_validity_days} days.`);
    if (m.usual_max_daily_units && this.quantity > m.usual_max_daily_units * this.days)
      found.push(`More than the usual maximum of ${m.usual_max_daily_units} a day for ${this.days} days.`);
    return found;
  },
});
