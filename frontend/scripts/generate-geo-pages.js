const fs = require('fs');
const path = require('path');

const buildDir = path.join(__dirname, '../build');

// 🔧 CONFIG
const pages = [
  { slug: "best-women-safety-app", type: "Women Safety App", variant: "best" },
  { slug: "kids-safety-app", type: "Kids Safety App", variant: "normal" },
  { slug: "personal-safety-app", type: "Personal Safety App", variant: "normal" }
];

const cities = ["mumbai", "delhi", "pune"];

// 🧠 H1 GENERATOR
function generateH1(type, city, variant) {
  city = city.charAt(0).toUpperCase() + city.slice(1);

  if (variant === "best") {
    return `Best ${type} in ${city}`;
  }
  return `${type} in ${city}`;
}

// 🏗️ PAGE GENERATOR
function generateHTML(title, city) {
  return `<!doctype html>
<html lang="en-IN">
<head>
<meta charset="utf-8"/>
<title>${title} | NISCHINT</title>
<meta name="description" content="${title}. AI-powered safety system by NISCHINT."/>
</head>

<body>

<noscript>
  <h1>${title}</h1>
</noscript>

<section style="max-width:800px;margin:40px auto;">
  <h1>${title}</h1>
  <p>AI-powered safety system for ${city}.</p>
</section>

<div id="root"></div>

</body>
</html>`;
}

// 🔁 GENERATE FILES
pages.forEach(page => {
  cities.forEach(city => {
    const title = generateH1(page.type, city, page.variant);
    const fileName = `${page.slug}-${city}.html`;
    const filePath = path.join(buildDir, fileName);

    fs.writeFileSync(filePath, generateHTML(title, city));
    console.log("Generated:", fileName);
  });
});