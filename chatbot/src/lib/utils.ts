import type { Message } from "@langchain/langgraph-sdk";

const UI_MODE_PREFIX_RE = /^\[UI_MODE: (IFRS|AUDIT|AUTO)\]\n사용자 질문:\s*/;

export function stripUiModePrefix(content: string): string {
  return content.replace(UI_MODE_PREFIX_RE, "");
}

export function extractStringFromMessageContent(message: Message): string {
  if (typeof message.content === "string") {
    return stripUiModePrefix(message.content);
  }
  if (Array.isArray(message.content)) {
    const content = message.content
      .filter(
        (c: unknown) =>
          (typeof c === "object" &&
            c !== null &&
            "type" in c &&
            (c as { type: string }).type === "text") ||
          typeof c === "string",
      )
      .map((c: unknown) =>
        typeof c === "string"
          ? c
          : typeof c === "object" && c !== null && "text" in c
            ? (c as { text?: string }).text || ""
          : "",
      )
      .join("");
    return stripUiModePrefix(content);
  }
  return "";
}

export function isSearching(messages: Message[]): boolean {
  if (messages.length === 0) return false;
  const last = messages[messages.length - 1];
  if (last.type !== "ai") return false;

  const toolCalls = (last as Record<string, unknown>).tool_calls as
    | Array<{ name?: string }>
    | undefined;
  if (!toolCalls || toolCalls.length === 0) return false;

  const hasTask = toolCalls.some((tc) => tc.name === "task");
  if (!hasTask) return true;

  // task 호출이 있지만 아직 응답이 없으면 검색 중
  const lastToolCallId = (toolCalls[toolCalls.length - 1] as { id?: string })
    .id;
  const hasResponse = messages.some(
    (m) =>
      m.type === "tool" &&
      (m as Record<string, unknown>).tool_call_id === lastToolCallId,
  );
  return !hasResponse;
}
