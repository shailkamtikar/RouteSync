"use client";

import { CheckCircle2, CircleAlert } from "lucide-react";
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

import styles from "./kit.module.css";

type Toast = { id: number; kind: "ok" | "bad"; message: string };
type Notify = { success: (message: string) => void; failure: (message: string) => void };

const ToastContext = createContext<Notify>({ success: () => {}, failure: () => {} });
let counter = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const push = useCallback((kind: Toast["kind"], message: string) => {
    const id = ++counter;
    setToasts((current) => [...current.slice(-3), { id, kind, message }]);
    setTimeout(() => setToasts((current) => current.filter((toast) => toast.id !== id)), 5000);
  }, []);

  const notify = useMemo<Notify>(
    () => ({ success: (m) => push("ok", m), failure: (m) => push("bad", m) }),
    [push],
  );

  return (
    <ToastContext.Provider value={notify}>
      {children}
      <div className={styles.toasts} role="status" aria-live="polite">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`${styles.toast} ${toast.kind === "ok" ? styles.toastOk : styles.toastBad}`}
            data-testid="toast"
          >
            {toast.kind === "ok" ? <CheckCircle2 size={18} aria-hidden /> : <CircleAlert size={18} aria-hidden />}
            <span>{toast.message}</span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
