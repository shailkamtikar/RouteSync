"use client";

import { X } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";

import ui from "../ui.module.css";
import styles from "./kit.module.css";

/** Accessible dialog on the native element: focus is trapped and Escape closes it. */
export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  wide = false,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className={styles.modal}
      aria-labelledby="modal-title"
      onClose={onClose}
      onClick={(event) => {
        if (event.target === ref.current) onClose();
      }}
    >
      {open && (
        <div className={`${styles.modalBox} ${wide ? styles.modalWide : ""}`}>
          <div className={styles.modalHead}>
            <div>
              <h2 id="modal-title">{title}</h2>
              {description && <p className={styles.subtitle}>{description}</p>}
            </div>
            <button type="button" className={styles.iconButton} onClick={onClose} aria-label="Close">
              <X size={18} aria-hidden />
            </button>
          </div>
          <div className={styles.modalBody}>{children}</div>
        </div>
      )}
    </dialog>
  );
}

/** Asks before a destructive action. */
export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel,
  busy = false,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  message: ReactNode;
  confirmLabel: string;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <Modal open={open} onClose={onCancel} title={title}>
      <div style={{ display: "grid", gap: 20 }}>
        <p style={{ color: "var(--text-2)" }}>{message}</p>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
          <button type="button" className={ui.buttonGhost} onClick={onCancel} disabled={busy}>
            Keep it
          </button>
          <button type="button" className={ui.buttonDanger} onClick={onConfirm} disabled={busy}>
            {busy ? "Working…" : confirmLabel}
          </button>
        </div>
      </div>
    </Modal>
  );
}
