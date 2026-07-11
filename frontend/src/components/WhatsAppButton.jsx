import React, { useState } from 'react';
import { MessageCircle, X } from 'lucide-react';

const WHATSAPP_NUMBER = '919999999999';
const WHATSAPP_MESSAGE = encodeURIComponent('Hi, I would like to learn more about Nischint AI Safety Infrastructure.');

export default function WhatsAppButton() {
  const [tooltip, setTooltip] = useState(false);

  return (
    <div className="fixed bottom-6 right-6 z-50" data-testid="whatsapp-button">
      {tooltip && (
        <div className="absolute bottom-16 right-0 bg-white rounded-xl shadow-xl p-4 w-64 animate-in fade-in slide-in-from-bottom-2">
          <button
            onClick={() => setTooltip(false)}
            className="absolute top-2 right-2 text-slate-400 hover:text-slate-600"
          >
            <X className="w-3.5 h-3.5" />
          </button>
          <p className="text-sm font-semibold text-slate-900 mb-1">Chat with us</p>
          <p className="text-xs text-slate-500 mb-3">Quick queries, pilot interest, or demo requests</p>
          <a
            href={`https://wa.me/${WHATSAPP_NUMBER}?text=${WHATSAPP_MESSAGE}`}
            target="_blank"
            rel="noopener noreferrer"
            className="block w-full text-center py-2 bg-[#25D366] text-white text-sm font-medium rounded-lg hover:bg-[#20bd5a] transition-colors"
            data-testid="whatsapp-chat-link"
          >
            Open WhatsApp
          </a>
        </div>
      )}
      <button
        onClick={() => setTooltip(!tooltip)}
        className="w-14 h-14 bg-[#25D366] rounded-full shadow-lg shadow-emerald-500/20 flex items-center justify-center hover:scale-105 active:scale-95 transition-transform"
        aria-label="WhatsApp Support"
        data-testid="whatsapp-fab"
      >
        <MessageCircle className="w-6 h-6 text-white" />
      </button>
    </div>
  );
}
