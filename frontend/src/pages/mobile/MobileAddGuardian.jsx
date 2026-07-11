import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../../api';
import {
  ArrowLeft, UserPlus, Loader2, Mail, Heart, Users,
  ShieldCheck, Building, User, Link2, Share2, Copy, Check,
} from 'lucide-react';

const RELATIONSHIPS = [
  { id: 'parent', icon: Heart, label: 'Parent' },
  { id: 'spouse', icon: Heart, label: 'Spouse' },
  { id: 'sibling', icon: Users, label: 'Sibling' },
  { id: 'friend', icon: User, label: 'Friend' },
  { id: 'campus_security', icon: Building, label: 'Campus Security' },
  { id: 'other', icon: ShieldCheck, label: 'Other' },
];

export default function MobileAddGuardian() {
  const navigate = useNavigate();
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [relationship, setRelationship] = useState('');
  const [isPrimary, setIsPrimary] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // Invite link state
  const [inviteResult, setInviteResult] = useState(null);
  const [copied, setCopied] = useState(false);

  const handleCreateInvite = async () => {
    if (!relationship) {
      setError('Please select a relationship type');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const res = await api.post('/guardian-network/invite', {
        guardian_email: email || undefined,
        guardian_name: name || undefined,
        relationship_type: relationship,
      });
      setInviteResult(res.data);
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to create invite');
    }
    setLoading(false);
  };

  const handleDirectAdd = async () => {
    if (!name || !relationship) {
      setError('Name and relationship are required');
      return;
    }
    setLoading(true);
    setError('');
    try {
      await api.post('/guardian-network/', {
        guardian_name: name,
        guardian_email: email || undefined,
        relationship_type: relationship,
        is_primary: isPrimary,
      });
      navigate('/m/guardians', { replace: true });
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to add guardian');
    }
    setLoading(false);
  };

  const getShareUrl = () => {
    if (!inviteResult?.invite?.invite_token) return '';
    return `${window.location.origin}/invite/${inviteResult.invite.invite_token}`;
  };

  const shareInvite = async () => {
    const url = getShareUrl();
    const text = `${inviteResult.share_message}${url}`;

    if (navigator.share) {
      try {
        await navigator.share({ title: 'Nischint Safety - Guardian Invite', text, url });
        return;
      } catch { /* user cancelled or not supported */ }
    }
    copyLink();
  };

  const copyLink = () => {
    const url = getShareUrl();
    navigator.clipboard.writeText(url).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }).catch(() => {});
  };

  // Success — show invite link
  if (inviteResult) {
    const url = getShareUrl();
    return (
      <div className="px-4 pt-4 pb-6" data-testid="invite-created">
        <button onClick={() => navigate('/m/guardians')} className="p-2 -ml-2 rounded-full active:bg-slate-800">
          <ArrowLeft className="w-5 h-5 text-slate-400" />
        </button>

        <div className="mt-6 text-center mb-6">
          <div className="w-16 h-16 rounded-full bg-teal-500/15 flex items-center justify-center mx-auto mb-3">
            <Link2 className="w-7 h-7 text-teal-400" />
          </div>
          <h1 className="text-lg font-bold text-white">Invite Link Created</h1>
          <p className="text-sm text-slate-400 mt-1">Share this link with your guardian</p>
        </div>

        {/* Link Display */}
        <div className="p-3 rounded-xl bg-slate-800 border border-slate-700 mb-4">
          <p className="text-[11px] text-teal-400 font-mono break-all leading-relaxed" data-testid="invite-url">
            {url}
          </p>
        </div>

        {/* Action Buttons */}
        <div className="grid grid-cols-2 gap-3 mb-6">
          <button
            onClick={shareInvite}
            className="py-3 rounded-xl bg-teal-500 text-white text-xs font-bold flex items-center justify-center gap-2 active:scale-95 transition-transform"
            data-testid="share-invite-btn"
          >
            <Share2 className="w-4 h-4" /> Share
          </button>
          <button
            onClick={copyLink}
            className="py-3 rounded-xl bg-slate-800 border border-slate-700 text-white text-xs font-bold flex items-center justify-center gap-2 active:scale-95 transition-transform"
            data-testid="copy-invite-btn"
          >
            {copied ? <><Check className="w-4 h-4 text-teal-400" /> Copied!</> : <><Copy className="w-4 h-4" /> Copy Link</>}
          </button>
        </div>

        {/* Invite Details */}
        <div className="p-4 rounded-2xl bg-slate-800/30 border border-slate-700/30 mb-4">
          <h3 className="text-[10px] text-slate-500 uppercase font-medium mb-2">Invite Details</h3>
          <div className="space-y-1.5">
            {inviteResult.invite.guardian_name && (
              <p className="text-xs text-slate-300">Name: {inviteResult.invite.guardian_name}</p>
            )}
            {inviteResult.invite.guardian_email && (
              <p className="text-xs text-slate-300">Email: {inviteResult.invite.guardian_email}</p>
            )}
            <p className="text-xs text-slate-300 capitalize">Relationship: {inviteResult.invite.relationship_type.replace(/_/g, ' ')}</p>
            <p className="text-xs text-slate-500">Expires in 48 hours</p>
          </div>
        </div>

        {/* Share Message Preview */}
        <div className="p-3 rounded-xl bg-blue-500/8 border border-blue-500/20">
          <p className="text-[10px] text-blue-300 leading-relaxed">
            "{inviteResult.share_message}{url}"
          </p>
        </div>

        <button
          onClick={() => { setInviteResult(null); setName(''); setEmail(''); setRelationship(''); }}
          className="w-full mt-4 py-3 rounded-xl bg-slate-800/30 border border-slate-700/30 text-slate-400 text-xs font-medium active:scale-[0.98] transition-transform"
          data-testid="create-another-btn"
        >
          Create Another Invite
        </button>
      </div>
    );
  }

  return (
    <div className="px-4 pt-4 pb-6" data-testid="mobile-add-guardian">
      <div className="flex items-center gap-3 mb-5">
        <button onClick={() => navigate('/m/guardians')} className="p-2 -ml-2 rounded-full active:bg-slate-800">
          <ArrowLeft className="w-5 h-5 text-slate-400" />
        </button>
        <h1 className="text-base font-bold text-white">Add Guardian</h1>
      </div>

      <div className="space-y-4">
        {/* Name */}
        <div>
          <label className="text-[11px] text-slate-500 uppercase font-medium mb-1.5 block">Guardian's Name</label>
          <input
            type="text"
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="Their name"
            className="w-full px-4 py-3 rounded-xl bg-slate-800 border border-slate-700 text-white text-sm placeholder:text-slate-600 focus:border-teal-500/50 focus:outline-none"
            data-testid="guardian-name-input"
          />
        </div>

        {/* Email */}
        <div>
          <label className="text-[11px] text-slate-500 uppercase font-medium mb-1.5 block">Email (Optional)</label>
          <div className="relative">
            <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
            <input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="guardian@email.com"
              className="w-full pl-10 pr-4 py-3 rounded-xl bg-slate-800 border border-slate-700 text-white text-sm placeholder:text-slate-600 focus:border-teal-500/50 focus:outline-none"
              data-testid="guardian-email-input"
            />
          </div>
        </div>

        {/* Relationship */}
        <div>
          <label className="text-[11px] text-slate-500 uppercase font-medium mb-2 block">Relationship</label>
          <div className="grid grid-cols-3 gap-2">
            {RELATIONSHIPS.map(({ id, icon: Icon, label }) => (
              <button
                key={id}
                onClick={() => setRelationship(id)}
                className={`py-3 rounded-xl flex flex-col items-center gap-1.5 transition-all border ${
                  relationship === id
                    ? 'bg-teal-500/15 border-teal-500/40 text-teal-400'
                    : 'bg-slate-800 border-slate-700 text-slate-500'
                }`}
                data-testid={`rel-${id}`}
              >
                <Icon className="w-4 h-4" />
                <span className="text-[10px] font-medium">{label}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Primary Toggle */}
        <div className="flex items-center justify-between p-3 rounded-xl bg-slate-800/30 border border-slate-700/30">
          <div>
            <p className="text-xs text-white font-medium">Set as Primary Guardian</p>
            <p className="text-[9px] text-slate-500">Primary guardian is alerted first</p>
          </div>
          <button
            onClick={() => setIsPrimary(!isPrimary)}
            className={`w-11 h-6 rounded-full transition-colors relative ${isPrimary ? 'bg-teal-500' : 'bg-slate-700'}`}
            data-testid="primary-toggle"
          >
            <div className={`w-5 h-5 rounded-full bg-white shadow-sm absolute top-0.5 transition-transform ${isPrimary ? 'translate-x-[22px]' : 'translate-x-0.5'}`} />
          </button>
        </div>

        {/* Error */}
        {error && (
          <div className="p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-center">
            <p className="text-xs text-red-400">{error}</p>
          </div>
        )}

        {/* Invite Link Button (Primary) */}
        <button
          onClick={handleCreateInvite}
          disabled={loading || !relationship}
          className="w-full py-3.5 rounded-2xl bg-teal-500 text-white font-bold text-sm flex items-center justify-center gap-2 active:scale-[0.98] transition-transform disabled:opacity-50 shadow-lg shadow-teal-500/20"
          data-testid="create-invite-btn"
        >
          {loading ? (
            <><Loader2 className="w-4 h-4 animate-spin" /> Creating...</>
          ) : (
            <><Link2 className="w-4 h-4" /> Create Invite Link</>
          )}
        </button>

        {/* Direct Add Button (Secondary) */}
        <button
          onClick={handleDirectAdd}
          disabled={loading || !name || !relationship}
          className="w-full py-3 rounded-2xl bg-slate-800 border border-slate-700 text-white text-xs font-medium flex items-center justify-center gap-2 active:scale-[0.98] transition-transform disabled:opacity-40"
          data-testid="direct-add-btn"
        >
          <UserPlus className="w-3.5 h-3.5" /> Add Directly (Without Invite)
        </button>

        <p className="text-center text-[9px] text-slate-600">
          Invite links expire after 48 hours
        </p>
      </div>
    </div>
  );
}
