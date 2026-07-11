import React, { useState } from 'react';
import { Share2 } from 'lucide-react';
import { SOCIALS_FLOAT, SocialIcon, trackSocialClick } from '../utils/socialLinks';

export default function FloatingSocialBar() {
  const [expanded, setExpanded] = useState(false);

  return (
    <>
      {/* Desktop: vertical sticky bar */}
      <div className="hidden md:flex fixed right-4 top-1/2 -translate-y-1/2 z-40 flex-col gap-2" data-testid="floating-social-desktop">
        {SOCIALS_FLOAT.map(s => (
          <a
            key={s.key}
            href={s.url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={() => trackSocialClick(s.key)}
            className={`w-10 h-10 rounded-xl bg-[#111827] border border-slate-800/50 flex items-center justify-center text-slate-500 ${s.hover} transition-all hover:scale-110 hover:border-slate-600`}
            title={s.name}
            data-testid={`float-social-${s.key}`}
          >
            <SocialIcon platform={s.key} size={16} />
          </a>
        ))}
      </div>

      {/* Mobile: expandable FAB */}
      <div className="md:hidden fixed left-4 bottom-20 z-40" data-testid="floating-social-mobile">
        {expanded && (
          <div className="flex flex-col gap-2 mb-2 animate-fade-in">
            {SOCIALS_FLOAT.map(s => (
              <a
                key={s.key}
                href={s.url}
                target="_blank"
                rel="noopener noreferrer"
                onClick={() => trackSocialClick(s.key)}
                className={`w-10 h-10 rounded-xl bg-[#111827] border border-slate-800/50 flex items-center justify-center text-slate-500 ${s.hover} transition-all`}
                data-testid={`float-mobile-${s.key}`}
              >
                <SocialIcon platform={s.key} size={16} />
              </a>
            ))}
          </div>
        )}
        <button
          type="button"
          aria-label={expanded ? "Hide social links" : "Show social links"}
          aria-expanded={expanded}
          onClick={() => setExpanded(!expanded)}
          className="w-11 h-11 rounded-full bg-[#111827] border border-slate-700/60 flex items-center justify-center text-slate-400 hover:text-white transition-colors shadow-lg"
          data-testid="float-social-toggle"
        >
          <Share2 className="w-4 h-4" />
        </button>
      </div>

      <style>{`
        @keyframes fade-in { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
        .animate-fade-in { animation: fade-in 0.2s ease-out; }
      `}</style>
    </>
  );
}
