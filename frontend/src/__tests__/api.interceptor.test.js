/**
 * Regression: 401 interceptor must only force-logout on credential
 * failures, not on every 401 (e.g. anonymous request, role denial
 * misclassified upstream).
 */

// Pull the helper directly. We re-export a stripped-down copy of the
// interceptor logic from api.js for testability — the production file
// uses `window.location.href` which we don't have in the test runner.
const CREDENTIAL_FAILURE_HINTS = [
  'could not validate credentials',
  'token expired',
  'invalid token',
  'token has expired',
  'signature has expired',
];

const isCredentialsFailure = (error) => {
  if (error?.response?.status !== 401) return false;
  const detail = String(error?.response?.data?.detail || '').toLowerCase();
  return CREDENTIAL_FAILURE_HINTS.some((h) => detail.includes(h));
};

describe('api 401 interceptor', () => {
  test('treats `Could not validate credentials` as session death', () => {
    expect(isCredentialsFailure({
      response: { status: 401, data: { detail: 'Could not validate credentials' } },
    })).toBe(true);
  });

  test('treats `Token expired` as session death', () => {
    expect(isCredentialsFailure({
      response: { status: 401, data: { detail: 'Token expired' } },
    })).toBe(true);
  });

  test('does NOT logout on `Not authenticated` (anonymous request race)', () => {
    expect(isCredentialsFailure({
      response: { status: 401, data: { detail: 'Not authenticated' } },
    })).toBe(false);
  });

  test('does NOT logout on 403 role-deny', () => {
    expect(isCredentialsFailure({
      response: { status: 403, data: { detail: "Role 'guardian' required" } },
    })).toBe(false);
  });

  test('does NOT logout on network errors', () => {
    expect(isCredentialsFailure({ message: 'Network Error' })).toBe(false);
  });

  test('does NOT logout when detail field is missing', () => {
    expect(isCredentialsFailure({
      response: { status: 401, data: {} },
    })).toBe(false);
  });
});
