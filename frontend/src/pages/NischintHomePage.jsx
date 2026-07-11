import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Shield, Activity, Brain, MapPin, Radio, Users, ChevronRight, ArrowRight, Zap, Eye, Lock, Globe, Server, Mic, Cpu, Network, Building2, Mail, ChevronDown, Heart } from 'lucide-react';
import FloatingSocialBar from '../components/FloatingSocialBar';
import SocialCTASection from '../components/SocialCTASection';
import { SOCIALS, SocialIcon, trackSocialClick, useStructuredData } from '../utils/socialLinks';
import { Helmet } from 'react-helmet-async';
import CitySafetySimulation from '../components/CitySafetySimulation';

const TICKER_EVENTS = [
  { time: '12:41', msg: 'Behavioral deviation detected — Zone 4', type: 'warning' },
  { time: '12:42', msg: 'Route anomaly flagged — User 2847', type: 'alert' },
  { time: '12:43', msg: 'Safety alert triggered — Campus North', type: 'critical' },
  { time: '12:44', msg: 'Risk score normalized — Zone 7', type: 'info' },
  { time: '12:45', msg: 'Guardian response confirmed — 12s', type: 'success' },
  { time: '12:46', msg: 'AI prediction: Low risk next 30min', type: 'info' },
  { time: '12:47', msg: 'Geofence exit detected — Industrial area', type: 'warning' },
  { time: '12:48', msg: 'Night travel pattern activated', type: 'alert' },
  { time: '12:49', msg: 'Session completed safely — User 1923', type: 'success' },
  { time: '12:50', msg: 'Incident replay generated — ID 8842', type: 'info' },
  { time: '12:51', msg: 'Campus perimeter breach — South Gate', type: 'critical' },
  { time: '12:52', msg: 'Patrol unit dispatched — Zone 12', type: 'warning' },
  { time: '12:53', msg: 'Digital twin updated — User 4410', type: 'info' },
  { time: '12:54', msg: 'Voice distress signal analyzed — Clear', type: 'success' },
];

const TRUSTED_ENVIRONMENTS = [
  { icon: Building2, name: 'Schools', desc: 'K-12 student safety during commute and campus hours' },
  { icon: Users, name: 'Universities', desc: 'Hostel, late-night travel, campus perimeter security' },
  { icon: Lock, name: 'Corporate Campuses', desc: 'Employee safety for field workers, women, night shifts' },
  { icon: Globe, name: 'Smart Cities', desc: 'City-wide zone monitoring and predictive deployment' },
  { icon: Radio, name: 'Public Safety', desc: 'Government and law enforcement intelligence systems' },
];

const THREAT_SIGNALS = [
  { label: 'Behavioral Anomalies', value: 847, delta: '+12%', color: 'text-amber-400', bg: 'bg-amber-400' },
  { label: 'Route Deviations', value: 234, delta: '+8%', color: 'text-orange-400', bg: 'bg-orange-400' },
  { label: 'Geofence Violations', value: 89, delta: '-3%', color: 'text-red-400', bg: 'bg-red-400' },
  { label: 'Risk Predictions', value: 12403, delta: '+22%', color: 'text-teal-400', bg: 'bg-teal-400' },
  { label: 'Voice Alerts', value: 56, delta: '+5%', color: 'text-violet-400', bg: 'bg-violet-400' },
  { label: 'Resolved Safely', value: 11892, delta: '+19%', color: 'text-emerald-400', bg: 'bg-emerald-400' },
];

const CITY_OPS = [
  { zone: 'Zone Alpha', risk: 'Low', sessions: 342, color: 'border-emerald-500/30', dot: 'bg-emerald-400' },
  { zone: 'Zone Bravo', risk: 'Medium', sessions: 178, color: 'border-amber-500/30', dot: 'bg-amber-400' },
  { zone: 'Zone Charlie', risk: 'Low', sessions: 561, color: 'border-emerald-500/30', dot: 'bg-emerald-400' },
  { zone: 'Zone Delta', risk: 'High', sessions: 94, color: 'border-red-500/30', dot: 'bg-red-400' },
  { zone: 'Zone Echo', risk: 'Low', sessions: 423, color: 'border-emerald-500/30', dot: 'bg-emerald-400' },
  { zone: 'Zone Foxtrot', risk: 'Medium', sessions: 215, color: 'border-amber-500/30', dot: 'bg-amber-400' },
];

const PIPELINE = [
  { icon: Users, title: 'User App', desc: 'Mobile safety interface generating safety signals', color: 'from-blue-500/10 to-blue-500/5', border: 'border-blue-500/20', accent: 'text-blue-400' },
  { icon: Brain, title: 'AI Safety Brain', desc: 'Behavioral analysis, anomaly detection, predictive risk', color: 'from-violet-500/10 to-violet-500/5', border: 'border-violet-500/20', accent: 'text-violet-400' },
  { icon: Radio, title: 'Command Center', desc: 'Real-time operational dashboard for guardians and institutions', color: 'from-amber-500/10 to-amber-500/5', border: 'border-amber-500/20', accent: 'text-amber-400' },
  { icon: Globe, title: 'City Intelligence', desc: 'Aggregated safety insights for large-scale monitoring', color: 'from-teal-500/10 to-teal-500/5', border: 'border-teal-500/20', accent: 'text-teal-400' },
];

const METRICS = [
  { value: '24/7', label: 'Active Monitoring' },
  { value: '< 3s', label: 'Alert Response' },
  { value: '99.9%', label: 'Uptime SLA' },
  { value: '8', label: 'AI Engines' },
];

const FOOTER_LINKS = [
  { category: 'General', email: 'hello@nischint.app' },
  { category: 'Support', email: 'support@nischint.app' },
  { category: 'Partnerships', email: 'partners@nischint.app' },
  { category: 'Press', email: 'press@nischint.app' },
  { category: 'Security', email: 'security@nischint.app' },
];

export default function NischintHomePage() {
  const navigate = useNavigate();
  const [tickerIndex, setTickerIndex] = useState(0);
  const [gridVisible, setGridVisible] = useState(false);
  const [safetyOpen, setSafetyOpen] = useState(false);
  useStructuredData();

  useEffect(() => {
    setGridVisible(true);
    const iv = setInterval(() => {
      setTickerIndex(i => (i + 1) % TICKER_EVENTS.length);
    }, 2200);
    return () => clearInterval(iv);
  }, []);

  return (
    <div className="min-h-screen bg-[#0a0e1a] text-slate-200 overflow-x-hidden">
      {/* Nav */}
      <nav className="fixed top-0 left-0 right-0 z-50 bg-[#0a0e1a]/80 backdrop-blur-xl border-b border-slate-800/40">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2.5" data-testid="nav-logo">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-teal-500 to-emerald-600 flex items-center justify-center">
              <Shield className="w-4 h-4 text-white" />
            </div>
            <span className="text-lg font-bold tracking-tight">NISCHINT</span>
          </div>
          <div className="hidden md:flex items-center gap-8">
            <a href="#platform" className="text-sm text-slate-400 hover:text-white transition-colors">Platform</a>
            <button onClick={() => navigate('/what-is-nischint')} className="text-sm text-teal-400/80 hover:text-teal-300 transition-colors" data-testid="nav-what-is">About</button>
            <a href="#intelligence" className="text-sm text-slate-400 hover:text-white transition-colors">Intelligence</a>
            <div className="relative" onMouseEnter={() => setSafetyOpen(true)} onMouseLeave={() => setSafetyOpen(false)}>
              <button className="text-sm text-slate-400 hover:text-white transition-colors flex items-center gap-1" data-testid="nav-safety">
                Safety <ChevronDown className={`w-3 h-3 transition-transform ${safetyOpen ? 'rotate-180' : ''}`} />
              </button>
              {safetyOpen && (
                <div className="absolute top-full left-1/2 -translate-x-1/2 pt-2 w-52" data-testid="nav-safety-dropdown">
                  <div className="bg-[#111827] border border-slate-700/60 rounded-xl shadow-xl shadow-black/30 py-1.5 overflow-hidden">
                    <button onClick={() => navigate('/women-safety-app')} className="w-full px-4 py-2.5 text-left text-sm text-slate-300 hover:bg-rose-500/10 hover:text-rose-400 transition-colors flex items-center gap-3" data-testid="nav-safety-women">
                      <div className="w-2 h-2 rounded-full bg-rose-400" />Women Safety
                    </button>
                    <button onClick={() => navigate('/kids-safety-app')} className="w-full px-4 py-2.5 text-left text-sm text-slate-300 hover:bg-blue-500/10 hover:text-blue-400 transition-colors flex items-center gap-3" data-testid="nav-safety-kids">
                      <div className="w-2 h-2 rounded-full bg-blue-400" />Kids Safety
                    </button>
                    <button onClick={() => navigate('/family-safety-app')} className="w-full px-4 py-2.5 text-left text-sm text-slate-300 hover:bg-emerald-500/10 hover:text-emerald-400 transition-colors flex items-center gap-3" data-testid="nav-safety-family">
                      <div className="w-2 h-2 rounded-full bg-emerald-400" />Family Safety
                    </button>
                  </div>
                </div>
              )}
            </div>
            <button onClick={() => navigate('/telemetry')} className="text-sm text-slate-400 hover:text-white transition-colors" data-testid="nav-telemetry">Live Network</button>
            <button onClick={() => navigate('/safety-dashboard')} className="text-sm text-slate-400 hover:text-white transition-colors" data-testid="nav-dashboard">Dashboard</button>
            <button onClick={() => navigate('/investors')} className="text-sm text-slate-400 hover:text-white transition-colors" data-testid="nav-investors">Investors</button>
            <button onClick={() => navigate('/blog')} className="text-sm text-slate-400 hover:text-white transition-colors" data-testid="nav-blog">Blog</button>
            <button onClick={() => navigate('/pilot')} className="text-sm text-teal-400 hover:text-teal-300 transition-colors font-medium" data-testid="nav-pilot">Request Pilot</button>
            <div className="flex items-center gap-1.5" data-testid="nav-social-icons">
              {SOCIALS.slice(0, 4).map(s => (
                <a key={s.key} href={s.url} target="_blank" rel="noopener noreferrer" onClick={() => trackSocialClick(s.key)} className={`w-7 h-7 rounded-lg flex items-center justify-center text-slate-400 ${s.hover} transition-all hover:bg-white/5`} title={s.name} data-testid={`nav-social-${s.key}`}>
                  <SocialIcon platform={s.key} size={14} />
                </a>
              ))}
            </div>
            <button onClick={() => navigate('/login')} className="px-4 py-1.5 bg-white/5 border border-slate-700/60 rounded-lg text-sm hover:bg-white/10 transition-colors" data-testid="nav-login">Sign In</button>
          </div>
          <button onClick={() => navigate('/login')} className="md:hidden px-3 py-1.5 bg-white/5 border border-slate-700/60 rounded-lg text-xs">Sign In</button>
        </div>
      </nav>

      {/* ── 1. Hero ── */}
      <section className="relative pt-32 pb-20 px-6" data-testid="hero-section">
        <div className={`absolute inset-0 transition-opacity duration-[3000ms] ${gridVisible ? 'opacity-100' : 'opacity-0'}`}>
          <div className="absolute inset-0" style={{
            backgroundImage: `linear-gradient(rgba(45,212,191,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(45,212,191,0.03) 1px, transparent 1px)`,
            backgroundSize: '60px 60px',
          }} />
          <div className="absolute top-1/4 left-1/3 w-96 h-96 bg-teal-500/5 rounded-full blur-[120px]" />
          <div className="absolute bottom-1/4 right-1/4 w-72 h-72 bg-emerald-500/5 rounded-full blur-[100px]" />
        </div>

        <div className="max-w-5xl mx-auto text-center relative z-10">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-teal-500/5 border border-teal-500/20 mb-8">
            <span className="w-1.5 h-1.5 rounded-full bg-teal-400 animate-pulse" />
            <span className="text-xs text-teal-400 font-medium tracking-wide">INTELLIGENCE NETWORK ACTIVE</span>
          </div>

          <h1 className="text-5xl sm:text-6xl lg:text-7xl font-bold tracking-tight leading-[1.05] mb-6">
            <span className="text-white">AI Safety</span><br />
            <span className="bg-gradient-to-r from-teal-400 to-emerald-400 bg-clip-text text-transparent">Infrastructure</span>
          </h1>

          <p className="text-lg sm:text-xl text-slate-400 max-w-2xl mx-auto mb-10 leading-relaxed">
            The operating system for real-world safety. Nischint connects individuals, institutions, and cities into one predictive safety intelligence network.
          </p>

          <div className="flex flex-col sm:flex-row items-center justify-center gap-4 mb-16">
            <a
              href="mailto:hello@nischint.app"
              className="group px-6 py-3 bg-gradient-to-r from-teal-500 to-emerald-500 text-white font-semibold rounded-xl hover:shadow-lg hover:shadow-teal-500/20 transition-all flex items-center gap-2"
              data-testid="hero-cta-access"
            >
              Request Platform Access
              <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
            </a>
            <a
              href="mailto:hello@nischint.app?subject=Nischint Demo Request"
              className="px-6 py-3 bg-white/5 border border-slate-700/60 text-slate-300 font-medium rounded-xl hover:bg-white/10 transition-colors"
              data-testid="hero-cta-demo"
            >
              Schedule Demo
            </a>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 max-w-2xl mx-auto">
            {METRICS.map((m, i) => (
              <div key={i} className="text-center p-4 rounded-xl bg-white/[0.02] border border-slate-800/40">
                <p className="text-2xl font-bold text-white">{m.value}</p>
                <p className="text-[11px] text-slate-400 uppercase tracking-wider mt-1">{m.label}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 1b. Who Do You Want to Protect ── */}
      <section className="py-20 px-6" data-testid="protect-section">
        <div className="max-w-4xl mx-auto">
          <div className="text-center mb-12">
            <p className="text-xs text-teal-400 font-bold uppercase tracking-widest mb-3">Personal Safety</p>
            <h2 className="text-3xl sm:text-4xl font-bold text-white">Who Do You Want to Protect?</h2>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
            <button onClick={() => navigate('/women-safety-app')} className="group p-6 rounded-2xl bg-white/[0.02] border border-slate-800/40 hover:border-rose-500/40 hover:bg-rose-500/[0.03] transition-all text-left" data-testid="protect-women">
              <div className="w-12 h-12 rounded-xl bg-rose-500/10 flex items-center justify-center mb-4 group-hover:bg-rose-500/20 transition-colors">
                <Shield className="w-6 h-6 text-rose-400" />
              </div>
              <h3 className="text-lg font-semibold text-white mb-1">Women Safety</h3>
              <p className="text-sm text-slate-400 mb-4">AI-powered protection for women — live tracking, voice distress, auto-escalation.</p>
              <span className="text-sm text-rose-400 font-medium flex items-center gap-1 group-hover:gap-2 transition-all">Learn more <ArrowRight className="w-3.5 h-3.5" /></span>
            </button>
            <button onClick={() => navigate('/kids-safety-app')} className="group p-6 rounded-2xl bg-white/[0.02] border border-slate-800/40 hover:border-blue-500/40 hover:bg-blue-500/[0.03] transition-all text-left" data-testid="protect-kids">
              <div className="w-12 h-12 rounded-xl bg-blue-500/10 flex items-center justify-center mb-4 group-hover:bg-blue-500/20 transition-colors">
                <Heart className="w-6 h-6 text-blue-400" />
              </div>
              <h3 className="text-lg font-semibold text-white mb-1">Kids Safety</h3>
              <p className="text-sm text-slate-400 mb-4">Real-time child monitoring — school routes, safe zones, instant parent alerts.</p>
              <span className="text-sm text-blue-400 font-medium flex items-center gap-1 group-hover:gap-2 transition-all">Learn more <ArrowRight className="w-3.5 h-3.5" /></span>
            </button>
            <button onClick={() => navigate('/family-safety-app')} className="group p-6 rounded-2xl bg-white/[0.02] border border-slate-800/40 hover:border-emerald-500/40 hover:bg-emerald-500/[0.03] transition-all text-left" data-testid="protect-family">
              <div className="w-12 h-12 rounded-xl bg-emerald-500/10 flex items-center justify-center mb-4 group-hover:bg-emerald-500/20 transition-colors">
                <Users className="w-6 h-6 text-emerald-400" />
              </div>
              <h3 className="text-lg font-semibold text-white mb-1">Family Safety</h3>
              <p className="text-sm text-slate-400 mb-4">One app for the whole family — kids, parents, elders connected in one safety network.</p>
              <span className="text-sm text-emerald-400 font-medium flex items-center gap-1 group-hover:gap-2 transition-all">Learn more <ArrowRight className="w-3.5 h-3.5" /></span>
            </button>
          </div>
        </div>
      </section>

      {/* ── 2. Live Intelligence Ticker ── */}
      <section className="border-y border-slate-800/40 bg-[#0c1020]" data-testid="intelligence-ticker">
        <div className="max-w-7xl mx-auto px-6 py-3 flex items-center gap-4 overflow-hidden">
          <div className="flex items-center gap-2 shrink-0">
            <span className="w-2 h-2 rounded-full bg-teal-400 animate-pulse" />
            <span className="text-[10px] font-bold text-teal-400 uppercase tracking-widest">LIVE</span>
          </div>
          <div className="flex-1 overflow-hidden">
            <div className="flex items-center gap-3">
              <span className="text-xs text-slate-400 font-mono shrink-0">{TICKER_EVENTS[tickerIndex].time}</span>
              <span className={`text-xs font-medium ${
                TICKER_EVENTS[tickerIndex].type === 'critical' ? 'text-red-400' :
                TICKER_EVENTS[tickerIndex].type === 'alert' ? 'text-amber-400' :
                TICKER_EVENTS[tickerIndex].type === 'warning' ? 'text-orange-400' :
                TICKER_EVENTS[tickerIndex].type === 'success' ? 'text-emerald-400' :
                'text-slate-400'
              }`}>
                {TICKER_EVENTS[tickerIndex].msg}
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* ── 3. Trusted Environments ── */}
      <section className="py-24 px-6" data-testid="trusted-environments">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-16">
            <p className="text-xs text-teal-400 font-bold uppercase tracking-widest mb-3">Trusted Environments</p>
            <h2 className="text-3xl sm:text-4xl font-bold text-white mb-4">Safety Across Every Scale</h2>
            <p className="text-slate-400 max-w-xl mx-auto">From individual users to entire cities — Nischint adapts to protect every environment.</p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
            {TRUSTED_ENVIRONMENTS.map((env, i) => (
              <div key={i} className="group text-center p-6 rounded-2xl bg-white/[0.02] border border-slate-800/40 hover:border-teal-500/30 hover:bg-teal-500/[0.02] transition-all duration-300">
                <div className="w-12 h-12 rounded-xl bg-slate-800/50 flex items-center justify-center mx-auto mb-4 group-hover:bg-teal-500/10 transition-colors">
                  <env.icon className="w-6 h-6 text-slate-400 group-hover:text-teal-400 transition-colors" />
                </div>
                <p className="text-sm font-semibold text-white mb-1">{env.name}</p>
                <p className="text-[11px] text-slate-400 leading-relaxed">{env.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 4. Live Threat Intelligence ── */}
      <section id="intelligence" className="py-24 px-6 bg-[#0c1020]" data-testid="live-threat-intelligence">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-16">
            <p className="text-xs text-teal-400 font-bold uppercase tracking-widest mb-3">Threat Intelligence</p>
            <h2 className="text-3xl sm:text-4xl font-bold text-white mb-4">Real-Time Signal Processing</h2>
            <p className="text-slate-400 max-w-xl mx-auto">Continuous analysis of safety signals across the entire network. Every anomaly detected, scored, and acted upon.</p>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
            {THREAT_SIGNALS.map((sig, i) => (
              <div key={i} className="p-4 rounded-xl bg-white/[0.02] border border-slate-800/40 text-center">
                <div className="flex items-center justify-center gap-1.5 mb-2">
                  <span className={`w-1.5 h-1.5 rounded-full ${sig.bg}`} />
                  <span className={`text-xs font-semibold ${sig.color}`}>{sig.delta}</span>
                </div>
                <p className="text-xl font-bold text-white">{sig.value.toLocaleString()}</p>
                <p className="text-[9px] text-slate-400 uppercase tracking-wider mt-1">{sig.label}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 4.5 City Safety Simulation ── */}
      <section className="py-24 px-6" data-testid="city-simulation-section">
        <div className="max-w-5xl mx-auto">
          <CitySafetySimulation />
        </div>
      </section>

      {/* ── 5. City Safety Operations ── */}
      <section className="py-24 px-6" data-testid="city-safety-ops">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-16">
            <p className="text-xs text-teal-400 font-bold uppercase tracking-widest mb-3">Operations</p>
            <h2 className="text-3xl sm:text-4xl font-bold text-white mb-4">City Safety Operations</h2>
            <p className="text-slate-400 max-w-xl mx-auto">Zone-level monitoring with real-time risk assessment, active session tracking, and automated response coordination.</p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {CITY_OPS.map((zone, i) => (
              <div key={i} className={`p-5 rounded-xl bg-white/[0.02] border ${zone.color} flex items-center gap-4`}>
                <div className="shrink-0">
                  <span className={`block w-3 h-3 rounded-full ${zone.dot}`} />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-white">{zone.zone}</p>
                  <p className="text-[10px] text-slate-400">{zone.sessions} active sessions</p>
                </div>
                <div className="shrink-0 text-right">
                  <span className={`text-[10px] font-bold uppercase tracking-wider ${
                    zone.risk === 'Low' ? 'text-emerald-400' : zone.risk === 'Medium' ? 'text-amber-400' : 'text-red-400'
                  }`}>{zone.risk} Risk</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 6. Platform Architecture ── */}
      <section id="platform" className="py-24 px-6 bg-[#0c1020]" data-testid="platform-architecture">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-16">
            <p className="text-xs text-teal-400 font-bold uppercase tracking-widest mb-3">Architecture</p>
            <h2 className="text-3xl sm:text-4xl font-bold text-white mb-4">End-to-End Safety Pipeline</h2>
            <p className="text-slate-400 max-w-xl mx-auto">From individual user to city-scale intelligence — every layer is connected, predictive, and autonomous.</p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
            {PIPELINE.map((item, i) => (
              <div key={i} className="relative">
                <div className={`p-6 rounded-2xl bg-gradient-to-b ${item.color} border ${item.border} h-full`}>
                  <item.icon className={`w-8 h-8 ${item.accent} mb-4`} />
                  <h3 className="text-base font-semibold text-white mb-2">{item.title}</h3>
                  <p className="text-xs text-slate-400 leading-relaxed">{item.desc}</p>
                </div>
                {i < 3 && (
                  <div className="hidden sm:flex absolute top-1/2 -right-3 z-10">
                    <ChevronRight className="w-5 h-5 text-slate-600" />
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 7. Safety Network Effect ── */}
      <section className="py-24 px-6" data-testid="safety-network-effect">
        <div className="max-w-4xl mx-auto text-center">
          <p className="text-xs text-teal-400 font-bold uppercase tracking-widest mb-3">Network Effect</p>
          <h2 className="text-3xl sm:text-4xl font-bold text-white mb-6">Every Node Makes the Network Smarter</h2>
          <p className="text-slate-400 max-w-2xl mx-auto mb-12 leading-relaxed">
            Every user, guardian, institution, and city connected to Nischint strengthens the entire safety network. More data. Better predictions. Faster responses.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="p-6 rounded-2xl bg-gradient-to-b from-blue-500/5 to-transparent border border-blue-500/15">
              <div className="w-12 h-12 rounded-xl bg-blue-500/10 flex items-center justify-center mx-auto mb-4">
                <Users className="w-6 h-6 text-blue-400" />
              </div>
              <h3 className="text-sm font-semibold text-white mb-2">Individual Layer</h3>
              <p className="text-[11px] text-slate-400 leading-relaxed">Personal safety sessions, SOS, shake detection, and guardian alerts creating ground-level safety signals.</p>
            </div>
            <div className="p-6 rounded-2xl bg-gradient-to-b from-violet-500/5 to-transparent border border-violet-500/15">
              <div className="w-12 h-12 rounded-xl bg-violet-500/10 flex items-center justify-center mx-auto mb-4">
                <Building2 className="w-6 h-6 text-violet-400" />
              </div>
              <h3 className="text-sm font-semibold text-white mb-2">Institutional Layer</h3>
              <p className="text-[11px] text-slate-400 leading-relaxed">Schools, corporates, and campuses deploying Nischint at scale — aggregating intelligence across populations.</p>
            </div>
            <div className="p-6 rounded-2xl bg-gradient-to-b from-teal-500/5 to-transparent border border-teal-500/15">
              <div className="w-12 h-12 rounded-xl bg-teal-500/10 flex items-center justify-center mx-auto mb-4">
                <Network className="w-6 h-6 text-teal-400" />
              </div>
              <h3 className="text-sm font-semibold text-white mb-2">City Layer</h3>
              <p className="text-[11px] text-slate-400 leading-relaxed">City-wide safety intelligence — zone risk mapping, predictive patrol routing, and coordinated emergency response.</p>
            </div>
          </div>
        </div>
      </section>

      {/* ── 8. Call to Action ── */}
      <section className="py-24 px-6 bg-gradient-to-b from-[#0c1020] to-[#0a0e1a]" data-testid="cta-section">
        <div className="max-w-3xl mx-auto text-center">
          <h2 className="text-3xl sm:text-4xl font-bold text-white mb-4">Deploy Nischint at Your Institution</h2>
          <p className="text-slate-400 mb-8 max-w-xl mx-auto">Join the pilot program. Schools, universities, corporate campuses, and smart city projects are onboarding now.</p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <button
              onClick={() => navigate('/pilot')}
              className="group px-8 py-3.5 bg-gradient-to-r from-teal-500 to-emerald-500 text-white font-semibold rounded-xl hover:shadow-lg hover:shadow-teal-500/20 transition-all flex items-center gap-2"
              data-testid="cta-pilot"
            >
              Request Pilot Deployment
              <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
            </button>
            <a
              href="mailto:hello@nischint.app?subject=Nischint Demo Request"
              className="px-8 py-3.5 bg-white/5 border border-slate-700/60 text-slate-300 rounded-xl hover:bg-white/10 transition-colors"
              data-testid="cta-demo"
            >
              Schedule Demo
            </a>
          </div>
        </div>
      </section>

      {/* ── Social CTA ── */}
      <SocialCTASection />

      {/* ── 9. Footer ── */}
      <footer className="border-t border-slate-800/40 py-12 px-6" data-testid="footer">
        <div className="max-w-5xl mx-auto">
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-10 mb-10">
            {/* Brand */}
            <div>
              <div className="flex items-center gap-2 mb-3">
                <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-teal-500 to-emerald-600 flex items-center justify-center">
                  <Shield className="w-3.5 h-3.5 text-white" />
                </div>
                <span className="text-sm font-bold tracking-tight">NISCHINT</span>
              </div>
              <p className="text-xs text-slate-400 leading-relaxed">AI Safety Infrastructure.<br />The AI Safety Operating System.</p>
            </div>
            {/* Navigation */}
            <div>
              <p className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-3">Platform</p>
              <div className="space-y-2">
                <button onClick={() => navigate('/telemetry')} className="block text-xs text-slate-400 hover:text-slate-300 transition-colors">Live Network</button>
                <button onClick={() => navigate('/what-is-nischint')} className="block text-xs text-slate-400 hover:text-teal-400 transition-colors">What is Nischint</button>
                <button onClick={() => navigate('/about')} className="block text-xs text-slate-400 hover:text-teal-400 transition-colors" data-testid="footer-about">About</button>
                <button onClick={() => navigate('/investors')} className="block text-xs text-slate-400 hover:text-slate-300 transition-colors">Investors</button>
                <button onClick={() => navigate('/pilot')} className="block text-xs text-slate-400 hover:text-slate-300 transition-colors">Pilot Program</button>
                <button onClick={() => navigate('/blog')} className="block text-xs text-slate-400 hover:text-slate-300 transition-colors">Blog</button>
                <button onClick={() => navigate('/login')} className="block text-xs text-slate-400 hover:text-slate-300 transition-colors">Sign In</button>
                <button onClick={() => navigate('/privacy-policy')} className="block text-xs text-slate-400 hover:text-slate-300 transition-colors" data-testid="footer-privacy">Privacy Policy</button>
                <a href="/api/dpo" target="_blank" rel="noopener" className="block text-xs text-slate-400 hover:text-slate-300 transition-colors" data-testid="footer-dpo">Data Protection Officer</a>
              </div>
            </div>
            {/* Safety */}
            <div>
              <p className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-3">Safety</p>
              <div className="space-y-2">
                <button onClick={() => navigate('/women-safety-app')} className="block text-xs text-slate-400 hover:text-rose-400 transition-colors">Women Safety</button>
                <button onClick={() => navigate('/kids-safety-app')} className="block text-xs text-slate-400 hover:text-blue-400 transition-colors">Kids Safety</button>
                <button onClick={() => navigate('/family-safety-app')} className="block text-xs text-slate-400 hover:text-emerald-400 transition-colors">Family Safety</button>
              </div>
            </div>
            {/* Connect */}
            <div>
              <p className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-3">Connect with NISCHINT</p>
              <div className="grid grid-cols-3 gap-2" data-testid="footer-social-grid">
                {SOCIALS.map(s => (
                  <a key={s.key} href={s.url} target="_blank" rel="noopener noreferrer" onClick={() => trackSocialClick(s.key)} className={`flex items-center justify-center w-9 h-9 rounded-lg bg-white/[0.03] border border-slate-800/40 text-slate-400 ${s.hover} transition-all hover:scale-110 hover:border-slate-600`} title={s.name} data-testid={`footer-social-${s.key}`}>
                    <SocialIcon platform={s.key} size={14} />
                  </a>
                ))}
              </div>
            </div>
          </div>
          <div className="border-t border-slate-800/40 pt-6 flex flex-col sm:flex-row items-center justify-between gap-3">
            <p className="text-[10px] text-slate-400">&copy; 2026 Nischint Technologies. All rights reserved.</p>
            <a href="mailto:alerts@nischint.app" className="text-[10px] text-slate-400 hover:text-slate-400 transition-colors">alerts@nischint.app</a>
          </div>
        </div>
      </footer>

      <FloatingSocialBar />
    </div>
  );
}
