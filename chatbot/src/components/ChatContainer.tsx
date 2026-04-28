"use client";

import { useState } from "react";
import { useChat } from "@/hooks/useChat";
import {
  DOMAIN_UI,
  getStoredDomainMode,
  storeDomainMode,
} from "@/lib/domain";
import type { AppConfig, DomainMode } from "@/types";
import { MessageList } from "./MessageList";
import { ChatInput } from "./ChatInput";
import { EmptyState } from "./EmptyState";

interface ChatContainerProps {
  config: AppConfig;
  onOpenSettings: () => void;
}

export function ChatContainer({ config, onOpenSettings }: ChatContainerProps) {
  const [domainMode, setDomainMode] = useState<DomainMode>(() =>
    getStoredDomainMode(),
  );
  const { messages, isLoading, sendMessage, stopStream, startNewChat } =
    useChat(config, domainMode);

  const hasMessages = messages.length > 0;
  const domain = DOMAIN_UI[domainMode];

  function handleModeChange(mode: DomainMode) {
    if (isLoading) return;
    setDomainMode(mode);
    storeDomainMode(mode);
  }

  return (
    <div className="flex h-screen flex-col">
      {/* 헤더 */}
      <header className="border-b border-gray-100 px-4 py-3">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10">
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                className="text-primary"
              >
                <path d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
              </svg>
            </div>
            <div className="min-w-0">
              <h1 className="truncate text-sm font-semibold text-gray-900">
                {domain.title}
              </h1>
              <p className="truncate text-xs text-gray-500">
                {domain.subtitle}
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 md:justify-end">
            <div className="grid grid-cols-3 rounded-lg border border-gray-200 bg-gray-50 p-0.5">
              {(["ifrs", "audit", "auto"] as DomainMode[]).map((mode) => (
                <button
                  key={mode}
                  onClick={() => handleModeChange(mode)}
                  disabled={isLoading}
                  className={`min-w-[72px] rounded-md px-3 py-1.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
                    domainMode === mode
                      ? "bg-white text-primary shadow-sm"
                      : "text-gray-500 hover:text-gray-800"
                  }`}
                  title={`${DOMAIN_UI[mode].label} 모드`}
                >
                  {DOMAIN_UI[mode].label}
                </button>
              ))}
            </div>
            <button
              onClick={startNewChat}
              className="rounded-lg px-3 py-1.5 text-xs text-gray-500 transition-colors hover:bg-gray-100"
              title="현재 모드 새 대화"
            >
              + 새 대화
            </button>
            <button
              onClick={onOpenSettings}
              className="rounded-lg p-1.5 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600"
              title="설정"
            >
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <circle cx="12" cy="12" r="3" />
                <path d="M12 1v2m0 18v2M4.22 4.22l1.42 1.42m12.72 12.72l1.42 1.42M1 12h2m18 0h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
              </svg>
            </button>
          </div>
        </div>
      </header>

      {/* 본문 */}
      {hasMessages ? (
        <MessageList
          messages={messages}
          isLoading={isLoading}
          domainMode={domainMode}
        />
      ) : (
        <EmptyState onExampleClick={sendMessage} domainMode={domainMode} />
      )}

      {/* 입력 */}
      <ChatInput
        onSend={sendMessage}
        onStop={stopStream}
        isLoading={isLoading}
        domainMode={domainMode}
      />
    </div>
  );
}
