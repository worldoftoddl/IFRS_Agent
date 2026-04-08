import { Client } from "@langchain/langgraph-sdk";
import type { AppConfig } from "@/types";

let cachedClient: Client | null = null;
let cachedUrl: string | null = null;

export function getClient(config: AppConfig): Client {
  if (cachedClient && cachedUrl === config.apiUrl) {
    return cachedClient;
  }

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (config.apiKey) {
    headers["X-Api-Key"] = config.apiKey;
  }

  cachedClient = new Client({
    apiUrl: config.apiUrl,
    defaultHeaders: headers,
  });
  cachedUrl = config.apiUrl;

  return cachedClient;
}

export function clearClient(): void {
  cachedClient = null;
  cachedUrl = null;
}
