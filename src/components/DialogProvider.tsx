"use client";

import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";

type Request = {
  message: string;
  confirmLabel: string;
  alertOnly: boolean;
  resolve: (ok: boolean) => void;
};

type Dialog = {
  confirm: (message: string, options?: { confirmLabel?: string }) => Promise<boolean>;
  alert: (message: string) => Promise<void>;
};

const DialogContext = createContext<Dialog | null>(null);

// In-page replacement for window.confirm()/alert(). Native dialogs aren't
// reliable where this app runs: the desktop app's browser pane and embedded
// webviews (Telegram's among them) suppress them, and a suppressed confirm()
// returns false — the action silently never happens.
export function DialogProvider({ children }: { children: ReactNode }) {
  const [request, setRequest] = useState<Request | null>(null);
  const confirmButton = useRef<HTMLButtonElement>(null);

  const dialog: Dialog = {
    confirm: (message, options) =>
      new Promise((resolve) =>
        setRequest({ message, confirmLabel: options?.confirmLabel ?? "Tasdiqlash", alertOnly: false, resolve }),
      ),
    alert: (message) =>
      new Promise((resolve) =>
        setRequest({ message, confirmLabel: "Yopish", alertOnly: true, resolve: () => resolve() }),
      ),
  };

  function close(ok: boolean) {
    request?.resolve(ok);
    setRequest(null);
  }

  useEffect(() => {
    if (!request) return;
    confirmButton.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      request.resolve(false);
      setRequest(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [request]);

  return (
    <DialogContext.Provider value={dialog}>
      {children}
      {request && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="app-dialog-message"
            className="glass-panel-strong w-full max-w-md p-5"
          >
            <p id="app-dialog-message" className="text-sm leading-relaxed text-ivory">
              {request.message}
            </p>
            <div className="mt-5 flex justify-end gap-2">
              {!request.alertOnly && (
                <button type="button" className="btn-ghost" onClick={() => close(false)}>
                  Bekor qilish
                </button>
              )}
              <button ref={confirmButton} type="button" className="btn-gold" onClick={() => close(true)}>
                {request.confirmLabel}
              </button>
            </div>
          </div>
        </div>
      )}
    </DialogContext.Provider>
  );
}

export function useDialog(): Dialog {
  const dialog = useContext(DialogContext);
  if (!dialog) throw new Error("useDialog() needs <DialogProvider> (src/app/layout.tsx)");
  return dialog;
}
