import React from 'react';
import { SocialIcon, trackSocialClick } from '../utils/socialLinks';

const CTA_SOCIALS = [
  { key: 'instagram', label: 'Follow on Instagram', url: 'https://www.instagram.com/nischintcare/', hover: 'hover:border-pink-500/40 hover:bg-pink-500/[0.05] hover:text-pink-400' },
  { key: 'youtube', label: 'Watch on YouTube', url: 'https://www.youtube.com/@NischintCare', hover: 'hover:border-red-500/40 hover:bg-red-500/[0.05] hover:text-red-400' },
  { key: 'linkedin', label: 'Connect on LinkedIn', url: 'https://www.linkedin.com/in/nischintcare/', hover: 'hover:border-blue-500/40 hover:bg-blue-500/[0.05] hover:text-blue-400' },
];

export default function SocialCTASection() {
  return (
    <section className="py-16 px-6 border-t border-slate-800/40" data-testid="social-cta-section">
      <div className="max-w-3xl mx-auto text-center">
        <p className="text-xs text-teal-400 font-bold uppercase tracking-widest mb-3">Community</p>
        <h2 className="text-2xl sm:text-3xl font-bold text-white mb-4">Join 1000+ People Staying Protected with NISCHINT</h2>
        <p className="text-sm text-slate-400 mb-8 max-w-md mx-auto">Follow us for safety tips, product updates, and real stories of protection.</p>
        <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
          {CTA_SOCIALS.map(s => (
            <a
              key={s.key}
              href={s.url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => trackSocialClick(s.key)}
              className={`flex items-center gap-2.5 px-5 py-3 rounded-xl bg-white/[0.02] border border-slate-800/40 text-slate-300 text-sm font-medium transition-all ${s.hover}`}
              data-testid={`social-cta-${s.key}`}
            >
              <SocialIcon platform={s.key} size={16} />
              {s.label}
            </a>
          ))}
        </div>
      </div>
    </section>
  );
}
