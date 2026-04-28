"use client";

import { useEffect, useRef } from "react";
import type { DomainMode, Message } from "@/types";
import { MessageBubble } from "./MessageBubble";
import { SearchIndicator } from "./SearchIndicator";
import { isSearching } from "@/lib/utils";

interface MessageListProps {
  messages: Message[];
  isLoading: boolean;
  domainMode: DomainMode;
}

export function MessageList({
  messages,
  isLoading,
  domainMode,
}: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  // AI/human 메시지만 표시 (tool 메시지는 숨김)
  const visibleMessages = messages.filter(
    (m) => m.type === "human" || (m.type === "ai" && m.content),
  );

  const showSearching = isLoading && isSearching(messages);

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-3xl py-4">
        {visibleMessages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} domainMode={domainMode} />
        ))}
        {showSearching && <SearchIndicator domainMode={domainMode} />}
        {isLoading && !showSearching && (
          <div className="px-4 py-2">
            <div className="mx-auto max-w-3xl pl-8">
              <div className="dot-pulse flex gap-1">
                <span className="h-2 w-2 rounded-full bg-gray-400" />
                <span className="h-2 w-2 rounded-full bg-gray-400" />
                <span className="h-2 w-2 rounded-full bg-gray-400" />
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
