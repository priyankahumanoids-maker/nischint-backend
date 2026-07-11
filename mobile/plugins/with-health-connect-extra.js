/**
 * HC-01 Day 1 — Health Connect prebuild extras for Expo SDK 55.
 *
 * `react-native-health-connect@3.5.3` ships its own config plugin that
 * injects the `androidx.health.ACTION_SHOW_PERMISSIONS_RATIONALE`
 * intent-filter into the main Activity. That plugin does NOT cover the
 * three things the integration spec also requires:
 *
 *   1. `<uses-permission android:name="android.permission.health.READ_*"/>`
 *      → handled by app.json `android.permissions[]` (Expo writes these
 *        into AndroidManifest at prebuild time).
 *
 *   2. `<queries><package android:name="com.google.android.apps.healthdata"/></queries>`
 *      Android 11+ visibility requirement so the app can detect that the
 *      Health Connect package is installed. Expo has no first-class
 *      `android.queries` key, so this plugin writes it directly.
 *
 *   3. `<meta-data android:name="health_permissions"
 *                  android:resource="@array/health_permissions"/>`
 *      inside `<application>` + the matching string-array resource at
 *      `android/app/src/main/res/values/health_permissions.xml`.
 *
 * Net effect after `expo prebuild` / EAS Build: the generated
 * AndroidManifest.xml is exactly the snippet that was requested in the
 * HC-01 Day 1 task.
 */

const {
  withAndroidManifest,
  withDangerousMod,
  AndroidConfig,
} = require('@expo/config-plugins');
const fs = require('fs');
const path = require('path');

const HEALTH_PERMISSIONS = [
  'androidx.health.permission.HeartRate.READ',
  'androidx.health.permission.OxygenSaturation.READ',
  'androidx.health.permission.Steps.READ',
];

// ── 1. <queries><package .../></queries> ───────────────────────────
const withHealthConnectQueries = (config) =>
  withAndroidManifest(config, (cfg) => {
    const manifest = cfg.modResults.manifest;

    manifest.queries = manifest.queries || [];
    const hasHealthData = manifest.queries.some(
      (q) =>
        (q.package || []).some(
          (p) => p?.$?.['android:name'] === 'com.google.android.apps.healthdata'
        ),
    );
    if (!hasHealthData) {
      manifest.queries.push({
        package: [{ $: { 'android:name': 'com.google.android.apps.healthdata' } }],
      });
    }
    return cfg;
  });

// ── 2. <meta-data android:name="health_permissions" .../> ─────────
const withHealthConnectMetaData = (config) =>
  withAndroidManifest(config, (cfg) => {
    const application = AndroidConfig.Manifest.getMainApplicationOrThrow(
      cfg.modResults,
    );
    application['meta-data'] = application['meta-data'] || [];
    const exists = application['meta-data'].some(
      (m) => m?.$?.['android:name'] === 'health_permissions',
    );
    if (!exists) {
      application['meta-data'].push({
        $: {
          'android:name': 'health_permissions',
          'android:resource': '@array/health_permissions',
        },
      });
    }
    return cfg;
  });

// ── 3. res/values/health_permissions.xml resource file ────────────
const withHealthConnectPermissionsResource = (config) =>
  withDangerousMod(config, [
    'android',
    async (cfg) => {
      const resDir = path.join(
        cfg.modRequest.platformProjectRoot,
        'app',
        'src',
        'main',
        'res',
        'values',
      );
      fs.mkdirSync(resDir, { recursive: true });

      const items = HEALTH_PERMISSIONS.map((p) => `        <item>${p}</item>`).join('\n');
      const xml = `<?xml version="1.0" encoding="utf-8"?>
<resources>
    <array name="health_permissions">
${items}
    </array>
</resources>
`;
      fs.writeFileSync(path.join(resDir, 'health_permissions.xml'), xml);
      return cfg;
    },
  ]);

module.exports = function withHealthConnectExtra(config) {
  config = withHealthConnectQueries(config);
  config = withHealthConnectMetaData(config);
  config = withHealthConnectPermissionsResource(config);
  return config;
};
