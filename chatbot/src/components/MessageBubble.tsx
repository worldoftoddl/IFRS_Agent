"use client";

import { DOMAIN_UI } from "@/lib/domain";
import type { DomainMode, Message } from "@/types";
import { extractStringFromMessageContent } from "@/lib/utils";
import { MarkdownRenderer } from "./MarkdownRenderer";

interface MessageBubbleProps {
  message: Message;
  domainMode: DomainMode;
}

export function MessageBubble({ message, domainMode }: MessageBubbleProps) {
  const content = extractStringFromMessageContent(message);
  if (!content) return null;

  const isHuman = message.type === "human";
  const domain = DOMAIN_UI[domainMode];

  if (isHuman) {
    return (
      <div className="flex justify-end px-4 py-2">
        <div className="max-w-[80%] rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-sm text-white">
          {content}
        </div>
      </div>
    );
  }

  return (
    <div className="px-4 py-2">
      <div className="mx-auto max-w-3xl">
        <div className="mb-1 flex items-center gap-2">
          <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary/10 text-xs font-bold text-primary">
            AI
          </div>
          <span className="text-xs text-gray-400">{domain.assistantLabel}</span>
        </div>
        <div className="pl-8">
          <MarkdownRenderer content={content} />
        </div>
      </div>
    </div>
  );
}
