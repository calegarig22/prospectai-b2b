"use client";

import { useEffect } from "react";

export function Modal({
  title,
  onClose,
  children,
  large = false,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  large?: boolean;
}) {
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);
  return (
    <div className="overlay" role="presentation" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal${large ? " lg" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <h2>{title}</h2>
        {children}
      </div>
    </div>
  );
}

export function Note({ kind = "", children }: { kind?: "" | "ok" | "warn" | "err"; children: React.ReactNode }) {
  return <div className={`note ${kind}`} role={kind === "err" ? "alert" : undefined}>{children}</div>;
}
