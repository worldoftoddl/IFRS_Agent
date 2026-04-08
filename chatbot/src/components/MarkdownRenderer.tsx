"use client";

import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";

interface MarkdownRendererProps {
  content: string;
}

export const MarkdownRenderer = React.memo<MarkdownRendererProps>(
  ({ content }) => {
    return (
      <div className="prose prose-sm max-w-none text-gray-900 prose-headings:font-semibold prose-p:my-3 prose-p:leading-relaxed prose-a:text-primary prose-a:no-underline hover:prose-a:underline prose-blockquote:my-3 prose-pre:my-3 prose-ol:my-3 prose-ul:my-3">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            code({
              inline,
              className,
              children,
              ...props
            }: {
              inline?: boolean;
              className?: string;
              children?: React.ReactNode;
            }) {
              const match = /language-(\w+)/.exec(className || "");
              return !inline && match ? (
                <SyntaxHighlighter
                  style={oneDark}
                  language={match[1]}
                  PreTag="div"
                  wrapLongLines
                  customStyle={{
                    margin: 0,
                    borderRadius: "0.5rem",
                    fontSize: "0.8125rem",
                  }}
                >
                  {String(children).replace(/\n$/, "")}
                </SyntaxHighlighter>
              ) : (
                <code
                  className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[0.85em] text-gray-800"
                  {...props}
                >
                  {children}
                </code>
              );
            },
            pre({ children }: { children?: React.ReactNode }) {
              return (
                <div className="my-3 overflow-hidden rounded-lg">
                  {children}
                </div>
              );
            },
            table({ children }: { children?: React.ReactNode }) {
              return (
                <div className="my-3 overflow-x-auto rounded-lg border border-border">
                  <table className="w-full border-collapse text-sm">
                    {children}
                  </table>
                </div>
              );
            },
          }}
        >
          {content}
        </ReactMarkdown>
      </div>
    );
  },
);

MarkdownRenderer.displayName = "MarkdownRenderer";
