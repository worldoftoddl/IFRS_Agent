"use client";

import { DOMAIN_UI } from "@/lib/domain";
import type { DomainMode } from "@/types";

interface SearchIndicatorProps {
  domainMode: DomainMode;
}

export function SearchIndicator({ domainMode }: SearchIndicatorProps) {
  const domain = DOMAIN_UI[domainMode];

  return (
    <div className="flex items-center gap-2 px-4 py-3">
      <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10">
        <svg
          className="h-4 w-4 animate-spin text-primary"
          viewBox="0 0 24 24"
          fill="none"
        >
          <circle
            className="opacity-25"
            cx="12"
            cy="12"
            r="10"
            stroke="currentColor"
            strokeWidth="4"
          />
          <path
            className="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
          />
        </svg>
      </div>
      <span className="text-sm text-gray-500">{domain.searchText}</span>
    </div>
  );
}
