import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Shield, ArrowLeft, CheckCircle, Building2, User, Mail, Phone, MapPin, Users, MessageSquare, Loader2 } from 'lucide-react';
import api from '../api';

const INSTITUTION_TYPES = [
  'School (K-12)',
  'University / College',
  'Corporate Office',
  'Manufacturing / Industrial',
  'Government / Municipal',
  'Smart City Project',
  'NGO / Non-Profit',
  'Other',
];

export default function PilotSignupPage() {
  const navigate = useNavigate();
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [form, setForm] = useState({
    institution_name: '',
    contact_person: '',
    email: '',
    phone: '',
    city: '',
    institution_type: '',
    headcount: '',
    message: '',
  });

  const set = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.value }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.institution_name || !form.contact_person || !form.email) {
      setError('Please fill in all required fields');
      return;
    }
    setLoading(true);
    setError('');
    try {
      await api.post('/pilot/signup', form);
      setSubmitted(true);
    } catch (err) {
      setError('Something went wrong. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  if (submitted) {
    return (
      <div className="min-h-screen bg-[#0a0e1a] flex items-center justify-center px-6">
        <div className="max-w-md w-full text-center" data-testid="pilot-success">
          <div className="w-16 h-16 rounded-2xl bg-teal-500/10 border border-teal-500/20 flex items-center justify-center mx-auto mb-6">
            <CheckCircle className="w-8 h-8 text-teal-400" />
          </div>
          <h1 className="text-2xl font-bold text-white mb-3">Thank You</h1>
          <p className="text-slate-400 leading-relaxed mb-2">Thank you for your interest in deploying Nischint.</p>
          <p className="text-slate-400 leading-relaxed mb-8">Our team will contact you within <span className="text-teal-400 font-semibold">48 hours</span> to schedule a pilot deployment discussion.</p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
            <button onClick={() => navigate('/')} className="px-6 py-2.5 bg-white/5 border border-slate-700/60 rounded-xl text-sm text-slate-300 hover:bg-white/10 transition-colors">
              Back to Home
            </button>
            <button onClick={() => navigate('/investors')} className="px-6 py-2.5 bg-teal-500/10 border border-teal-500/30 rounded-xl text-sm text-teal-400 hover:bg-teal-500/20 transition-colors">
              View Investor Overview
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0a0e1a] text-slate-200">
      {/* Nav */}
      <nav className="fixed top-0 left-0 right-0 z-50 bg-[#0a0e1a]/80 backdrop-blur-xl border-b border-slate-800/40">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <button onClick={() => navigate('/')} className="flex items-center gap-2.5" data-testid="pilot-nav-logo">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-teal-500 to-emerald-600 flex items-center justify-center">
              <Shield className="w-4.5 h-4.5 text-white" />
            </div>
            <span className="text-lg font-bold tracking-tight">NISCHINT</span>
          </button>
          <button onClick={() => navigate('/login')} className="px-4 py-1.5 bg-white/5 border border-slate-700/60 rounded-lg text-sm hover:bg-white/10 transition-colors">Platform</button>
        </div>
      </nav>

      <div className="pt-28 pb-20 px-6">
        <div className="max-w-2xl mx-auto">
          {/* Header */}
          <div className="text-center mb-10">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-teal-500/5 border border-teal-500/20 mb-5">
              <span className="text-[10px] font-bold text-teal-400 uppercase tracking-widest">PILOT PROGRAM</span>
            </div>
            <h1 className="text-3xl sm:text-4xl font-bold text-white mb-3" data-testid="pilot-heading">Request a Pilot Deployment</h1>
            <p className="text-slate-400">Deploy Nischint's AI safety infrastructure at your institution. We'll work with your team to customize and launch within weeks.</p>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-4" data-testid="pilot-form">
            {/* Institution Name */}
            <div>
              <label className="flex items-center gap-2 text-xs font-medium text-slate-400 mb-1.5">
                <Building2 className="w-3.5 h-3.5" /> Institution Name <span className="text-red-400">*</span>
              </label>
              <input
                type="text" value={form.institution_name} onChange={set('institution_name')}
                placeholder="e.g. Delhi Public School, Noida"
                className="w-full px-4 py-2.5 bg-white/[0.03] border border-slate-800/60 rounded-xl text-sm text-white placeholder-slate-600 focus:border-teal-500/40 focus:outline-none transition-colors"
                data-testid="pilot-institution"
              />
            </div>

            {/* Contact + Email */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="flex items-center gap-2 text-xs font-medium text-slate-400 mb-1.5">
                  <User className="w-3.5 h-3.5" /> Contact Person <span className="text-red-400">*</span>
                </label>
                <input
                  type="text" value={form.contact_person} onChange={set('contact_person')}
                  placeholder="Full name"
                  className="w-full px-4 py-2.5 bg-white/[0.03] border border-slate-800/60 rounded-xl text-sm text-white placeholder-slate-600 focus:border-teal-500/40 focus:outline-none"
                  data-testid="pilot-contact"
                />
              </div>
              <div>
                <label className="flex items-center gap-2 text-xs font-medium text-slate-400 mb-1.5">
                  <Mail className="w-3.5 h-3.5" /> Email <span className="text-red-400">*</span>
                </label>
                <input
                  type="email" value={form.email} onChange={set('email')}
                  placeholder="admin@institution.edu"
                  className="w-full px-4 py-2.5 bg-white/[0.03] border border-slate-800/60 rounded-xl text-sm text-white placeholder-slate-600 focus:border-teal-500/40 focus:outline-none"
                  data-testid="pilot-email"
                />
              </div>
            </div>

            {/* Phone + City */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="flex items-center gap-2 text-xs font-medium text-slate-400 mb-1.5">
                  <Phone className="w-3.5 h-3.5" /> Phone
                </label>
                <input
                  type="tel" value={form.phone} onChange={set('phone')}
                  placeholder="+91 98765 43210"
                  className="w-full px-4 py-2.5 bg-white/[0.03] border border-slate-800/60 rounded-xl text-sm text-white placeholder-slate-600 focus:border-teal-500/40 focus:outline-none"
                  data-testid="pilot-phone"
                />
              </div>
              <div>
                <label className="flex items-center gap-2 text-xs font-medium text-slate-400 mb-1.5">
                  <MapPin className="w-3.5 h-3.5" /> City
                </label>
                <input
                  type="text" value={form.city} onChange={set('city')}
                  placeholder="Mumbai"
                  className="w-full px-4 py-2.5 bg-white/[0.03] border border-slate-800/60 rounded-xl text-sm text-white placeholder-slate-600 focus:border-teal-500/40 focus:outline-none"
                  data-testid="pilot-city"
                />
              </div>
            </div>

            {/* Institution Type + Headcount */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="flex items-center gap-2 text-xs font-medium text-slate-400 mb-1.5">
                  <Building2 className="w-3.5 h-3.5" /> Institution Type
                </label>
                <select
                  value={form.institution_type} onChange={set('institution_type')}
                  className="w-full px-4 py-2.5 bg-white/[0.03] border border-slate-800/60 rounded-xl text-sm text-white focus:border-teal-500/40 focus:outline-none appearance-none"
                  data-testid="pilot-type"
                >
                  <option value="" className="bg-slate-900">Select type</option>
                  {INSTITUTION_TYPES.map(t => <option key={t} value={t} className="bg-slate-900">{t}</option>)}
                </select>
              </div>
              <div>
                <label className="flex items-center gap-2 text-xs font-medium text-slate-400 mb-1.5">
                  <Users className="w-3.5 h-3.5" /> Number of Students / Employees
                </label>
                <input
                  type="text" value={form.headcount} onChange={set('headcount')}
                  placeholder="e.g. 5000"
                  className="w-full px-4 py-2.5 bg-white/[0.03] border border-slate-800/60 rounded-xl text-sm text-white placeholder-slate-600 focus:border-teal-500/40 focus:outline-none"
                  data-testid="pilot-headcount"
                />
              </div>
            </div>

            {/* Message */}
            <div>
              <label className="flex items-center gap-2 text-xs font-medium text-slate-400 mb-1.5">
                <MessageSquare className="w-3.5 h-3.5" /> Message
              </label>
              <textarea
                value={form.message} onChange={set('message')}
                rows={3}
                placeholder="Tell us about your safety requirements or any specific use cases..."
                className="w-full px-4 py-2.5 bg-white/[0.03] border border-slate-800/60 rounded-xl text-sm text-white placeholder-slate-600 focus:border-teal-500/40 focus:outline-none resize-none"
                data-testid="pilot-message"
              />
            </div>

            {error && <p className="text-red-400 text-xs">{error}</p>}

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 bg-gradient-to-r from-teal-500 to-emerald-500 text-white font-semibold rounded-xl hover:shadow-lg hover:shadow-teal-500/20 transition-all disabled:opacity-50 flex items-center justify-center gap-2"
              data-testid="pilot-submit"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
              {loading ? 'Submitting...' : 'Request Pilot Deployment'}
            </button>
          </form>
        </div>
      </div>

      {/* Footer */}
      <footer className="border-t border-slate-800/40 py-12 px-6" data-testid="pilot-footer">
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
                <button onClick={() => navigate('/investors')} className="block text-xs text-slate-400 hover:text-slate-300 transition-colors">Investors</button>
                <button onClick={() => navigate('/login')} className="block text-xs text-slate-400 hover:text-slate-300 transition-colors">Sign In</button>
              </div>
            </div>
            <div>
              <p className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-3">Contact</p>
              <div className="space-y-1.5">
                <a href="mailto:hello@nischint.app" className="block text-[11px] text-slate-400 hover:text-teal-400 transition-colors">hello@nischint.app</a>
                <a href="mailto:partners@nischint.app" className="block text-[11px] text-slate-400 hover:text-teal-400 transition-colors">partners@nischint.app</a>
                <a href="mailto:support@nischint.app" className="block text-[11px] text-slate-400 hover:text-teal-400 transition-colors">support@nischint.app</a>
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
