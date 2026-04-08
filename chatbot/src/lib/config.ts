import type { AppConfig } from "@/types";

const CONFIG_KEY = "kifrs-chatbot-config";

const DEFAULT_CONFIG: AppConfig = {
  apiUrl: "http://localhost:2024",
  assistantId: "ifrs-agent",
};

export function getConfig(): AppConfig | null {
  if (typeof window === "undefined") return null;

  const stored = localStorage.getItem(CONFIG_KEY);
  if (!stored) return null;

  try {
    return JSON.parse(stored);
  } catch {
    return null;
  }
}

export function saveConfig(config: AppConfig): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(CONFIG_KEY, JSON.stringify(config));
}

export function getDefaultConfig(): AppConfig {
  return { ...DEFAULT_CONFIG };
}
