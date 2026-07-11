import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Shield, Users, Headphones, Loader2, UserPlus } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { authApi } from '../api';
import { toast } from 'sonner';
import api from '../api';

// REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
const GOOGLE_CLIENT_ID = process.env.REACT_APP_GOOGLE_CLIENT_ID;

// Google Sign-In Button Component
const GoogleSignInButton = ({ onSuccess, disabled }) => {
  const [googleLoading, setGoogleLoading] = useState(false);

  const handleGoogleLogin = async (credentialResponse) => {
    setGoogleLoading(true);
    try {
      const resp = await api.post('/auth/google', {
        credential: credentialResponse.credential,
      });
      onSuccess(resp.data);
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Google sign-in failed');
    } finally {
      setGoogleLoading(false);
    }
  };

  if (!GOOGLE_CLIENT_ID) return null;

  // Use the Google Sign-In library
  const GoogleLoginImport = React.lazy(() =>
    import('@react-oauth/google').then(mod => ({ default: mod.GoogleLogin }))
  );

  return (
    <React.Suspense fallback={<div className="h-10" />}>
      <div className="w-full" data-testid="google-signin-container">
        {googleLoading ? (
          <div className="flex items-center justify-center py-2">
            <Loader2 className="w-5 h-5 animate-spin text-slate-400 mr-2" />
            <span className="text-sm text-slate-500">Signing in with Google...</span>
          </div>
        ) : (
          <GoogleLoginImport
            onSuccess={handleGoogleLogin}
            onError={() => toast.error('Google sign-in failed')}
            width="100%"
            text="signin_with"
            shape="rectangular"
            theme="outline"
            size="large"
          />
        )}
      </div>
    </React.Suspense>
  );
};

const Login = () => {
  const navigate = useNavigate();
  const { login, isAuthenticated } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [showRegister, setShowRegister] = useState(false);

  // Registration fields
  const [regName, setRegName] = useState('');
  const [regEmail, setRegEmail] = useState('');
  const [regPhone, setRegPhone] = useState('');
  const [regPassword, setRegPassword] = useState('');
  const [regConfirm, setRegConfirm] = useState('');

  const getPostLoginRedirect = (role) => {
    const pendingInvite = sessionStorage.getItem('nischint_pending_invite');
    if (pendingInvite) {
      sessionStorage.removeItem('nischint_pending_invite');
      return `/invite/${pendingInvite}`;
    }
    if (role === 'operator') return '/command-center';
    if (role === 'admin') return '/admin';
    return '/family';
  };

  const handleGoogleSuccess = (data) => {
    login(data.access_token, { auth_provider: 'google' });
    const decoded = JSON.parse(atob(data.access_token.split('.')[1]));
    const role = decoded.role || 'guardian';
    toast.success(data.is_new_user ? 'Account created with Google! Welcome to NISCHINT.' : 'Signed in with Google!');
    navigate(getPostLoginRedirect(role), { replace: true });
  };

  const { user: authUser } = useAuth();
  React.useEffect(() => {
    if (isAuthenticated() && authUser) {
      navigate(getPostLoginRedirect(authUser.role), { replace: true });
    }
  }, [authUser]);

  const handleFamilyLogin = async (e) => {
    e.preventDefault();
    if (!email || !password) { toast.error('Please enter email and password'); return; }
    setLoading(true);
    try {
      const data = await authApi.login(email, password);
      login(data.access_token, { auth_provider: data.auth_provider, refresh_token: data.refresh_token, cognito_username: data.cognito_username });
      toast.success('Login successful!');
      navigate(getPostLoginRedirect(data.role), { replace: true });
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Login failed. Please check your credentials.');
    } finally { setLoading(false); }
  };

  const handleOperatorLogin = async (e) => {
    e.preventDefault();
    if (!email || !password) { toast.error('Please enter email and password'); return; }
    setLoading(true);
    try {
      const data = await authApi.login(email, password);
      if (data.role !== 'operator' && data.role !== 'admin') { toast.error('This account is not an operator'); return; }
      login(data.access_token, { auth_provider: data.auth_provider, refresh_token: data.refresh_token, cognito_username: data.cognito_username });
      toast.success('Operator login successful!');
      navigate('/command-center', { replace: true });
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Login failed. Please check your credentials.');
    } finally { setLoading(false); }
  };

  const handleRegister = async (e) => {
    e.preventDefault();
    if (!regName || !regEmail || !regPassword) { toast.error('Please fill in all required fields'); return; }
    if (regPassword.length < 8) { toast.error('Password must be at least 8 characters'); return; }
    if (regPassword !== regConfirm) { toast.error('Passwords do not match'); return; }
    setLoading(true);
    try {
      const data = await authApi.register(regEmail, regPassword, regName, regPhone);
      login(data.access_token, { auth_provider: data.auth_provider, refresh_token: data.refresh_token, cognito_username: data.cognito_username });
      toast.success('Account created! Welcome to NISCHINT.');
      navigate('/family', { replace: true });
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Registration failed. Please try again.');
    } finally { setLoading(false); }
  };

  if (showRegister) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-teal-600 to-teal-800 p-4">
        <div className="w-full max-w-md">
          <div className="text-center mb-8">
            <div className="inline-flex items-center justify-center w-20 h-20 bg-white rounded-2xl shadow-lg mb-4">
              <Shield className="w-12 h-12 text-teal-600" />
            </div>
            <h1 className="text-3xl font-bold text-white tracking-wide">NISCHINT</h1>
            <p className="text-teal-100 mt-2">Create your family account</p>
          </div>

          <Card className="backdrop-blur-sm bg-white/95 shadow-2xl border-0">
            <CardHeader className="text-center pb-2">
              <CardTitle className="text-xl flex items-center justify-center gap-2">
                <UserPlus className="w-5 h-5 text-teal-600" />
                Guardian Registration
              </CardTitle>
              <CardDescription>Start monitoring your loved ones</CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleRegister} className="space-y-4">
                {GOOGLE_CLIENT_ID && (
                  <>
                    <GoogleSignInButton onSuccess={handleGoogleSuccess} disabled={loading} />
                    <div className="relative my-2">
                      <div className="absolute inset-0 flex items-center">
                        <span className="w-full border-t border-slate-200" />
                      </div>
                      <div className="relative flex justify-center text-xs uppercase">
                        <span className="bg-white px-2 text-slate-400">or register with email</span>
                      </div>
                    </div>
                  </>
                )}
                <div className="space-y-2">
                  <Label htmlFor="reg-name">Full Name *</Label>
                  <Input
                    id="reg-name" placeholder="Your full name"
                    value={regName} onChange={(e) => setRegName(e.target.value)}
                    data-testid="register-name-input" disabled={loading}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="reg-email">Email *</Label>
                  <Input
                    id="reg-email" type="email" placeholder="you@example.com"
                    value={regEmail} onChange={(e) => setRegEmail(e.target.value)}
                    data-testid="register-email-input" disabled={loading}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="reg-phone">Phone (optional)</Label>
                  <Input
                    id="reg-phone" type="tel" placeholder="+91 98765 43210"
                    value={regPhone} onChange={(e) => setRegPhone(e.target.value)}
                    data-testid="register-phone-input" disabled={loading}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="reg-password">Password *</Label>
                  <Input
                    id="reg-password" type="password" placeholder="Minimum 8 characters"
                    value={regPassword} onChange={(e) => setRegPassword(e.target.value)}
                    data-testid="register-password-input" disabled={loading}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="reg-confirm">Confirm Password *</Label>
                  <Input
                    id="reg-confirm" type="password" placeholder="Re-enter password"
                    value={regConfirm} onChange={(e) => setRegConfirm(e.target.value)}
                    data-testid="register-confirm-input" disabled={loading}
                  />
                </div>
                <Button
                  type="submit" className="w-full bg-teal-600 hover:bg-teal-700"
                  data-testid="register-submit-btn" disabled={loading}
                >
                  {loading ? <><Loader2 className="w-4 h-4 mr-2 animate-spin" />Creating account...</> : 'Create Guardian Account'}
                </Button>
              </form>
              <div className="mt-4 text-center">
                <button
                  onClick={() => setShowRegister(false)}
                  className="text-sm text-teal-600 hover:text-teal-700 hover:underline"
                  data-testid="back-to-login-btn"
                >
                  Already have an account? Sign in
                </button>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-teal-600 to-teal-800 p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-20 h-20 bg-white rounded-2xl shadow-lg mb-4">
            <Shield className="w-12 h-12 text-teal-600" />
          </div>
          <h1 className="text-3xl font-bold text-white tracking-wide">NISCHINT</h1>
          <p className="text-teal-100 mt-2">Digital Care Monitoring Platform</p>
        </div>

        <Card className="backdrop-blur-sm bg-white/95 shadow-2xl border-0">
          <CardHeader className="text-center pb-2">
            <CardTitle className="text-xl">Welcome Back</CardTitle>
            <CardDescription>Sign in to your account</CardDescription>
          </CardHeader>
          <CardContent>
            <Tabs defaultValue="family" className="w-full">
              <TabsList className="grid w-full grid-cols-2 mb-6">
                <TabsTrigger value="family" className="flex items-center gap-2" data-testid="family-tab">
                  <Users className="w-4 h-4" />Family
                </TabsTrigger>
                <TabsTrigger value="operator" className="flex items-center gap-2" data-testid="operator-tab">
                  <Headphones className="w-4 h-4" />Operator
                </TabsTrigger>
              </TabsList>

              <TabsContent value="family">
                <form onSubmit={handleFamilyLogin} className="space-y-4">
                  <div className="space-y-2">
                    <Label htmlFor="family-email">Email</Label>
                    <Input id="family-email" type="email" placeholder="Enter your email"
                      value={email} onChange={(e) => setEmail(e.target.value)}
                      data-testid="family-email-input" disabled={loading} />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="family-password">Password</Label>
                    <Input id="family-password" type="password" placeholder="Enter your password"
                      value={password} onChange={(e) => setPassword(e.target.value)}
                      data-testid="family-password-input" disabled={loading} />
                  </div>
                  <Button type="submit" className="w-full bg-teal-600 hover:bg-teal-700"
                    data-testid="family-login-btn" disabled={loading}>
                    {loading ? <><Loader2 className="w-4 h-4 mr-2 animate-spin" />Signing in...</> : 'Sign in as Family Member'}
                  </Button>
                </form>
                {GOOGLE_CLIENT_ID && (
                  <>
                    <div className="relative my-4">
                      <div className="absolute inset-0 flex items-center">
                        <span className="w-full border-t border-slate-200" />
                      </div>
                      <div className="relative flex justify-center text-xs uppercase">
                        <span className="bg-white px-2 text-slate-400">or continue with</span>
                      </div>
                    </div>
                    <GoogleSignInButton onSuccess={handleGoogleSuccess} disabled={loading} />
                  </>
                )}
              </TabsContent>

              <TabsContent value="operator">
                <form onSubmit={handleOperatorLogin} className="space-y-4">
                  <div className="space-y-2">
                    <Label htmlFor="operator-email">Email</Label>
                    <Input id="operator-email" type="email" placeholder="Enter your email"
                      value={email} onChange={(e) => setEmail(e.target.value)}
                      data-testid="operator-email-input" />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="operator-password">Password</Label>
                    <Input id="operator-password" type="password" placeholder="Enter your password"
                      value={password} onChange={(e) => setPassword(e.target.value)}
                      data-testid="operator-password-input" />
                  </div>
                  <Button type="submit" className="w-full bg-slate-800 hover:bg-slate-900"
                    data-testid="operator-login-btn" disabled={loading}>
                    {loading ? <><Loader2 className="w-4 h-4 mr-2 animate-spin" />Signing in...</> : 'Sign in as Operator'}
                  </Button>
                </form>
              </TabsContent>
            </Tabs>

            <div className="mt-6 text-center space-y-2">
              <button
                onClick={() => setShowRegister(true)}
                className="text-sm text-teal-600 hover:text-teal-700 font-medium hover:underline"
                data-testid="go-to-register-btn"
              >
                New guardian? Create an account
              </button>
            </div>
          </CardContent>
        </Card>

        <p className="text-center text-teal-100 text-sm mt-6">
          &copy; 2025 NISCHINT. All rights reserved.
        </p>
      </div>
    </div>
  );
};

export default Login;
