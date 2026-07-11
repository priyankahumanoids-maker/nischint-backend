import React, { useState, useEffect } from 'react';
import { Download, X } from 'lucide-react';

export default function InstallPrompt() {
  const [deferredPrompt, setDeferredPrompt] = useState(null);
  const [show, setShow] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    // Don't show if already installed or user dismissed
    if (window.matchMedia('(display-mode: standalone)').matches) return;
    if (sessionStorage.getItem('nischint_install_dismissed')) return;

    const handler = (e) => {
      e.preventDefault();
      setDeferredPrompt(e);
      setShow(true);
    };
    window.addEventListener('beforeinstallprompt', handler);
    return () => window.removeEventListener('beforeinstallprompt', handler);
  }, []);

  const handleInstall = async () => {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    const result = await deferredPrompt.userChoice;
    if (result.outcome === 'accepted') {
      setShow(false);
    }
    setDeferredPrompt(null);
  };

  const dismiss = () => {
    setShow(false);
    setDismissed(true);
    sessionStorage.setItem('nischint_install_dismissed', 'true');
  };

  if (!show || dismissed) return null;

  return (
    <div className="fixed bottom-20 left-0 right-0 z-[90] max-w-[430px] mx-auto px-4" data-testid="install-prompt">
      <div className="p-3.5 rounded-2xl bg-slate-800/95 backdrop-blur-xl border border-teal-500/20 shadow-xl shadow-black/30 flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl bg-teal-500/15 flex items-center justify-center shrink-0">
          <Download className="w-5 h-5 text-teal-400" />
        </div>
        <div className="flex-1">
          <p className="text-xs font-semibold text-white">Install Nischint</p>
          <p className="text-[10px] text-slate-400">Add to home screen for quick access</p>
        </div>
        <button
          onClick={handleInstall}
          className="px-3.5 py-2 rounded-xl bg-teal-400 text-slate-900 text-[11px] font-bold active:scale-95 transition-transform shrink-0"
          data-testid="install-btn"
        >
          Install
        </button>
        <button onClick={dismiss} aria-label="Dismiss install prompt" data-testid="install-dismiss-btn" className="p-1 rounded-full active:bg-slate-700 shrink-0">
          <X className="w-3.5 h-3.5 text-slate-400" aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
