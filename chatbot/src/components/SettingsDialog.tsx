"use client";

import { useState } from "react";
import { Client } from "@langchain/langgraph-sdk";
import { saveConfig, getDefaultConfig } from "@/lib/config";
import type { AppConfig } from "@/types";

interface SettingsDialogProps {
  initialConfig?: AppConfig | null;
  onSave: (config: AppConfig) => void;
  onClose?: () => void;
  isModal?: boolean;
}

export function SettingsDialog({
  initialConfig,
  onSave,
  onClose,
  isModal = false,
}: SettingsDialogProps) {
  const defaults = initialConfig ?? getDefaultConfig();
  const [apiUrl, setApiUrl] = useState(defaults.apiUrl);
  const [apiKey, setApiKey] = useState(defaults.apiKey ?? "");
  const [assistantId, setAssistantId] = useState(defaults.assistantId);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);

  async function handleTest() {
    setTesting(true);
    setTestResult(null);
    try {
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };
      if (apiKey) headers["X-Api-Key"] = apiKey;

      const client = new Client({ apiUrl, defaultHeaders: headers });
      const assistants = await client.assistants.search({
        graphId: assistantId,
        limit: 1,
      });
      if (assistants.length > 0) {
        setTestResult("success");
      } else {
        setTestResult("Agent를 찾을 수 없습니다. Assistant ID를 확인하세요.");
      }
    } catch (e) {
      setTestResult(
        `연결 실패: ${e instanceof Error ? e.message : String(e)}`,
      );
    } finally {
      setTesting(false);
    }
  }

  function handleSave() {
    const config: AppConfig = {
      apiUrl: apiUrl.replace(/\/+$/, ""),
      apiKey: apiKey || undefined,
      assistantId,
    };
    saveConfig(config);
    onSave(config);
  }

  return (
    <div
      className={
        isModal
          ? "fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          : "flex min-h-screen items-center justify-center bg-gray-50"
      }
    >
      <div className="w-full max-w-md rounded-xl bg-white p-8 shadow-lg">
        <h2 className="mb-1 text-xl font-bold text-gray-900">
          K-IFRS AI 설정
        </h2>
        <p className="mb-6 text-sm text-gray-500">
          LangGraph 서버에 연결하여 시작합니다.
        </p>

        <div className="space-y-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              API URL
            </label>
            <input
              type="url"
              value={apiUrl}
              onChange={(e) => setApiUrl(e.target.value)}
              placeholder="http://localhost:2024"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              API Key{" "}
              <span className="font-normal text-gray-400">(선택)</span>
            </label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="lsv2_pt_..."
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              Assistant ID
            </label>
            <input
              type="text"
              value={assistantId}
              onChange={(e) => setAssistantId(e.target.value)}
              placeholder="ifrs-agent"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>
        </div>

        {testResult && (
          <div
            className={`mt-4 rounded-lg px-3 py-2 text-sm ${
              testResult === "success"
                ? "bg-emerald-50 text-emerald-700"
                : "bg-red-50 text-red-700"
            }`}
          >
            {testResult === "success"
              ? "연결 성공! 서버가 정상 응답합니다."
              : testResult}
          </div>
        )}

        <div className="mt-6 flex gap-3">
          <button
            onClick={handleTest}
            disabled={testing || !apiUrl}
            className="flex-1 rounded-lg border border-primary px-4 py-2 text-sm font-medium text-primary hover:bg-primary/5 disabled:opacity-50"
          >
            {testing ? "테스트 중..." : "연결 테스트"}
          </button>
          <button
            onClick={handleSave}
            disabled={!apiUrl || !assistantId}
            className="flex-1 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-dark disabled:opacity-50"
          >
            저장
          </button>
        </div>

        {isModal && onClose && (
          <button
            onClick={onClose}
            className="mt-3 w-full text-center text-sm text-gray-400 hover:text-gray-600"
          >
            취소
          </button>
        )}
      </div>
    </div>
  );
}
