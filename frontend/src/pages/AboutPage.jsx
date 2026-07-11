// SF-01 v2 — DPDP-compliant About page.
//
// Content sourced verbatim from the legal artifact provided 2026-05-21.
// Brand palette matches the source HTML (navy + cyan) and the existing
// nischint.care marketing surfaces.
import React from 'react';
import { Helmet } from 'react-helmet-async';
import { Link } from 'react-router-dom';

const STATS = [
  { num: '320+',   desc: 'API Endpoints' },
  { num: '78',     desc: 'AI Engines' },
  { num: '5',      desc: 'Detection Layers' },
  { num: '3',      desc: 'User Archetypes' },
  { num: 'Mumbai', desc: 'Headquartered' },
];

const DETECTION_LAYERS = [
  { icon: '🫀', title: 'Fall Detection',           body: 'Accelerometer + AI fusion to detect falls in real time and trigger immediate guardian alerts.' },
  { icon: '🗺️', title: 'Route Deviation',          body: 'Live GPS monitoring against expected routes. Alerts guardians when a user deviates beyond safe thresholds.' },
  { icon: '🎙️', title: 'Voice Distress Detection', body: 'On-device AI analysis of ambient audio to detect screams, panic, and distress signals without storing audio.' },
  { icon: '🧭', title: 'Wandering Detection',      body: 'Pattern-based AI for senior users — detects unusual movement patterns and time-out-of-home anomalies.' },
  { icon: '🚗', title: 'Pickup Anomaly',           body: 'Validates school pickups against pre-registered guardian profiles. Flags unauthorised pickup attempts.' },
];

const COMPANY_FACTS = [
  { icon: '🏢', label: 'Legal Entity',  value: 'NISCHINT Technology Private Limited' },
  { icon: '📍', label: 'Headquarters',  value: 'Mumbai, Maharashtra, India' },
  { icon: '⚖️', label: 'Incorporation', value: 'Companies Act, 2013 — Indian Private Limited' },
  { icon: '☁️', label: 'Data Hosting',  value: 'AWS Mumbai (ap-south-1) — Database + Auth + Compute · DPDP-aligned' },
  { icon: '🛡️', label: 'Compliance',    value: 'DPDP Act 2023 · Draft DPDP Rules 2026' },
  { icon: '📱', label: 'Platform',      value: 'iOS & Android (React Native / Expo)' },
];

const STACK_TAGS = [
  'React Native / Expo', 'FastAPI (Python)', 'PostgreSQL + PostGIS', 'NeonDB',
  'AWS Cognito', 'Upstash Redis', 'AWS Mumbai (ap-south-1) — Database', 'Twilio', 'SendGrid',
  'Firebase FCM', 'Cloudflare', 'n8n Cloud', 'EAS (Expo Application Services)',
  'SSE Real-time Events', 'On-device AI (Voice Distress)',
];

export default function AboutPage() {
  return (
    <div className="min-h-screen bg-[#0B1F3A] text-[#E8EDF2]" data-testid="about-page">
      <Helmet>
        <title>About | NISCHINT — India&apos;s AI Safety OS</title>
        <meta name="description" content="NISCHINT is building India's AI safety infrastructure for women, children, and seniors — real-time, intelligent, and built in Mumbai." />
      </Helmet>

      {/* Header */}
      <header className="border-b border-[#1E3A5F] px-6 py-4 flex items-center gap-3">
        <div className="text-xl font-extrabold tracking-widest text-white">
          NISCH<span className="text-[#00C6FF]">INT</span>
        </div>
        <div className="flex-1" />
        <Link to="/" className="text-sm text-[#00C6FF] hover:underline" data-testid="about-back-link">
          ← Back to nischint.care
        </Link>
      </header>

      {/* Hero */}
      <div className="border-b border-[#1E3A5F] bg-gradient-to-br from-[#0B1F3A] to-[#1E3A5F] px-6 pt-20 pb-16 text-center">
        <div className="inline-block rounded-full border border-[#00C6FF]/30 bg-[#00C6FF]/10 px-3.5 py-1 text-[12px] font-semibold uppercase tracking-wide text-[#00C6FF]">
          About NISCHINT
        </div>
        <h1 className="mx-auto mt-5 max-w-3xl text-4xl font-extrabold text-white sm:text-5xl lg:text-6xl">
          Protecting India&apos;s<br /><span className="text-[#00C6FF]">Most Vulnerable</span>
        </h1>
        <p className="mx-auto mt-5 max-w-2xl text-[15px] text-[#8BA3C4]">
          We&apos;re building the AI safety infrastructure that every woman, child, and senior in India deserves — real-time, intelligent, and built in Mumbai.
        </p>
        <div className="mt-7 flex flex-wrap justify-center gap-3">
          <Link to="/pilot" className="rounded-md bg-[#00C6FF] px-6 py-2.5 text-sm font-semibold text-[#0B1F3A] hover:bg-[#00B0E0]" data-testid="about-cta-pilot">
            Request a Pilot
          </Link>
          <a href="mailto:hello@nischint.app" className="rounded-md border border-[#00C6FF] px-6 py-2.5 text-sm font-semibold text-[#00C6FF] hover:bg-[#00C6FF]/10" data-testid="about-cta-contact">
            Get in Touch
          </a>
        </div>
      </div>

      <div className="mx-auto max-w-5xl px-6 py-16">
        {/* Mission */}
        <div className="mb-16" data-testid="about-mission">
          <div className="mb-3 text-[12px] font-bold uppercase tracking-widest text-[#00C6FF]">Our Mission</div>
          <h2 className="mb-4 text-3xl font-bold text-white sm:text-4xl">Make Indian cities safe for those who need it most</h2>
          <p className="max-w-3xl text-[15px] leading-relaxed text-[#8BA3C4]">
            India has 472 million people under 18, millions of women navigating unsafe public spaces, and a rapidly growing senior population living independently. NISCHINT fuses AI, mobile technology, and real-time guardian networks to give vulnerable users — and the people who care for them — a safety infrastructure that actually works.
          </p>
        </div>

        {/* Stats */}
        <div className="mb-16 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5" data-testid="about-stats">
          {STATS.map((s) => (
            <div key={s.desc} className="rounded-xl border border-[#1E3A5F] bg-[#112240] p-5 text-center">
              <div className="text-2xl font-extrabold text-[#00C6FF]">{s.num}</div>
              <div className="mt-1.5 text-[12px] uppercase tracking-wide text-[#4A6FA5]">{s.desc}</div>
            </div>
          ))}
        </div>

        {/* Founder */}
        <div className="mb-16" data-testid="about-founder">
          <div className="mb-3 text-[12px] font-bold uppercase tracking-widest text-[#00C6FF]">Founder</div>
          <div className="grid gap-6 rounded-2xl border border-[#1E3A5F] bg-[#112240] p-7 sm:grid-cols-[120px_1fr] sm:items-start">
            <div className="flex h-[120px] w-[120px] items-center justify-center rounded-full bg-gradient-to-br from-[#00C6FF] to-[#0080A0] text-2xl font-extrabold text-[#0B1F3A]">
              FS
            </div>
            <div>
              <h3 className="text-2xl font-bold text-white">Feroz Shaikh</h3>
              <div className="mt-1 text-[14px] text-[#00C6FF]">Founder &amp; CEO, NISCHINT Technology Private Limited</div>
              <div className="mt-4 space-y-3 text-[15px] text-[#8BA3C4]">
                <p>Feroz brings 25+ years of enterprise technology leadership — building and scaling 200+ person engineering teams across cloud infrastructure, regulated platforms, and large-scale IT services. He has led global delivery operations across multiple technology organisations, managing complex, multi-cloud architectures at scale.</p>
                <p>He founded NISCHINT after recognising a fundamental gap in India&apos;s safety technology landscape: the platforms protecting India&apos;s most vulnerable users were either fragmented, hardware-dependent, or simply didn&apos;t exist. NISCHINT is his answer — a fully mobile, AI-native, person-centric safety OS built ground-up for India.</p>
                <p>Feroz is hands-on across the full stack: product architecture, FastAPI backend, React Native mobile, AI agent design, and GTM strategy. He also runs Spotlight (entertainment news portal) and AISA OS (AI-powered media campus operating system for Atal Innovation).</p>
              </div>
              <div className="mt-5 flex flex-wrap gap-2">
                <a href="https://linkedin.com/in/ferozshaikh1" target="_blank" rel="noreferrer" className="rounded-md border border-[#1E3A5F] bg-[#0B1F3A] px-4 py-1.5 text-[13px] text-[#8BA3C4] hover:border-[#00C6FF] hover:text-[#00C6FF]">🔗 LinkedIn</a>
                <a href="mailto:hello@nischint.app" className="rounded-md border border-[#1E3A5F] bg-[#0B1F3A] px-4 py-1.5 text-[13px] text-[#8BA3C4] hover:border-[#00C6FF] hover:text-[#00C6FF]">✉️ hello@nischint.app</a>
                <Link to="/" className="rounded-md border border-[#1E3A5F] bg-[#0B1F3A] px-4 py-1.5 text-[13px] text-[#8BA3C4] hover:border-[#00C6FF] hover:text-[#00C6FF]">🌐 nischint.care</Link>
              </div>
            </div>
          </div>
        </div>

        {/* Detection Layers */}
        <div className="mb-16" data-testid="about-product">
          <div className="mb-3 text-[12px] font-bold uppercase tracking-widest text-[#00C6FF]">The Product</div>
          <h2 className="mb-6 text-3xl font-bold text-white sm:text-4xl">NISCHINT Safety Brain — 5 Detection Layers</h2>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {DETECTION_LAYERS.map((d) => (
              <div key={d.title} className="rounded-xl border border-[#1E3A5F] bg-[#112240] p-5" data-testid={`about-detection-${d.title.toLowerCase().replace(/[^a-z]+/g, '-').replace(/(^-|-$)/g, '')}`}>
                <div className="mb-2 text-3xl" aria-hidden>{d.icon}</div>
                <h4 className="text-[15px] font-bold text-white">{d.title}</h4>
                <p className="mt-2 text-[14px] text-[#8BA3C4]">{d.body}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Company Facts */}
        <div className="mb-16" data-testid="about-company">
          <div className="mb-3 text-[12px] font-bold uppercase tracking-widest text-[#00C6FF]">Company</div>
          <h2 className="mb-6 text-3xl font-bold text-white sm:text-4xl">NISCHINT Technology Private Limited</h2>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {COMPANY_FACTS.map((f) => (
              <div key={f.label} className="flex items-start gap-3 rounded-xl border border-[#1E3A5F] bg-[#112240] p-4">
                <div className="text-2xl" aria-hidden>{f.icon}</div>
                <div>
                  <div className="text-[12px] uppercase tracking-wide text-[#4A6FA5]">{f.label}</div>
                  <div className="mt-0.5 text-[14px] font-medium text-[#C8D8E8]">{f.value}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Tech Stack */}
        <div className="mb-16" data-testid="about-tech-stack">
          <div className="mb-3 text-[12px] font-bold uppercase tracking-widest text-[#00C6FF]">Technology</div>
          <h2 className="mb-2 text-3xl font-bold text-white sm:text-4xl">Built on Production-Grade Infrastructure</h2>
          <p className="mb-6 text-[15px] text-[#8BA3C4]">No no-code shortcuts. Every layer is purpose-built for safety at scale.</p>
          <div className="flex flex-wrap gap-2">
            {STACK_TAGS.map((t) => (
              <span key={t} className="rounded-full border border-[#1E3A5F] bg-[#112240] px-3.5 py-1.5 text-[13px] text-[#8BA3C4]">{t}</span>
            ))}
          </div>
        </div>

        {/* CTA */}
        <div className="rounded-2xl border border-[#00C6FF]/25 bg-gradient-to-br from-[#00C6FF]/[0.08] to-transparent p-8 text-center" data-testid="about-cta-section">
          <h2 className="text-3xl font-bold text-white sm:text-4xl">Ready to deploy NISCHINT?</h2>
          <p className="mx-auto mt-3 max-w-2xl text-[15px] text-[#8BA3C4]">
            Whether you&apos;re a school, housing society, corporate campus, or family — we have a deployment path for you. Get in touch to explore a pilot.
          </p>
          <div className="mt-6 flex flex-wrap justify-center gap-3">
            <Link to="/pilot" className="rounded-md bg-[#00C6FF] px-6 py-2.5 text-sm font-semibold text-[#0B1F3A] hover:bg-[#00B0E0]">
              Request a Pilot
            </Link>
            <a href="mailto:partners@nischint.app" className="rounded-md border border-[#00C6FF] px-6 py-2.5 text-sm font-semibold text-[#00C6FF] hover:bg-[#00C6FF]/10">
              Partner With Us
            </a>
          </div>
        </div>
      </div>

      <footer className="border-t border-[#1E3A5F] bg-[#071428] px-6 py-6 text-center text-[13px] text-[#2A4A70]">
        © 2026 NISCHINT Technology Private Limited · Mumbai, India &nbsp;|&nbsp;
        <Link to="/" className="text-[#4A6FA5] hover:text-[#00C6FF]">Home</Link> &nbsp;|&nbsp;
        <Link to="/about" className="text-[#4A6FA5] hover:text-[#00C6FF]">About</Link> &nbsp;|&nbsp;
        <Link to="/privacy-policy" className="text-[#4A6FA5] hover:text-[#00C6FF]">Privacy Policy</Link> &nbsp;|&nbsp;
        <a href="mailto:hello@nischint.app" className="text-[#4A6FA5] hover:text-[#00C6FF]">hello@nischint.app</a>
      </footer>
    </div>
  );
}
