"use client";

import { useEffect, useState } from "react";
import { getConfig } from "@/lib/config";
import type { AppConfig } from "@/types";
import { SettingsDialog } from "@/components/SettingsDialog";
import { ChatContainer } from "@/components/ChatContainer";

export default function Home() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    const saved = getConfig();
    setConfig(saved);
    setLoaded(true);
  }, []);

  if (!loaded) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    );
  }

  // 설정이 없으면 설정 화면
  if (!config) {
    return (
      <SettingsDialog
        onSave={(c) => {
          setConfig(c);
          setShowSettings(false);
        }}
      />
    );
  }

  return (
    <>
      <ChatContainer
        config={config}
        onOpenSettings={() => setShowSettings(true)}
      />
      {showSettings && (
        <SettingsDialog
          initialConfig={config}
          isModal
          onSave={(c) => {
            setConfig(c);
            setShowSettings(false);
          }}
          onClose={() => setShowSettings(false)}
        />
      )}
    </>
  );
}
