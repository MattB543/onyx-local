"use client";

import { useCallback, useRef, useState } from "react";
import { SvgCheck, SvgCopy } from "@opal/icons";

interface CopyEmailButtonProps {
  email: string;
}

export default function CopyEmailButton({ email }: CopyEmailButtonProps) {
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleCopy = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      e.stopPropagation();
      void navigator.clipboard.writeText(email);
      setCopied(true);
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setCopied(false), 2000);
    },
    [email]
  );

  return (
    <button
      type="button"
      onClick={handleCopy}
      className="flex h-5 w-5 shrink-0 items-center justify-center rounded hover:bg-background-tint-02"
      title="Copy email"
    >
      {copied ? (
        <SvgCheck className="h-3 w-3 stroke-green-600" />
      ) : (
        <SvgCopy className="h-3 w-3 stroke-text-03" />
      )}
    </button>
  );
}
