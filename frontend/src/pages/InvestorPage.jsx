import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Shield, Brain, Radio, Globe, Users, Activity, MapPin, Eye, Zap, ArrowRight, ChevronRight, Server, Lock, ArrowLeft, Mic, Cpu } from 'lucide-react';

const LIVE_METRICS = [
  { label: 'Active Safety Sessions', value: 1247, suffix: '', icon: Activity },
  { label: 'Signals Processed', value: 847302, suffix: '', icon: Radio },
  { label: 'AI Predictions Generated', value: 23841, suffix: '', icon: Brain },
  { label: 'Alerts Triggered', value: 412, suffix: '', icon: Zap },
  { label: 'Cities Covered', value: 6, suffix: '', icon: Globe },
  { label: 'Response Time', value: 2.8, suffix: 's', icon: Shield },
];

const TECH_MODULES = [
  { name: 'Behavior Pattern Engine', desc: 'ML-based gait, pace, and behavioral anomaly detection using accelerometer and gyroscope fusion', icon: Brain },
  { name: 'Digital Twin Engine', desc: 'Virtual safety profile mirroring real-world user context — schedule, routines, risk baseline', icon: Eye },
  { name: 'Risk Prediction Engine', desc: 'Multi-factor risk scoring combining location, time, behavior, weather, and historical incident data', icon: Activity },
  { name: 'Incident Narrative AI', desc: 'GPT-powered auto-generation of incident reports with causal analysis and recommendation engine', icon: Cpu },
  { name: 'Replay Intelligence', desc: 'Full spatiotemporal reconstruction of incidents with timeline scrubbing and counterfactual analysis', icon: MapPin },
  { name: 'Location Risk Intelligence', desc: 'Zone-level risk heatmaps built from crime data, lighting, foot traffic, and historical patterns', icon: Globe },
  { name: 'Voice AI Detection', desc: 'Real-time audio analysis for distress signals, raised voices, and environmental threat patterns', icon: Mic },
  { name: 'Environmental AI', desc: 'Weather, lighting, crowd density, and infrastructure condition fusion for situational risk assessment', icon: Server },
];

const MARKETS = [
  { name: 'School Safety', size: '$3.2B', growth: '18% CAGR', desc: 'K-12 student safety during commute and campus activities' },
  { name: 'Campus Safety', size: '$5.1B', growth: '22% CAGR', desc: 'University student safety — hostels, late-night travel, campus perimeter' },
  { name: 'Corporate Safety', size: '$8.4B', growth: '15% CAGR', desc: 'Employee safety for field workers, women employees, night shifts' },
  { name: 'Smart Cities', size: '$12.8B', growth: '25% CAGR', desc: 'City-wide safety infrastructure — zone monitoring, predictive deployment' },
  { name: 'Public Safety', size: '$15.2B', growth: '20% CAGR', desc: 'Government and law enforcement safety intelligence and response' },
];

function AnimatedCounter({ target, suffix = '', duration = 2000 }) {
  const [count, setCount] = useState(0);
  useEffect(() => {
    let start = 0;
    const step = target / (duration / 16);
    const timer = setInterval(() => {
      start += step;
      if (start >= target) { setCount(target); clearInterval(timer); }
      else { setCount(Math.floor(start)); }
    }, 16);
    return () => clearInterval(timer);
  }, [target, duration]);
  return <>{typeof target === 'number' && target < 100 ? count.toFixed(1) : count.toLocaleString()}{suffix}</>;
}

export default function InvestorPage() {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-[#0a0e1a] text-slate-200">
      {/* Nav */}
      <nav className="fixed top-0 left-0 right-0 z-50 bg-[#0a0e1a]/80 backdrop-blur-xl border-b border-slate-800/40">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <button onClick={() => navigate('/')} className="flex items-center gap-2.5" data-testid="inv-nav-logo">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-teal-500 to-emerald-600 flex items-center justify-center">
              <Shield className="w-4.5 h-4.5 text-white" />
            </div>
            <span className="text-lg font-bold tracking-tight">NISCHINT</span>
          </button>
          <div className="flex items-center gap-4">
            <button onClick={() => navigate('/pilot')} className="text-sm text-teal-400 hover:text-teal-300 font-medium" data-testid="inv-nav-pilot">Request Pilot</button>
            <button onClick={() => navigate('/login')} className="px-4 py-1.5 bg-white/5 border border-slate-700/60 rounded-lg text-sm hover:bg-white/10 transition-colors">Platform</button>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="pt-32 pb-20 px-6" data-testid="inv-hero">
        <div className="max-w-4xl mx-auto text-center relative">
          <div className="absolute inset-0 -z-10">
            <div className="absolute top-0 left-1/3 w-96 h-96 bg-teal-500/5 rounded-full blur-[120px]" />
          </div>
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-violet-500/5 border border-violet-500/20 mb-6">
            <span className="text-[10px] font-bold text-violet-400 uppercase tracking-widest">INVESTOR OVERVIEW</span>
          </div>
          <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold tracking-tight leading-[1.08] mb-6">
            Building the AI Safety<br />
            <span className="bg-gradient-to-r from-teal-400 to-emerald-400 bg-clip-text text-transparent">Infrastructure for the Real World</span>
          </h1>
          <p className="text-lg text-slate-400 max-w-2xl mx-auto leading-relaxed">
            Nischint is evolving from personal safety technology into a national safety intelligence network — connecting individuals, institutions, and cities into one predictive safety operating system.
          </p>
        </div>
      </section>

      {/* Live Metrics */}
      <section className="py-16 px-6 border-y border-slate-800/40 bg-[#0c1020]" data-testid="inv-metrics">
        <div className="max-w-5xl mx-auto">
          <p className="text-xs text-teal-400 font-bold uppercase tracking-widest text-center mb-8">Platform Metrics</p>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
            {LIVE_METRICS.map((m, i) => (
              <div key={i} className="text-center p-4 rounded-xl bg-white/[0.02] border border-slate-800/40">
                <m.icon className="w-5 h-5 text-teal-400/60 mx-auto mb-2" />
                <p className="text-xl font-bold text-white"><AnimatedCounter target={m.value} suffix={m.suffix} /></p>
                <p className="text-[9px] text-slate-400 uppercase tracking-wider mt-1">{m.label}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Architecture Pipeline */}
      <section className="py-24 px-6" data-testid="inv-architecture">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-16">
            <p className="text-xs text-teal-400 font-bold uppercase tracking-widest mb-3">Platform Architecture</p>
            <h2 className="text-3xl sm:text-4xl font-bold text-white">Safety Intelligence Pipeline</h2>
          </div>
          <div className="space-y-3">
            {[
              { layer: 'User App Layer', desc: 'Mobile PWA with SOS, safety sessions, shake detection, guardian network, AI insights', color: 'border-blue-500/30 bg-blue-500/5', accent: 'text-blue-400' },
              { layer: 'AI Safety Brain', desc: '8 specialized AI engines — behavior analysis, risk prediction, anomaly detection, narrative generation', color: 'border-violet-500/30 bg-violet-500/5', accent: 'text-violet-400' },
              { layer: 'Command Center', desc: 'Real-time operational dashboard — incident monitoring, guardian tracking, SLA management, demo mode', color: 'border-amber-500/30 bg-amber-500/5', accent: 'text-amber-400' },
              { layer: 'City Intelligence Layer', desc: 'Zone risk mapping, heatmaps, city-scale anomaly detection, predictive resource deployment', color: 'border-teal-500/30 bg-teal-500/5', accent: 'text-teal-400' },
            ].map((l, i) => (
              <div key={i} className={`p-5 rounded-2xl border ${l.color} flex items-center gap-6`}>
                <div className="w-10 h-10 rounded-xl bg-slate-800/50 flex items-center justify-center shrink-0">
                  <span className={`text-lg font-bold ${l.accent}`}>{i + 1}</span>
                </div>
                <div>
                  <h3 className={`text-sm font-semibold ${l.accent}`}>{l.layer}</h3>
                  <p className="text-xs text-slate-400 mt-0.5">{l.desc}</p>
                </div>
                {i < 3 && <ChevronRight className="w-4 h-4 text-slate-700 ml-auto rotate-90 shrink-0" />}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Technology Stack */}
      <section className="py-24 px-6 bg-[#0c1020]" data-testid="inv-techstack">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-16">
            <p className="text-xs text-teal-400 font-bold uppercase tracking-widest mb-3">Technology</p>
            <h2 className="text-3xl sm:text-4xl font-bold text-white">8 Specialized AI Engines</h2>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {TECH_MODULES.map((m, i) => (
              <div key={i} className="p-4 rounded-xl bg-white/[0.02] border border-slate-800/40 hover:border-teal-500/20 transition-colors">
                <m.icon className="w-5 h-5 text-teal-400/60 mb-2" />
                <h3 className="text-xs font-semibold text-white mb-1">{m.name}</h3>
                <p className="text-[10px] text-slate-400 leading-relaxed">{m.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Market Opportunity */}
      <section className="py-24 px-6" data-testid="inv-market">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-16">
            <p className="text-xs text-teal-400 font-bold uppercase tracking-widest mb-3">Market Opportunity</p>
            <h2 className="text-3xl sm:text-4xl font-bold text-white">$44.7B Total Addressable Market</h2>
          </div>
          <div className="space-y-2">
            {MARKETS.map((m, i) => (
              <div key={i} className="p-4 rounded-xl bg-white/[0.02] border border-slate-800/40 flex items-center gap-6">
                <div className="w-24 shrink-0">
                  <p className="text-sm font-bold text-white">{m.name}</p>
                </div>
                <div className="flex-1">
                  <p className="text-xs text-slate-400">{m.desc}</p>
                </div>
                <div className="text-right shrink-0">
                  <p className="text-sm font-bold text-teal-400">{m.size}</p>
                  <p className="text-[10px] text-slate-400">{m.growth}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Pilot Deployments */}
      <section className="py-24 px-6 bg-[#0c1020]" data-testid="inv-pilots">
        <div className="max-w-4xl mx-auto text-center">
          <p className="text-xs text-teal-400 font-bold uppercase tracking-widest mb-3">Pilot Program</p>
          <h2 className="text-3xl sm:text-4xl font-bold text-white mb-4">Active Pilot Deployments</h2>
          <p className="text-slate-400 max-w-xl mx-auto mb-10">Nischint is launching pilot deployments with schools, universities, corporate campuses, and smart city projects.</p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {['Schools', 'Universities', 'Corporate Campuses', 'Smart City Projects'].map((p, i) => (
              <div key={i} className="p-5 rounded-xl bg-white/[0.02] border border-slate-800/40">
                <p className="text-sm font-semibold text-white">{p}</p>
                <p className="text-[10px] text-teal-400 mt-1">Accepting pilots</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Founder Vision */}
      <section className="py-24 px-6" data-testid="inv-vision">
        <div className="max-w-3xl mx-auto text-center">
          <p className="text-xs text-teal-400 font-bold uppercase tracking-widest mb-3">Vision</p>
          <h2 className="text-3xl sm:text-4xl font-bold text-white mb-6">India's AI Safety Network</h2>
          <div className="p-8 rounded-2xl bg-gradient-to-b from-teal-500/5 to-transparent border border-teal-500/10">
            <p className="text-lg text-slate-300 leading-relaxed italic">
              "Nischint aims to become the 911-equivalent safety network for India — an AI-powered infrastructure that connects individuals, institutions, and cities into one predictive safety system. Every person protected. Every risk predicted. Every response instant."
            </p>
            <div className="mt-6 flex items-center justify-center gap-3">
              <div className="w-10 h-10 rounded-full bg-gradient-to-br from-teal-500 to-emerald-600 flex items-center justify-center">
                <span className="text-white text-sm font-bold">N</span>
              </div>
              <div className="text-left">
                <p className="text-sm font-semibold text-white">Nischint Technologies</p>
                <p className="text-[10px] text-slate-400">Building safety infrastructure for 1.4B people</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-20 px-6 bg-gradient-to-b from-[#0c1020] to-[#0a0e1a]" data-testid="inv-cta">
        <div className="max-w-3xl mx-auto text-center">
          <h2 className="text-2xl sm:text-3xl font-bold text-white mb-4">Partner with Nischint</h2>
          <p className="text-slate-400 mb-8">Join us in building the AI safety infrastructure for the real world.</p>
          <button onClick={() => navigate('/pilot')} className="group px-8 py-3.5 bg-gradient-to-r from-teal-500 to-emerald-500 text-white font-semibold rounded-xl hover:shadow-lg hover:shadow-teal-500/20 transition-all flex items-center gap-2 mx-auto" data-testid="inv-cta-btn">
            Start a Conversation <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
          </button>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-slate-800/40 py-12 px-6" data-testid="inv-footer">
        <div className="max-w-5xl mx-auto">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-10 mb-10">
            <div>
              <div className="flex items-center gap-2 mb-3">
                <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-teal-500 to-emerald-600 flex items-center justify-center">
                  <Shield className="w-3.5 h-3.5 text-white" />
                </div>
                <span className="text-sm font-bold tracking-tight">NISCHINT</span>
              </div>
              <p className="text-xs text-slate-400">AI Safety Infrastructure</p>
            </div>
            <div>
              <p className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-3">Platform</p>
              <div className="space-y-2">
                <button onClick={() => navigate('/')} className="block text-xs text-slate-400 hover:text-slate-300 transition-colors">Home</button>
                <button onClick={() => navigate('/pilot')} className="block text-xs text-slate-400 hover:text-slate-300 transition-colors">Pilot Program</button>
                <button onClick={() => navigate('/login')} className="block text-xs text-slate-400 hover:text-slate-300 transition-colors">Sign In</button>
              </div>
            </div>
            <div>
              <p className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-3">Contact</p>
              <div className="space-y-1.5">
                <a href="mailto:hello@nischint.app" className="block text-[11px] text-slate-400 hover:text-teal-400 transition-colors">hello@nischint.app</a>
                <a href="mailto:partners@nischint.app" className="block text-[11px] text-slate-400 hover:text-teal-400 transition-colors">partners@nischint.app</a>
                <a href="mailto:press@nischint.app" className="block text-[11px] text-slate-400 hover:text-teal-400 transition-colors">press@nischint.app</a>
              </div>
            </div>
          </div>
          <div className="border-t border-slate-800/40 pt-6 flex items-center justify-between">
            <p className="text-[10px] text-slate-400">&copy; 2026 Nischint Technologies. All rights reserved.</p>
            <a href="mailto:security@nischint.app" className="text-[10px] text-slate-400 hover:text-slate-400 transition-colors">security@nischint.app</a>
          </div>
        </div>
      </footer>
    </div>
  );
}
