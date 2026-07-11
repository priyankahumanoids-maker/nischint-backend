/**
 * Social media links, icons, and tracking for NISCHINT.
 */
import React from 'react';
import posthog from 'posthog-js';

export const SOCIALS = [
  { name: 'Instagram', key: 'instagram', url: 'https://www.instagram.com/nischintcare/', hover: 'hover:text-pink-400' },
  { name: 'LinkedIn', key: 'linkedin', url: 'https://www.linkedin.com/in/nischintcare/', hover: 'hover:text-blue-400' },
  { name: 'X', key: 'twitter', url: 'https://x.com/nischintcare', hover: 'hover:text-white' },
  { name: 'YouTube', key: 'youtube', url: 'https://www.youtube.com/@NischintCare', hover: 'hover:text-red-400' },
  { name: 'Threads', key: 'threads', url: 'https://www.threads.com/@nischintcare', hover: 'hover:text-white' },
  { name: 'Pinterest', key: 'pinterest', url: 'https://www.pinterest.com/nischintcare/', hover: 'hover:text-red-500' },
];

export const SOCIALS_FLOAT = SOCIALS.filter(s => ['instagram', 'linkedin', 'youtube'].includes(s.key));

export function trackSocialClick(platform) {
  try { posthog.capture('social_click', { platform }); } catch (_) {}
}

export const ORG_JSONLD_STRING = JSON.stringify({
  '@context': 'https://schema.org',
  '@type': 'Organization',
  name: 'NISCHINT',
  url: 'https://nischint.care',
  sameAs: SOCIALS.map(s => s.url),
});

export function useStructuredData() {
  React.useEffect(() => {
    const existing = document.querySelector('script[data-nischint-ld]');
    if (existing) return;
    const script = document.createElement('script');
    script.type = 'application/ld+json';
    script.setAttribute('data-nischint-ld', 'true');
    script.textContent = ORG_JSONLD_STRING;
    document.head.appendChild(script);
    return () => { try { document.head.removeChild(script); } catch (_) {} };
  }, []);
}

// SVG icon paths (compact)
const paths = {
  instagram: <><rect x="2" y="2" width="20" height="20" rx="5" fill="none" stroke="currentColor" strokeWidth="1.5"/><circle cx="12" cy="12" r="5" fill="none" stroke="currentColor" strokeWidth="1.5"/><circle cx="17.5" cy="6.5" r="1.2" fill="currentColor"/></>,
  linkedin: <><path d="M16 8a6 6 0 016 6v7h-4v-7a2 2 0 00-4 0v7h-4v-7a6 6 0 016-6z" fill="none" stroke="currentColor" strokeWidth="1.5"/><rect x="2" y="9" width="4" height="12" fill="none" stroke="currentColor" strokeWidth="1.5"/><circle cx="4" cy="4" r="2" fill="none" stroke="currentColor" strokeWidth="1.5"/></>,
  twitter: <path d="M4 4l6.5 8L4 20h2l5.3-6.4L15.5 20H20l-6.8-8.4L19.5 4H17.5l-4.9 5.9L8.5 4H4z" fill="none" stroke="currentColor" strokeWidth="1.3"/>,
  youtube: <><rect x="2" y="4" width="20" height="16" rx="4" fill="none" stroke="currentColor" strokeWidth="1.5"/><polygon points="10,8 16,12 10,16" fill="currentColor"/></>,
  threads: <><circle cx="12" cy="12" r="9.5" fill="none" stroke="currentColor" strokeWidth="1.5"/><path d="M15.5 11c-.2-2-1.5-3.3-3.5-3.3s-3.3 1.5-3.3 3.8c0 2.5 1.3 4 3.5 4 1.5 0 2.5-.7 3-1.8" fill="none" stroke="currentColor" strokeWidth="1.3"/><path d="M15.5 11c.1.5.1 1 .1 1.5 0 2-1 3-2.5 3" fill="none" stroke="currentColor" strokeWidth="1.3"/></>,
  pinterest: <><circle cx="12" cy="12" r="9.5" fill="none" stroke="currentColor" strokeWidth="1.5"/><path d="M12 6c-3.3 0-5 2.5-5 4.5 0 1.3.5 2.4 1.5 2.8.2.1.3 0 .4-.2l.2-1c0-.1 0-.2-.1-.3-.4-.5-.6-1.1-.6-1.8C8.4 8.2 9.9 7 12 7c1.8 0 3 1 3 2.5 0 2-.9 3.5-2 3.5-.7 0-1.2-.5-1-1.2.2-.8.5-1.5.5-2 0-.5-.3-.9-.8-.9-.7 0-1.2.7-1.2 1.5 0 .6.2 1 .2 1l-.8 3.5c-.2.8 0 2 0 2.1 0 0 .1 0 .1 0 .1-.1 1-1.3 1.3-2.3.1-.3.5-1.8.5-1.8.3.5 1 .9 1.7.9 2.2 0 3.8-2 3.8-4.5C17.2 8.2 15.2 6 12 6z" fill="currentColor"/></>,
};

export function SocialIcon({ platform, size = 18 }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none">{paths[platform]}</svg>;
}
