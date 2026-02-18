import React, { useCallback, useMemo, JSX } from "react";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import "katex/dist/katex.min.css";
import "@/app/app/message/custom-code-styles.css";
import { CodeBlock } from "@/app/app/message/CodeBlock";
import { extractCodeText, preprocessLaTeX } from "@/app/app/message/codeUtils";
import {
  MemoizedAnchor,
  MemoizedParagraph,
} from "@/app/app/message/MemoizedTextComponents";
import { FullChatState } from "@/app/app/message/messageComponents/interfaces";
import { transformLinkUri, cn } from "@/lib/utils";

/**
 * Processes content for markdown rendering by handling code blocks and LaTeX
 */
export const processContent = (content: string): string => {
  const codeBlockRegex = /```(\w*)\n[\s\S]*?```|```[\s\S]*?$/g;
  const matches = content.match(codeBlockRegex);

  if (matches) {
    content = matches.reduce((acc, match) => {
      if (!match.match(/```\w+/)) {
        return acc.replace(match, match.replace("```", "```plaintext"));
      }
      return acc;
    }, content);

    const lastMatch = matches[matches.length - 1];
    if (lastMatch && !lastMatch.endsWith("```")) {
      return preprocessLaTeX(content);
    }
  }

  const processed = preprocessLaTeX(content);
  return processed;
};

/**
 * Hook that provides markdown component callbacks for consistent rendering
 */
export const useMarkdownComponents = (
  state: FullChatState | undefined,
  processedContent: string,
  className?: string
) => {
  const paragraphCallback = useCallback(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (props: any) => (
      <MemoizedParagraph className={className}>
        {props.children}
      </MemoizedParagraph>
    ),
    [className]
  );

  const anchorCallback = useCallback(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (props: any) => (
      <MemoizedAnchor
        updatePresentingDocument={state?.setPresentingDocument || (() => {})}
        docs={state?.docs || []}
        userFiles={state?.userFiles || []}
        citations={state?.citations}
        href={props.href}
      >
        {props.children}
      </MemoizedAnchor>
    ),
    [
      state?.docs,
      state?.userFiles,
      state?.citations,
      state?.setPresentingDocument,
    ]
  );

  const markdownComponents = useMemo(
    () => ({
      a: anchorCallback,
      p: paragraphCallback,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      pre: ({ node, className, children }: any) => {
        // Don't render the pre wrapper - CodeBlock handles its own wrapper
        return <>{children}</>;
      },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      b: ({ node, className, children }: any) => {
        return <span className={className}>{children}</span>;
      },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ul: ({ node, className, children, ...props }: any) => {
        return (
          <ul className={className} {...props}>
            {children}
          </ul>
        );
      },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ol: ({ node, className, children, ...props }: any) => {
        return (
          <ol className={className} {...props}>
            {children}
          </ol>
        );
      },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      li: ({ node, className, children, ...props }: any) => {
        return (
          <li className={className} {...props}>
            {children}
          </li>
        );
      },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      table: ({ node, className, children, ...props }: any) => {
        return (
          <div className="markdown-table-breakout">
            <table className={cn(className, "min-w-full")} {...props}>
              {children}
            </table>
          </div>
        );
      },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      code: ({ node, className, children }: any) => {
        const codeText = extractCodeText(node, processedContent, children);

        return (
          <CodeBlock className={className} codeText={codeText}>
            {children}
          </CodeBlock>
        );
      },
    }),
    [anchorCallback, paragraphCallback, processedContent]
  );

  return markdownComponents;
};

/**
 * Renders markdown content with consistent configuration
 */
export const renderMarkdown = (
  content: string,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  markdownComponents: any,
  textSize = "text-base"
): JSX.Element => {
  return (
    <div dir="auto">
      <ReactMarkdown
        className={`prose dark:prose-invert font-main-content-body max-w-full ${textSize}`}
        components={markdownComponents}
        remarkPlugins={[
          remarkGfm,
          [remarkMath, { singleDollarTextMath: true }],
        ]}
        rehypePlugins={[rehypeHighlight, rehypeKatex]}
        urlTransform={transformLinkUri}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
};

/**
 * Complete markdown processing and rendering utility
 */
export const useMarkdownRenderer = (
  content: string,
  state: FullChatState | undefined,
  textSize: string
) => {
  const processedContent = useMemo(() => processContent(content), [content]);
  const markdownComponents = useMarkdownComponents(
    state,
    processedContent,
    textSize
  );

  const renderedContent = useMemo(
    () => renderMarkdown(processedContent, markdownComponents, textSize),
    [processedContent, markdownComponents, textSize]
  );

  return {
    processedContent,
    markdownComponents,
    renderedContent,
  };
};
