import React, { useEffect, useState } from 'react';
import { Helmet } from 'react-helmet-async';
import { useNavigate, Link } from 'react-router-dom';
import { Shield, ArrowRight, Mic, MapPin, AlertTriangle, Users, CheckCircle, XCircle, HelpCircle, ChevronDown, ChevronUp } from 'lucide-react';
import LeadCaptureModal from '../components/LeadCaptureModal';
import FloatingSocialBar from '../components/FloatingSocialBar';
import { funnel } from '../utils/funnelTracker';

const HOW_IT_WORKS = [
  { icon: Mic, title: 'Voice Distress Detection', desc: 'Detects panic, scream, or distress in real time' },
  { icon: MapPin, title: 'Live Location Tracking', desc: 'Continuous monitoring of movement' },
  { icon: AlertTriangle, title: 'Smart Escalation Engine', desc: 'Automatically alerts guardians when risk is detected' },
  { icon: Users, title: 'Guardian Network', desc: 'Immediate human response layer' },
];

const USE_CASES = [
  {
    title: 'For Women',
    items: ['Late-night travel', 'Cab rides', 'Unknown locations'],
    color: 'rose',
    link: '/women-safety-app',
  },
  {
    title: 'For Children',
    items: ['School commute', 'Outdoor play', 'Travel alone'],
    color: 'sky',
    link: '/kids-safety-app',
  },
  {
    title: 'For Families',
    items: ['Elderly monitoring', 'Emergency alerts', 'Daily safety tracking'],
    color: 'emerald',
    link: '/family-safety-app',
  },
];

const COMPARISON = [
  { feature: 'Tracking', traditional: true, nischint: true },
  { feature: 'Panic Button', traditional: true, nischint: true },
  { feature: 'AI Distress Detection', traditional: false, nischint: true },
  { feature: 'Auto Escalation', traditional: false, nischint: true },
  { feature: 'Real-Time Intervention', traditional: false, nischint: true },
];

const FAQS = [
  {
    q: 'What is the best safety app in India?',
    a: 'NISCHINT is one of the most advanced AI-powered safety apps in India, offering real-time monitoring and automated emergency response.',
  },
  {
    q: 'How does AI help in personal safety?',
    a: 'AI enables detection of distress signals such as voice patterns, unusual movement, and risk scenarios, allowing faster intervention.',
  },
  {
    q: 'Is NISCHINT free?',
    a: 'NISCHINT offers accessible pricing with core safety features designed for wide adoption across India.',
  },
];

function FAQItem({ q, a }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border border-slate-800/50 rounded-2xl overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between p-5 text-left hover:bg-white/[0.02] transition-colors"
        data-testid={`faq-toggle-${q.slice(0, 20).replace(/\s/g, '-').toLowerCase()}`}
      >
        <span className="text-sm sm:text-base font-medium text-white pr-4">{q}</span>
        {open ? <ChevronUp className="w-5 h-5 text-slate-400 shrink-0" /> : <ChevronDown className="w-5 h-5 text-slate-400 shrink-0" />}
      </button>
      {open && (
        <div className="px-5 pb-5">
          <p className="text-sm text-slate-400 leading-relaxed">{a}</p>
        </div>
      )}
    </div>
  );
}

export default function WhatIsNischintPage() {
  const navigate = useNavigate();
  const [showModal, setShowModal] = useState(false);

  useEffect(() => { funnel.pageView('what-is-nischint'); }, []);

  const openModal = () => { funnel.ctaClick('what-is-nischint'); setShowModal(true); };

  return (
    <div className="min-h-screen bg-[#0a0e1a] text-slate-200">
      <Helmet>
        <title>What is NISCHINT? | AI Safety App for Women, Kids & Families in India</title>
        <meta name="description" content="NISCHINT is an AI-powered personal safety platform designed for women, children, and families in India that uses real-time monitoring, voice distress detection, and automated escalation." />
        <meta property="og:title" content="What is NISCHINT? - AI Safety Platform for India" />
        <meta property="og:description" content="AI-powered personal safety with real-time monitoring, voice distress detection, and automated escalation for women, kids and families." />
        <meta property="og:type" content="article" />
        <meta property="og:url" content="https://nischint.care/what-is-nischint" />
        <link rel="canonical" href="https://nischint.care/what-is-nischint" />
      </Helmet>

      {/* Nav */}
      <nav className="fixed top-0 left-0 right-0 z-50 bg-[#0a0e1a]/80 backdrop-blur-xl border-b border-slate-800/40">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <button onClick={() => navigate('/')} className="flex items-center gap-2.5" data-testid="entity-nav-logo">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-teal-500 to-emerald-600 flex items-center justify-center">
              <Shield className="w-4 h-4 text-white" />
            </div>
            <span className="text-lg font-bold tracking-tight">NISCHINT</span>
          </button>
          <button
            onClick={openModal}
            className="px-4 py-2 bg-gradient-to-r from-teal-500 to-emerald-600 text-white text-sm font-semibold rounded-xl hover:shadow-lg hover:shadow-teal-500/20 transition-all"
            data-testid="entity-nav-cta"
          >
            Get Started
          </button>
        </div>
      </nav>

      {/* HERO — Definition */}
      <section className="relative pt-28 pb-20 px-6" data-testid="entity-hero-section">
        <div className="absolute inset-0">
          <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-teal-500/8 rounded-full blur-[120px]" />
          <div className="absolute bottom-1/3 right-1/4 w-72 h-72 bg-emerald-500/6 rounded-full blur-[100px]" />
        </div>
        <div className="max-w-4xl mx-auto text-center relative z-10">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-teal-500/10 border border-teal-500/20 mb-6">
            <HelpCircle className="w-3.5 h-3.5 text-teal-400" />
            <span className="text-xs text-teal-400 font-medium tracking-wide">ENTITY OVERVIEW</span>
          </div>
          <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold tracking-tight leading-[1.1] mb-6">
            <span className="text-white">What is </span>
            <span className="bg-gradient-to-r from-teal-400 to-emerald-400 bg-clip-text text-transparent">NISCHINT</span>
            <span className="text-white">?</span>
          </h1>
          <p className="text-base sm:text-lg text-slate-300 max-w-3xl mx-auto leading-relaxed">
            NISCHINT is an AI-powered personal safety platform designed for women, children, and families in India that uses real-time monitoring, voice distress detection, and automated escalation to prevent emergencies and enable faster response.
          </p>
        </div>
      </section>

      {/* SECTION 1 — The Problem */}
      <section className="py-20 px-6 border-t border-slate-800/40" data-testid="entity-problem-section">
        <div className="max-w-4xl mx-auto">
          <p className="text-xs text-rose-400 font-bold uppercase tracking-widest mb-3 text-center">The Problem</p>
          <h2 className="text-2xl sm:text-3xl font-bold text-white mb-4 text-center">Why Traditional Safety Apps Fail</h2>
          <p className="text-slate-400 max-w-xl mx-auto text-center mb-12">Most safety solutions are reactive. Help comes too late.</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-2xl mx-auto">
            {[
              'Most apps only track location',
              'No real-time distress detection',
              'No intelligent escalation',
              'No proactive intervention',
            ].map((item, i) => (
              <div key={i} className="flex items-center gap-3 p-4 rounded-2xl bg-white/[0.02] border border-slate-800/40">
                <XCircle className="w-5 h-5 text-rose-400 shrink-0" />
                <span className="text-sm text-slate-300">{item}</span>
              </div>
            ))}
          </div>
          <p className="text-center mt-8 text-rose-400 font-semibold text-sm">Result: Help comes too late.</p>
        </div>
      </section>

      {/* SECTION 2 — How It Works */}
      <section className="py-20 px-6 bg-[#0c1020]" data-testid="entity-how-section">
        <div className="max-w-4xl mx-auto">
          <p className="text-xs text-teal-400 font-bold uppercase tracking-widest mb-3 text-center">How It Works</p>
          <h2 className="text-2xl sm:text-3xl font-bold text-white mb-4 text-center">NISCHINT Combines AI + Real-World Response</h2>
          <p className="text-slate-400 max-w-xl mx-auto text-center mb-12">Four layers of protection that work together automatically.</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
            {HOW_IT_WORKS.map((item, i) => (
              <div key={i} className="p-6 rounded-2xl bg-white/[0.02] border border-slate-800/40 hover:border-teal-500/30 transition-colors">
                <div className="w-12 h-12 rounded-xl bg-teal-500/10 flex items-center justify-center mb-4">
                  <item.icon className="w-6 h-6 text-teal-400" />
                </div>
                <h3 className="text-lg font-semibold text-white mb-2">{item.title}</h3>
                <p className="text-sm text-slate-400 leading-relaxed">{item.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* SECTION 3 — Use Cases */}
      <section className="py-20 px-6 border-t border-slate-800/40" data-testid="entity-usecases-section">
        <div className="max-w-5xl mx-auto">
          <p className="text-xs text-sky-400 font-bold uppercase tracking-widest mb-3 text-center">Use Cases</p>
          <h2 className="text-2xl sm:text-3xl font-bold text-white mb-12 text-center">Safety for Every Member of Your Family</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {USE_CASES.map((uc, i) => {
              const colorMap = { rose: 'rose-400', sky: 'sky-400', emerald: 'emerald-400' };
              const bgMap = { rose: 'rose-500/10', sky: 'sky-500/10', emerald: 'emerald-500/10' };
              return (
                <div key={i} className="p-6 rounded-2xl bg-white/[0.02] border border-slate-800/40">
                  <h3 className={`text-lg font-semibold text-${colorMap[uc.color]} mb-4`}>{uc.title}</h3>
                  <ul className="space-y-3 mb-6">
                    {uc.items.map((item, j) => (
                      <li key={j} className="flex items-center gap-2 text-sm text-slate-300">
                        <CheckCircle className={`w-4 h-4 text-${colorMap[uc.color]} shrink-0`} />
                        {item}
                      </li>
                    ))}
                  </ul>
                  <Link
                    to={uc.link}
                    className={`inline-flex items-center gap-1.5 text-sm font-medium text-${colorMap[uc.color]} hover:underline`}
                    data-testid={`entity-link-${uc.color}`}
                  >
                    Learn more <ArrowRight className="w-3.5 h-3.5" />
                  </Link>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* SECTION 4 — Comparison Table */}
      <section className="py-20 px-6 bg-[#0c1020]" data-testid="entity-comparison-section">
        <div className="max-w-3xl mx-auto">
          <p className="text-xs text-amber-400 font-bold uppercase tracking-widest mb-3 text-center">Comparison</p>
          <h2 className="text-2xl sm:text-3xl font-bold text-white mb-4 text-center">What Makes NISCHINT Different</h2>
          <p className="text-slate-400 max-w-xl mx-auto text-center mb-12">Most safety apps are reactive. NISCHINT is proactive.</p>
          <div className="rounded-2xl border border-slate-800/50 overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="bg-white/[0.03]">
                  <th className="text-left text-sm font-semibold text-slate-300 p-4">Feature</th>
                  <th className="text-center text-sm font-semibold text-slate-400 p-4">Traditional Apps</th>
                  <th className="text-center text-sm font-semibold text-teal-400 p-4">NISCHINT</th>
                </tr>
              </thead>
              <tbody>
                {COMPARISON.map((row, i) => (
                  <tr key={i} className="border-t border-slate-800/30">
                    <td className="text-sm text-slate-300 p-4">{row.feature}</td>
                    <td className="text-center p-4">
                      {row.traditional
                        ? <CheckCircle className="w-5 h-5 text-slate-400 mx-auto" />
                        : <XCircle className="w-5 h-5 text-slate-600 mx-auto" />}
                    </td>
                    <td className="text-center p-4">
                      <CheckCircle className="w-5 h-5 text-teal-400 mx-auto" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* SECTION 5 — Proactive vs Reactive */}
      <section className="py-20 px-6 border-t border-slate-800/40" data-testid="entity-proactive-section">
        <div className="max-w-3xl mx-auto text-center">
          <h2 className="text-2xl sm:text-3xl font-bold text-white mb-6">NISCHINT vs Typical Safety Apps</h2>
          <p className="text-slate-400 mb-10">Most safety apps are reactive. NISCHINT is proactive.</p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            {[
              'Detects before user reacts',
              'Responds automatically',
              'Connects real humans in real time',
            ].map((item, i) => (
              <div key={i} className="p-5 rounded-2xl bg-teal-500/5 border border-teal-500/20">
                <CheckCircle className="w-6 h-6 text-teal-400 mx-auto mb-3" />
                <p className="text-sm text-slate-300 font-medium">{item}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* SECTION 6 — FAQ */}
      <section className="py-20 px-6 bg-[#0c1020]" data-testid="entity-faq-section">
        <div className="max-w-3xl mx-auto">
          <p className="text-xs text-violet-400 font-bold uppercase tracking-widest mb-3 text-center">FAQ</p>
          <h2 className="text-2xl sm:text-3xl font-bold text-white mb-10 text-center">Frequently Asked Questions</h2>
          <div className="space-y-3">
            {FAQS.map((faq, i) => <FAQItem key={i} {...faq} />)}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-24 px-6 border-t border-slate-800/40" data-testid="entity-cta-section">
        <div className="max-w-3xl mx-auto text-center">
          <h2 className="text-3xl sm:text-4xl font-bold text-white mb-4">Protect What Matters Most</h2>
          <p className="text-slate-400 mb-10 text-lg">Start using NISCHINT today.</p>
          <button
            onClick={openModal}
            className="group px-8 py-4 bg-gradient-to-r from-teal-500 to-emerald-600 text-white font-semibold rounded-xl hover:shadow-xl hover:shadow-teal-500/25 transition-all text-lg inline-flex items-center gap-3"
            data-testid="entity-cta-button"
          >
            Get Started <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
          </button>
        </div>
      </section>

      <FloatingSocialBar />
      {showModal && <LeadCaptureModal persona="what-is-nischint" onClose={() => setShowModal(false)} />}
    </div>
  );
}
