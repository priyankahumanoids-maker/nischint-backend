// SF-01 v2 — DPDP-compliant Privacy Policy page.
//
// Content sourced verbatim from the legal artifact provided 2026-05-21.
// DO NOT modify the legal text without sign-off from the Grievance
// Officer (Feroz Shaikh, Founder & CEO).
//
// Brand notes:
//   * Navy + cyan palette (matches the artifact + nischint.care)
//   * Section anchors retained for in-page navigation
//   * Test IDs locked for QA
import React from 'react';
import { Helmet } from 'react-helmet-async';
import { Link } from 'react-router-dom';

const RIGHT_CARDS = [
  { icon: '📋', title: 'Right to Access',          body: 'Request a summary of personal data we hold about you and how it is being processed.' },
  { icon: '✏️', title: 'Right to Correction',      body: 'Request correction of inaccurate or incomplete personal data.' },
  { icon: '🗑️', title: 'Right to Erasure',         body: 'Request deletion of your personal data when it is no longer necessary for the purpose it was collected.' },
  { icon: '🚫', title: 'Right to Withdraw Consent', body: 'Withdraw consent for any data processing at any time. Withdrawal does not affect prior processing.' },
  { icon: '📣', title: 'Right to Grievance',       body: 'Lodge a grievance with our Grievance Officer. If unresolved, escalate to the Data Protection Board of India.' },
  { icon: '👤', title: 'Nominee Rights',           body: 'Designate a nominee to exercise your rights in the event of death or incapacity.' },
];

const DATA_TABLE = [
  { cat: 'Identity',       points: 'Name, phone number, email address, profile photo',          purpose: 'Account creation and authentication',                                basis: 'Consent' },
  { cat: 'Location',       points: 'Real-time GPS coordinates, route history, geofence zones',  purpose: 'Safety monitoring, route deviation detection, emergency response',   basis: 'Consent (explicit, revocable)' },
  { cat: 'Audio',          points: 'Ambient audio during active safety sessions only',          purpose: 'Voice distress detection (on-device AI processing)',                 basis: 'Explicit consent (session-by-session)' },
  { cat: 'Device',         points: 'Device ID, OS version, push notification token',            purpose: 'App functionality, emergency alerts',                                basis: 'Legitimate use' },
  { cat: 'Guardian Links', points: 'Guardian/child relationship, emergency contacts',           purpose: 'Guardian network coordination and alerts',                           basis: 'Consent of both parties' },
  { cat: 'Usage Data',     points: 'App interactions, feature usage patterns',                  purpose: 'Product improvement, safety algorithm training',                     basis: 'Legitimate use (anonymised)' },
];

const SHARING_TABLE = [
  { party: 'Amazon Web Services (Mumbai Region, ap-south-1)', purpose: 'Cloud infrastructure hosting', shared: 'All platform data — hosted in AWS Asia Pacific (Mumbai, ap-south-1) · DPDP-aligned' },
  { party: 'Twilio',                              purpose: 'SMS and voice alerts',         shared: 'Phone number, alert message content' },
  { party: 'SendGrid',                            purpose: 'Email notifications',          shared: 'Email address, notification content' },
  { party: 'Firebase (Google)',                   purpose: 'Push notifications (FCM)',     shared: 'Device push token' },
  { party: 'Law Enforcement',                     purpose: 'Legal obligation, emergency response', shared: 'As required by valid legal process' },
];

const TOC = [
  ['who-we-are',     'Who We Are'],
  ['data-we-collect','Data We Collect'],
  ['how-we-use',     'How We Use Your Data'],
  ['children',       "Children's Data & Parental Consent"],
  ['sharing',        'Data Sharing & Third Parties'],
  ['retention',      'Data Retention'],
  ['security',       'Security'],
  ['your-rights',    'Your Rights Under DPDP Act 2023'],
  ['grievance',      'Grievance Officer'],
  ['changes',        'Changes to This Policy'],
  ['contact',        'Contact Us'],
];

export default function PrivacyPolicyPage() {
  return (
    <div className="min-h-screen bg-[#0B1F3A] text-[#E8EDF2]" data-testid="privacy-policy-page">
      <Helmet>
        <title>Privacy Policy | NISCHINT</title>
        <meta name="description" content="NISCHINT Privacy Policy — how we collect, use, and protect your personal data under India's Digital Personal Data Protection Act 2023." />
      </Helmet>

      {/* Header */}
      <header className="border-b border-[#1E3A5F] px-6 py-4 flex items-center gap-3">
        <div className="text-xl font-extrabold tracking-widest text-white">
          NISCH<span className="text-[#00C6FF]">INT</span>
        </div>
        <div className="flex-1" />
        <Link to="/" className="text-sm text-[#00C6FF] hover:underline" data-testid="privacy-back-link">
          ← Back to nischint.care
        </Link>
      </header>

      {/* Hero */}
      <div className="border-b border-[#1E3A5F] bg-gradient-to-br from-[#0B1F3A] to-[#1E3A5F] px-6 pt-16 pb-12 text-center">
        <div className="inline-block rounded-full border border-[#00C6FF]/30 bg-[#00C6FF]/10 px-3.5 py-1 text-[12px] font-semibold uppercase tracking-wide text-[#00C6FF]">
          Legal Document
        </div>
        <h1 className="mt-4 text-4xl font-extrabold text-white sm:text-5xl">Privacy Policy</h1>
        <p className="mx-auto mt-3 max-w-xl text-[15px] text-[#8BA3C4]">
          How NISCHINT collects, uses, stores, and protects your personal data — and your rights under Indian law.
        </p>
        <div className="mt-4 text-[13px] text-[#4A6FA5]" data-testid="privacy-effective-date">
          Last updated: 18 May 2026 &nbsp;·&nbsp; Effective: 18 May 2026
        </div>
      </div>

      <div className="mx-auto max-w-3xl px-6 pt-12 pb-20">
        {/* DPDP banner */}
        <div className="mb-12 flex items-start gap-4 rounded-xl border border-[#00C6FF]/25 bg-gradient-to-br from-[#00C6FF]/[0.08] to-[#00C6FF]/[0.03] px-6 py-5">
          <div className="text-[28px]" aria-hidden>🛡️</div>
          <div>
            <h3 className="text-[15px] font-bold text-[#00C6FF]">DPDP Act 2023 Compliance</h3>
            <p className="mt-1.5 text-[14px] text-[#8BA3C4]">
              This policy is prepared in accordance with India&apos;s Digital Personal Data Protection Act, 2023 (DPDP Act) and the Draft Digital Personal Data Protection Rules, 2026.
              NISCHINT is committed to processing your personal data lawfully, fairly, and transparently.
            </p>
          </div>
        </div>

        {/* TOC */}
        <nav className="mb-12 rounded-xl border border-[#1E3A5F] bg-[#112240] px-7 py-6" aria-label="Table of contents">
          <h2 className="mb-3.5 text-[14px] font-bold uppercase tracking-wide text-[#00C6FF]">Contents</h2>
          <ol className="list-decimal space-y-1.5 pl-5 text-[14px]">
            {TOC.map(([id, label]) => (
              <li key={id}>
                <a href={`#${id}`} className="text-[#8BA3C4] hover:text-[#00C6FF]">{label}</a>
              </li>
            ))}
          </ol>
        </nav>

        {/* 1 */}
        <Section id="who-we-are" title="1. Who We Are">
          <p><strong className="text-[#C8D8E8]">NISCHINT Technology Private Limited</strong> (&quot;NISCHINT&quot;, &quot;we&quot;, &quot;us&quot;, &quot;our&quot;) is a company incorporated under the Companies Act, 2013, with its registered office in Mumbai, Maharashtra, India.</p>
          <p>We operate the NISCHINT mobile application and the website nischint.care — an AI-powered urban safety platform designed to protect vulnerable users including women, children, and senior citizens across Indian cities.</p>
          <p>For the purposes of the DPDP Act 2023, NISCHINT acts as the <strong className="text-[#C8D8E8]">Data Fiduciary</strong> in respect of personal data processed through our platform.</p>
        </Section>

        {/* 2 */}
        <Section id="data-we-collect" title="2. Data We Collect">
          <p>We collect only the data necessary to provide safety services. The categories of personal data we process are:</p>
          <DataTable headers={['Category', 'Data Points', 'Purpose', 'Basis']} rows={DATA_TABLE.map(r => [<strong key="c">{r.cat}</strong>, r.points, r.purpose, r.basis])} />
          <Highlight>
            ⚠️ <strong>Audio Processing:</strong> Audio captured during safety sessions is processed on-device using AI. Audio data is not stored on our servers unless a distress event is detected and you have consented to incident logging.
          </Highlight>
        </Section>

        {/* 3 */}
        <Section id="how-we-use" title="3. How We Use Your Data">
          <p>We use personal data for the following purposes:</p>
          <ul className="list-disc space-y-2 pl-5 text-[15px] text-[#8BA3C4]">
            <li><strong className="text-[#C8D8E8]">Safety Monitoring:</strong> Real-time GPS tracking, fall detection, route deviation alerts, wandering detection, and pickup anomaly detection.</li>
            <li><strong className="text-[#C8D8E8]">Emergency Response:</strong> Triggering SOS alerts, notifying guardians, escalating to emergency contacts.</li>
            <li><strong className="text-[#C8D8E8]">Guardian Network:</strong> Coordinating between linked guardians and protected users.</li>
            <li><strong className="text-[#C8D8E8]">AI Safety Brain:</strong> Training and improving our five-layer detection model using anonymised, aggregated data only.</li>
            <li><strong className="text-[#C8D8E8]">Communications:</strong> Safety alerts, account notifications, service updates. We do not send marketing emails without your explicit opt-in.</li>
            <li><strong className="text-[#C8D8E8]">Legal Compliance:</strong> Complying with applicable Indian laws, court orders, and regulatory requirements.</li>
          </ul>
          <p>We do not sell your personal data to any third party. We do not use your data for advertising profiling.</p>
        </Section>

        {/* 4 */}
        <Section id="children" title="4. Children's Data & Parental Consent">
          <p>NISCHINT processes personal data of children (users under 18 years of age) as a core part of our child safety product. We take this responsibility seriously and comply fully with Section 9 of the DPDP Act 2023 and the Draft DPDP Rules 2026.</p>
          <h3 className="mt-6 mb-2.5 text-[16px] font-semibold text-[#00C6FF]">Parental / Guardian Consent</h3>
          <ul className="list-disc space-y-2 pl-5 text-[15px] text-[#8BA3C4]">
            <li>No child&apos;s account is created without verifiable consent from a parent or legal guardian.</li>
            <li>Guardian consent is obtained through our in-app consent flow, which requires the guardian to create their own verified account and explicitly link the child&apos;s profile.</li>
            <li>Guardians may review all data associated with a child&apos;s account at any time through the Guardian Dashboard.</li>
            <li>Guardians may withdraw consent and request deletion of a child&apos;s data at any time.</li>
          </ul>
          <h3 className="mt-6 mb-2.5 text-[16px] font-semibold text-[#00C6FF]">Data Minimisation for Children</h3>
          <ul className="list-disc space-y-2 pl-5 text-[15px] text-[#8BA3C4]">
            <li>Location data for child accounts is accessible only to verified, linked guardians.</li>
            <li>Child accounts have no social or public-facing features.</li>
            <li>Audio monitoring for child accounts requires fresh, session-level consent from the guardian for each session.</li>
            <li>We do not display behavioural advertising to child users under any circumstances.</li>
          </ul>
          <Highlight>
            🔒 NISCHINT may be classified as a <strong>Significant Data Fiduciary</strong> under Section 10 of the DPDP Act 2023 given our processing of children&apos;s personal data at scale. We are proactively building the compliance infrastructure required under the Draft DPDP Rules 2026, including Data Protection Impact Assessments and annual audit readiness.
          </Highlight>
        </Section>

        {/* 5 */}
        <Section id="sharing" title="5. Data Sharing & Third Parties">
          <p>We share personal data with third parties only where necessary for service delivery, with appropriate data processing agreements in place.</p>
          <DataTable headers={['Party', 'Purpose', 'Data Shared']} rows={SHARING_TABLE.map(r => [r.party, r.purpose, r.shared])} />
          <p>Our primary database infrastructure is hosted on <strong className="text-[#C8D8E8]">AWS Asia Pacific (Mumbai, ap-south-1)</strong> ✓. Authentication infrastructure runs on AWS Mumbai (ap-south-1). All personal data is stored and processed within India, in alignment with the Digital Personal Data Protection Act 2023. SMS delivery is handled via Twilio and push notifications via Firebase FCM.</p>
        </Section>

        {/* 6 */}
        <Section id="retention" title="6. Data Retention">
          <ul className="list-disc space-y-2 pl-5 text-[15px] text-[#8BA3C4]">
            <li><strong className="text-[#C8D8E8]">Active account data:</strong> Retained for the duration of your account plus 90 days after account deletion.</li>
            <li><strong className="text-[#C8D8E8]">Location history:</strong> 30 days rolling, unless you enable extended history in settings.</li>
            <li><strong className="text-[#C8D8E8]">Incident logs:</strong> Retained for 1 year to support follow-up safety investigations, then permanently deleted.</li>
            <li><strong className="text-[#C8D8E8]">Audio clips (distress events):</strong> Retained for 72 hours unless you explicitly save them to your incident log.</li>
            <li><strong className="text-[#C8D8E8]">Anonymised usage analytics:</strong> Retained indefinitely for product improvement (no personal identifiers).</li>
          </ul>
          <p>Upon account deletion, all personal data is permanently erased within 30 days, except where retention is required by law.</p>
        </Section>

        {/* 7 */}
        <Section id="security" title="7. Security">
          <ul className="list-disc space-y-2 pl-5 text-[15px] text-[#8BA3C4]">
            <li>Data in transit is encrypted using TLS 1.3.</li>
            <li>Data at rest is encrypted using AES-256.</li>
            <li>Location and audio data is processed using end-to-end encryption within the safety session.</li>
            <li>Access to production data is restricted to authorised personnel only, with audit logging.</li>
            <li>We conduct regular security reviews of our infrastructure and APIs.</li>
            <li>In the event of a personal data breach, we will notify affected users and, where required by law, the Data Protection Board of India within the prescribed timeframe.</li>
          </ul>
        </Section>

        {/* 8 */}
        <Section id="your-rights" title="8. Your Rights Under DPDP Act 2023">
          <p>As a Data Principal under the DPDP Act 2023, you have the following rights:</p>
          <div className="my-4 grid gap-4 sm:grid-cols-2" data-testid="privacy-rights-grid">
            {RIGHT_CARDS.map((r) => (
              <div key={r.title} className="rounded-[10px] border border-[#1E3A5F] bg-[#112240] p-5" data-testid={`privacy-right-${r.title.toLowerCase().replace(/[^a-z]+/g, '-').replace(/(^-|-$)/g, '')}`}>
                <div className="mb-2 text-[22px]" aria-hidden>{r.icon}</div>
                <h4 className="text-[14px] font-bold text-white">{r.title}</h4>
                <p className="mt-1.5 text-[13px] text-[#4A6FA5]">{r.body}</p>
              </div>
            ))}
          </div>
          <p>To exercise any of these rights, email <a href="mailto:privacy@nischint.app" className="text-[#00C6FF] hover:underline">privacy@nischint.app</a> with your registered phone number and the right you wish to exercise. We will respond within 72 hours.</p>
        </Section>

        {/* 9 */}
        <Section id="grievance" title="9. Grievance Officer">
          <p>In accordance with the DPDP Act 2023, NISCHINT has designated a Grievance Officer for data privacy matters:</p>
          <ContactBlock
            data-testid="grievance-officer-block"
            heading="Grievance Officer — Data Privacy"
            rows={[
              ['Name',        'Feroz Shaikh'],
              ['Designation', 'Founder & CEO, NISCHINT Technology Private Limited'],
              ['Email',       <a href="mailto:privacy@nischint.app" className="text-[#00C6FF] hover:underline" key="e">privacy@nischint.app</a>],
              ['Address',     'Mumbai, Maharashtra, India'],
              ['Response SLA','72 hours acknowledgement · 30 days resolution'],
            ]}
          />
          <p className="mt-4">If your grievance is not resolved to your satisfaction, you may escalate to the <strong className="text-[#C8D8E8]">Data Protection Board of India</strong> once it becomes operational under the DPDP Act 2023.</p>
        </Section>

        {/* 10 */}
        <Section id="changes" title="10. Changes to This Policy">
          <p>We may update this Privacy Policy from time to time to reflect changes in our practices, the law, or our services. When we make material changes, we will:</p>
          <ul className="list-disc space-y-2 pl-5 text-[15px] text-[#8BA3C4]">
            <li>Update the &quot;Last updated&quot; date at the top of this page.</li>
            <li>Send an in-app notification to all registered users.</li>
            <li>For material changes affecting children&apos;s data, seek fresh parental consent where required.</li>
          </ul>
          <p>Continued use of NISCHINT after the effective date of an updated policy constitutes acceptance of the updated terms.</p>
        </Section>

        {/* 11 */}
        <Section id="contact" title="11. Contact Us">
          <ContactBlock
            data-testid="privacy-contact-block"
            heading="NISCHINT Technology Private Limited"
            rows={[
              ['General',  <a href="mailto:hello@nischint.app" className="text-[#00C6FF] hover:underline" key="g">hello@nischint.app</a>],
              ['Privacy',  <a href="mailto:privacy@nischint.app" className="text-[#00C6FF] hover:underline" key="p">privacy@nischint.app</a>],
              ['Partners', <a href="mailto:partners@nischint.app" className="text-[#00C6FF] hover:underline" key="pt">partners@nischint.app</a>],
              ['Website',  <Link to="/" className="text-[#00C6FF] hover:underline" key="w">nischint.care</Link>],
            ]}
          />
        </Section>
      </div>

      <footer className="border-t border-[#1E3A5F] bg-[#071428] px-6 py-6 text-center text-[13px] text-[#2A4A70]">
        © 2026 NISCHINT Technology Private Limited · Mumbai, India &nbsp;|&nbsp;
        <Link to="/" className="text-[#4A6FA5] hover:text-[#00C6FF]">Home</Link> &nbsp;|&nbsp;
        <Link to="/about" className="text-[#4A6FA5] hover:text-[#00C6FF]">About</Link> &nbsp;|&nbsp;
        <Link to="/privacy-policy" className="text-[#4A6FA5] hover:text-[#00C6FF]">Privacy Policy</Link> &nbsp;|&nbsp;
        <a href="mailto:privacy@nischint.app" className="text-[#4A6FA5] hover:text-[#00C6FF]">privacy@nischint.app</a>
      </footer>
    </div>
  );
}

// ── Local primitives ────────────────────────────────────────────

const Section = ({ id, title, children }) => (
  <section id={id} className="mb-12 scroll-mt-24" data-testid={`privacy-section-${id}`}>
    <h2 className="mb-4 border-b border-[#1E3A5F] pb-2.5 text-[22px] font-bold text-white">{title}</h2>
    <div className="space-y-3.5 text-[15px] text-[#8BA3C4]">{children}</div>
  </section>
);

const DataTable = ({ headers, rows }) => (
  <div className="my-4 overflow-x-auto">
    <table className="w-full border-collapse text-[14px]">
      <thead>
        <tr>
          {headers.map((h) => (
            <th key={h} className="border-b border-[#1A2F50] bg-[#1E3A5F] px-3.5 py-2.5 text-left text-[13px] font-semibold uppercase tracking-wide text-[#00C6FF]">{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((cells, i) => (
          <tr key={i} className="hover:bg-[#1E3A5F]/30">
            {cells.map((c, j) => (
              <td key={j} className="border-b border-[#1A2F50] px-3.5 py-2.5 align-top text-[#8BA3C4]">{c}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

const Highlight = ({ children }) => (
  <div className="my-4 rounded-[10px] border border-yellow-400/20 bg-yellow-400/5 px-5 py-4">
    <p className="text-[14px] text-[#C8B45A]">{children}</p>
  </div>
);

const ContactBlock = ({ heading, rows, ...rest }) => (
  <div className="rounded-xl border border-[#1E3A5F] bg-[#112240] p-7" {...rest}>
    <h3 className="mb-4 text-[16px] font-bold text-white">{heading}</h3>
    {rows.map(([label, value]) => (
      <div key={label} className="mb-3.5 flex items-start gap-3 last:mb-0">
        <div className="min-w-[100px] pt-0.5 text-[13px] font-semibold uppercase tracking-wide text-[#4A6FA5]">{label}</div>
        <div className="text-[14px] text-[#8BA3C4]">{value}</div>
      </div>
    ))}
  </div>
);
