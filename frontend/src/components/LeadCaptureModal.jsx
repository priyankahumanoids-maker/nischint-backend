import React, { useState, useRef, useEffect } from 'react';
import { X, ArrowRight, Loader2, Phone, User, CheckCircle } from 'lucide-react';
import { funnel, geo } from '../utils/funnelTracker';

const API_BASE = '';  // same-origin — no CORS, no stale baked-URL risk

export default function LeadCaptureModal({ isOpen, onClose, page, whatsappLink }) {
  const [phone, setPhone] = useState('');
  const [name, setName] = useState('');
  const [loading, setLoading] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState('');
  const phoneRef = useRef(null);
  const trackedOpen = useRef(false);

  // Reset state when modal opens
  useEffect(() => {
    if (isOpen) {
      setPhone('');
      setName('');
      setConfirmed(false);
      setLoading(false);
      setError('');
      document.body.style.overflow = 'hidden';
      setTimeout(() => phoneRef.current?.focus(), 100);
      if (!trackedOpen.current) {
        funnel.modalOpen(page);
        // GEO CTA tracking — extract city/variant from URL slug
        const slug = window.location.pathname.replace(/^\//, '').replace(/\/$/, '');
        const geoMatch = slug.match(/^(?:(best|personal)-)?(?:women|kids|family)-safety-app-(.+)$/);
        if (geoMatch) {
          geo.ctaClick({ city: geoMatch[2].charAt(0).toUpperCase() + geoMatch[2].slice(1), variant: geoMatch[1] || 'default', type: page });
        } else if (['women', 'kids', 'family'].includes(page)) {
          geo.ctaClick({ type: page });
        }
        trackedOpen.current = true;
      }
    } else {
      document.body.style.overflow = '';
      trackedOpen.current = false;
    }
    return () => { document.body.style.overflow = ''; };
  }, [isOpen, page]);

  const submit = async () => {
    const trimmed = phone.replace(/\s/g, '');
    if (!trimmed || trimmed.length < 10) {
      setError('Please enter a valid phone number');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 5000);
      await fetch(`${API_BASE}/api/enquiry`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source: 'seo_page',
          page,
          intent: 'high',
          phone: trimmed,
          name: name.trim() || null,
          message: 'Lead captured from SEO page',
        }),
        signal: ctrl.signal,
      });
      clearTimeout(timer);
    } catch (_) {}
    setLoading(false);
    // Show confirmation AND open WhatsApp simultaneously
    setConfirmed(true);
    funnel.leadSubmit(page, trimmed);
    funnel.whatsappRedirect(page);
    window.open(whatsappLink, '_blank');
    // Auto-close modal after 1.5s
    setTimeout(() => { setConfirmed(false); onClose(); }, 1500);
  };

  const skip = () => {
    funnel.whatsappRedirect(page);
    try {
      fetch(`${API_BASE}/api/enquiry`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source: 'seo_page',
          page,
          intent: 'high',
          message: 'CTA clicked from SEO page (skipped lead capture)',
        }),
      });
    } catch (_) {}
    onClose();
    window.open(whatsappLink, '_blank');
  };

  if (!isOpen) return null;

  const gradients = {
    women: 'from-rose-500 to-pink-600',
    kids: 'from-blue-500 to-indigo-600',
    family: 'from-emerald-500 to-teal-600',
  };
  const rings = {
    women: 'focus:ring-rose-500/40 border-rose-500/30',
    kids: 'focus:ring-blue-500/40 border-blue-500/30',
    family: 'focus:ring-emerald-500/40 border-emerald-500/30',
  };
  const checks = { women: 'text-rose-400', kids: 'text-blue-400', family: 'text-emerald-400' };
  const grad = gradients[page] || gradients.family;
  const ring = rings[page] || rings.family;
  const check = checks[page] || checks.family;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-end sm:items-center justify-center"
      onClick={confirmed ? undefined : onClose}
      data-testid="lead-capture-overlay"
    >
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
      <div
        className="relative w-full sm:max-w-md bg-[#111827] border border-slate-700/60 rounded-t-3xl sm:rounded-2xl p-6 sm:p-8 z-10 animate-slide-up"
        onClick={e => e.stopPropagation()}
        data-testid="lead-capture-modal"
      >
        {confirmed ? (
          <div className="flex flex-col items-center justify-center py-6 animate-fade-in" data-testid="lead-capture-confirmed">
            <div className={`w-14 h-14 rounded-full bg-white/5 flex items-center justify-center mb-4 ${check}`}>
              <CheckCircle className="w-8 h-8" />
            </div>
            <p className="text-lg font-semibold text-white mb-1">You're protected.</p>
            <p className="text-sm text-slate-400">We'll reach out shortly.</p>
            <p className="text-xs text-slate-500 mt-3">Connecting you to WhatsApp...</p>
          </div>
        ) : (
          <>
            <button
              onClick={onClose}
              className="absolute top-4 right-4 w-8 h-8 rounded-full bg-white/5 flex items-center justify-center text-slate-400 hover:text-white hover:bg-white/10 transition-colors"
              data-testid="lead-capture-close"
            >
              <X className="w-4 h-4" />
            </button>

            <h3 className="text-xl font-bold text-white mb-1">One last step</h3>
            <p className="text-sm text-slate-400 mb-6">Share your number and we'll reach out on WhatsApp</p>

            <div className="space-y-4">
              <div>
                <div className="relative">
                  <Phone className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
                  <input
                    ref={phoneRef}
                    type="tel"
                    inputMode="numeric"
                    placeholder="Phone number *"
                    value={phone}
                    onChange={e => { setPhone(e.target.value); setError(''); }}
                    onKeyDown={e => e.key === 'Enter' && submit()}
                    className={`w-full pl-10 pr-4 py-3.5 bg-white/5 border rounded-xl text-white placeholder-slate-500 text-base outline-none focus:ring-2 transition-all ${ring} ${error ? 'border-red-500/60' : ''}`}
                    data-testid="lead-capture-phone"
                  />
                </div>
                {error && <p className="text-xs text-red-400 mt-1.5 pl-1" data-testid="lead-capture-error">{error}</p>}
              </div>

              <div className="relative">
                <User className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
                <input
                  type="text"
                  placeholder="Name (optional)"
                  value={name}
                  onChange={e => setName(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && submit()}
                  className={`w-full pl-10 pr-4 py-3.5 bg-white/5 border border-slate-700/60 rounded-xl text-white placeholder-slate-500 text-base outline-none focus:ring-2 transition-all ${ring}`}
                  data-testid="lead-capture-name"
                />
              </div>

              <button
                onClick={submit}
                disabled={loading}
                className={`w-full py-3.5 bg-gradient-to-r ${grad} text-white font-semibold rounded-xl hover:shadow-lg transition-all text-base flex items-center justify-center gap-2`}
                data-testid="lead-capture-submit"
              >
                {loading ? <><Loader2 className="w-5 h-5 animate-spin" /> Securing your request...</> : <>Continue to WhatsApp <ArrowRight className="w-4 h-4" /></>}
              </button>

              <button
                onClick={skip}
                className="w-full py-2.5 text-sm text-slate-500 hover:text-slate-300 transition-colors"
                data-testid="lead-capture-skip"
              >
                Continue without details
              </button>
            </div>
          </>
        )}
      </div>

      <style>{`
        @keyframes slide-up {
          from { transform: translateY(100%); opacity: 0; }
          to { transform: translateY(0); opacity: 1; }
        }
        .animate-slide-up { animation: slide-up 0.25s ease-out; }
        @keyframes fade-in {
          from { opacity: 0; transform: scale(0.95); }
          to { opacity: 1; transform: scale(1); }
        }
        .animate-fade-in { animation: fade-in 0.2s ease-out; }
      `}</style>
    </div>
  );
}
