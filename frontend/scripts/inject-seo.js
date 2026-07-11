/**
 * inject-seo.js — NISCHINT (PRODUCTION SEO ENGINE)
 * Generates static .html SEO pages with REAL H1 (not just noscript)
 */

const fs   = require('fs');
const path = require('path');

const BUILD_DIR  = path.resolve(__dirname, '..', 'build');
const INDEX_PATH = path.join(BUILD_DIR, 'index.html');
const BASE_URL   = 'https://nischint.care';

// ── GEO CONFIG ────────────────────────────────────────────────────

const CITIES = [
  { slug: 'mumbai', label: 'Mumbai' },
  { slug: 'delhi', label: 'Delhi' },
  { slug: 'bangalore', label: 'Bangalore' },
  { slug: 'pune', label: 'Pune' },
  { slug: 'hyderabad', label: 'Hyderabad' },
];

const GEO_TEMPLATES = [
  {
    slug: 'kids-safety-app',
    persona: 'children',
    title: (city) => `Best Kids Safety App in ${city} | NISCHINT`,
    description: (city) => `Protect your child in ${city} with AI-powered GPS tracking, distress alerts, and real-time monitoring.`,
  },
  {
    slug: 'best-women-safety-app',
    persona: 'women',
    title: (city) => `Best Women Safety App in ${city} | NISCHINT`,
    description: (city) => `Rated #1 women safety app in ${city}. AI distress detection, auto-escalation, and real-time GPS tracking.`,
  }
];

// ── CORE INJECTION FUNCTION ───────────────────────────────────────

function injectSEO(html, config) {
  let out = html;

  // 🔹 Replace SEO meta
  out = out
    .replace(/<title>.*?<\/title>/, `<title>${config.title}</title>`)
    .replace(/<meta name="description".*?>/, `<meta name="description" content="${config.description}">`)
    .replace(/<link rel="canonical".*?>/, `<link rel="canonical" href="${config.canonical}">`)
    .replace(/<meta property="og:title".*?>/, `<meta property="og:title" content="${config.title}">`)
    .replace(/<meta property="og:description".*?>/, `<meta property="og:description" content="${config.description}">`)
    .replace(/<meta name="twitter:title".*?>/, `<meta name="twitter:title" content="${config.title}">`)
    .replace(/<meta name="twitter:description".*?>/, `<meta name="twitter:description" content="${config.description}">`)
    .replace(/<meta name="geo.placename".*?>/, `<meta name="geo.placename" content="${config.city}">`);

  // 🔥 Inject REAL visible H1 (CRITICAL FIX)
  out = out.replace(
    '<div id="root"></div>',
    `
    <div style="max-width:800px;margin:40px auto;padding:0 20px;font-family:system-ui,sans-serif;color:#e2e8f0">
      <h1 style="font-size:2rem;margin-bottom:16px;color:#fff;">
        ${config.title}
      </h1>
      <p style="line-height:1.6;margin-bottom:20px;">
        ${config.description}
      </p>
    </div>
    <div id="root"></div>
    `
  );

  // 🔹 Keep noscript fallback
  if (!out.includes('<noscript>')) {
    out = out.replace(
      '<body>',
      `<body>
<noscript>
<h1>${config.title}</h1>
<p>${config.description}</p>
</noscript>`
    );
  }

  return out;
}

// ── EXECUTION ─────────────────────────────────────────────────────

if (!fs.existsSync(INDEX_PATH)) {
  console.error('❌ build/index.html not found');
  process.exit(1);
}

const indexHtml = fs.readFileSync(INDEX_PATH, 'utf-8');

// 🧹 Cleanup old files
fs.readdirSync(BUILD_DIR).forEach(file => {
  const fullPath = path.join(BUILD_DIR, file);

  if (file.endsWith('.html') && file !== 'index.html') {
    fs.unlinkSync(fullPath);
  }
});

// ── GENERATE GEO HTML FILES ───────────────────────────────────────

for (const city of CITIES) {
  for (const template of GEO_TEMPLATES) {

    const slug = `${template.slug}-${city.slug}`;

    const config = {
      title: template.title(city.label),
      description: template.description(city.label),
      canonical: `${BASE_URL}/${slug}.html`,
      city: city.label,
    };

    const filePath = path.join(BUILD_DIR, `${slug}.html`);

    fs.writeFileSync(filePath, injectSEO(indexHtml, config));

    console.log(`✅ Generated: ${slug}.html`);
  }
}

console.log(`[inject-seo] Done. ${count} SEO pages generated.`);

// ── GEO City Pages ──────────────────────────────────────────────────

const GEO_PAGES = [
  { slug: "women-safety-app-mumbai", city: "Mumbai", state: "Maharashtra", type: "women", variant: "default" },
  { slug: "best-women-safety-app-mumbai", city: "Mumbai", state: "Maharashtra", type: "women", variant: "best" },
  { slug: "kids-safety-app-mumbai", city: "Mumbai", state: "Maharashtra", type: "kids", variant: "default" },
  { slug: "best-kids-safety-app-mumbai", city: "Mumbai", state: "Maharashtra", type: "kids", variant: "best" },
  { slug: "family-safety-app-mumbai", city: "Mumbai", state: "Maharashtra", type: "family", variant: "default" },
  { slug: "best-family-safety-app-mumbai", city: "Mumbai", state: "Maharashtra", type: "family", variant: "best" },
  { slug: "personal-safety-app-mumbai", city: "Mumbai", state: "Maharashtra", type: "women", variant: "default" },
  { slug: "best-personal-safety-app-mumbai", city: "Mumbai", state: "Maharashtra", type: "women", variant: "best" },
  { slug: "women-safety-app-delhi", city: "Delhi", state: "Delhi", type: "women", variant: "default" },
  { slug: "best-women-safety-app-delhi", city: "Delhi", state: "Delhi", type: "women", variant: "best" },
  { slug: "kids-safety-app-delhi", city: "Delhi", state: "Delhi", type: "kids", variant: "default" },
  { slug: "best-kids-safety-app-delhi", city: "Delhi", state: "Delhi", type: "kids", variant: "best" },
  { slug: "family-safety-app-delhi", city: "Delhi", state: "Delhi", type: "family", variant: "default" },
  { slug: "best-family-safety-app-delhi", city: "Delhi", state: "Delhi", type: "family", variant: "best" },
  { slug: "personal-safety-app-delhi", city: "Delhi", state: "Delhi", type: "women", variant: "default" },
  { slug: "best-personal-safety-app-delhi", city: "Delhi", state: "Delhi", type: "women", variant: "best" },
  { slug: "women-safety-app-bangalore", city: "Bangalore", state: "Karnataka", type: "women", variant: "default" },
  { slug: "best-women-safety-app-bangalore", city: "Bangalore", state: "Karnataka", type: "women", variant: "best" },
  { slug: "kids-safety-app-bangalore", city: "Bangalore", state: "Karnataka", type: "kids", variant: "default" },
  { slug: "best-kids-safety-app-bangalore", city: "Bangalore", state: "Karnataka", type: "kids", variant: "best" },
  { slug: "family-safety-app-bangalore", city: "Bangalore", state: "Karnataka", type: "family", variant: "default" },
  { slug: "best-family-safety-app-bangalore", city: "Bangalore", state: "Karnataka", type: "family", variant: "best" },
  { slug: "personal-safety-app-bangalore", city: "Bangalore", state: "Karnataka", type: "women", variant: "default" },
  { slug: "best-personal-safety-app-bangalore", city: "Bangalore", state: "Karnataka", type: "women", variant: "best" },
  { slug: "women-safety-app-chennai", city: "Chennai", state: "Tamil Nadu", type: "women", variant: "default" },
  { slug: "best-women-safety-app-chennai", city: "Chennai", state: "Tamil Nadu", type: "women", variant: "best" },
  { slug: "kids-safety-app-chennai", city: "Chennai", state: "Tamil Nadu", type: "kids", variant: "default" },
  { slug: "best-kids-safety-app-chennai", city: "Chennai", state: "Tamil Nadu", type: "kids", variant: "best" },
  { slug: "family-safety-app-chennai", city: "Chennai", state: "Tamil Nadu", type: "family", variant: "default" },
  { slug: "best-family-safety-app-chennai", city: "Chennai", state: "Tamil Nadu", type: "family", variant: "best" },
  { slug: "personal-safety-app-chennai", city: "Chennai", state: "Tamil Nadu", type: "women", variant: "default" },
  { slug: "best-personal-safety-app-chennai", city: "Chennai", state: "Tamil Nadu", type: "women", variant: "best" },
  { slug: "women-safety-app-hyderabad", city: "Hyderabad", state: "Telangana", type: "women", variant: "default" },
  { slug: "best-women-safety-app-hyderabad", city: "Hyderabad", state: "Telangana", type: "women", variant: "best" },
  { slug: "kids-safety-app-hyderabad", city: "Hyderabad", state: "Telangana", type: "kids", variant: "default" },
  { slug: "best-kids-safety-app-hyderabad", city: "Hyderabad", state: "Telangana", type: "kids", variant: "best" },
  { slug: "family-safety-app-hyderabad", city: "Hyderabad", state: "Telangana", type: "family", variant: "default" },
  { slug: "best-family-safety-app-hyderabad", city: "Hyderabad", state: "Telangana", type: "family", variant: "best" },
  { slug: "personal-safety-app-hyderabad", city: "Hyderabad", state: "Telangana", type: "women", variant: "default" },
  { slug: "best-personal-safety-app-hyderabad", city: "Hyderabad", state: "Telangana", type: "women", variant: "best" },
  { slug: "women-safety-app-kolkata", city: "Kolkata", state: "West Bengal", type: "women", variant: "default" },
  { slug: "best-women-safety-app-kolkata", city: "Kolkata", state: "West Bengal", type: "women", variant: "best" },
  { slug: "kids-safety-app-kolkata", city: "Kolkata", state: "West Bengal", type: "kids", variant: "default" },
  { slug: "best-kids-safety-app-kolkata", city: "Kolkata", state: "West Bengal", type: "kids", variant: "best" },
  { slug: "family-safety-app-kolkata", city: "Kolkata", state: "West Bengal", type: "family", variant: "default" },
  { slug: "best-family-safety-app-kolkata", city: "Kolkata", state: "West Bengal", type: "family", variant: "best" },
  { slug: "personal-safety-app-kolkata", city: "Kolkata", state: "West Bengal", type: "women", variant: "default" },
  { slug: "best-personal-safety-app-kolkata", city: "Kolkata", state: "West Bengal", type: "women", variant: "best" },
  { slug: "women-safety-app-pune", city: "Pune", state: "Maharashtra", type: "women", variant: "default" },
  { slug: "best-women-safety-app-pune", city: "Pune", state: "Maharashtra", type: "women", variant: "best" },
  { slug: "kids-safety-app-pune", city: "Pune", state: "Maharashtra", type: "kids", variant: "default" },
  { slug: "best-kids-safety-app-pune", city: "Pune", state: "Maharashtra", type: "kids", variant: "best" },
  { slug: "family-safety-app-pune", city: "Pune", state: "Maharashtra", type: "family", variant: "default" },
  { slug: "best-family-safety-app-pune", city: "Pune", state: "Maharashtra", type: "family", variant: "best" },
  { slug: "personal-safety-app-pune", city: "Pune", state: "Maharashtra", type: "women", variant: "default" },
  { slug: "best-personal-safety-app-pune", city: "Pune", state: "Maharashtra", type: "women", variant: "best" },
  { slug: "women-safety-app-ahmedabad", city: "Ahmedabad", state: "Gujarat", type: "women", variant: "default" },
  { slug: "best-women-safety-app-ahmedabad", city: "Ahmedabad", state: "Gujarat", type: "women", variant: "best" },
  { slug: "kids-safety-app-ahmedabad", city: "Ahmedabad", state: "Gujarat", type: "kids", variant: "default" },
  { slug: "best-kids-safety-app-ahmedabad", city: "Ahmedabad", state: "Gujarat", type: "kids", variant: "best" },
  { slug: "family-safety-app-ahmedabad", city: "Ahmedabad", state: "Gujarat", type: "family", variant: "default" },
  { slug: "best-family-safety-app-ahmedabad", city: "Ahmedabad", state: "Gujarat", type: "family", variant: "best" },
  { slug: "personal-safety-app-ahmedabad", city: "Ahmedabad", state: "Gujarat", type: "women", variant: "default" },
  { slug: "best-personal-safety-app-ahmedabad", city: "Ahmedabad", state: "Gujarat", type: "women", variant: "best" },
  { slug: "women-safety-app-jaipur", city: "Jaipur", state: "Rajasthan", type: "women", variant: "default" },
  { slug: "best-women-safety-app-jaipur", city: "Jaipur", state: "Rajasthan", type: "women", variant: "best" },
  { slug: "kids-safety-app-jaipur", city: "Jaipur", state: "Rajasthan", type: "kids", variant: "default" },
  { slug: "best-kids-safety-app-jaipur", city: "Jaipur", state: "Rajasthan", type: "kids", variant: "best" },
  { slug: "family-safety-app-jaipur", city: "Jaipur", state: "Rajasthan", type: "family", variant: "default" },
  { slug: "best-family-safety-app-jaipur", city: "Jaipur", state: "Rajasthan", type: "family", variant: "best" },
  { slug: "personal-safety-app-jaipur", city: "Jaipur", state: "Rajasthan", type: "women", variant: "default" },
  { slug: "best-personal-safety-app-jaipur", city: "Jaipur", state: "Rajasthan", type: "women", variant: "best" },
  { slug: "women-safety-app-lucknow", city: "Lucknow", state: "Uttar Pradesh", type: "women", variant: "default" },
  { slug: "best-women-safety-app-lucknow", city: "Lucknow", state: "Uttar Pradesh", type: "women", variant: "best" },
  { slug: "kids-safety-app-lucknow", city: "Lucknow", state: "Uttar Pradesh", type: "kids", variant: "default" },
  { slug: "best-kids-safety-app-lucknow", city: "Lucknow", state: "Uttar Pradesh", type: "kids", variant: "best" },
  { slug: "family-safety-app-lucknow", city: "Lucknow", state: "Uttar Pradesh", type: "family", variant: "default" },
  { slug: "best-family-safety-app-lucknow", city: "Lucknow", state: "Uttar Pradesh", type: "family", variant: "best" },
  { slug: "personal-safety-app-lucknow", city: "Lucknow", state: "Uttar Pradesh", type: "women", variant: "default" },
  { slug: "best-personal-safety-app-lucknow", city: "Lucknow", state: "Uttar Pradesh", type: "women", variant: "best" },
  { slug: "women-safety-app-chandigarh", city: "Chandigarh", state: "Chandigarh", type: "women", variant: "default" },
  { slug: "best-women-safety-app-chandigarh", city: "Chandigarh", state: "Chandigarh", type: "women", variant: "best" },
  { slug: "kids-safety-app-chandigarh", city: "Chandigarh", state: "Chandigarh", type: "kids", variant: "default" },
  { slug: "best-kids-safety-app-chandigarh", city: "Chandigarh", state: "Chandigarh", type: "kids", variant: "best" },
  { slug: "family-safety-app-chandigarh", city: "Chandigarh", state: "Chandigarh", type: "family", variant: "default" },
  { slug: "best-family-safety-app-chandigarh", city: "Chandigarh", state: "Chandigarh", type: "family", variant: "best" },
  { slug: "personal-safety-app-chandigarh", city: "Chandigarh", state: "Chandigarh", type: "women", variant: "default" },
  { slug: "best-personal-safety-app-chandigarh", city: "Chandigarh", state: "Chandigarh", type: "women", variant: "best" },
  { slug: "women-safety-app-indore", city: "Indore", state: "Madhya Pradesh", type: "women", variant: "default" },
  { slug: "best-women-safety-app-indore", city: "Indore", state: "Madhya Pradesh", type: "women", variant: "best" },
  { slug: "kids-safety-app-indore", city: "Indore", state: "Madhya Pradesh", type: "kids", variant: "default" },
  { slug: "best-kids-safety-app-indore", city: "Indore", state: "Madhya Pradesh", type: "kids", variant: "best" },
  { slug: "family-safety-app-indore", city: "Indore", state: "Madhya Pradesh", type: "family", variant: "default" },
  { slug: "best-family-safety-app-indore", city: "Indore", state: "Madhya Pradesh", type: "family", variant: "best" },
  { slug: "personal-safety-app-indore", city: "Indore", state: "Madhya Pradesh", type: "women", variant: "default" },
  { slug: "best-personal-safety-app-indore", city: "Indore", state: "Madhya Pradesh", type: "women", variant: "best" },
  { slug: "women-safety-app-nagpur", city: "Nagpur", state: "Maharashtra", type: "women", variant: "default" },
  { slug: "best-women-safety-app-nagpur", city: "Nagpur", state: "Maharashtra", type: "women", variant: "best" },
  { slug: "kids-safety-app-nagpur", city: "Nagpur", state: "Maharashtra", type: "kids", variant: "default" },
  { slug: "best-kids-safety-app-nagpur", city: "Nagpur", state: "Maharashtra", type: "kids", variant: "best" },
  { slug: "family-safety-app-nagpur", city: "Nagpur", state: "Maharashtra", type: "family", variant: "default" },
  { slug: "best-family-safety-app-nagpur", city: "Nagpur", state: "Maharashtra", type: "family", variant: "best" },
  { slug: "personal-safety-app-nagpur", city: "Nagpur", state: "Maharashtra", type: "women", variant: "default" },
  { slug: "best-personal-safety-app-nagpur", city: "Nagpur", state: "Maharashtra", type: "women", variant: "best" },
  { slug: "women-safety-app-surat", city: "Surat", state: "Gujarat", type: "women", variant: "default" },
  { slug: "best-women-safety-app-surat", city: "Surat", state: "Gujarat", type: "women", variant: "best" },
  { slug: "kids-safety-app-surat", city: "Surat", state: "Gujarat", type: "kids", variant: "default" },
  { slug: "best-kids-safety-app-surat", city: "Surat", state: "Gujarat", type: "kids", variant: "best" },
  { slug: "family-safety-app-surat", city: "Surat", state: "Gujarat", type: "family", variant: "default" },
  { slug: "best-family-safety-app-surat", city: "Surat", state: "Gujarat", type: "family", variant: "best" },
  { slug: "personal-safety-app-surat", city: "Surat", state: "Gujarat", type: "women", variant: "default" },
  { slug: "best-personal-safety-app-surat", city: "Surat", state: "Gujarat", type: "women", variant: "best" },
  { slug: "women-safety-app-coimbatore", city: "Coimbatore", state: "Tamil Nadu", type: "women", variant: "default" },
  { slug: "best-women-safety-app-coimbatore", city: "Coimbatore", state: "Tamil Nadu", type: "women", variant: "best" },
  { slug: "kids-safety-app-coimbatore", city: "Coimbatore", state: "Tamil Nadu", type: "kids", variant: "default" },
  { slug: "best-kids-safety-app-coimbatore", city: "Coimbatore", state: "Tamil Nadu", type: "kids", variant: "best" },
  { slug: "family-safety-app-coimbatore", city: "Coimbatore", state: "Tamil Nadu", type: "family", variant: "default" },
  { slug: "best-family-safety-app-coimbatore", city: "Coimbatore", state: "Tamil Nadu", type: "family", variant: "best" },
  { slug: "personal-safety-app-coimbatore", city: "Coimbatore", state: "Tamil Nadu", type: "women", variant: "default" },
  { slug: "best-personal-safety-app-coimbatore", city: "Coimbatore", state: "Tamil Nadu", type: "women", variant: "best" },
  { slug: "women-safety-app-kochi", city: "Kochi", state: "Kerala", type: "women", variant: "default" },
  { slug: "best-women-safety-app-kochi", city: "Kochi", state: "Kerala", type: "women", variant: "best" },
  { slug: "kids-safety-app-kochi", city: "Kochi", state: "Kerala", type: "kids", variant: "default" },
  { slug: "best-kids-safety-app-kochi", city: "Kochi", state: "Kerala", type: "kids", variant: "best" },
  { slug: "family-safety-app-kochi", city: "Kochi", state: "Kerala", type: "family", variant: "default" },
  { slug: "best-family-safety-app-kochi", city: "Kochi", state: "Kerala", type: "family", variant: "best" },
  { slug: "personal-safety-app-kochi", city: "Kochi", state: "Kerala", type: "women", variant: "default" },
  { slug: "best-personal-safety-app-kochi", city: "Kochi", state: "Kerala", type: "women", variant: "best" },
  { slug: "women-safety-app-thiruvananthapuram", city: "Thiruvananthapuram", state: "Kerala", type: "women", variant: "default" },
  { slug: "best-women-safety-app-thiruvananthapuram", city: "Thiruvananthapuram", state: "Kerala", type: "women", variant: "best" },
  { slug: "kids-safety-app-thiruvananthapuram", city: "Thiruvananthapuram", state: "Kerala", type: "kids", variant: "default" },
  { slug: "best-kids-safety-app-thiruvananthapuram", city: "Thiruvananthapuram", state: "Kerala", type: "kids", variant: "best" },
  { slug: "family-safety-app-thiruvananthapuram", city: "Thiruvananthapuram", state: "Kerala", type: "family", variant: "default" },
  { slug: "best-family-safety-app-thiruvananthapuram", city: "Thiruvananthapuram", state: "Kerala", type: "family", variant: "best" },
  { slug: "personal-safety-app-thiruvananthapuram", city: "Thiruvananthapuram", state: "Kerala", type: "women", variant: "default" },
  { slug: "best-personal-safety-app-thiruvananthapuram", city: "Thiruvananthapuram", state: "Kerala", type: "women", variant: "best" },
  { slug: "women-safety-app-visakhapatnam", city: "Visakhapatnam", state: "Andhra Pradesh", type: "women", variant: "default" },
  { slug: "best-women-safety-app-visakhapatnam", city: "Visakhapatnam", state: "Andhra Pradesh", type: "women", variant: "best" },
  { slug: "kids-safety-app-visakhapatnam", city: "Visakhapatnam", state: "Andhra Pradesh", type: "kids", variant: "default" },
  { slug: "best-kids-safety-app-visakhapatnam", city: "Visakhapatnam", state: "Andhra Pradesh", type: "kids", variant: "best" },
  { slug: "family-safety-app-visakhapatnam", city: "Visakhapatnam", state: "Andhra Pradesh", type: "family", variant: "default" },
  { slug: "best-family-safety-app-visakhapatnam", city: "Visakhapatnam", state: "Andhra Pradesh", type: "family", variant: "best" },
  { slug: "personal-safety-app-visakhapatnam", city: "Visakhapatnam", state: "Andhra Pradesh", type: "women", variant: "default" },
  { slug: "best-personal-safety-app-visakhapatnam", city: "Visakhapatnam", state: "Andhra Pradesh", type: "women", variant: "best" },
  { slug: "women-safety-app-bhopal", city: "Bhopal", state: "Madhya Pradesh", type: "women", variant: "default" },
  { slug: "best-women-safety-app-bhopal", city: "Bhopal", state: "Madhya Pradesh", type: "women", variant: "best" },
  { slug: "kids-safety-app-bhopal", city: "Bhopal", state: "Madhya Pradesh", type: "kids", variant: "default" },
  { slug: "best-kids-safety-app-bhopal", city: "Bhopal", state: "Madhya Pradesh", type: "kids", variant: "best" },
  { slug: "family-safety-app-bhopal", city: "Bhopal", state: "Madhya Pradesh", type: "family", variant: "default" },
  { slug: "best-family-safety-app-bhopal", city: "Bhopal", state: "Madhya Pradesh", type: "family", variant: "best" },
  { slug: "personal-safety-app-bhopal", city: "Bhopal", state: "Madhya Pradesh", type: "women", variant: "default" },
  { slug: "best-personal-safety-app-bhopal", city: "Bhopal", state: "Madhya Pradesh", type: "women", variant: "best" },
  { slug: "women-safety-app-patna", city: "Patna", state: "Bihar", type: "women", variant: "default" },
  { slug: "best-women-safety-app-patna", city: "Patna", state: "Bihar", type: "women", variant: "best" },
  { slug: "kids-safety-app-patna", city: "Patna", state: "Bihar", type: "kids", variant: "default" },
  { slug: "best-kids-safety-app-patna", city: "Patna", state: "Bihar", type: "kids", variant: "best" },
  { slug: "family-safety-app-patna", city: "Patna", state: "Bihar", type: "family", variant: "default" },
  { slug: "best-family-safety-app-patna", city: "Patna", state: "Bihar", type: "family", variant: "best" },
  { slug: "personal-safety-app-patna", city: "Patna", state: "Bihar", type: "women", variant: "default" },
  { slug: "best-personal-safety-app-patna", city: "Patna", state: "Bihar", type: "women", variant: "best" },
  { slug: "women-safety-app-guwahati", city: "Guwahati", state: "Assam", type: "women", variant: "default" },
  { slug: "best-women-safety-app-guwahati", city: "Guwahati", state: "Assam", type: "women", variant: "best" },
  { slug: "kids-safety-app-guwahati", city: "Guwahati", state: "Assam", type: "kids", variant: "default" },
  { slug: "best-kids-safety-app-guwahati", city: "Guwahati", state: "Assam", type: "kids", variant: "best" },
  { slug: "family-safety-app-guwahati", city: "Guwahati", state: "Assam", type: "family", variant: "default" },
  { slug: "best-family-safety-app-guwahati", city: "Guwahati", state: "Assam", type: "family", variant: "best" },
  { slug: "personal-safety-app-guwahati", city: "Guwahati", state: "Assam", type: "women", variant: "default" },
  { slug: "best-personal-safety-app-guwahati", city: "Guwahati", state: "Assam", type: "women", variant: "best" },
  { slug: "women-safety-app-dehradun", city: "Dehradun", state: "Uttarakhand", type: "women", variant: "default" },
  { slug: "best-women-safety-app-dehradun", city: "Dehradun", state: "Uttarakhand", type: "women", variant: "best" },
  { slug: "kids-safety-app-dehradun", city: "Dehradun", state: "Uttarakhand", type: "kids", variant: "default" },
  { slug: "best-kids-safety-app-dehradun", city: "Dehradun", state: "Uttarakhand", type: "kids", variant: "best" },
  { slug: "family-safety-app-dehradun", city: "Dehradun", state: "Uttarakhand", type: "family", variant: "default" },
  { slug: "best-family-safety-app-dehradun", city: "Dehradun", state: "Uttarakhand", type: "family", variant: "best" },
  { slug: "personal-safety-app-dehradun", city: "Dehradun", state: "Uttarakhand", type: "women", variant: "default" },
  { slug: "best-personal-safety-app-dehradun", city: "Dehradun", state: "Uttarakhand", type: "women", variant: "best" },
  { slug: "women-safety-app-ranchi", city: "Ranchi", state: "Jharkhand", type: "women", variant: "default" },
  { slug: "best-women-safety-app-ranchi", city: "Ranchi", state: "Jharkhand", type: "women", variant: "best" },
  { slug: "kids-safety-app-ranchi", city: "Ranchi", state: "Jharkhand", type: "kids", variant: "default" },
  { slug: "best-kids-safety-app-ranchi", city: "Ranchi", state: "Jharkhand", type: "kids", variant: "best" },
  { slug: "family-safety-app-ranchi", city: "Ranchi", state: "Jharkhand", type: "family", variant: "default" },
  { slug: "best-family-safety-app-ranchi", city: "Ranchi", state: "Jharkhand", type: "family", variant: "best" },
  { slug: "personal-safety-app-ranchi", city: "Ranchi", state: "Jharkhand", type: "women", variant: "default" },
  { slug: "best-personal-safety-app-ranchi", city: "Ranchi", state: "Jharkhand", type: "women", variant: "best" },
  { slug: "women-safety-app-bhubaneswar", city: "Bhubaneswar", state: "Odisha", type: "women", variant: "default" },
  { slug: "best-women-safety-app-bhubaneswar", city: "Bhubaneswar", state: "Odisha", type: "women", variant: "best" },
  { slug: "kids-safety-app-bhubaneswar", city: "Bhubaneswar", state: "Odisha", type: "kids", variant: "default" },
  { slug: "best-kids-safety-app-bhubaneswar", city: "Bhubaneswar", state: "Odisha", type: "kids", variant: "best" },
  { slug: "family-safety-app-bhubaneswar", city: "Bhubaneswar", state: "Odisha", type: "family", variant: "default" },
  { slug: "best-family-safety-app-bhubaneswar", city: "Bhubaneswar", state: "Odisha", type: "family", variant: "best" },
  { slug: "personal-safety-app-bhubaneswar", city: "Bhubaneswar", state: "Odisha", type: "women", variant: "default" },
  { slug: "best-personal-safety-app-bhubaneswar", city: "Bhubaneswar", state: "Odisha", type: "women", variant: "best" },
];

function generateGeoSEO(page) {
  const { city, type, slug, variant } = page;
  const v = variant || 'default';

  const titles = {
    default: {
      women: `Women Safety App in ${city} | NISCHINT AI Protection`,
      kids: `Kids Safety App in ${city} | NISCHINT Child Safety`,
      family: `Family Safety App in ${city} | NISCHINT Family Protection`,
    },
    best: {
      women: `Best Women Safety App in ${city} | NISCHINT`,
      kids: `Best Kids Safety App in ${city} | NISCHINT`,
      family: `Best Family Safety App in ${city} | NISCHINT`,
    },
    personal: {
      women: `Personal Safety App in ${city} | NISCHINT`,
      kids: `Personal Safety App in ${city} for Kids | NISCHINT`,
      family: `Personal Safety App in ${city} for Families | NISCHINT`,
    },
  };

  const descriptions = {
    default: {
      women: `AI-powered women safety app in ${city} with GPS tracking, voice distress detection, and instant alerts.`,
      kids: `Track and protect your child in ${city} with GPS, geofencing, and AI alerts.`,
      family: `Protect your family in ${city} with real-time tracking and emergency alerts.`,
    },
    best: {
      women: `Rated #1 women safety app in ${city}. NISCHINT outperforms traditional safety apps with AI distress detection, auto-escalation, and real-time GPS.`,
      kids: `The best child safety app in ${city}. GPS tracking, geofencing, and AI-powered alerts trusted by parents.`,
      family: `Top-rated family safety app in ${city}. Complete protection with live tracking and coordinated guardian response.`,
    },
    personal: {
      women: `Personal safety app for individuals in ${city}. AI-powered protection with voice detection, live tracking, and emergency response.`,
      kids: `Personal safety solution for children in ${city}. Real-time monitoring, smart alerts, and parent notification.`,
      family: `Personal safety platform for families in ${city}. Unified protection with live tracking and automated alerts.`,
    },
  };

  return {
    title: (titles[v] || titles.default)[type],
    description: (descriptions[v] || descriptions.default)[type],
    canonical: `${BASE_URL}/${slug}`,
    city,
  };
}

function injectGeoSEO(html, seo) {
  let result = html;

  // Replace <title>
  result = result.replace(/<title>[^<]*<\/title>/, `<title>${escapeHtml(seo.title)}</title>`);

  // Replace <meta name="description">
  result = result.replace(
    /<meta name="description" content="[^"]*"/,
    `<meta name="description" content="${escapeHtml(seo.description)}"`
  );

  // Replace <link rel="canonical">
  result = result.replace(
    /<link rel="canonical" href="[^"]*"/,
    `<link rel="canonical" href="${seo.canonical}"`
  );

  // Replace hreflang tags
  result = result.replace(
    /<link rel="alternate" hreflang="en-IN" href="[^"]*"/,
    `<link rel="alternate" hreflang="en-IN" href="${seo.canonical}"`
  );
  result = result.replace(
    /<link rel="alternate" hreflang="x-default" href="[^"]*"/,
    `<link rel="alternate" hreflang="x-default" href="${seo.canonical}"`
  );

  // Replace og:title, og:description, og:url
  result = result.replace(
    /<meta property="og:title" content="[^"]*"/,
    `<meta property="og:title" content="${escapeHtml(seo.title)}"`
  );
  result = result.replace(
    /<meta property="og:description" content="[^"]*"/,
    `<meta property="og:description" content="${escapeHtml(seo.description)}"`
  );
  result = result.replace(
    /<meta property="og:url" content="[^"]*"/,
    `<meta property="og:url" content="${seo.canonical}"`
  );

  // Replace twitter:title, twitter:description
  result = result.replace(
    /<meta name="twitter:title" content="[^"]*"/,
    `<meta name="twitter:title" content="${escapeHtml(seo.title)}"`
  );
  result = result.replace(
    /<meta name="twitter:description" content="[^"]*"/,
    `<meta name="twitter:description" content="${escapeHtml(seo.description)}"`
  );

  // Replace geo.placename with city-specific value
  result = result.replace(
    /<meta name="geo.placename" content="[^"]*"/,
    `<meta name="geo.placename" content="${seo.city}"`
  );

  return result;
}

// ── City Content Engine ──────────────────────────────────────────────

const SAFETY_INSIGHTS = {
  Mumbai: 'High commuting density, late-night travel risks, crowded public transport.',
  Delhi: 'Higher reported safety concerns, need for real-time tracking and alert systems.',
  Bangalore: 'IT hub with late working hours, frequent cab-based travel.',
  Chennai: 'Urban spread with moderate commuting risks.',
  Hyderabad: 'Growing metro with increasing late-hour movement.',
  Pune: 'Student-heavy city with frequent night travel.',
  Kolkata: 'Dense public areas with varying safety patterns.',
  Ahmedabad: 'Rapidly urbanizing with expanding commute distances and emerging safety needs.',
  Jaipur: 'Tourist-heavy areas mixed with dense local traffic and crowded bazaars.',
  Lucknow: 'Growing urban sprawl with increasing late-evening commuting patterns.',
};

const TYPE_LABELS = { women: 'Women', kids: 'Children', family: 'Families' };

const TYPE_FEATURES = {
  women: [
    'Voice distress detection that identifies panic or threat in real time',
    'Silent SOS that alerts guardians without drawing attention',
    'Live GPS sharing during cab rides and late-night commutes',
    'Automated escalation to emergency contacts within seconds',
  ],
  kids: [
    'Real-time GPS tracking for school commute and outdoor activities',
    'Geofencing alerts when your child leaves designated safe zones',
    'AI-powered anomaly detection for unusual movement patterns',
    'Instant parent notification with one-tap emergency response',
  ],
  family: [
    'Live location sharing across all family members',
    'Emergency SOS with coordinated multi-guardian response',
    'Elderly monitoring with fall detection and inactivity alerts',
    'Daily safety tracking with automated check-in reminders',
  ],
};

function generateCityContent(city, type, variant) {
  const insight = SAFETY_INSIGHTS[city] || 'Urban safety challenges requiring real-time monitoring.';
  const label = TYPE_LABELS[type] || 'People';
  const features = TYPE_FEATURES[type] || [];
  const v = variant || 'default';

  if (v === 'best') {
    return `<section style="max-width:800px;margin:40px auto;padding:0 20px;font-family:system-ui,sans-serif;color:#cbd5e1"><h2 style="color:#fff;font-size:1.5em;margin-bottom:12px">Why NISCHINT is the Best Safety App in ${city}</h2><p style="line-height:1.7;margin-bottom:24px">${insight} Compared to other safety apps available in ${city}, NISCHINT is the only platform that combines AI voice distress detection, automated escalation, and real-time guardian alerts in a single app.</p><h2 style="color:#fff;font-size:1.5em;margin-bottom:12px">NISCHINT vs Other Safety Apps in ${city}</h2><table style="width:100%;border-collapse:collapse;margin-bottom:24px"><tr style="border-bottom:1px solid #334155"><th style="text-align:left;padding:10px;color:#fff">Feature</th><th style="text-align:center;padding:10px;color:#94a3b8">Others</th><th style="text-align:center;padding:10px;color:#2dd4bf">NISCHINT</th></tr><tr style="border-bottom:1px solid #1e293b"><td style="padding:10px">GPS Tracking</td><td style="text-align:center;padding:10px">Yes</td><td style="text-align:center;padding:10px;color:#2dd4bf">Yes</td></tr><tr style="border-bottom:1px solid #1e293b"><td style="padding:10px">AI Distress Detection</td><td style="text-align:center;padding:10px;color:#ef4444">No</td><td style="text-align:center;padding:10px;color:#2dd4bf">Yes</td></tr><tr style="border-bottom:1px solid #1e293b"><td style="padding:10px">Auto Escalation</td><td style="text-align:center;padding:10px;color:#ef4444">No</td><td style="text-align:center;padding:10px;color:#2dd4bf">Yes</td></tr><tr style="border-bottom:1px solid #1e293b"><td style="padding:10px">Real-Time Intervention</td><td style="text-align:center;padding:10px;color:#ef4444">No</td><td style="text-align:center;padding:10px;color:#2dd4bf">Yes</td></tr></table><h2 style="color:#fff;font-size:1.5em;margin-bottom:12px">Trusted by ${label} Across ${city}</h2><p style="line-height:1.7">NISCHINT has been designed with the specific safety challenges of Indian cities in mind. ${label} in ${city} trust NISCHINT because it goes beyond panic buttons to deliver proactive, AI-driven protection that works even when you cannot call for help.</p></section>`;
  }

  if (v === 'personal') {
    return `<section style="max-width:800px;margin:40px auto;padding:0 20px;font-family:system-ui,sans-serif;color:#cbd5e1"><h2 style="color:#fff;font-size:1.5em;margin-bottom:12px">Your Personal Safety Companion in ${city}</h2><p style="line-height:1.7;margin-bottom:24px">${insight} Whether you are commuting, traveling alone, or in an unfamiliar part of ${city}, NISCHINT acts as your personal safety companion that is always watching, always ready.</p><h2 style="color:#fff;font-size:1.5em;margin-bottom:12px">How NISCHINT Keeps You Safe Personally</h2><ul style="line-height:2.2;padding-left:20px;margin-bottom:24px"><li>Runs silently in the background while you go about your day in ${city}</li><li>Listens for distress signals without you needing to press any button</li><li>Shares your live location with chosen guardians automatically</li><li>Escalates to emergency contacts if you cannot respond</li></ul><h2 style="color:#fff;font-size:1.5em;margin-bottom:12px">Safety That Adapts to Your Life in ${city}</h2><p style="line-height:1.7">NISCHINT is not a generic safety app. It understands the safety landscape of ${city} and provides personalized protection that fits your lifestyle. From daily commutes to late-night outings, your safety is always personal with NISCHINT.</p></section>`;
  }

  const featuresHtml = features.map(f => `<li>${f}</li>`).join('');
  return `<section style="max-width:800px;margin:40px auto;padding:0 20px;font-family:system-ui,sans-serif;color:#cbd5e1"><h2 style="color:#fff;font-size:1.5em;margin-bottom:12px">Safety Challenges in ${city}</h2><p style="line-height:1.7;margin-bottom:24px">${insight} ${label} in ${city} face unique urban safety risks that require more than basic location tracking. NISCHINT addresses these with AI-powered proactive protection.</p><h2 style="color:#fff;font-size:1.5em;margin-bottom:12px">How NISCHINT Protects ${label} in ${city}</h2><p style="line-height:1.7;margin-bottom:16px">NISCHINT uses AI-powered voice distress detection, continuous GPS tracking, and instant automated alerts to ensure safety across ${city}. Key capabilities include:</p><ul style="line-height:2;padding-left:20px;margin-bottom:24px">${featuresHtml}</ul><h2 style="color:#fff;font-size:1.5em;margin-bottom:12px">Why ${city} Residents Choose NISCHINT</h2><p style="line-height:1.7">Unlike traditional safety apps that only react after an emergency, NISCHINT detects distress signals proactively and escalates automatically. Whether commuting through ${city}'s busiest areas or traveling at night, NISCHINT provides an always-on safety layer for ${label.toLowerCase()}.</p></section>`;
}

function generateGeoJsonLd(city, type, canonical) {
  const serviceTypes = { women: 'Women Safety', kids: 'Child Safety', family: 'Family Safety' };
  return JSON.stringify({
    "@context": "https://schema.org",
    "@type": "Service",
    "name": `NISCHINT ${serviceTypes[type]} App`,
    "description": `AI-powered ${serviceTypes[type].toLowerCase()} application for ${city}, India`,
    "url": canonical,
    "areaServed": { "@type": "City", "name": city, "containedInPlace": { "@type": "Country", "name": "India" } },
    "serviceType": `${serviceTypes[type]} Application`,
    "provider": { "@type": "Organization", "name": "NISCHINT", "url": "https://nischint.care" },
  });
}

// Generate GEO pages
console.log('\n[inject-seo] Generating GEO city pages...');
let geoCount = 0;

for (const page of GEO_PAGES) {
  const seo = generateGeoSEO(page);
  let injected = injectGeoSEO(indexHtml, seo);

  // Replace JSON-LD with city-specific Service schema
  injected = injected.replace(
    /<script type="application\/ld\+json">[\s\S]*?<\/script>/,
    `<script type="application/ld+json">${generateGeoJsonLd(page.city, page.type, seo.canonical)}</script>`
  );

  // Replace noscript with rich city-specific content
  const label = TYPE_LABELS[page.type] || 'People';
  const insight = SAFETY_INSIGHTS[page.city] || 'Urban safety challenges requiring real-time monitoring.';
  injected = injected.replace(
    /<noscript>[\s\S]*?<\/noscript>/,
    `<noscript><h1>${escapeHtml(label)} Safety App in ${page.city} | NISCHINT</h1><p>${insight}</p><p>NISCHINT uses AI-powered voice distress detection, GPS tracking, and instant alerts to ensure safety in ${page.city}.</p><p><a href="${BASE_URL}/women-safety-app">Women Safety</a> | <a href="${BASE_URL}/kids-safety-app">Kids Safety</a> | <a href="${BASE_URL}/family-safety-app">Family Safety</a></p></noscript>`
  );

  // Inject city content section before </body>
  const cityContent = generateCityContent(page.city, page.type, page.variant);

  // Inline GEO tracking script — fires geo_page_view on page load (before React hydrates)
  const geoTrackScript = `<script>(function(){try{var d=${JSON.stringify({event:'geo_page_view',city:page.city,type:page.type,variant:page.variant||'default',channel:'seo_geo',url:'/'+page.slug})};if(navigator.sendBeacon){navigator.sendBeacon('/api/geo-events',new Blob([JSON.stringify(d)],{type:'application/json'}))}else{fetch('/api/geo-events',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d),keepalive:true})}}catch(e){}})()</script>`;

  injected = injected.replace('</body>', `${cityContent}${geoTrackScript}</body>`);

  // Create folder-based URL
  const dir = path.join(BUILD_DIR, page.slug);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });

  const outputPath = path.join(dir, 'index.html');
  fs.writeFileSync(outputPath, injected, 'utf-8');

  // Also create flat .html file for CDN/direct access (e.g. /kids-safety-app-delhi.html)
  const flatPath = path.join(BUILD_DIR, `${page.slug}.html`);
  fs.writeFileSync(flatPath, injected, 'utf-8');

  console.log(`[inject-seo] GEO page created: ${page.slug} (folder + .html)`);
  geoCount++;
}

console.log(`[inject-seo] Done. ${geoCount} GEO city pages generated.`);
console.log(`[inject-seo] Total: ${count + geoCount} pages.`);
