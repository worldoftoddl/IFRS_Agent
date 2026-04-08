"use client";

interface EmptyStateProps {
  onExampleClick: (question: string) => void;
}

const EXAMPLES = [
  "충당부채 인식 조건 3가지는?",
  "리스 이용자의 최초 인식 회계처리는?",
  "수익 인식의 5단계 모형을 설명해줘",
];

export function EmptyState({ onExampleClick }: EmptyStateProps) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center px-4">
      <div className="mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10">
        <svg
          width="28"
          height="28"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          className="text-primary"
        >
          <path d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
        </svg>
      </div>
      <h1 className="mb-2 text-xl font-bold text-gray-900">
        K-IFRS 회계 자문 AI
      </h1>
      <p className="mb-8 max-w-sm text-center text-sm text-gray-500">
        한국채택국제회계기준에 대해 질문하세요.
        <br />
        기준서를 검색하고 근거 문단을 인용하여 답변합니다.
      </p>

      <div className="flex w-full max-w-md flex-col gap-2">
        {EXAMPLES.map((q) => (
          <button
            key={q}
            onClick={() => onExampleClick(q)}
            className="rounded-lg border border-gray-200 px-4 py-3 text-left text-sm text-gray-700 transition-colors hover:border-primary/30 hover:bg-primary/5"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
