import React, { useState, useCallback } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { Home, Map, Shield, User, Bell } from 'lucide-react';
import FloatingSafetyIndicator from '../../components/mobile/FloatingSafetyIndicator';
import ShakeSOSOverlay from '../../components/mobile/ShakeSOSOverlay';
import useShakeDetector from '../../hooks/useShakeDetector';
import usePushNotifications from '../../hooks/usePushNotifications';

const tabs = [
  { path: '/m/home', icon: Home, label: 'Home' },
  { path: '/m/safe-route', icon: Map, label: 'Map' },
  { path: '/m/sos', icon: Shield, label: 'SOS' },
  { path: '/m/alerts', icon: Bell, label: 'Alerts' },
  { path: '/m/profile', icon: User, label: 'Profile' },
];

export default function MobileLayout() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [shakeOverlay, setShakeOverlay] = useState(false);

  // Initialize push notifications — registers FCM token & handles foreground messages
  usePushNotifications();

  // Read shake SOS preference from localStorage
  const shakeEnabled = localStorage.getItem('nischint_shake_sos') !== 'false';

  const onShakeDetected = useCallback(() => {
    if (!shakeOverlay) {
      setShakeOverlay(true);
    }
  }, [shakeOverlay]);

  useShakeDetector(onShakeDetected, shakeEnabled);

  // Hide tab bar on immersive screens
  const hideTabBar = ['/m/live', '/m/fake-call'].some(p => pathname.startsWith(p));
  // Hide floating indicator on these screens
  const hideIndicator = ['/m/sos', '/m/live', '/m/fake-call'].some(p => pathname.startsWith(p));

  return (
    <div className="h-[100dvh] w-full max-w-[430px] mx-auto bg-slate-950 text-white flex flex-col overflow-hidden relative" data-testid="mobile-layout">
      {/* Floating Safety Indicator */}
      {!hideIndicator && <FloatingSafetyIndicator />}

      {/* Status bar spacer */}
      <div className={`shrink-0 ${hideIndicator ? 'h-0' : 'h-10'}`} />

      {/* Content */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden">
        <Outlet />
      </div>

      {/* Tab bar */}
      {!hideTabBar && (
        <nav className="shrink-0 bg-slate-900/95 backdrop-blur-lg border-t border-slate-800/60 px-2 pb-[env(safe-area-inset-bottom,8px)]" data-testid="mobile-tab-bar">
          <div className="flex items-center justify-around h-14">
            {tabs.map(({ path, icon: Icon, label }) => {
              const active = pathname === path || (path === '/m/home' && (pathname === '/m' || pathname === '/m/'));
              return (
                <button
                  key={path}
                  onClick={() => navigate(path)}
                  className={`flex flex-col items-center gap-0.5 px-3 py-1 rounded-xl transition-all ${
                    path === '/m/sos'
                      ? 'relative -mt-5'
                      : active ? 'text-teal-400' : 'text-slate-500'
                  }`}
                  data-testid={`tab-${label.toLowerCase()}`}
                >
                  {path === '/m/sos' ? (
                    <div className="w-14 h-14 rounded-full bg-red-500 flex items-center justify-center shadow-lg shadow-red-500/30 active:scale-95 transition-transform">
                      <Icon className="w-6 h-6 text-white" />
                    </div>
                  ) : (
                    <>
                      <Icon className="w-5 h-5" />
                      <span className="text-[10px] font-medium">{label}</span>
                    </>
                  )}
                </button>
              );
            })}
          </div>
        </nav>
      )}

      {/* Shake SOS Overlay */}
      <ShakeSOSOverlay
        visible={shakeOverlay}
        onCancel={() => setShakeOverlay(false)}
        onComplete={() => {
          setShakeOverlay(false);
          navigate('/m/sos');
        }}
      />
    </div>
  );
}
