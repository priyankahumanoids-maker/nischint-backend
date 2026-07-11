const puppeteer = require('puppeteer');
const fs = require('fs');

const POST_LIMIT = 2;
const STATE_FILE = './postState.json';

function canPostToday() {
  if (!fs.existsSync(STATE_FILE)) return true;

  const state = JSON.parse(fs.readFileSync(STATE_FILE));

  const today = new Date().toDateString();

  if (state.date !== today) {
    return true;
  }

  return state.count < POST_LIMIT;
}

function updatePostCount() {
  const today = new Date().toDateString();

  let state = { date: today, count: 0 };

  if (fs.existsSync(STATE_FILE)) {
    state = JSON.parse(fs.readFileSync(STATE_FILE));
  }

  if (state.date !== today) {
    state = { date: today, count: 1 };
  } else {
    state.count += 1;
  }

  fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
}

(async () => {
  const postText = process.argv[2];

  if (!postText) {
    console.log("❌ No post content provided");
    return;
  }

  if (!canPostToday()) {
    console.log("🚫 Daily post limit reached (2/day)");
    return;
  }

  const browser = await puppeteer.launch({
    headless: false,
    defaultViewport: null
  });

  const page = await browser.newPage();

  await page.goto('https://www.linkedin.com/login');

  await page.type('#username', 'YOUR_EMAIL', { delay: 50 });
  await page.type('#password', 'YOUR_PASSWORD', { delay: 50 });

  await Promise.all([
    page.click('[type="submit"]'),
    page.waitForNavigation()
  ]);

  // random delay (human-like)
  await page.waitForTimeout(3000 + Math.random() * 3000);

  await page.goto('https://www.linkedin.com/feed/');

  await page.waitForSelector('[aria-label="Start a post"]');
  await page.click('[aria-label="Start a post"]');

  await page.waitForSelector('[role="textbox"]');

  await page.type('[role="textbox"]', postText, { delay: 20 });

  await page.waitForTimeout(2000);

  await page.click('[aria-label="Post"]');

  console.log("✅ Posted to LinkedIn");

  updatePostCount();

  await page.waitForTimeout(5000);
  await browser.close();
})();