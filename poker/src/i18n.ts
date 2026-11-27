type MiniAppWindow = Window & {
  NoraI18n?: { language: string; server(value: string): string };
};

export function copy(value: string, pokerTerm = false) {
  const i18n = (window as MiniAppWindow).NoraI18n;
  if (i18n?.language !== "en") return value;
  return i18n.server(pokerTerm ? value + " (покер)" : value);
}
