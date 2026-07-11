import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import api from '../../api';
import AIBrainProfileCard from '../../components/AIBrainProfileCard';
import {
  User, Shield, Users, Phone, LogOut, ChevronRight,
  Bell, Lock, Settings, Loader2, Smartphone,
} from 'lucide-react';

export default function MobileProfile() {
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const [guardianData, setGuardianData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [shakeSOS, setShakeSOS] = useState(() => localStorage.getItem('nischint_shake_sos') !== 'false');

  const toggleShakeSOS = () => {
    const next = !shakeSOS;
    setShakeSOS(next);
    localStorage.setItem('nischint_shake_sos', next ? 'true' : 'false');
  };

  useEffect(() => {
    (async () => {
      try {
        const [guardians, contacts] = await Promise.all([
          api.get('/guardian-network/'),
          api.get('/guardian-network/emergency-contacts'),
        ]);
        setGuardianData({
          guardians: guardians.data.guardians || [],
          contacts: contacts.data.contacts || [],
        });
      } catch { /* silent */ }
      setLoading(false);
    })();
  }, []);

  const handleLogout = () => {
    logout();
    navigate('/login', { replace: true });
  };

  return (
    <div className="px-4 pt-4 pb-6" data-testid="mobile-profile">
      {/* User Card */}
      <div className="p-4 rounded-2xl bg-slate-800/50 border border-slate-700/40 mb-4">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 rounded-full bg-teal-500/15 flex items-center justify-center">
            <User className="w-6 h-6 text-teal-400" />
          </div>
          <div className="flex-1">
            <p className="text-sm font-semibold text-white">{user?.full_name || user?.email}</p>
            <p className="text-[11px] text-slate-500">{user?.email}</p>
            <div className="flex items-center gap-1 mt-0.5">
              <Shield className="w-3 h-3 text-teal-400" />
              <span className="text-[10px] text-teal-400 uppercase font-medium">{user?.role || 'guardian'}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Who Am I to the Brain? — personalised adaptation profile */}
      <AIBrainProfileCard userId={user?.id || user?.email} />

      {/* Guardian Network */}
      <div className="mb-4">
        <h2 className="text-xs text-slate-500 uppercase font-medium mb-2 px-1">Safety Network</h2>
        {loading ? (
          <div className="flex justify-center py-6">
            <Loader2 className="w-5 h-5 text-slate-500 animate-spin" />
          </div>
        ) : (
          <div className="space-y-2">
            <ProfileRow
              icon={<Users className="w-4 h-4 text-teal-400" />}
              label="Guardians"
              value={`${guardianData?.guardians?.length || 0} active`}
              onClick={() => navigate('/m/guardians')}
              testId="profile-guardians"
            />
            <ProfileRow
              icon={<Phone className="w-4 h-4 text-blue-400" />}
              label="Emergency Contacts"
              value={`${guardianData?.contacts?.length || 0} saved`}
              testId="profile-emergency-contacts"
            />
          </div>
        )}
      </div>

      {/* Guardian List Preview */}
      {guardianData?.guardians?.length > 0 && (
        <div className="mb-4">
          <h2 className="text-xs text-slate-500 uppercase font-medium mb-2 px-1">Your Guardians</h2>
          <div className="space-y-1.5">
            {guardianData.guardians.slice(0, 3).map(g => (
              <div key={g.id} className="p-3 rounded-xl bg-slate-800/30 border border-slate-700/30 flex items-center gap-3">
                <div className="w-8 h-8 rounded-full bg-teal-500/10 flex items-center justify-center">
                  <span className="text-xs text-teal-400 font-bold">{g.guardian_name?.charAt(0)}</span>
                </div>
                <div className="flex-1">
                  <p className="text-xs text-white font-medium">{g.guardian_name}</p>
                  <p className="text-[10px] text-slate-500">{g.relationship_type}{g.is_primary ? ' (Primary)' : ''}</p>
                </div>
                {g.is_primary && <Shield className="w-3.5 h-3.5 text-teal-400" />}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Settings Rows */}
      <div className="mb-6">
        <h2 className="text-xs text-slate-500 uppercase font-medium mb-2 px-1">Emergency Controls</h2>
        <div className="space-y-2">
          {/* Shake SOS Toggle */}
          <div className="w-full p-3 rounded-xl bg-slate-800/30 border border-slate-700/30 flex items-center gap-3" data-testid="shake-sos-setting">
            <Smartphone className="w-4 h-4 text-red-400" />
            <div className="flex-1">
              <p className="text-xs text-white font-medium">Shake to SOS</p>
              <p className="text-[9px] text-slate-500">Shake phone to trigger emergency alert</p>
            </div>
            <button
              onClick={toggleShakeSOS}
              className={`w-11 h-6 rounded-full transition-colors relative ${shakeSOS ? 'bg-red-500' : 'bg-slate-700'}`}
              data-testid="shake-sos-toggle"
            >
              <div className={`w-5 h-5 rounded-full bg-white shadow-sm absolute top-0.5 transition-transform ${shakeSOS ? 'translate-x-[22px]' : 'translate-x-0.5'}`} />
            </button>
          </div>

          <ProfileRow icon={<Bell className="w-4 h-4 text-amber-400" />} label="Notification Settings" value="Manage Alerts" onClick={() => navigate('/m/notification-settings')} testId="profile-notifications" />
          <ProfileRow icon={<Lock className="w-4 h-4 text-purple-400" />} label="Privacy & My Data" value="DPDP" onClick={() => navigate('/m/privacy')} testId="profile-privacy" />
          <ProfileRow icon={<Settings className="w-4 h-4 text-slate-400" />} label="SOS Configuration" value="" onClick={() => navigate('/family/sos')} testId="profile-sos-config" />
        </div>
      </div>

      {/* Logout */}
      <button
        onClick={handleLogout}
        className="w-full py-3 rounded-2xl bg-red-500/10 border border-red-500/30 text-red-400 text-sm font-medium flex items-center justify-center gap-2 active:scale-[0.98] transition-transform"
        data-testid="logout-btn"
      >
        <LogOut className="w-4 h-4" /> Sign Out
      </button>

      <p className="text-center text-[9px] text-slate-600 mt-4">Nischint v1.0 — Powered by Guardian AI</p>
    </div>
  );
}

const ProfileRow = ({ icon, label, value, onClick, testId }) => (
  <button
    onClick={onClick}
    className="w-full p-3 rounded-xl bg-slate-800/30 border border-slate-700/30 flex items-center gap-3 active:bg-slate-800/50 transition-colors text-left"
    data-testid={testId}
  >
    {icon}
    <span className="flex-1 text-xs text-white font-medium">{label}</span>
    {value && <span className="text-[10px] text-slate-500">{value}</span>}
    <ChevronRight className="w-4 h-4 text-slate-600" />
  </button>
);
