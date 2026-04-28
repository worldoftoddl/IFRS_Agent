import type { DomainMode } from "@/types";

export interface DomainUiConfig {
  label: string;
  title: string;
  subtitle: string;
  assistantLabel: string;
  inputPlaceholder: string;
  searchText: string;
  examples: string[];
}

export const DOMAIN_UI: Record<DomainMode, DomainUiConfig> = {
  ifrs: {
    label: "K-IFRS",
    title: "K-IFRS 회계 자문 AI",
    subtitle: "한국채택국제회계기준",
    assistantLabel: "K-IFRS 자문",
    inputPlaceholder: "K-IFRS에 대해 질문하세요...",
    searchText: "K-IFRS 기준서 검색 중...",
    examples: [
      "충당부채 인식 조건 3가지는?",
      "리스 이용자의 최초 인식 회계처리는?",
      "수익 인식의 5단계 모형을 설명해줘",
    ],
  },
  audit: {
    label: "감사기준",
    title: "감사기준 자문 AI",
    subtitle: "회계감사·품질관리·인증업무 기준",
    assistantLabel: "감사기준 자문",
    inputPlaceholder: "감사기준에 대해 질문하세요...",
    searchText: "감사기준 검색 중...",
    examples: [
      "수행중요성이란 무엇인가?",
      "계속기업 가정에 대한 감사인의 책임은?",
      "충분하고 적합한 감사증거는 무엇인가?",
    ],
  },
  auto: {
    label: "자동",
    title: "통합 기준서 자문 AI",
    subtitle: "질문 내용에 따라 K-IFRS 또는 감사기준 선택",
    assistantLabel: "통합 자문",
    inputPlaceholder: "회계기준 또는 감사기준에 대해 질문하세요...",
    searchText: "관련 기준서 검색 중...",
    examples: [
      "K-IFRS 1037의 충당부채 인식 조건은?",
      "ISA 570에서 계속기업 가정 평가는 어떻게 다루나?",
      "리스 회계처리와 관련 감사절차를 함께 설명해줘",
    ],
  },
};

export const DOMAIN_MODE_STORAGE_KEY = "kifrs-domain-mode";

export function getDomainModeLabel(mode: DomainMode): string {
  return DOMAIN_UI[mode].label;
}

export function getStoredDomainMode(): DomainMode {
  if (typeof window === "undefined") return "ifrs";
  const stored = window.localStorage.getItem(DOMAIN_MODE_STORAGE_KEY);
  if (stored === "ifrs" || stored === "audit" || stored === "auto") {
    return stored;
  }
  return "ifrs";
}

export function storeDomainMode(mode: DomainMode): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(DOMAIN_MODE_STORAGE_KEY, mode);
}
