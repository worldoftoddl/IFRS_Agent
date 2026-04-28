import type { Message } from "@langchain/langgraph-sdk";

export type { Message };

export interface AppConfig {
  apiUrl: string;
  apiKey?: string;
  assistantId: string;
}

export type DomainMode = "ifrs" | "audit" | "auto";

export type StateType = {
  messages: Message[];
};

export interface ToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
  status: "pending" | "completed" | "error";
  result?: string;
}
