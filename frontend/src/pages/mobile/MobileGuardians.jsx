import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../../api';
import {
  Users, UserPlus, Shield, Trash2, ArrowLeft, ChevronRight,
  Loader2, GripVertical, Crown, Star, Phone, Mail,
} from 'lucide-react';

export default function MobileGuardians() {
  const navigate = useNavigate();
  const [guardians, setGuardians] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetch_ = useCallback(async () => {
    try {
      const res = await api.get('/guardian-network/');
      setGuardians(res.data.guardians || []);
    } catch { /* silent */ }
    setLoading(false);
  }, []);

  useEffect(() => { fetch_(); }, [fetch_]);

  const removeGuardian = async (id) => {
    if (!window.confirm('Remove this guardian from your safety network?')) return;
    try {
      await api.delete(`/guardian-network/${id}`);
      setGuardians(g => g.filter(x => x.id !== id));
    } catch { /* silent */ }
  };

  const setPrimary = async (id) => {
    try {
      await api.put(`/guardian-network/${id}`, { is_primary: true });
      fetch_();
    } catch { /* silent */ }
  };

  return (
    <div className="px-4 pt-4 pb-6" data-testid="mobile-guardians">
      <div className="flex items-center justify-between mb-4">
        <button onClick={() => navigate('/m/profile')} className="p-2 -ml-2 rounded-full active:bg-slate-800">
          <ArrowLeft className="w-5 h-5 text-slate-400" />
        </button>
        <h1 className="text-base font-bold text-white">Guardian Network</h1>
        <button
          onClick={() => navigate('/m/add-guardian')}
          className="p-2 rounded-full bg-teal-500/15 active:bg-teal-500/25"
          data-testid="add-guardian-btn"
        >
          <UserPlus className="w-4 h-4 text-teal-400" />
        </button>
      </div>

      {/* Escalation Order Info */}
      <div className="p-3 rounded-xl bg-blue-500/8 border border-blue-500/20 mb-4">
        <p className="text-[10px] text-blue-300 leading-relaxed">
          Guardians are alerted in escalation order during emergencies. The primary guardian is always notified first.
        </p>
      </div>

      {loading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="w-6 h-6 text-teal-400 animate-spin" />
        </div>
      ) : guardians.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <Users className="w-12 h-12 text-slate-700 mb-3" />
          <p className="text-sm text-slate-400 font-medium">No guardians yet</p>
          <p className="text-xs text-slate-600 mt-1 mb-4">Add your first guardian to build your safety network</p>
          <button
            onClick={() => navigate('/m/add-guardian')}
            className="px-5 py-2.5 rounded-full bg-teal-500 text-white text-xs font-bold active:scale-95 transition-transform"
            data-testid="add-first-guardian-btn"
          >
            <UserPlus className="w-3.5 h-3.5 inline mr-1.5" /> Add Guardian
          </button>
        </div>
      ) : (
        <div className="space-y-2" data-testid="guardians-list">
          {guardians.map((g, i) => (
            <div
              key={g.id}
              className={`p-3 rounded-2xl border transition-all ${
                g.is_primary
                  ? 'bg-teal-500/8 border-teal-500/25'
                  : 'bg-slate-800/30 border-slate-700/30'
              }`}
              data-testid={`guardian-card-${g.id}`}
            >
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-1 text-slate-600">
                  <span className="text-[10px] font-bold font-mono w-4 text-center">{i + 1}</span>
                  <GripVertical className="w-3 h-3" />
                </div>

                <div className={`w-9 h-9 rounded-full flex items-center justify-center shrink-0 ${
                  g.is_primary ? 'bg-teal-500/20' : 'bg-slate-700'
                }`}>
                  <span className={`text-xs font-bold ${g.is_primary ? 'text-teal-400' : 'text-slate-400'}`}>
                    {(g.guardian_name || g.guardian_email || '?').charAt(0).toUpperCase()}
                  </span>
                </div>

                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <p className="text-xs font-semibold text-white truncate">
                      {g.guardian_name || g.guardian_email}
                    </p>
                    {g.is_primary && <Crown className="w-3 h-3 text-amber-400 shrink-0" />}
                  </div>
                  <p className="text-[10px] text-slate-500 capitalize">{g.relationship_type || 'guardian'}</p>
                </div>

                <div className="flex items-center gap-1">
                  {!g.is_primary && (
                    <button
                      onClick={() => setPrimary(g.id)}
                      className="p-1.5 rounded-lg active:bg-slate-700/50"
                      title="Set as primary"
                      data-testid={`set-primary-${g.id}`}
                    >
                      <Star className="w-3.5 h-3.5 text-slate-500" />
                    </button>
                  )}
                  <button
                    onClick={() => removeGuardian(g.id)}
                    className="p-1.5 rounded-lg active:bg-red-500/20"
                    data-testid={`remove-guardian-${g.id}`}
                  >
                    <Trash2 className="w-3.5 h-3.5 text-red-400/60" />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Emergency Contacts Link */}
      <button
        onClick={() => navigate('/m/contacts')}
        className="w-full mt-6 p-3.5 rounded-2xl bg-slate-800/30 border border-slate-700/30 flex items-center gap-3 active:bg-slate-800/50 transition-colors"
        data-testid="emergency-contacts-link"
      >
        <Phone className="w-4 h-4 text-blue-400" />
        <span className="flex-1 text-xs text-white font-medium text-left">Emergency Contacts</span>
        <ChevronRight className="w-4 h-4 text-slate-600" />
      </button>
    </div>
  );
}
