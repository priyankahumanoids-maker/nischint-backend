import React, { useState, useEffect } from 'react';
import { Helmet } from 'react-helmet-async';
import { useNavigate } from 'react-router-dom';
import { Shield, ArrowRight, MapPin, Brain, Phone, Clock, Bus, CheckCircle, AlertTriangle, Loader2 } from 'lucide-react';
import LeadCaptureModal from '../components/LeadCaptureModal';
import SocialCTASection from '../components/SocialCTASection';
import FloatingSocialBar from '../components/FloatingSocialBar';
import { funnel, geo } from '../utils/funnelTracker';
import { useStructuredData } from '../utils/socialLinks';

const WHATSAPP_LINK = 'https://wa.me/919999999999?text=I%20want%20to%20setup%20Nischint%20safety';

const PROBLEMS = [
  { icon: Bus, text: 'School bus delays — no idea where the child is' },
  { icon: MapPin, text: 'Playground wandering — child leaves the safe zone' },
  { icon: Clock, text: 'Tuition commute — no tracking between classes' },
  { icon: AlertTriangle, text: 'Stranger danger — child can\'t call for help fast enough' },
];

const SOLUTIONS = [
  { title: 'Real-Time Location', desc: 'Know exactly where your child is — school, tuition, playground. Live map updates every few seconds.', icon: MapPin },
  { title: 'AI Route Monitoring', desc: 'Set expected routes. If the child deviates — you get an instant alert with their new location.', icon: Brain },
  { title: 'Voice Distress Detection', desc: 'AI detects screams and distress words — triggers an alert even if the child can\'t reach the phone.', icon: AlertTriangle },
  { title: 'Guardian Escalation', desc: 'If you don\'t respond in 60 seconds — Nischint calls other guardians, sends SMS, activates command center.', icon: Phone },
];

const SCENARIOS = [
  { title: 'School Bus Tracking', desc: 'Your child starts a journey to school. You see the live route on your phone. If the bus takes a different turn — you know immediately.' },
  { title: 'After-School Tuition', desc: 'Child walks to tuition class. AI monitors the expected route. Any unexpected stop triggers a parent notification with exact location.' },
  { title: 'Weekend at the Park', desc: 'Child plays at the park. You set a safe zone. If they walk beyond the boundary — instant alert to your phone with live tracking.' },
];

const TRUST_POINTS = [
  'Designed specifically for children\'s safety',
  'AI monitoring — not just manual check-ins',
  'Multi-guardian support — both parents get alerts',
  'Auto-escalation if no parent responds',
  'Kid-friendly interface on child\'s device',
];

export default function KidsSafetyPage() {
  const navigate = useNavigate();
  const [showModal, setShowModal] = useState(false);

  useEffect(() => { funnel.pageView('kids'); geo.pageView({ type: 'kids' }); }, []);
  useStructuredData();

  const openModal = () => { funnel.ctaClick('kids'); setShowModal(true); };

  return (
    <div className="min-h-screen bg-[#0a0e1a] text-slate-200">
      <Helmet>
        <title>Kids Safety App — Nischint | AI-Powered Child Protection</title>
        <meta name="description" content="Nischint keeps your child safe with AI-powered GPS tracking, route monitoring, voice distress detection, and auto-escalation. Know where your child is — always." />
        <meta property="og:title" content="Kids Safety App — Nischint" />
        <meta property="og:description" content="AI-powered child safety. Live tracking, route monitoring, voice distress detection. Built for Indian parents." />
        <meta property="og:type" content="website" />
        <meta property="og:url" content="https://nischint.care/kids-safety-app" />
        <link rel="canonical" href="https://nischint.care/kids-safety-app" />
      </Helmet>

      {/* Nav */}
      <nav className="fixed top-0 left-0 right-0 z-50 bg-[#0a0e1a]/80 backdrop-blur-xl border-b border-slate-800/40">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <button onClick={() => navigate('/')} className="flex items-center gap-2.5" data-testid="seo-nav-logo-kids">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-teal-500 to-emerald-600 flex items-center justify-center">
              <Shield className="w-4 h-4 text-white" />
            </div>
            <span className="text-lg font-bold tracking-tight">NISCHINT</span>
          </button>
          <button
            onClick={openModal}
            className="px-4 py-2 bg-gradient-to-r from-blue-500 to-indigo-600 text-white text-sm font-semibold rounded-xl hover:shadow-lg hover:shadow-blue-500/20 transition-all"
            data-testid="kids-nav-cta"
          >
            Protect Your Child
          </button>
        </div>
      </nav>

      {/* HERO */}
      <section className="relative pt-28 pb-20 px-6" data-testid="kids-hero-section">
        <div className="absolute inset-0">
          <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-blue-500/8 rounded-full blur-[120px]" />
          <div className="absolute bottom-1/3 right-1/4 w-72 h-72 bg-indigo-500/6 rounded-full blur-[100px]" />
        </div>
        <div className="max-w-4xl mx-auto text-center relative z-10">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-blue-500/10 border border-blue-500/20 mb-6">
            <Shield className="w-3.5 h-3.5 text-blue-400" />
            <span className="text-xs text-blue-400 font-medium tracking-wide">KIDS SAFETY</span>
          </div>
          <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold tracking-tight leading-[1.1] mb-6">
            <span className="text-white">Know Where Your</span><br />
            <span className="bg-gradient-to-r from-blue-400 to-indigo-400 bg-clip-text text-transparent">Child Is — Always</span>
          </h1>
          <p className="text-base sm:text-lg text-slate-400 max-w-2xl mx-auto mb-10 leading-relaxed">
            Nischint gives parents real-time visibility into their child's location, route, and safety — with AI that detects danger before your child can even call.
          </p>
          <button
            onClick={openModal}
            className="group px-8 py-4 bg-gradient-to-r from-blue-500 to-indigo-600 text-white font-semibold rounded-xl hover:shadow-xl hover:shadow-blue-500/25 transition-all text-lg flex items-center gap-3 mx-auto"
            data-testid="kids-hero-cta"
          >
            Setup Nischint for Your Child <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
          </button>
        </div>
      </section>

      {/* PROBLEM */}
      <section className="py-20 px-6 border-t border-slate-800/40" data-testid="kids-problem-section">
        <div className="max-w-4xl mx-auto">
          <p className="text-xs text-blue-400 font-bold uppercase tracking-widest mb-3 text-center">The Problem</p>
          <h2 className="text-2xl sm:text-3xl font-bold text-white mb-4 text-center">50,000+ Children Go Missing in India Every Year</h2>
          <p className="text-slate-400 max-w-xl mx-auto text-center mb-12">Most parents rely on phone calls. But a child in danger can't always make that call.</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {PROBLEMS.map((p, i) => (
              <div key={i} className="flex items-start gap-4 p-5 rounded-2xl bg-white/[0.02] border border-slate-800/40">
                <div className="w-10 h-10 rounded-xl bg-blue-500/10 flex items-center justify-center shrink-0">
                  <p.icon className="w-5 h-5 text-blue-400" />
                </div>
                <p className="text-slate-300 text-sm leading-relaxed">{p.text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* SOLUTION */}
      <section className="py-20 px-6 bg-[#0c1020]" data-testid="kids-solution-section">
        <div className="max-w-4xl mx-auto">
          <p className="text-xs text-teal-400 font-bold uppercase tracking-widest mb-3 text-center">The Solution</p>
          <h2 className="text-2xl sm:text-3xl font-bold text-white mb-4 text-center">Nischint Watches Over Your Child — So You Don't Have To Worry</h2>
          <p className="text-slate-400 max-w-xl mx-auto text-center mb-12">AI-powered monitoring that keeps your child safe during school, tuition, and play.</p>
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
      <section className="py-20 px-6" data-testid="kids-scenario-section">
        <div className="max-w-4xl mx-auto">
          <p className="text-xs text-amber-400 font-bold uppercase tracking-widest mb-3 text-center">Real Scenarios</p>
          <h2 className="text-2xl sm:text-3xl font-bold text-white mb-12 text-center">How Nischint Keeps Kids Safe Every Day</h2>
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
      <section className="py-20 px-6 bg-[#0c1020]" data-testid="kids-trust-section">
        <div className="max-w-3xl mx-auto text-center">
          <p className="text-xs text-emerald-400 font-bold uppercase tracking-widest mb-3">Why Parents Trust Nischint</p>
          <h2 className="text-2xl sm:text-3xl font-bold text-white mb-10">Built by Parents, for Parents</h2>
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
      <section className="py-24 px-6" data-testid="kids-cta-section">
        <div className="max-w-3xl mx-auto text-center">
          <h2 className="text-3xl sm:text-4xl font-bold text-white mb-4">Protect Your Child Today</h2>
          <p className="text-slate-400 mb-10 max-w-lg mx-auto">Setup takes 2 minutes. Install the app, link your child's device, and start monitoring — instantly.</p>
          <button
            onClick={openModal}
            className="group px-10 py-4 bg-gradient-to-r from-blue-500 to-indigo-600 text-white font-bold rounded-xl hover:shadow-xl hover:shadow-blue-500/25 transition-all text-lg flex items-center gap-3 mx-auto"
            data-testid="kids-bottom-cta"
          >
            Start on WhatsApp <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
          </button>
          <p className="text-xs text-slate-400 mt-4">Free to use. No credit card required.</p>
        </div>
      </section>

      <LeadCaptureModal isOpen={showModal} onClose={() => setShowModal(false)} page="kids" whatsappLink={WHATSAPP_LINK} />

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