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
