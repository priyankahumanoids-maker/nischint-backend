# NISCHINT Mobile App

React Native (Expo) mobile application for the NISCHINT safety platform.

## Architecture

```
mobile/
├── app/                    # Expo Router screens
│   ├── _layout.tsx         # Root layout with auth guard
│   ├── index.tsx           # Entry redirect
│   ├── (auth)/             # Authentication flow
│   │   ├── _layout.tsx     # Auth stack navigator
│   │   ├── login.tsx       # Sign in screen
│   │   ├── register.tsx    # Create account screen
│   │   └── profile-select.tsx  # Profile mode selection
│   └── (tabs)/             # Main app tabs
│       ├── _layout.tsx     # Bottom tab navigator
│       ├── home.tsx        # Safety dashboard
│       ├── journey.tsx     # Start/manage journeys + safe routes
│       ├── safety-score.tsx # Location/route/journey scores
│       ├── alerts.tsx      # Predictive danger alerts
│       └── guardian.tsx    # Guardian dashboard / share safety
├── services/               # API layer
│   ├── api.ts              # Axios instance with auth interceptors
│   └── endpoints.ts        # All API service functions
├── stores/                 # Zustand state management
│   └── authStore.ts        # Auth state, token, profile mode
├── theme/                  # Design system
│   └── index.ts            # Colors, spacing, typography, utilities
└── .env                    # API URL configuration
```

## Profile Modes

Single app with 3 safety profiles:
- **Women Safety** — Late-night travel, safe routes, live sharing
- **Kids Safety** — School commute, guardian alerts, geo-fencing
- **Parents Care** — Elderly monitoring, fall detection, wellness

## Development

```bash
cd mobile
npm install

# Start development server
npx expo start

# Run on platforms
npx expo start --ios
npx expo start --android
npx expo start --web

# Build for web
npx expo export --platform web
```

## API Integration

All API calls go through `services/api.ts` which:
- Auto-attaches JWT tokens from SecureStore
- Handles 401 responses by clearing stored tokens
- Uses `EXPO_PUBLIC_API_URL` from `.env`

## Wave Roadmap

### Wave 1 — Core MVP (Current)
- Auth + profile selection
- Home safety dashboard
- Journey management (start/stop/safe routes)
- Safety Score (location/route/journey)
- Predictive alerts
- Guardian family dashboard
- Share safety

### Wave 2 — Device Safety Layer (Next)
- Silent SOS
- Background tracking
- App lifecycle handling
- Low battery / offline safety

### Wave 3 — Sensor Intelligence
- Fall Detection
- Wandering Detection
- Pickup Verification
- Voice Distress Detection
