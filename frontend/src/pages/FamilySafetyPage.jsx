import React, { useState, useEffect } from 'react';
import { Helmet } from 'react-helmet-async';
import { useNavigate } from 'react-router-dom';
import { Shield, ArrowRight, MapPin, Users, Phone, Heart, Clock, CheckCircle, AlertTriangle, Loader2 } from 'lucide-react';
import LeadCaptureModal from '../components/LeadCaptureModal';
import SocialCTASection from '../components/SocialCTASection';
import FloatingSocialBar from '../components/FloatingSocialBar';
import { funnel, geo } from '../utils/funnelTracker';
import { useStructuredData } from '../utils/socialLinks';

const WHATSAPP_LINK = 'https://wa.me/919999999999?text=I%20want%20to%20setup%20Nischint%20safety';

const PROBLEMS = [
  { icon: Users, text: 'Family scattered across the city — no shared safety view' },
  { icon: Clock, text: 'Elderly parent alone at home — no way to know if they fell' },
  { icon: MapPin, text: 'Teenager out late — you\'re calling every 10 minutes' },
  { icon: AlertTriangle, text: 'Emergency happens — no one knows who to call first' },
];

const SOLUTIONS = [
  { title: 'Family Safety Dashboard', desc: 'One screen showing every family member\'s live location, journey status, and safety score. Mother, father, child — all connected.', icon: Users },
  { title: 'Multi-Guardian Alerts', desc: 'When someone needs help — every family member gets notified instantly. If the primary guardian doesn\'t respond, others are escalated.', icon: Phone },
  { title: 'AI Safety Monitoring', desc: 'Route deviations, unusual stops, voice distress — Nischint detects danger and alerts the family automatically.', icon: AlertTriangle },
  { title: 'Elderly Fall Detection', desc: 'Connected wearable detects falls and unusual inactivity. Family gets instant alerts with location and emergency contacts.', icon: Heart },
];

const SCENARIOS = [
  { title: 'Daughter\'s Evening Commute', desc: 'Daughter starts her commute home. Father tracks on his phone. Mother gets a notification when she arrives. If the route changes — both parents are alerted instantly.' },
  { title: 'Elderly Father at Home', desc: 'Grandfather wears a Nischint band. A fall is detected — son gets an alert, daughter-in-law gets a call, and the emergency contact list is activated.' },
  { title: 'Family Road Trip', desc: 'The family drives to a hill station. Nischint tracks the journey, detects risky driving patterns, and shares live location with relatives back home.' },
];

const TRUST_POINTS = [
  'Whole-family protection — not just one person',
  'Multi-role: child, parent, elder — each gets the right interface',
  'Auto-escalation across the entire family tree',
  'Privacy-first — location shared only with linked guardians',
  'Works across Android and iOS devices',
];

export default function FamilySafetyPage() {
  const navigate = useNavigate();
  const [showModal, setShowModal] = useState(false);

  useEffect(() => { funnel.pageView('family'); geo.pageView({ type: 'family' }); }, []);
  useStructuredData();

  const openModal = () => { funnel.ctaClick('family'); setShowModal(true); };

  return (
    <div className="min-h-screen bg-[#0a0e1a] text-slate-200">
      <Helmet>
        <title>Family Safety App — Nischint | AI-Powered Family Protection</title>
        <meta name="description" content="Nischint connects your entire family in one safety network. Live tracking, multi-guardian alerts, elderly fall detection, and AI monitoring. Protect everyone you love." />
        <meta property="og:title" content="Family Safety App — Nischint" />
        <meta property="og:description" content="AI-powered family safety. Live tracking for kids, women, and elders. Multi-guardian escalation. One app for the whole family." />
        <meta property="og:type" content="website" />
        <meta property="og:url" content="https://nischint.care/family-safety-app" />
        <link rel="canonical" href="https://nischint.care/family-safety-app" />
      </Helmet>

      {/* Nav */}
      <nav className="fixed top-0 left-0 right-0 z-50 bg-[#0a0e1a]/80 backdrop-blur-xl border-b border-slate-800/40">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <button onClick={() => navigate('/')} className="flex items-center gap-2.5" data-testid="seo-nav-logo-family">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-teal-500 to-emerald-600 flex items-center justify-center">
              <Shield className="w-4 h-4 text-white" />
            </div>
            <span className="text-lg font-bold tracking-tight">NISCHINT</span>
          </button>
          <button
            onClick={openModal}
            className="px-4 py-2 bg-gradient-to-r from-emerald-500 to-teal-600 text-white text-sm font-semibold rounded-xl hover:shadow-lg hover:shadow-emerald-500/20 transition-all"
            data-testid="family-nav-cta"
          >
            Protect Your Family
          </button>
        </div>
      </nav>

      {/* HERO */}
      <section className="relative pt-28 pb-20 px-6" data-testid="family-hero-section">
        <div className="absolute inset-0">
          <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-emerald-500/8 rounded-full blur-[120px]" />
          <div className="absolute bottom-1/3 right-1/4 w-72 h-72 bg-teal-500/6 rounded-full blur-[100px]" />
        </div>
        <div className="max-w-4xl mx-auto text-center relative z-10">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 mb-6">
            <Shield className="w-3.5 h-3.5 text-emerald-400" />
            <span className="text-xs text-emerald-400 font-medium tracking-wide">FAMILY SAFETY</span>
          </div>
          <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold tracking-tight leading-[1.1] mb-6">
            <span className="text-white">One App to Protect</span><br />
            <span className="bg-gradient-to-r from-emerald-400 to-teal-400 bg-clip-text text-transparent">Your Entire Family</span>
          </h1>
          <p className="text-base sm:text-lg text-slate-400 max-w-2xl mx-auto mb-10 leading-relaxed">
            Nischint connects kids, parents, and elders into one AI-powered safety network. Real-time tracking, voice distress detection, and multi-guardian escalation — for every member.
          </p>
          <button
            onClick={openModal}
            className="group px-8 py-4 bg-gradient-to-r from-emerald-500 to-teal-600 text-white font-semibold rounded-xl hover:shadow-xl hover:shadow-emerald-500/25 transition-all text-lg flex items-center gap-3 mx-auto"
            data-testid="family-hero-cta"
          >
            Setup Nischint for Your Family <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
          </button>
        </div>
      </section>

      {/* PROBLEM */}
      <section className="py-20 px-6 border-t border-slate-800/40" data-testid="family-problem-section">
        <div className="max-w-4xl mx-auto">
          <p className="text-xs text-emerald-400 font-bold uppercase tracking-widest mb-3 text-center">The Problem</p>
          <h2 className="text-2xl sm:text-3xl font-bold text-white mb-4 text-center">Families Are Connected Online — But Not in Safety</h2>
          <p className="text-slate-400 max-w-xl mx-auto text-center mb-12">WhatsApp groups aren't safety systems. When something goes wrong, you need instant, automated response.</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {PROBLEMS.map((p, i) => (
              <div key={i} className="flex items-start gap-4 p-5 rounded-2xl bg-white/[0.02] border border-slate-800/40">
                <div className="w-10 h-10 rounded-xl bg-emerald-500/10 flex items-center justify-center shrink-0">
                  <p.icon className="w-5 h-5 text-emerald-400" />
                </div>
                <p className="text-slate-300 text-sm leading-relaxed">{p.text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* SOLUTION */}
      <section className="py-20 px-6 bg-[#0c1020]" data-testid="family-solution-section">
        <div className="max-w-4xl mx-auto">
          <p className="text-xs text-teal-400 font-bold uppercase tracking-widest mb-3 text-center">The Solution</p>
          <h2 className="text-2xl sm:text-3xl font-bold text-white mb-4 text-center">Nischint — The Safety OS for Your Family</h2>
          <p className="text-slate-400 max-w-xl mx-auto text-center mb-12">One platform that protects children, women, and elders — with AI doing the heavy lifting.</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
            {SOLUTIONS.map((s, i) => (
              <div key={i} className="p-6 rounded-2xl bg-white/[0.02] border border-slate-800/40 hover:border-teal-500/30 transition-colors">
                <div className="w-12 h-12 rounded-xl bg-teal-500/10 flex items-center justify-center mb-4">
                  <s.icon className="w-6 h-6 text-teal-400" />
                </div>
                <h3 className="text-lg font-semibold text-white mb-2">{s.title}</h3>
                <p className="text-sm text-slate-400 leading-relaxed">{s.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* SCENARIO */}
      <section className="py-20 px-6" data-testid="family-scenario-section">
        <div className="max-w-4xl mx-auto">
          <p className="text-xs text-amber-400 font-bold uppercase tracking-widest mb-3 text-center">Real Scenarios</p>
          <h2 className="text-2xl sm:text-3xl font-bold text-white mb-12 text-center">How Nischint Keeps Families Safe</h2>
          <div className="space-y-6">
            {SCENARIOS.map((s, i) => (
              <div key={i} className="flex gap-5 p-6 rounded-2xl bg-white/[0.02] border border-slate-800/40">
                <div className="w-10 h-10 rounded-full bg-amber-500/10 border border-amber-500/20 flex items-center justify-center shrink-0 text-amber-400 font-bold text-sm">{i + 1}</div>
                <div>
                  <h3 className="text-base font-semibold text-white mb-1">{s.title}</h3>
                  <p className="text-sm text-slate-400 leading-relaxed">{s.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* TRUST */}
      <section className="py-20 px-6 bg-[#0c1020]" data-testid="family-trust-section">
        <div className="max-w-3xl mx-auto text-center">
          <p className="text-xs text-emerald-400 font-bold uppercase tracking-widest mb-3">Why Families Choose Nischint</p>
          <h2 className="text-2xl sm:text-3xl font-bold text-white mb-10">Safety for the Whole Family — In One App</h2>
          <div className="space-y-4">
            {TRUST_POINTS.map((t, i) => (
              <div key={i} className="flex items-center gap-3 justify-center">
                <CheckCircle className="w-5 h-5 text-emerald-400 shrink-0" />
                <span className="text-slate-300">{t}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-24 px-6" data-testid="family-cta-section">
        <div className="max-w-3xl mx-auto text-center">
          <h2 className="text-3xl sm:text-4xl font-bold text-white mb-4">Start Protecting Your Family</h2>
          <p className="text-slate-400 mb-10 max-w-lg mx-auto">Setup takes 2 minutes per member. Connect everyone you love into one safety network.</p>
          <button
            onClick={openModal}
            className="group px-10 py-4 bg-gradient-to-r from-emerald-500 to-teal-600 text-white font-bold rounded-xl hover:shadow-xl hover:shadow-emerald-500/25 transition-all text-lg flex items-center gap-3 mx-auto"
            data-testid="family-bottom-cta"
          >
            Start on WhatsApp <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
          </button>
          <p className="text-xs text-slate-400 mt-4">Free to use. No credit card required.</p>
        </div>
      </section>

      <LeadCaptureModal isOpen={showModal} onClose={() => setShowModal(false)} page="family" whatsappLink={WHATSAPP_LINK} />

      <SocialCTASection />

      {/* Footer */}
      <footer className="border-t border-slate-800/40 py-8 px-6">
        <div className="max-w-4xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <Shield className="w-4 h-4 text-teal-400" />
            <span className="text-sm text-slate-400">NISCHINT</span>
          </div>
          <div className="flex items-center gap-6 text-sm text-slate-400">
            <button onClick={() => navigate('/women-safety-app')} className="hover:text-rose-400 transition-colors">Women</button>
            <button onClick={() => navigate('/kids-safety-app')} className="hover:text-blue-400 transition-colors">Kids</button>
            <button onClick={() => navigate('/family-safety-app')} className="hover:text-emerald-400 transition-colors">Family</button>
            <button onClick={() => navigate('/')} className="hover:text-white transition-colors">Home</button>
          </div>
          <p className="text-xs text-slate-600">&copy; 2026 Nischint. All rights reserved.</p>
        </div>
      </footer>
      <FloatingSocialBar />
    </div>
  );
}