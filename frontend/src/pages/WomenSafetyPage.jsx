import React, { useState, useEffect } from 'react';
import { Helmet } from 'react-helmet-async';
import { useNavigate } from 'react-router-dom';
import { Shield, ArrowRight, MapPin, Mic, Phone, Clock, Users, CheckCircle, AlertTriangle, Loader2 } from 'lucide-react';
import LeadCaptureModal from '../components/LeadCaptureModal';
import SocialCTASection from '../components/SocialCTASection';
import FloatingSocialBar from '../components/FloatingSocialBar';
import { funnel, geo } from '../utils/funnelTracker';
import { useStructuredData } from '../utils/socialLinks';

const WHATSAPP_LINK = 'https://wa.me/919999999999?text=I%20want%20to%20setup%20Nischint%20safety';

const PROBLEMS = [
  { icon: MapPin, text: 'Unsafe commutes — no one knows if she reached safely' },
  { icon: Clock, text: 'Late night travel — no real-time tracking or SOS' },
  { icon: AlertTriangle, text: 'Harassment situations — no instant alert to family' },
  { icon: Phone, text: 'Phone snatched — no way to send distress signal' },
];

const SOLUTIONS = [
  { title: 'Live GPS Tracking', desc: 'Family sees her real-time location during every journey. No manual check-ins needed.', icon: MapPin },
  { title: 'Voice Distress Detection', desc: 'AI listens for screams and distress keywords — triggers alerts automatically even if she can\'t touch the phone.', icon: Mic },
  { title: 'One-Tap SOS', desc: 'Instant emergency alert to all guardians with live location, audio recording, and auto-escalation.', icon: AlertTriangle },
  { title: 'Auto Escalation', desc: 'If no guardian responds in 60 seconds — automated calls, SMS, and command center activation.', icon: Phone },
];

const SCENARIOS = [
  { title: 'Late Night Cab', desc: 'She starts a Nischint journey. Family tracks the route live. Any deviation triggers an alert. If she screams, guardians are notified in 3 seconds.' },
  { title: 'College Commute', desc: 'Daily route monitored by AI. If the route changes unexpectedly, parents get an instant notification with her live location.' },
  { title: 'Alone in New City', desc: 'Walking alone at night? Nischint runs voice monitoring. A cry for help triggers SOS — guardians get calls, SMS, and live location.' },
];

const TRUST_POINTS = [
  'AI-powered — not just a panic button',
  'Works even when phone is locked',
  'Guardians get automated calls if no response',
  'End-to-end encrypted location data',
  'Built in India, for Indian women',
];

export default function WomenSafetyPage() {
  const navigate = useNavigate();
  const [showModal, setShowModal] = useState(false);

  useEffect(() => { funnel.pageView('women'); geo.pageView({ type: 'women' }); }, []);
  useStructuredData();

  const openModal = () => { funnel.ctaClick('women'); setShowModal(true); };

  return (
    <div className="min-h-screen bg-[#0a0e1a] text-slate-200">
      <Helmet>
        <title>Women Safety App — Nischint | AI-Powered Protection for Women</title>
        <meta name="description" content="Nischint protects women with AI-powered live GPS tracking, voice distress detection, one-tap SOS, and auto-escalation to guardians. Real safety, not just a panic button." />
        <meta property="og:title" content="Women Safety App — Nischint" />
        <meta property="og:description" content="AI-powered safety for women. Live tracking, voice distress detection, auto-escalation. Built for Indian women." />
        <meta property="og:type" content="website" />
        <meta property="og:url" content="https://nischint.care/women-safety-app" />
        <link rel="canonical" href="https://nischint.care/women-safety-app" />
      </Helmet>

      {/* Nav */}
      <nav className="fixed top-0 left-0 right-0 z-50 bg-[#0a0e1a]/80 backdrop-blur-xl border-b border-slate-800/40">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <button onClick={() => navigate('/')} className="flex items-center gap-2.5" data-testid="seo-nav-logo">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-teal-500 to-emerald-600 flex items-center justify-center">
              <Shield className="w-4 h-4 text-white" />
            </div>
            <span className="text-lg font-bold tracking-tight">NISCHINT</span>
          </button>
          <button
            onClick={openModal}
            className="px-4 py-2 bg-gradient-to-r from-rose-500 to-pink-600 text-white text-sm font-semibold rounded-xl hover:shadow-lg hover:shadow-rose-500/20 transition-all"
            data-testid="women-nav-cta"
          >
            Get Protected
          </button>
        </div>
      </nav>

      {/* HERO */}
      <section className="relative pt-28 pb-20 px-6" data-testid="women-hero-section">
        <div className="absolute inset-0">
          <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-rose-500/8 rounded-full blur-[120px]" />
          <div className="absolute bottom-1/3 right-1/4 w-72 h-72 bg-pink-500/6 rounded-full blur-[100px]" />
        </div>
        <div className="max-w-4xl mx-auto text-center relative z-10">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-rose-500/10 border border-rose-500/20 mb-6">
            <Shield className="w-3.5 h-3.5 text-rose-400" />
            <span className="text-xs text-rose-400 font-medium tracking-wide">WOMEN SAFETY</span>
          </div>
          <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold tracking-tight leading-[1.1] mb-6">
            <span className="text-white">She Deserves to</span><br />
            <span className="bg-gradient-to-r from-rose-400 to-pink-400 bg-clip-text text-transparent">Walk Without Fear</span>
          </h1>
          <p className="text-base sm:text-lg text-slate-400 max-w-2xl mx-auto mb-10 leading-relaxed">
            Nischint gives every woman an AI-powered safety shield. Live tracking, voice distress detection, and automatic escalation — so her family always knows she's safe.
          </p>
          <button
            onClick={openModal}
            className="group px-8 py-4 bg-gradient-to-r from-rose-500 to-pink-600 text-white font-semibold rounded-xl hover:shadow-xl hover:shadow-rose-500/25 transition-all text-lg flex items-center gap-3 mx-auto"
            data-testid="women-hero-cta"
          >
            Setup Nischint for Her <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
          </button>
        </div>
      </section>

      {/* PROBLEM */}
      <section className="py-20 px-6 border-t border-slate-800/40" data-testid="women-problem-section">
        <div className="max-w-4xl mx-auto">
          <p className="text-xs text-rose-400 font-bold uppercase tracking-widest mb-3 text-center">The Problem</p>
          <h2 className="text-2xl sm:text-3xl font-bold text-white mb-4 text-center">Every 4 Minutes, a Crime Against Women in India</h2>
          <p className="text-slate-400 max-w-xl mx-auto text-center mb-12">Most safety apps are just panic buttons. By the time she presses it — it might be too late.</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {PROBLEMS.map((p, i) => (
              <div key={i} className="flex items-start gap-4 p-5 rounded-2xl bg-white/[0.02] border border-slate-800/40">
                <div className="w-10 h-10 rounded-xl bg-rose-500/10 flex items-center justify-center shrink-0">
                  <p.icon className="w-5 h-5 text-rose-400" />
                </div>
                <p className="text-slate-300 text-sm leading-relaxed">{p.text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* SOLUTION */}
      <section className="py-20 px-6 bg-[#0c1020]" data-testid="women-solution-section">
        <div className="max-w-4xl mx-auto">
          <p className="text-xs text-teal-400 font-bold uppercase tracking-widest mb-3 text-center">The Solution</p>
          <h2 className="text-2xl sm:text-3xl font-bold text-white mb-4 text-center">Nischint Protects — Even When She Can't Call</h2>
          <p className="text-slate-400 max-w-xl mx-auto text-center mb-12">AI-powered safety that works automatically. No buttons to press in a crisis.</p>
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
      <section className="py-20 px-6" data-testid="women-scenario-section">
        <div className="max-w-4xl mx-auto">
          <p className="text-xs text-amber-400 font-bold uppercase tracking-widest mb-3 text-center">Real Scenarios</p>
          <h2 className="text-2xl sm:text-3xl font-bold text-white mb-12 text-center">How Nischint Works in Real Life</h2>
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
      <section className="py-20 px-6 bg-[#0c1020]" data-testid="women-trust-section">
        <div className="max-w-3xl mx-auto text-center">
          <p className="text-xs text-emerald-400 font-bold uppercase tracking-widest mb-3">Why Trust Nischint</p>
          <h2 className="text-2xl sm:text-3xl font-bold text-white mb-10">Not Just Another Safety App</h2>
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
      <section className="py-24 px-6" data-testid="women-cta-section">
        <div className="max-w-3xl mx-auto text-center">
          <h2 className="text-3xl sm:text-4xl font-bold text-white mb-4">Protect Her Today</h2>
          <p className="text-slate-400 mb-10 max-w-lg mx-auto">Setup takes 2 minutes. Download the app, add guardians, and she's protected — 24/7.</p>
          <button
            onClick={openModal}
            className="group px-10 py-4 bg-gradient-to-r from-rose-500 to-pink-600 text-white font-bold rounded-xl hover:shadow-xl hover:shadow-rose-500/25 transition-all text-lg flex items-center gap-3 mx-auto"
            data-testid="women-bottom-cta"
          >
            Start on WhatsApp <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
          </button>
          <p className="text-xs text-slate-400 mt-4">Free to use. No credit card required.</p>
        </div>
      </section>

      <LeadCaptureModal isOpen={showModal} onClose={() => setShowModal(false)} page="women" whatsappLink={WHATSAPP_LINK} />

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