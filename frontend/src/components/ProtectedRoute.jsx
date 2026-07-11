// Protected Route Component
import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

const ROLE_HOME = {
  operator: '/command-center',
  admin: '/admin',
  guardian: '/family',
  child: '/family',
  woman: '/family',
  elderly: '/family',
  family_member: '/family',
  caregiver: '/caregiver',
};

const ProtectedRoute = ({ children, allowedRoles }) => {
  const { user, isAuthenticated, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <div className="text-center">
          <div className="w-8 h-8 border-4 border-teal-600 border-t-transparent rounded-full animate-spin mx-auto mb-4"></div>
          <p className="text-slate-500">Loading...</p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated()) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  // Role-gated route: require a concrete role in the allowed list.
  // A roleless user (token without `role` claim) is NOT silently
  // granted access — they are bounced to `/family` (safe default).
  if (allowedRoles) {
    const userRole = user?.role;
    const rolesList = Array.isArray(user?.roles) ? user.roles : [];
    const matches = (userRole && allowedRoles.includes(userRole))
      || rolesList.some((r) => allowedRoles.includes(r));
    if (!matches) {
      const home = ROLE_HOME[userRole] || '/family';
      return <Navigate to={home} replace />;
    }
  }

  return children;
};

export default ProtectedRoute;
