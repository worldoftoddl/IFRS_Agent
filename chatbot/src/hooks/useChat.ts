"use client";

import { useCallback, useMemo, useState } from "react";
import { useStream } from "@langchain/langgraph-sdk/react";
import type { Message } from "@langchain/langgraph-sdk";
import { v4 as uuidv4 } from "uuid";
import { getClient } from "@/lib/client";
import type { AppConfig, StateType } from "@/types";

const THREAD_ID_KEY = "kifrs-thread-id";

function getStoredThreadId(): string | null {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem(THREAD_ID_KEY);
}

function storeThreadId(id: string): void {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(THREAD_ID_KEY, id);
}

export function useChat(config: AppConfig) {
  const client = useMemo(() => getClient(config), [config]);
  const [threadId, setThreadId] = useState<string | null>(getStoredThreadId);

  const handleThreadId = useCallback((id: string) => {
    setThreadId(id);
    storeThreadId(id);
  }, []);

  const stream = useStream<StateType>({
    assistantId: config.assistantId,
    client,
    reconnectOnMount: true,
    threadId,
    onThreadId: handleThreadId,
  });

  const sendMessage = useCallback(
    (content: string) => {
      const newMessage: Message = { id: uuidv4(), type: "human", content };
      stream.submit(
        { messages: [newMessage] },
        {
          optimisticValues: (prev) => ({
            messages: [...(prev.messages ?? []), newMessage],
          }),
          config: { recursion_limit: 100 },
        },
      );
    },
    [stream],
  );

  const stopStream = useCallback(() => {
    stream.stop();
  }, [stream]);

  const startNewChat = useCallback(() => {
    setThreadId(null);
    sessionStorage.removeItem(THREAD_ID_KEY);
  }, []);

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
