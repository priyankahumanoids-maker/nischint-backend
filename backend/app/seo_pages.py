"""
SEO landing page configuration — AI-SEO enhanced (Feb 2026).

Each route carries:
  • unique <title> / <meta description>
  • canonical + hreflang
  • OG + Twitter tags
  • noscript HTML block
  • faqs:   list of {question, answer} — rendered as visible Q&A + FAQPage JSON-LD
  • schema_type: "WebPage" | "SoftwareApplication" | "AboutPage" | "Blog"
  • page_keywords: comma-separated string for <meta keywords>

This structure targets both classic Google SEO and AI-crawler SEO
(GPTBot, ChatGPT-User, PerplexityBot, ClaudeBot).
"""

from typing import List, Optional
from typing_extensions import TypedDict

BASE_URL = "https://nischint.care"
ORG_LOGO = f"{BASE_URL}/icons/icon-512x512.png"


class FAQItem(TypedDict):
    question: str
    answer: str


class SEOPageConfig(TypedDict, total=False):
    title: str
    description: str
    canonical: str
    og_title: str
    og_description: str
    og_url: str
    twitter_title: str
    twitter_description: str
    noscript_h1: str
    noscript_html: str
    # New (AI-SEO)
    faqs: List[FAQItem]
    schema_type: str          # "WebPage" | "SoftwareApplication" | "AboutPage" | "Blog"
    page_keywords: str


# ─── Common FAQs reused as blueprint ────────────────────────────────────
_COMMON_FAQS_HOMEPAGE: List[FAQItem] = [
    {"question": "What is NISCHINT?",
     "answer": "NISCHINT is an AI-powered personal safety platform for women, children, and families in India. It uses real-time GPS tracking, voice distress detection, and automated guardian escalation to prevent emergencies and ensure faster human response."},
    {"question": "How does NISCHINT's AI safety detection work?",
     "answer": "NISCHINT continuously monitors location, movement patterns, device signals, and voice input (when enabled) to score risk every few seconds. When risk crosses a threshold, the Journey Engine automatically notifies your guardians via push, SMS, and a live dashboard — even if you cannot open the app."},
    {"question": "Which Indian cities does NISCHINT support?",
     "answer": "NISCHINT works across all major Indian cities including Delhi, Mumbai, Bangalore, Chennai, Hyderabad, Kolkata, Pune, Ahmedabad, Jaipur, Lucknow, and 180+ other cities. GPS and cellular-based tracking works anywhere in India."},
    {"question": "Is NISCHINT safe for children to use?",
     "answer": "Yes. NISCHINT is built for children as young as 8 years with a simplified Child Mode. Parents control guardians, alerts, and geofences through the Guardian Dashboard. All data is encrypted and never shared with third parties."},
    {"question": "How is NISCHINT different from other safety apps?",
     "answer": "Most safety apps are reactive — they need the user to press a button. NISCHINT is proactive: it detects risk automatically via AI, escalates to multiple guardians in priority order, and pre-alerts authorities in critical situations — all without user action."},
    {"question": "Does NISCHINT work without internet?",
     "answer": "Yes. NISCHINT has an offline mesh mode and SMS fallback. If the network drops mid-journey, SOS alerts are queued and sent when connectivity returns, and critical alerts fall back to SMS automatically."},
]


_WOMEN_FAQS: List[FAQItem] = [
    {"question": "What is the best women safety app in India?",
     "answer": "NISCHINT is India's leading AI-powered women safety app, offering voice distress detection in Indian languages, silent SOS, multi-guardian alerts, and real-time GPS tracking tuned for Indian cities and commute patterns."},
    {"question": "Can NISCHINT detect distress when my phone is locked?",
     "answer": "Yes. NISCHINT's background voice listener can detect scream, panic words, and distress tones even when the screen is off, and instantly trigger a silent SOS to your guardians without unlocking the phone."},
    {"question": "How does silent SOS work on NISCHINT?",
     "answer": "Silent SOS activates via a triple-press of the power button, a discreet in-app gesture, or an automatic AI detection. It immediately shares your live location with your guardian network and starts the escalation timer — all without any visible alert on the phone."},
    {"question": "Is NISCHINT free for women?",
     "answer": "NISCHINT offers a free tier with core safety features including SOS, live location sharing, and guardian alerts. Premium features like AI voice detection and unlimited journey history are available on affordable monthly plans."},
    {"question": "How fast are guardians alerted in an emergency?",
     "answer": "Guardians receive push and SMS alerts within 2-3 seconds of a SOS trigger. NISCHINT's escalation engine auto-notifies the next guardian if the first does not acknowledge within 30 seconds, and pre-alerts authorities in critical risk situations."},
]


_KIDS_FAQS: List[FAQItem] = [
    {"question": "What is the best kids safety app in India?",
     "answer": "NISCHINT is designed for Indian school children with live GPS tracking, geofencing for school/home/tuition, school-bus route monitoring, and an SOS button accessible even on the lock screen."},
    {"question": "Can parents track multiple children on NISCHINT?",
     "answer": "Yes. Multi-child, multi-guardian support is built in. One parent dashboard can monitor all children, and grandparents or close family can be added as co-guardians with permission controls."},
    {"question": "Does NISCHINT work on both Android and iPhone for kids?",
     "answer": "NISCHINT works on Android 7+ and iOS 13+. Both platforms support background tracking, geofence alerts, SOS, and battery-friendly monitoring."},
    {"question": "How does geofencing work for children's safety?",
     "answer": "Parents define safe zones (school, home, tuition). The app instantly alerts you when the child enters or leaves a zone. Timeline view shows all zone entries and exits for the day."},
    {"question": "Is my child's location data private?",
     "answer": "Yes. All location data is encrypted in transit (TLS) and at rest (AES-256). Only assigned guardians can view the child's location. NISCHINT never sells or shares personal data with third parties."},
]


_FAMILY_FAQS: List[FAQItem] = [
    {"question": "What is the best family safety app for Indian families?",
     "answer": "NISCHINT unifies safety for every family member — children, spouse, elderly parents — in a single app. It supports multi-generational guardians, fall detection for seniors, and coordinated SOS response for joint and nuclear families."},
    {"question": "How many family members can I add to NISCHINT?",
     "answer": "The family plan supports up to 10 members with unlimited guardians per member. Perfect for joint families or extended families who want everyone visible on a single safety dashboard."},
    {"question": "Can NISCHINT help with elderly parent safety?",
     "answer": "Yes. NISCHINT's elderly safety module includes fall detection, inactivity alerts, medication reminders, and one-tap SOS. Adult children can monitor parents remotely with the Guardian app."},
    {"question": "Does NISCHINT support Indian emergency numbers like 112 and 1091?",
     "answer": "Yes. NISCHINT integrates with India's emergency helplines — 112 (ERSS), 1091 (Women Helpline), 1098 (Child Helpline) — and can auto-dial them when a critical SOS is verified by a guardian."},
    {"question": "Can I share my location with only one family member?",
     "answer": "Absolutely. NISCHINT gives granular privacy controls — you choose exactly which guardians see your live location, who gets SOS alerts, and who sees journey history."},
]


_WHAT_IS_FAQS: List[FAQItem] = [
    {"question": "What does NISCHINT mean?",
     "answer": "NISCHINT is a Sanskrit and Hindi word meaning 'free from worry' or 'reassured'. The name captures our product promise — AI-powered safety infrastructure that lets you and your family live without fear."},
    {"question": "Who founded NISCHINT?",
     "answer": "NISCHINT is built by a team of safety technology veterans in India focused on solving real safety challenges faced by women, children, and families across Indian cities."},
    {"question": "How is NISCHINT's AI trained?",
     "answer": "NISCHINT's AI models are trained on anonymized Indian safety incident patterns, Indian-language distress vocabulary, and location-risk datasets covering 200+ Indian cities. Models are continually refined with on-device feedback."},
    {"question": "What data does NISCHINT collect?",
     "answer": "Only the minimum required for safety: GPS location (while tracking is on), device battery, network status, and (optional) microphone input for distress detection. All data is encrypted, and users can export or delete their data at any time."},
    {"question": "Is NISCHINT compliant with Indian data laws?",
     "answer": "Yes. NISCHINT follows India's Digital Personal Data Protection Act (DPDP), stores user data on servers hosted in India, and gives users full data portability and deletion rights."},
]


_BLOG_FAQS: List[FAQItem] = [
    {"question": "What topics does the NISCHINT safety blog cover?",
     "answer": "The blog covers personal safety, women's safety in Indian cities, child safety during school commutes, family emergency planning, elderly safety, and product updates for AI-powered safety technology."},
    {"question": "How often is the safety blog updated?",
     "answer": "New safety guides, expert interviews, and product updates are published weekly. Subscribe via email to get each post in your inbox."},
    {"question": "Who writes NISCHINT's safety content?",
     "answer": "Articles are written by safety experts, former law-enforcement professionals, Indian women's-safety activists, and the NISCHINT product team. Each piece is fact-checked for Indian legal and emergency-response accuracy."},
]


_PILOT_FAQS: List[FAQItem] = [
    {"question": "What is the NISCHINT Pilot Program?",
     "answer": "The Pilot Program deploys NISCHINT's AI safety infrastructure across schools, universities, and corporate campuses in India. Typical pilots run 30-90 days with full onboarding and dashboard training."},
    {"question": "Which institutions can apply for the NISCHINT pilot?",
     "answer": "K-12 schools, universities, women's colleges, corporate campuses, residential societies, and smart-city projects across India. Minimum deployment starts at 200 users."},
    {"question": "How much does the NISCHINT pilot cost?",
     "answer": "Pilot pricing is based on scale and duration. We offer subsidized pilots for girls' schools and women's colleges as part of our safety mission. Contact partners@nischint.app for a custom quote."},
]


# ─── Page configs with FAQs + schema_type ────────────────────────────────
SEO_PAGES: dict[str, SEOPageConfig] = {
    "/": {
        "title": "NISCHINT — AI Safety Infrastructure | Real-Time Safety Monitoring for India",
        "description": "NISCHINT is India's AI-powered personal safety platform. Real-time GPS tracking, voice distress detection, silent SOS, and instant guardian alerts for women, children, and families across 200+ Indian cities.",
        "canonical": f"{BASE_URL}/",
        "og_title": "NISCHINT — AI Safety Infrastructure for India",
        "og_description": "AI-powered safety for women, children, and families across India. Real-time GPS tracking, voice distress detection, instant guardian alerts.",
        "og_url": f"{BASE_URL}/",
        "twitter_title": "NISCHINT — AI Safety Infrastructure for India",
        "twitter_description": "AI-powered safety for women, children, and families across India.",
        "noscript_h1": "NISCHINT — AI Safety Infrastructure for India",
        "page_keywords": "personal safety app India, women safety app, kids safety app, family safety app, AI safety, GPS tracker India, emergency SOS, voice distress detection, NISCHINT",
        "schema_type": "WebPage",
        "faqs": _COMMON_FAQS_HOMEPAGE,
        "noscript_html": """
            <h1>NISCHINT — AI Safety Infrastructure for India</h1>
            <p>NISCHINT is India's AI-powered personal safety platform for women, children, and families. Our safety operating system combines real-time GPS tracking, voice distress detection, intelligent SOS escalation, and a multi-guardian alert network.</p>
            <h2>Who Do You Want to Protect?</h2>
            <p>Whether you're a woman on a late-night commute, a parent tracking your child's school bus, or an adult child caring for elderly parents — NISCHINT has a dedicated safety mode for you.</p>
            <p><a href="https://nischint.care/women-safety-app">Women Safety</a> · <a href="https://nischint.care/kids-safety-app">Kids Safety</a> · <a href="https://nischint.care/family-safety-app">Family Safety</a> · <a href="https://nischint.care/what-is-nischint">What is NISCHINT?</a> · <a href="https://nischint.care/blog">Safety Blog</a></p>
            <h2>Why NISCHINT</h2>
            <p>24/7 AI monitoring. Response under 3 seconds. 99.9% delivery reliability across 8 AI engines tuned for Indian cities.</p>
        """,
    },
    "/women-safety-app": {
        "title": "Women Safety App India | NISCHINT - AI-Powered Personal Safety",
        "description": "India's #1 AI women safety app with real-time GPS tracking, voice distress detection, silent SOS, and instant guardian alerts. Built for women's safety in Indian cities.",
        "canonical": f"{BASE_URL}/women-safety-app",
        "og_title": "NISCHINT Women Safety App - AI Protection for Women in India",
        "og_description": "Real-time GPS tracking, voice distress detection, silent SOS, and instant guardian alerts. India's most trusted AI women safety app.",
        "og_url": f"{BASE_URL}/women-safety-app",
        "twitter_title": "NISCHINT - AI Women Safety App for India",
        "twitter_description": "AI-powered personal safety with voice distress detection and instant guardian alerts.",
        "noscript_h1": "Women Safety App for India - AI-Powered Personal Protection",
        "page_keywords": "women safety app India, women safety, personal safety for women, silent SOS, voice distress detection, AI safety app, NISCHINT women",
        "schema_type": "SoftwareApplication",
        "faqs": _WOMEN_FAQS,
        "noscript_html": """
            <h1>Women Safety App for India - AI-Powered Personal Protection</h1>
            <p>NISCHINT is India's leading AI-powered women safety app, designed for the real safety challenges women face in Indian cities. Our platform combines real-time GPS tracking, voice distress detection that works even when your phone is locked, and instant alerts to multiple guardians.</p>
            <h2>Key Features for Women's Safety</h2>
            <p>Real-time location sharing with trusted contacts. Silent SOS activation through voice commands. Multi-guardian alert network that notifies family, friends, and emergency contacts within seconds. Background safety monitoring that works without draining your battery.</p>
            <h2>Built for Indian Women</h2>
            <p>NISCHINT understands the unique safety challenges of Indian cities — late-night commutes, ride-sharing safety, workplace concerns, and travel between cities. Our voice distress detection is trained on Indian languages and accents.</p>
            <p><a href="https://nischint.care/pilot">Request a demo</a> or download NISCHINT today to take control of your personal safety.</p>
        """,
    },
    "/kids-safety-app": {
        "title": "Kids Safety App India | NISCHINT - GPS Tracker & Child Safety",
        "description": "Protect your children with NISCHINT's AI-powered kids safety app. Real-time GPS tracking, geofencing, school commute monitoring, and instant parent alerts.",
        "canonical": f"{BASE_URL}/kids-safety-app",
        "og_title": "NISCHINT Kids Safety App - GPS Tracker for Children in India",
        "og_description": "Real-time GPS tracking, geofencing, and school commute safety for Indian parents. Know your children are safe.",
        "og_url": f"{BASE_URL}/kids-safety-app",
        "twitter_title": "NISCHINT - Kids Safety App with GPS Tracking",
        "twitter_description": "AI-powered child safety platform for Indian parents.",
        "noscript_h1": "Kids Safety App - GPS Tracker for Children in India",
        "page_keywords": "kids safety app India, child GPS tracker, school commute safety, geofencing for children, parental control India, NISCHINT kids",
        "schema_type": "SoftwareApplication",
        "faqs": _KIDS_FAQS,
        "noscript_html": """
            <h1>Kids Safety App - GPS Tracker for Children in India</h1>
            <p>NISCHINT helps Indian parents protect their children with real-time GPS tracking, geofencing, and intelligent safety alerts. Whether your child is at school, on the bus, or at a friend's house, you'll always know they're safe.</p>
            <h2>Child Safety Features</h2>
            <p>Live GPS location with location history. Geofencing alerts when your child enters or leaves designated areas like school or home. School bus tracking and route monitoring. Instant SOS button on the child's device. Battery-friendly background tracking.</p>
            <h2>Designed for Indian Families</h2>
            <p>Built for the realities of Indian school commutes, tuition classes, and busy urban environments. Multiple guardian access so both parents and grandparents can monitor safety.</p>
            <p><a href="https://nischint.care/pilot">Schedule a demo</a> to see how NISCHINT keeps your children safe.</p>
        """,
    },
    "/family-safety-app": {
        "title": "Family Safety App India | NISCHINT - Complete Family Protection",
        "description": "Keep your entire family safe with NISCHINT's family safety platform. Live location sharing, emergency SOS, elderly safety monitoring, coordinated guardian response.",
        "canonical": f"{BASE_URL}/family-safety-app",
        "og_title": "NISCHINT Family Safety App - Protect Your Whole Family",
        "og_description": "Complete family protection with live tracking, emergency SOS, and coordinated guardian network across India.",
        "og_url": f"{BASE_URL}/family-safety-app",
        "twitter_title": "NISCHINT - Family Safety App for India",
        "twitter_description": "Complete family protection with AI-powered safety monitoring.",
        "noscript_h1": "Family Safety App - Complete Protection for Indian Families",
        "page_keywords": "family safety app India, family GPS tracker, elderly safety app, joint family safety, multi-generational safety, NISCHINT family",
        "schema_type": "SoftwareApplication",
        "faqs": _FAMILY_FAQS,
        "noscript_html": """
            <h1>Family Safety App - Complete Protection for Indian Families</h1>
            <p>NISCHINT brings your entire family into one safety network. Track elderly parents, monitor children's school commutes, share locations with your spouse, and coordinate emergency response — all from a single app.</p>
            <h2>Family Safety Features</h2>
            <p>Live family location sharing with privacy controls. Elderly safety monitoring with fall detection alerts. Multi-generational guardian network. Coordinated SOS response across all family members. Family emergency dashboard.</p>
            <h2>For Multi-Generational Indian Families</h2>
            <p>Designed for joint families and nuclear families across India. Works for elderly parents, working couples, school-age children, and college students.</p>
            <p><a href="https://nischint.care/pilot">Get NISCHINT for your family</a> and stay connected through safety.</p>
        """,
    },
    "/what-is-nischint": {
        "title": "What is NISCHINT? | AI Safety App for Women, Kids & Families in India",
        "description": "NISCHINT is an AI-powered personal safety platform for women, children, and families in India using real-time monitoring, voice distress detection, and automated escalation to prevent emergencies.",
        "canonical": f"{BASE_URL}/what-is-nischint",
        "og_title": "What is NISCHINT? - AI Safety Platform for India",
        "og_description": "AI-powered personal safety with real-time monitoring, voice distress detection, and automated escalation for women, kids and families in India.",
        "og_url": f"{BASE_URL}/what-is-nischint",
        "twitter_title": "What is NISCHINT? - AI Safety App for India",
        "twitter_description": "AI-powered personal safety platform with real-time monitoring and automated escalation for women, children, and families.",
        "noscript_h1": "What is NISCHINT? AI-Powered Personal Safety for India",
        "page_keywords": "what is NISCHINT, about NISCHINT, AI safety platform India, safety infrastructure, DPDP compliant safety app",
        "schema_type": "AboutPage",
        "faqs": _WHAT_IS_FAQS,
        "noscript_html": """
            <h1>What is NISCHINT?</h1>
            <p>NISCHINT is an AI-powered personal safety platform for women, children, and families in India. It uses real-time monitoring, voice distress detection, and automated escalation to prevent emergencies and enable faster human response.</p>
            <h2>Why Traditional Safety Apps Fail</h2>
            <p>Most apps only track location. No real-time distress detection. No intelligent escalation. No proactive intervention. Result: help comes too late.</p>
            <h2>How NISCHINT Works</h2>
            <p>Voice Distress Detection: detects panic, scream, or distress in real time. Live Location Tracking: continuous monitoring of movement. Smart Escalation Engine: automatically alerts guardians when risk is detected. Guardian Network: immediate human response layer.</p>
            <h2>Use Cases</h2>
            <p>For Women: late-night travel, cab rides, unknown locations. <a href="https://nischint.care/women-safety-app">Women safety app</a>.</p>
            <p>For Children: school commute, outdoor play, travel alone. <a href="https://nischint.care/kids-safety-app">Kids safety app</a>.</p>
            <p>For Families: elderly monitoring, emergency alerts, daily safety tracking. <a href="https://nischint.care/family-safety-app">Family safety app</a>.</p>
            <p>Protect what matters most. <a href="https://nischint.care/pilot">Start using NISCHINT today</a>.</p>
        """,
    },
    "/blog": {
        "title": "Safety Blog | NISCHINT - Expert Guides on Personal & Child Safety",
        "description": "Expert safety guides, research, and product updates from NISCHINT. Personal safety for women, child safety tips for Indian parents, family emergency planning, and AI safety insights.",
        "canonical": f"{BASE_URL}/blog",
        "og_title": "NISCHINT Safety Blog - Guides for Indian Families",
        "og_description": "Expert safety guides for women, children, and families in India. Weekly articles from safety professionals and the NISCHINT team.",
        "og_url": f"{BASE_URL}/blog",
        "twitter_title": "NISCHINT Safety Blog",
        "twitter_description": "Expert safety guides and product updates from NISCHINT.",
        "noscript_h1": "NISCHINT Safety Blog - Expert Guides on Personal & Child Safety",
        "page_keywords": "safety blog India, women safety tips, child safety guide, family emergency planning, NISCHINT blog",
        "schema_type": "Blog",
        "faqs": _BLOG_FAQS,
        "noscript_html": """
            <h1>NISCHINT Safety Blog</h1>
            <p>Expert safety guides, research, and product updates from NISCHINT. We publish weekly articles on personal safety, child safety, women's safety in Indian cities, family emergency planning, and the AI behind our safety platform.</p>
            <h2>Latest Topics</h2>
            <p>Personal safety for women · Child safety during school commutes · Elderly safety at home · Family emergency planning · AI safety technology explained · Indian city safety guides.</p>
            <p>Explore more: <a href="https://nischint.care/women-safety-app">Women Safety App</a> · <a href="https://nischint.care/kids-safety-app">Kids Safety App</a> · <a href="https://nischint.care/family-safety-app">Family Safety App</a>.</p>
        """,
    },
    "/pilot": {
        "title": "NISCHINT Pilot Program | AI Safety for Schools & Campuses India",
        "description": "Deploy NISCHINT's AI safety platform for your school, university, or corporate campus. Pilot programs available across India. Schedule a demo with our safety experts.",
        "canonical": f"{BASE_URL}/pilot",
        "og_title": "NISCHINT Pilot - Campus Safety Deployment for India",
        "og_description": "Deploy AI-powered safety infrastructure for schools, universities, and corporate campuses across India.",
        "og_url": f"{BASE_URL}/pilot",
        "twitter_title": "NISCHINT Pilot Program - Campus Safety",
        "twitter_description": "AI safety deployment for institutions across India.",
        "noscript_h1": "NISCHINT Pilot Program for Schools and Campuses",
        "page_keywords": "NISCHINT pilot, campus safety India, school safety app, university safety deployment, corporate safety",
        "schema_type": "WebPage",
        "faqs": _PILOT_FAQS,
        "noscript_html": """
            <h1>NISCHINT Pilot Program for Schools and Campuses</h1>
            <p>Deploy NISCHINT's AI safety operating system across your school, university, or corporate campus. Our pilot program gives institutions a complete safety infrastructure with real-time monitoring, AI-powered risk detection, and coordinated emergency response.</p>
            <h2>What You Get in the Pilot</h2>
            <p>Campus-wide GPS tracking and geofencing. AI-powered voice distress detection across all student devices. Centralized safety dashboard for administrators. 24x7 emergency response coordination. Custom integration with existing campus systems.</p>
            <h2>Who It's For</h2>
            <p>K-12 schools, universities, women's colleges, corporate campuses, and smart cities across India. Pilot programs typically run 30-90 days with full support from the NISCHINT team.</p>
            <p>Contact us at partners@nischint.app or fill out the form below to schedule a discovery call.</p>
        """,
    },
}


def get_seo_config(path: str) -> Optional[SEOPageConfig]:
    """Returns SEO config for a path, or None if path is not an SEO landing page."""
    return SEO_PAGES.get(path)
