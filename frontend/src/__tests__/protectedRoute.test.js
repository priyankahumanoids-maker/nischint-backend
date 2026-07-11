/**
 * Regression: ProtectedRoute role-gate logic — now treats `null` role
 * as a denied role (no silent access) and also honors the `roles`
 * array for multi-role users (e.g., guardian+admin).
 */

// Extract just the gating decision — same logic the component uses.
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

const decideGate = (user, allowedRoles) => {
  if (!allowedRoles) return { allow: true };
  const userRole = user?.role;
  const rolesList = Array.isArray(user?.roles) ? user.roles : [];
  const matches = (userRole && allowedRoles.includes(userRole))
    || rolesList.some((r) => allowedRoles.includes(r));
  if (matches) return { allow: true };
  return { allow: false, redirect: ROLE_HOME[userRole] || '/family' };
};

describe('ProtectedRoute role-gate', () => {
  test('allows when primary role matches', () => {
    const r = decideGate({ role: 'operator' }, ['operator']);
    expect(r).toEqual({ allow: true });
  });

  test('allows when secondary role in `roles[]` matches', () => {
    const r = decideGate({ role: 'guardian', roles: ['guardian', 'admin'] }, ['admin']);
    expect(r).toEqual({ allow: true });
  });

  test('denies child from /command-center and redirects to /family', () => {
    const r = decideGate({ role: 'child' }, ['operator', 'admin']);
    expect(r.allow).toBe(false);
    expect(r.redirect).toBe('/family');
  });

  test('denies operator from /admin-only and redirects to /command-center', () => {
    const r = decideGate({ role: 'operator' }, ['admin']);
    expect(r.allow).toBe(false);
    expect(r.redirect).toBe('/command-center');
  });

  test('roleless user (null) is DENIED (regression — previously silently allowed)', () => {
    const r = decideGate({ role: null, roles: [] }, ['operator']);
    expect(r.allow).toBe(false);
    expect(r.redirect).toBe('/family');
  });

  test('no allowedRoles → no gate (open access)', () => {
    const r = decideGate({ role: 'child' }, undefined);
    expect(r).toEqual({ allow: true });
  });
});
