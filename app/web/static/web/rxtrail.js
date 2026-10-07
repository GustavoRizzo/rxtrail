// Icons, copy-to-clipboard and timestamps. Alpine.js handles the rest.
document.addEventListener("DOMContentLoaded", () => {
  window.lucide?.createIcons();
});

window.rxCopy = async (text, button) => {
  await navigator.clipboard.writeText(text);
  const label = button.querySelector("[data-label]");
  if (!label) return;
  const before = label.textContent;
  label.textContent = "Copied";
  setTimeout(() => (label.textContent = before), 1400);
};
