"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useStream } from "@langchain/langgraph-sdk/react";
import type { Message } from "@langchain/langgraph-sdk";
import { v4 as uuidv4 } from "uuid";
import { getClient } from "@/lib/client";
import type { AppConfig, DomainMode, StateType } from "@/types";

const THREAD_ID_KEY_PREFIX = "standard-chat-thread-id";

const MODE_HINT: Record<DomainMode, string> = {
  ifrs: "IFRS",
  audit: "AUDIT",
  auto: "AUTO",
};

function threadIdKey(mode: DomainMode): string {
  return `${THREAD_ID_KEY_PREFIX}:${mode}`;
}

function getStoredThreadId(mode: DomainMode): string | null {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem(threadIdKey(mode));
}

function storeThreadId(mode: DomainMode, id: string): void {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(threadIdKey(mode), id);
}

function clearStoredThreadId(mode: DomainMode): void {
  if (typeof window === "undefined") return;
  sessionStorage.removeItem(threadIdKey(mode));
}

function withModeHint(content: string, mode: DomainMode): string {
  return `[UI_MODE: ${MODE_HINT[mode]}]\n사용자 질문: ${content}`;
}

export function useChat(config: AppConfig, domainMode: DomainMode) {
  const client = useMemo(() => getClient(config), [config]);
  const [threadId, setThreadId] = useState<string | null>(() =>
    getStoredThreadId(domainMode),
  );

  useEffect(() => {
    setThreadId(getStoredThreadId(domainMode));
  }, [domainMode]);

  const handleThreadId = useCallback((id: string) => {
    setThreadId(id);
    storeThreadId(domainMode, id);
  }, [domainMode]);

  const stream = useStream<StateType>({
    assistantId: config.assistantId,
    client,
    reconnectOnMount: true,
    threadId,
    onThreadId: handleThreadId,
  });

  const sendMessage = useCallback(
    (content: string) => {
      const id = uuidv4();
      const submittedMessage: Message = {
        id,
        type: "human",
        content: withModeHint(content, domainMode),
      };
      const optimisticMessage: Message = { id, type: "human", content };
      stream.submit(
        { messages: [submittedMessage] },
        {
          optimisticValues: (prev) => ({
            messages: [...(prev.messages ?? []), optimisticMessage],
          }),
          config: { recursion_limit: 100 },
        },
      );
    },
    [domainMode, stream],
  );

  const stopStream = useCallback(() => {
    stream.stop();
  }, [stream]);

  const startNewChat = useCallback(() => {
    setThreadId(null);
    clearStoredThreadId(domainMode);
  }, [domainMode]);

  return {
    messages: stream.messages,
    isLoading: stream.isLoading,
    error: stream.error,
    sendMessage,
    stopStream,
    startNewChat,
    threadId,
  };
}
