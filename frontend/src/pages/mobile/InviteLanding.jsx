import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import api from '../../api';
import {
  Shield, Users, Clock, CheckCircle, AlertTriangle,
  Loader2, Download, ArrowRight, Heart,
} from 'lucide-react';

export default function InviteLanding() {
  const { token } = useParams();
  const navigate = useNavigate();
  const { user, isAuthenticated } = useAuth();
  const [invite, setInvite] = useState(null);
  const [loading, setLoading] = useState(true);
  const [accepting, setAccepting] = useState(false);
  const [error, setError] = useState('');
  const [accepted, setAccepted] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const res = await api.get(`/guardian-network/invite/${token}`);
        setInvite(res.data.invite);
        if (res.data.already_accepted) setAccepted(true);
      } catch (e) {
        const status = e.response?.status;
        if (status === 404) setError('This invite link is invalid.');
        else if (status === 410) setError(e.response?.data?.detail || 'This invite has expired.');
        else setError('Could not load invite.');
      }
      setLoading(false);
    })();
  }, [token]);

  const handleAccept = async () => {
    if (!isAuthenticated) {
      sessionStorage.setItem('nischint_pending_invite', token);
      navigate('/login');
      return;
    }
    setAccepting(true);
    try {
      const res = await api.post(`/guardian-network/invite/${token}/accept`);
      setAccepted(true);
      setInvite(prev => ({ ...prev, status: 'accepted' }));
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to accept invite');
    }
    setAccepting(false);
  };

  // Determine time remaining
  const getTimeRemaining = () => {
    if (!invite?.expires_at) return '';
    const diff = new Date(invite.expires_at) - Date.now();
    if (diff <= 0) return 'Expired';
    const hours = Math.floor(diff / 3600000);
    if (hours > 24) return `${Math.floor(hours / 24)}d ${hours % 24}h remaining`;
    return `${hours}h remaining`;
  };

  if (loading) {
    return (
      <div className="min-h-[100dvh] bg-slate-950 flex items-center justify-center">
        <Loader2 className="w-8 h-8 text-teal-400 animate-spin" />
      </div>
    );
  }

  if (error && !invite) {
    return (
      <div className="min-h-[100dvh] bg-slate-950 flex flex-col items-center justify-center px-6 text-center">
        <AlertTriangle className="w-12 h-12 text-amber-400 mb-4" />
        <h1 className="text-lg font-bold text-white mb-2">Invite Unavailable</h1>
        <p className="text-sm text-slate-400 mb-6">{error}</p>
        <button
          onClick={() => navigate('/login')}
          className="px-6 py-2.5 rounded-full bg-teal-500 text-white text-sm font-bold active:scale-95 transition-transform"
          data-testid="invite-login-btn"
        >
          Open Nischint
        </button>
      </div>
    );
  }

  if (accepted) {
    return (
      <div className="min-h-[100dvh] bg-slate-950 flex flex-col items-center justify-center px-6 text-center" data-testid="invite-accepted">
        <div className="w-20 h-20 rounded-full bg-teal-500/20 flex items-center justify-center mb-5">
          <CheckCircle className="w-10 h-10 text-teal-400" />
        </div>
        <h1 className="text-xl font-bold text-white mb-2">You're Now a Guardian</h1>
        <p className="text-sm text-slate-400 mb-1">
          You've joined {invite?.inviter_name}'s safety network
        </p>
        <p className="text-xs text-slate-500 mb-8">
          You'll receive alerts when they need help
        </p>
        <button
          onClick={() => navigate('/m/home')}
          className="px-6 py-3 rounded-2xl bg-teal-500 text-white font-bold text-sm flex items-center gap-2 active:scale-95 transition-transform"
          data-testid="invite-go-home"
        >
          Open Dashboard <ArrowRight className="w-4 h-4" />
        </button>
      </div>
    );
  }

  return (
    <div className="min-h-[100dvh] bg-slate-950 flex flex-col" data-testid="invite-landing">
      {/* Hero */}
      <div className="flex-1 flex flex-col items-center justify-center px-6 text-center">
        {/* Shield Animation */}
        <div className="relative mb-6">
          <div className="w-24 h-24 rounded-full bg-teal-500/10 flex items-center justify-center">
            <Shield className="w-12 h-12 text-teal-400" />
          </div>
          <div className="absolute -top-1 -right-1 w-8 h-8 rounded-full bg-red-500/20 flex items-center justify-center animate-pulse">
            <Heart className="w-4 h-4 text-red-400" />
          </div>
        </div>

        <h1 className="text-xl font-bold text-white mb-2">
          {invite?.inviter_name} needs you
        </h1>
        <p className="text-sm text-slate-400 mb-6 max-w-[280px] leading-relaxed">
          You've been invited to join their safety network as a
          <span className="text-teal-400 font-medium capitalize"> {invite?.relationship_type?.replace(/_/g, ' ')}</span>.
          You'll receive real-time safety alerts and can monitor their well-being.
        </p>

        {/* Invite Card */}
        <div className="w-full max-w-[340px] p-4 rounded-2xl bg-slate-800/50 border border-slate-700/40 mb-6">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-10 h-10 rounded-full bg-teal-500/15 flex items-center justify-center">
              <Users className="w-5 h-5 text-teal-400" />
            </div>
            <div className="text-left">
              <p className="text-xs font-semibold text-white">{invite?.inviter_name}</p>
              <p className="text-[10px] text-slate-500">Invited you as {invite?.relationship_type?.replace(/_/g, ' ')}</p>
            </div>
          </div>

          <div className="flex items-center gap-4 text-[10px] text-slate-500 pt-2 border-t border-slate-700/30">
            <span className="flex items-center gap-1">
              <Clock className="w-3 h-3" /> {getTimeRemaining()}
            </span>
            {invite?.guardian_email && (
              <span className="truncate">{invite.guardian_email}</span>
            )}
          </div>
        </div>

        {/* What you'll get */}
        <div className="w-full max-w-[340px] space-y-2 mb-8">
          {[
            'Real-time safety alerts',
            'SOS emergency notifications',
            'Live location tracking during sessions',
            'AI-powered risk assessments',
          ].map((item, i) => (
            <div key={i} className="flex items-center gap-2.5 text-left">
              <div className="w-1.5 h-1.5 rounded-full bg-teal-400 shrink-0" />
              <span className="text-[11px] text-slate-400">{item}</span>
            </div>
          ))}
        </div>

        {/* Accept Button */}
        <button
          onClick={handleAccept}
          disabled={accepting}
          className="w-full max-w-[340px] py-3.5 rounded-2xl bg-teal-500 text-white font-bold text-sm flex items-center justify-center gap-2 active:scale-[0.98] transition-transform disabled:opacity-50 shadow-lg shadow-teal-500/20"
          data-testid="accept-invite-btn"
        >
          {accepting ? (
            <><Loader2 className="w-4 h-4 animate-spin" /> Accepting...</>
          ) : isAuthenticated ? (
            <><Shield className="w-4 h-4" /> Accept & Join Safety Network</>
          ) : (
            <><ArrowRight className="w-4 h-4" /> Sign In to Accept</>
          )}
        </button>

        {!isAuthenticated && (
          <p className="text-[10px] text-slate-600 mt-2">You'll need to sign in or create an account first</p>
        )}

        {error && (
          <p className="text-xs text-red-400 mt-3">{error}</p>
        )}
      </div>

      {/* Install prompt */}
      <div className="px-6 pb-8 pt-4 border-t border-slate-800/50">
        <div className="flex items-center gap-3 mb-3">
          <Download className="w-5 h-5 text-slate-500" />
          <div>
            <p className="text-xs text-white font-medium">Install Nischint</p>
            <p className="text-[10px] text-slate-500">Add to home screen for instant alerts</p>
          </div>
        </div>
        <p className="text-[9px] text-slate-600 text-center">
          Nischint — AI-Powered Safety for Your Loved Ones
        </p>
      </div>
    </div>
  );
}
