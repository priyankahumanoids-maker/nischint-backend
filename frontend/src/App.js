import React, { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { Toaster } from 'sonner';
import { GoogleOAuthProvider } from '@react-oauth/google';
import { useJourneyLifecycle } from './journey/useJourneyLifecycle.web';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import ProtectedRoute from './components/ProtectedRoute';
import NischintHomePage from './pages/NischintHomePage';
import InvestorPage from './pages/InvestorPage';
import PilotSignupPage from './pages/PilotSignupPage';
import StatusPage from './pages/StatusPage';
import SafetyDashboard from './pages/SafetyDashboard';
import SystemStatusPage from './pages/SystemStatusPage';
import WhatsAppButton from './components/WhatsAppButton';
import NischintChatbot from './components/NischintChatbot';
import Login from './pages/Login';
import WomenSafetyPage from './pages/WomenSafetyPage';
import KidsSafetyPage from './pages/KidsSafetyPage';
import FamilySafetyPage from './pages/FamilySafetyPage';
import BlogListPage from './pages/BlogListPage';
import BlogPostPage from './pages/BlogPostPage';
import WhatIsNischintPage from './pages/WhatIsNischintPage';
import AboutPage from './pages/AboutPage';
import PrivacyPolicyPage from './pages/PrivacyPolicyPage';
import PublicStatusPage from './pages/PublicStatusPage';
import InstallPrompt from './components/mobile/InstallPrompt';
import './App.css';

// Code-splitting (Lighthouse P0): lazy-load every authenticated /
// operator / mobile-app-shell route so the marketing landing page
// no longer ships ~950 KB of unused bundle on first paint. Marketing
// pages above stay eagerly imported because they ARE the LCP target.
const FamilyDashboard         = lazy(() => import('./pages/FamilyDashboard'));
const OperatorConsole         = lazy(() => import('./pages/OperatorConsole'));
const OperatorDashboard       = lazy(() => import('./pages/OperatorDashboard'));
const CaregiverDashboard      = lazy(() => import('./pages/CaregiverDashboard'));
const JourneyReplayPage       = lazy(() => import('./pages/JourneyReplayPage'));
const AdminPanel              = lazy(() => import('./pages/AdminPanel'));
const CommandCenterPage       = lazy(() => import('./pages/CommandCenterPage'));
const LiveTrackingPage        = lazy(() => import('./pages/LiveTrackingPage'));
const FunnelDashboard         = lazy(() => import('./pages/FunnelDashboard'));
const GeoAnalyticsDashboard   = lazy(() => import('./pages/GeoAnalyticsDashboard'));
const PRDashboard             = lazy(() => import('./pages/PRDashboard'));
// Mobile app shell + all sub-routes — only enters the bundle once a
// user actually navigates to /m/*.
const MobileLayout              = lazy(() => import('./pages/mobile/MobileLayout'));
const MobileHome                = lazy(() => import('./pages/mobile/MobileHome'));
const MobileSOS                 = lazy(() => import('./pages/mobile/MobileSOS'));
const MobileFakeCall            = lazy(() => import('./pages/mobile/MobileFakeCall'));
const MobileSession             = lazy(() => import('./pages/mobile/MobileSession'));
const MobileLive                = lazy(() => import('./pages/mobile/MobileLive'));
const MobileSafeRoute           = lazy(() => import('./pages/mobile/MobileSafeRoute'));
const MobileAlerts              = lazy(() => import('./pages/mobile/MobileAlerts'));
const MobileProfile             = lazy(() => import('./pages/mobile/MobileProfile'));
const MobileGuardians           = lazy(() => import('./pages/mobile/MobileGuardians'));
const MobileAddGuardian         = lazy(() => import('./pages/mobile/MobileAddGuardian'));
const MobileContacts            = lazy(() => import('./pages/mobile/MobileContacts'));
const MobileAIInsights          = lazy(() => import('./pages/mobile/MobileAIInsights'));
const MobileNotifications       = lazy(() => import('./pages/mobile/MobileNotifications'));
const MobileNotificationSettings = lazy(() => import('./pages/mobile/MobileNotificationSettings'));
const MobilePrivacy             = lazy(() => import('./pages/mobile/MobilePrivacy'));
const MobileGuardianLiveMap     = lazy(() => import('./pages/mobile/MobileGuardianLiveMap'));
const MobileIncidentReplay      = lazy(() => import('./pages/mobile/MobileIncidentReplay'));
const InviteLanding             = lazy(() => import('./pages/mobile/InviteLanding'));

// REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
const GOOGLE_CLIENT_ID = process.env.REACT_APP_GOOGLE_CLIENT_ID;

const MARKETING_ROUTES = ['/', '/investors', '/pilot', '/telemetry', '/safety-dashboard', '/system-status', '/women-safety-app', '/kids-safety-app', '/family-safety-app', '/what-is-nischint'];

function MarketingWhatsApp() {
  const { pathname } = useLocation();
  if (!MARKETING_ROUTES.includes(pathname)) return null;
  return (
    <>
      <NischintChatbot />
      <WhatsAppButton />
    </>
  );
}

// Subdomain-aware routing: detect hostname and redirect to correct section
function SubdomainRedirect() {
  const hostname = window.location.hostname;
  const path = window.location.pathname;

  // Only redirect on root path to avoid breaking deep links
  if (path !== '/') return null;

  if (hostname === 'app.nischint.app') {
    return <Navigate to="/m/home" replace />;
  }
  if (hostname === 'command.nischint.app') {
    return <Navigate to="/command-center" replace />;
  }
  if (hostname === 'status.nischint.app') {
    return <Navigate to="/system-status" replace />;
  }
  // nischint.care and everything else → homepage
  return null;
}

// JourneyManager — mounts the journey lifecycle hook with `isActive`
// computed from auth + route. Critical for App Store compliance:
// `navigator.geolocation.getCurrentPosition()` is NEVER called on
// marketing / unauthenticated routes, so first-time visitors don't
// see a "Allow location?" prompt before any user action.
//
// Active iff: user is authenticated AND on an in-app route that
// genuinely needs live journey tracking (mobile app shell, family
// dashboard, operator). Marketing routes, login, blog, privacy
// policy, etc. all pass `isActive=false`.
const _JOURNEY_ACTIVE_PREFIXES = [
  '/m/',           // mobile app shell
  '/family',       // family dashboard
  '/operator',     // operator console
  '/command-center',
  '/driving',
];

function JourneyManager() {
  const auth = useAuth();
  const location = useLocation();
  const isAuthed = typeof auth?.isAuthenticated === 'function'
    ? auth.isAuthenticated()
    : !!auth?.user;
  const onActiveRoute = _JOURNEY_ACTIVE_PREFIXES.some(
    (p) => location.pathname === p || location.pathname.startsWith(p + '/') || location.pathname.startsWith(p)
  );
  const isActive = Boolean(isAuthed && onActiveRoute);

  useJourneyLifecycle({
    isActive,
    onRiskActions: (actions, _session) => {
      for (const a of actions) {
        if (a.type === 'push_notification') console.warn('[NISCHINT] Safety check:', a.message);
        if (a.type === 'guardian_alert') console.warn('[NISCHINT] Guardian alert:', a.message);
      }
    },
    onSOSStateChange: (state, session) => {
      console.warn('[NISCHINT] SOS state →', state, '| risk:', session.riskScore);
    },
    onAutoPreSOS: (session) => {
      console.warn('[NISCHINT] AUTO PRE-SOS: critical risk detected, score:', session.riskScore);
    },
    onSyncFlush: (events) => {
      if (events.length > 0) console.log('[NISCHINT] Synced', events.length, 'events');
    },
    onGeoAnomaly: (anomaly) => {
      console.warn('[NISCHINT] Geo anomaly:', anomaly.type);
    },
    onOffline: () => console.log('[NISCHINT] Offline — events queued'),
    onOnline: () => console.log('[NISCHINT] Online — flushing'),
  });
  return null;
}

function App() {
  const appContent = (
    <AuthProvider>
      <div className="App">
        <BrowserRouter>
          <SubdomainRedirect />
          <JourneyManager />
          <Suspense fallback={<div className="min-h-screen flex items-center justify-center" data-testid="route-suspense-fallback"><div className="w-10 h-10 border-4 border-slate-200 border-t-slate-700 rounded-full animate-spin" /></div>}>
          <Routes>
            <Route path="/" element={<NischintHomePage />} />
            <Route path="/investors" element={<InvestorPage />} />
            <Route path="/pilot" element={<PilotSignupPage />} />
            <Route path="/telemetry" element={<StatusPage />} />
            <Route path="/safety-dashboard" element={<SafetyDashboard />} />
            <Route path="/system-status" element={<SystemStatusPage />} />
            <Route path="/women-safety-app" element={<WomenSafetyPage />} />
            <Route path="/kids-safety-app" element={<KidsSafetyPage />} />
            <Route path="/family-safety-app" element={<FamilySafetyPage />} />
            <Route path="/what-is-nischint" element={<WhatIsNischintPage />} />
            <Route path="/about" element={<AboutPage />} />
            <Route path="/privacy-policy" element={<PrivacyPolicyPage />} />
            <Route path="/privacy" element={<Navigate to="/privacy-policy" replace />} />
            <Route path="/status" element={<PublicStatusPage />} />
            <Route path="/admin/funnel" element={<FunnelDashboard />} />
            <Route path="/admin/geo" element={<GeoAnalyticsDashboard />} />
            <Route path="/admin/pr" element={<PRDashboard />} />
            <Route path="/blog" element={<BlogListPage />} />
            <Route path="/blog/category/:category" element={<BlogListPage />} />
            <Route path="/blog/:slug" element={<BlogPostPage />} />
            <Route path="/login" element={<Login />} />
            <Route path="/invite/:token" element={<InviteLanding />} />
            <Route path="/track/:token" element={<LiveTrackingPage />} />
            <Route 
              path="/family/*" 
              element={
                <ProtectedRoute allowedRoles={['guardian', 'child', 'admin']}>
                  <FamilyDashboard />
                </ProtectedRoute>
              } 
            />
            <Route path="/operator/*" element={
              <ProtectedRoute allowedRoles={['operator', 'admin']}>
                <OperatorConsole />
              </ProtectedRoute>
            } />
            <Route path="/admin/*" element={
              <ProtectedRoute allowedRoles={['admin']}>
                <AdminPanel />
              </ProtectedRoute>
            } />
            <Route path="/command-center" element={
              <ProtectedRoute allowedRoles={['operator', 'admin']}>
                <CommandCenterPage />
              </ProtectedRoute>
            } />
            <Route path="/operator-dashboard" element={
              <ProtectedRoute allowedRoles={['operator', 'admin']}>
                <OperatorDashboard />
              </ProtectedRoute>
            } />
            <Route path="/caregiver/*" element={
              <ProtectedRoute>
                <CaregiverDashboard />
              </ProtectedRoute>
            } />
            <Route path="/replay" element={
              <ProtectedRoute>
                <JourneyReplayPage />
              </ProtectedRoute>
            } />
            <Route path="/replay/:sessionId" element={
              <ProtectedRoute>
                <JourneyReplayPage />
              </ProtectedRoute>
            } />
            {/* Mobile PWA Routes */}
            <Route path="/m" element={
              <ProtectedRoute>
                <MobileLayout />
              </ProtectedRoute>
            }>
              <Route index element={<Navigate to="/m/home" replace />} />
              <Route path="home" element={<MobileHome />} />
              <Route path="sos" element={<MobileSOS />} />
              <Route path="fake-call" element={<MobileFakeCall />} />
              <Route path="session" element={<MobileSession />} />
              <Route path="live" element={<MobileLive />} />
              <Route path="safe-route" element={<MobileSafeRoute />} />
              <Route path="alerts" element={<MobileAlerts />} />
              <Route path="profile" element={<MobileProfile />} />
              <Route path="guardians" element={<MobileGuardians />} />
              <Route path="add-guardian" element={<MobileAddGuardian />} />
              <Route path="contacts" element={<MobileContacts />} />
              <Route path="ai" element={<MobileAIInsights />} />
              <Route path="notifications" element={<MobileNotifications />} />
              <Route path="notification-settings" element={<MobileNotificationSettings />} />
              <Route path="privacy" element={<MobilePrivacy />} />
              <Route path="guardian-live-map" element={<MobileGuardianLiveMap />} />
              <Route path="incidents" element={<MobileIncidentReplay />} />
            </Route>
          </Routes>
          </Suspense>
          <MarketingWhatsApp />
          <InstallPrompt />
        </BrowserRouter>
        <Toaster position="top-right" richColors />
      </div>
    </AuthProvider>
  );

  // Wrap with GoogleOAuthProvider only if client ID is configured
  if (GOOGLE_CLIENT_ID) {
    return (
      <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
        {appContent}
      </GoogleOAuthProvider>
    );
  }

  return appContent;
}

export default App;
