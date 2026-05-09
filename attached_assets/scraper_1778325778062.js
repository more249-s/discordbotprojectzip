// ═══════════════════════════════════════════════════════════════
// 🌐  helpers/scraper.js — ADVANCED MANGA SCRAPER v5
//
//  Fixes vs v4:
//  • BUG FIX: network pool images were re-filtered by extension
//    on merge, dropping all CDN URLs without .jpg/.png — fixed
//    by using two separate pools (confirmed vs extension-based)
//  • Browser cookies passed to image downloads (Gen Z fix)
//  • JS source scan: tries to extract image arrays from the
//    page's JavaScript (fallback for heavily JS-driven readers)
//  • newtoki: longer wait + aggressive captcha retry
//  • Large chapter handling: batches images when ZIP > 8MB
// ═══════════════════════════════════════════════════════════════

const { chromium }   = require('playwright');
const axios          = require('axios');
const fs             = require('fs');
const pathLib        = require('path');
const { execSync }   = require('child_process');
const { callGemini } = require('../gemini');
const { OCR_MODEL }  = require('../config');

const MIN_FILE_SIZE = 15_000;  // 15 KB (slightly more permissive)

// ── Find chromium executable ──────────────────────────────────
function findChromiumExecutable() {
    const roots = [
        //  '/home/container/pw-browsers',
        pathLib.resolve(__dirname, '..', 'pw-browsers'),
        pathLib.resolve(__dirname, '..', '..', 'pw-browsers'),
        pathLib.resolve(process.cwd(), 'pw-browsers'),
        pathLib.resolve(process.cwd(), '..', 'pw-browsers'),
        pathLib.join(process.env.HOME || '/root', '.cache', 'ms-playwright'),
        // '/home/container/.cache/ms-playwright',
    ];
    for (const root of roots) {
        if (!fs.existsSync(root)) continue;
        let entries;
        try { entries = fs.readdirSync(root); } catch { continue; }
        entries.sort((a, b) => (a.includes('headless') ? 0 : 1) - (b.includes('headless') ? 0 : 1));
        for (const entry of entries) {
            if (!entry.startsWith('chromium')) continue;
            const base = pathLib.join(root, entry);
            for (const exe of [
                pathLib.join(base, 'chrome-headless-shell-linux64', 'chrome-headless-shell'),
                pathLib.join(base, 'chrome-linux64', 'chrome'),
                pathLib.join(base, 'chrome-linux', 'chrome'),
                pathLib.join(base, 'chrome'),
            ]) {
                if (fs.existsSync(exe)) {
                    try { execSync(`chmod +x "${exe}"`); } catch {}
                    console.log(`✅  Chromium: ${exe}`);
                    return exe;
                }
            }
        }
    }
    console.warn('⚠️  Chromium not found — using Playwright default.');
    return null;
}
let _cachedExe = undefined;
function getExecutablePath() {
    if (_cachedExe === undefined) _cachedExe = findChromiumExecutable();
    return _cachedExe;
}

// ── Site config ───────────────────────────────────────────────
function getSiteConfig(url) {
    try {
        const host = new URL(url).hostname.toLowerCase();
        if (host.includes('asura'))      return { jumpPasses: 4, waitPerJump: 1200, finalWait: 3000 };
        if (host.includes('newtoki'))    return { jumpPasses: 3, waitPerJump: 1500, finalWait: 4000, isNewtoki: true };
        if (host.includes('flamescans')) return { jumpPasses: 4, waitPerJump: 1000, finalWait: 2000 };
        if (host.includes('vortex'))     return { jumpPasses: 3, waitPerJump: 1000, finalWait: 2000 };
        if (host.includes('genz') || host.includes('gen-z')) return { jumpPasses: 3, waitPerJump: 1200, finalWait: 3000 };
        if (host.includes('webtoon'))    return { jumpPasses: 3, waitPerJump: 800,  finalWait: 1500 };
    } catch {}
    return { jumpPasses: 3, waitPerJump: 1000, finalWait: 2000 };
}

// ── Captcha solver ────────────────────────────────────────────
async function solveCaptchaWithGemini(page) {
    try {
        const captchaEl = await page.$('img[src*="captcha"], .captcha img, #captcha img, img[alt*="captcha"]');
        if (!captchaEl) return null;
        const b64 = (await captchaEl.screenshot({ type: 'png' })).toString('base64');
        const { text } = await callGemini(OCR_MODEL, [
            'This is a CAPTCHA image. Output ONLY the characters shown — no spaces, no explanation.',
            { inlineData: { data: b64, mimeType: 'image/png' } },
        ]);
        return text.trim().replace(/[^a-zA-Z0-9]/g, '');
    } catch { return null; }
}

async function handleCaptchaIfPresent(page, cfg = {}) {
    const maxAttempts = cfg.isNewtoki ? 6 : 4;
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
        const curr = page.url();
        const body = await page.content().catch(() => '');
        const hasCaptchaInput = !!(await page.$('input[name="captcha"], input[name="code"], #captcha_input').catch(() => null));
        const isCaptcha =
            curr.includes('captcha') ||
            body.includes('자동 입력 방지') ||
            body.toLowerCase().includes('not a robot') ||
            body.toLowerCase().includes('verify you are human') ||
            hasCaptchaInput;

        if (!isCaptcha) break;
        console.log(`🔒  Captcha attempt ${attempt + 1}/${maxAttempts}`);

        const answer = await solveCaptchaWithGemini(page);
        if (!answer) { await page.waitForTimeout(2000); continue; }

        const input = await page.$('input[name="captcha"], input[name="code"], input[name="answer"], #captcha_input, input[type="text"]:not([name="q"])');
        if (input) { await input.fill(answer); await page.waitForTimeout(400); }
        const submit = await page.$('input[type="submit"], button[type="submit"], .btn_check, input[value="확인"], button:has-text("확인")').catch(() => null);
        if (submit) await submit.click();
        else if (input) await input.press('Enter');
        await page.waitForTimeout(3500);
    }
}

// ── Fast position-jump scroll ─────────────────────────────────
async function fastScroll(page, cfg) {
    for (let pass = 0; pass < cfg.jumpPasses; pass++) {
        await page.evaluate(async (passes) => {
            const h = document.body.scrollHeight;
            const positions = Array.from({ length: passes + 1 }, (_, i) => Math.floor((i / passes) * h));
            for (const pos of positions) {
                window.scrollTo(0, pos);
                await new Promise(r => setTimeout(r, 80));
            }
        }, cfg.jumpPasses);
        await page.waitForTimeout(cfg.waitPerJump);
        if (pass < cfg.jumpPasses - 1) {
            await page.evaluate(() => window.scrollTo(0, 0));
            await page.waitForTimeout(200);
        }
    }
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await page.waitForTimeout(cfg.finalWait);
}

// ── Wait for lazy images ──────────────────────────────────────
async function waitForLazyImages(page) {
    await page.waitForFunction(() => {
        const lazies = Array.from(document.querySelectorAll('img[data-src], img[data-lazy-src], img[data-original]'));
        return lazies.every(img => img.src?.startsWith('http') || img.naturalHeight > 0);
    }, { timeout: 10_000 }).catch(() => {});
}

// ── DOM image collection ──────────────────────────────────────
async function collectFromDOM(page) {
    return page.evaluate(() => {
        const selectors = [
            '.reading-content img', '#readerarea img', '.chapter-content img',
            '.viewer-container img', '.manga-reader img', '.entry-content img',
            'img.wp-manga-chapter-img', '[class*="chapter"] img', '[class*="reader"] img',
            '[class*="content"] img', 'img[data-src]', 'img[data-original]',
        ];
        let imgs = [];
        for (const sel of selectors) {
            const found = Array.from(document.querySelectorAll(sel));
            if (found.length > 3) { imgs = found; break; }
        }
        if (!imgs.length) imgs = Array.from(document.querySelectorAll('img'));

        const seen = new Set();
        return imgs.map((img, idx) => {
            const src = img.getAttribute('data-src') || img.getAttribute('data-lazy-src')
                     || img.getAttribute('data-original') || img.getAttribute('data-cfsrc')
                     || img.getAttribute('src') || img.currentSrc || '';
            if (!src.startsWith('http') || seen.has(src)) return null;
            const h = img.naturalHeight || img.height || 0;
            const w = img.naturalWidth  || img.width  || 0;
            if (h > 0 && (h < 80 || w < 80)) return null;
            seen.add(src);
            return { src: src.trim(), idx };
        }).filter(Boolean).sort((a, b) => a.idx - b.idx).map(x => x.src);
    });
}

// ── JS source scan — finds image arrays in page scripts ───────
// Many readers store image URLs in a JS variable like:
//   var images = ["https://cdn.../001.jpg", "https://cdn.../002.jpg"]
// This extracts them even when the DOM never builds <img> tags.
async function collectFromJsSource(page) {
    try {
        const urls = await page.evaluate(() => {
            const found = new Set();
            // Match quoted URLs that look like image paths
            const pattern = /["'`](https?:\/\/[^"'`\s]+\.(?:jpe?g|png|webp|gif)[^"'`\s]*?)["'`]/gi;

            // Search inline scripts
            document.querySelectorAll('script:not([src])').forEach(s => {
                let m;
                while ((m = pattern.exec(s.textContent || '')) !== null) found.add(m[1]);
            });

            // Also search window variables for common patterns
            try {
                const winStr = JSON.stringify(window.__DATA__ || window.CHAPTER_INFO || window.images || window.pics || '');
                let m;
                while ((m = pattern.exec(winStr)) !== null) found.add(m[1]);
            } catch {}

            return [...found];
        });

        if (urls.length > 0) console.log(`📜  JS source scan found ${urls.length} image URLs`);
        return urls;
    } catch { return []; }
}

// ── Build final URL list ──────────────────────────────────────
// !! KEY FIX: confirmedByType pool is NOT re-filtered by extension.
//    These were already confirmed as image/* by Playwright's resource type.
async function buildUrlList(page, confirmedByType, confirmedByExt) {
    const domUrls = await collectFromDOM(page);
    const jsUrls  = await collectFromJsSource(page);

    const combined = new Set([
        ...domUrls,
        ...jsUrls,
        ...confirmedByType,    // ← no extension re-filter, these are confirmed images
        ...confirmedByExt,     // ← already passed extension filter at capture time
    ]);

    return [...combined];
}

// ── Parallel download with cookies ───────────────────────────
async function downloadImages(imageUrls, folderPath, pageUrl, cookies = '') {
    const CONCURRENCY = 8;
    const files  = [];
    const queue  = imageUrls.map((url, i) => ({ url, i }));
    const failed = [];

    const worker = async () => {
        while (queue.length > 0) {
            const { url, i } = queue.shift();
            const fileName = `page_${String(i + 1).padStart(3, '0')}.jpg`;
            const filePath = pathLib.join(folderPath, fileName);
            let saved = false;
            for (let attempt = 0; attempt < 3; attempt++) {
                try {
                    const headers = {
                        Referer      : pageUrl,
                        'User-Agent' : 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                        'Accept'     : 'image/webp,image/apng,image/*,*/*;q=0.8',
                    };
                    if (cookies) headers['Cookie'] = cookies;

                    const res = await axios({ url, responseType: 'arraybuffer', timeout: 25_000, headers });
                    if (res.data.length > MIN_FILE_SIZE) {
                        fs.writeFileSync(filePath, res.data);
                        files.push({ name: fileName, path: filePath });
                        saved = true; break;
                    }
                } catch { if (attempt < 2) await new Promise(r => setTimeout(r, 800)); }
            }
            if (!saved) failed.push(i + 1);
        }
    };

    await Promise.all(Array.from({ length: CONCURRENCY }, worker));
    if (failed.length) console.warn(`⚠️  Skipped pages: ${failed.join(', ')}`);
    files.sort((a, b) => a.name.localeCompare(b.name));
    return files;
}

// ── Browser launcher ──────────────────────────────────────────
async function launchBrowser() {
    const exe  = getExecutablePath();
    const opts = {
        headless : true,
        args     : [
            '--no-sandbox', '--disable-setuid-sandbox',
            '--disable-blink-features=AutomationControlled',
            '--disable-dev-shm-usage', '--disable-web-security',
            '--disable-features=IsolateOrigins,site-per-process',
            '--window-size=1280,900',
        ],
    };
    if (exe) opts.executablePath = exe;
    try {
        return await chromium.launch(opts);
    } catch (e) {
        throw new Error(
            `Playwright failed to launch.\nExecutable: ${exe ?? '(auto)'}\nError: ${e.message}\n` +
            `Fix: run  npx playwright install chromium  in the bot folder.`
        );
    }
}

// ── Public: scrape a single chapter ──────────────────────────
async function scrapeChapter(url) {
    const cfg = getSiteConfig(url);

    // !! Two separate pools to avoid incorrect re-filtering:
    const confirmedByType = new Set();  // resource type === 'image' (no extension needed)
    const confirmedByExt  = new Set();  // URL matched image extension pattern

    const browser = await launchBrowser();
    const context = await browser.newContext({
        viewport  : { width: 1280, height: 900 },
        userAgent : 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        extraHTTPHeaders: { 'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7' },
    });

    // Intercept ALL requests — populate the two pools separately
    await context.route('**/*', (route, request) => {
        const reqUrl = request.url();
        const type   = request.resourceType();

        if (type === 'image') {
            confirmedByType.add(reqUrl);  // confirmed by browser — no re-filter
        } else if (/\.(jpe?g|png|webp|gif)(\?|$)/i.test(reqUrl)) {
            confirmedByExt.add(reqUrl);   // matched extension — but could be non-image
        }

        route.continue();
    });

    const page = await context.newPage();

    // Stealth: hide automation fingerprints
    await page.addInitScript(() => {
        Object.defineProperty(navigator, 'webdriver',  { get: () => undefined });
        Object.defineProperty(navigator, 'plugins',    { get: () => [1, 2, 3, 4, 5] });
        Object.defineProperty(navigator, 'languages',  { get: () => ['ko-KR', 'ko', 'en-US', 'en'] });
        window.chrome = { runtime: {}, loadTimes: () => {}, csi: () => {} };
    });

    try {
        console.log(`📡  Scraping: ${url}`);
        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60_000 });
        await page.waitForTimeout(2500);

        await handleCaptchaIfPresent(page, cfg);

        await fastScroll(page, cfg);
        await waitForLazyImages(page);

        const imageUrls = await buildUrlList(page, confirmedByType, confirmedByExt);
        console.log(`🌐  Network: ${confirmedByType.size} by type + ${confirmedByExt.size} by ext`);
        console.log(`✅  Total image URLs: ${imageUrls.length}`);

        if (!imageUrls.length) {
            const bodyText = await page.innerText('body').catch(() => '');
            if (bodyText.includes('Just a moment') || bodyText.includes('Checking your browser')) {
                throw new Error('Cloudflare protection detected — this site cannot be scraped automatically.');
            }
            throw new Error('No images found. The site may use anti-scraping or the URL may be wrong.');
        }

        // Get browser cookies to pass to the downloader
        const cookieObjects = await context.cookies();
        const cookieHeader  = cookieObjects.map(c => `${c.name}=${c.value}`).join('; ');

        const folderPath = pathLib.join(__dirname, '..', `temp_${Date.now()}`);
        fs.mkdirSync(folderPath, { recursive: true });

        const files = await downloadImages(imageUrls, folderPath, page.url(), cookieHeader);
        console.log(`📦  Downloaded ${files.length}/${imageUrls.length} pages`);

        const pageTitle = await page.title().catch(() => '');
        const numMatch  = url.match(/chapter[-_\s]?(\d+[\.\d]*)/i)
                       || url.match(/[-/](\d+)화/i)
                       || pageTitle.match(/chapter[-_\s]?(\d+[\.\d]*)/i)
                       || url.match(/\/(\d+)\/?(?:\?|$)/);
        const title = numMatch ? `Ch_${numMatch[1]}` : 'Manga_Chapter';

        return { files, folderPath, title, totalFound: imageUrls.length };
    } finally {
        await browser.close();
    }
}

// ── Public: scrape chapter links from series page ─────────────
async function scrapeSeriesLinks(seriesUrl) {
    const browser = await launchBrowser();
    const context = await browser.newContext({ userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' });
    const page    = await context.newPage();
    try {
        await page.goto(seriesUrl, { waitUntil: 'domcontentloaded', timeout: 45_000 });
        await page.waitForTimeout(1500);
        await page.evaluate(() => {
            document.querySelectorAll('[class*="load-more"], [class*="show-all"], .chapter-list-toggle')
                    .forEach(t => { try { t.click(); } catch {} });
        }).catch(() => {});
        await page.waitForTimeout(800);

        const links = await page.evaluate(() =>
            Array.from(document.querySelectorAll('a'))
                .map(a => a.href)
                .filter(h => h && (h.includes('chapter') || /\/\d+[\.\d]*\/?(?:\?|$)/.test(h))
                          && !h.includes('comment') && !h.includes('login')
                          && !h.includes('register') && !h.includes('#'))
        );
        const unique = [...new Set(links)];
        unique.sort((a, b) => {
            const na = parseFloat((a.match(/(\d+[\.\d]*)/) || [0, 0])[1]);
            const nb = parseFloat((b.match(/(\d+[\.\d]*)/) || [0, 0])[1]);
            return na - nb;
        });
        return unique;
    } finally {
        await browser.close();
    }
}

function cleanupFolder(folderPath) {
    try { fs.rmSync(folderPath, { recursive: true, force: true }); }
    catch (e) { console.warn('⚠️  Cleanup failed:', e.message); }
}

module.exports = { scrapeChapter, scrapeSeriesLinks, cleanupFolder };
