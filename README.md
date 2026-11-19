# Studio: AI Creative Agency for E.A.S.E., EASE AI and GEC

**The AI creates. You review. You approve. Instagram publishes.**

There are two ways to run it:
- **Online for your team (recommended):** follow **DEPLOY-RENDER.md**. Everyone uses one link, nothing is installed, the admin connects OpenAI and Instagram inside the app, and team members just sign in.
- **On one Windows computer:** follow section 1 below.

In both cases you sign in first. The first person to open a new studio creates the admin account. OpenAI keys and Instagram accounts can be connected in **Settings → Connections**. The `.env` file is optional.

Studio turns a brief and your photos into five or more genuinely different Instagram posts. Each post has a finished design, three captions and hashtags. You refine the one you like, edit its caption, approve it, and only then publish it to Instagram with one explicit click.

---

## 1. One-time setup (Windows)

1. **Install Python** from https://www.python.org/downloads/. On the first installer screen, tick **"Add python.exe to PATH"**.
2. **Unzip this folder**, for example to `Documents\creative-agency`.
3. **Double-click `setup.bat`.** It installs everything: the renderer, the photo cut-out tool (about 200 MB on first use) and the public-link tool for publishing. When it finishes, Notepad opens the `.env` settings file.
4. Close Notepad (you can leave `.env` as it is; keys can be added in the app).
5. **Double-click `start.bat`.** Your browser opens at http://127.0.0.1:5000. Create your admin account.
6. In **Settings → Connections**, paste your OpenAI key. Then open **Setup & tests** and run every test.

If Windows shows *"Smart App Control blocked a file"*: delete the extracted folder, right-click the **zip** → **Properties** → tick **Unblock** → OK, then extract again. "Log in with Instagram" needs the online (https) version. On a single computer, use the token method in section 3.

## 2. OpenAI (text and images)

- Go to https://platform.openai.com → **API keys** → *Create new secret key*. Paste it into `.env` after `OPENAI_API_KEY=`.
- **The API is billed separately from ChatGPT.** A ChatGPT Plus or Free plan does not include API credit, so add credit under *Settings → Billing*.
- **Image models may need Organization Verification.** Do it at *Settings → Organization → General*. Without it, the image test in *Setup & tests* tells you so.
- Models are set in `.env`. The defaults are `gpt-5.6` for strategy, design, captions and review, and `gpt-image-2` (high quality) for images. Change them there if you need to.
- **Keys stay on your computer.** They're only in `.env`, never sent to the browser, and never included in anything you share. Don't email or upload `.env`.

### How the work is split between models
| Job | Model |
|---|---|
| Briefs, strategy, concepts, art direction, layout, captions, chat, six-part reviews | `OPENAI_TEXT_MODEL` (structured outputs, high reasoning) |
| Scenes, product shots, textures, surreal elements, edits of product photos | `OPENAI_IMAGE_MODEL` (Images API: generate and edit) |
| All words on the image | Real typography rendered by the app, so text is never misspelled |
| Cut-outs of people and products | Local background removal (free) |

The image model never draws words, and your real people are never regenerated. They're cut out and composited instead.

**The original Claude version is kept.** Set `TEXT_PROVIDER=claude` and add `ANTHROPIC_API_KEY` to switch back at any time.

## 3. Instagram publishing

Instagram's official API only works with **Professional accounts** (Business or Creator) and only accepts **JPEG** images that it downloads from a **public link**. The app handles the JPEG conversion and the public link. You need to connect the account once:

1. In the Instagram app, make sure the account is a **Professional** account (*Settings → Account type and tools*).
2. Go to https://developers.facebook.com → **My Apps → Create app**. Choose the use case for managing Instagram content (the *Instagram API*), then open **API setup with Instagram login**.
3. Under **Generate access tokens**, add your Instagram account, log in, and allow the permissions (`instagram_business_basic`, `instagram_business_content_publish`).
4. Copy the token into `.env` after `IG_ACCESS_TOKEN=`, then restart the app.
5. In **Setup & tests**, run *Instagram connection* and *Public link*.

Notes:
- While the Meta app is in *development mode* it can publish only to accounts that have a role on the app, such as your own. That's all you need for your own accounts.
- Tokens expire after about 60 days. Generate a new one the same way and replace it in `.env`.
- Instagram allows about 100 API posts per account per day. The Setup page shows your current usage.
- Meta's guide is at https://developers.facebook.com/docs/instagram-platform/content-publishing.

### Safety: test mode
`IG_TEST_MODE=true` is the default. In test mode, APPROVE & PUBLISH does everything except the real post: it builds the JPEG, opens the public link, checks Instagram could download the image, and reads your account. It then reports *"Test run complete. NOTHING was posted."* Set `IG_TEST_MODE=false` only after every test in *Setup & tests* passes.

### The approval workflow (always enforced)
1. You give a brief → 2. the AI develops concepts → 3. it designs them → 4. it writes captions and hashtags → 5. you review → 6. you **Select** one → 7. you edit the caption and hashtags (or **Edit design**) → 8. you click **Approve final version** → 9. the app shows an Instagram-style final preview → 10. you tick *"I've reviewed…"* and click **APPROVE & PUBLISH** → 11. only then does the app contact Instagram.

- Editing an approved post sends it back to draft, so it must be approved again.
- One click can't publish twice. A post that's already published can't be re-sent, and publishing the same design again needs an extra confirmation.
- Success is shown only after Instagram confirms it. The permalink and media ID are saved.
- If the connection drops at the last step, the post is marked **"Result unknown — check Instagram"** and the app won't retry until you confirm it isn't there. That prevents accidental duplicates.
- **Drafts & publishing** lists every draft, approval and published post.
- **The public link only ever exposes the one approved image,** behind a random one-time address, for the few seconds of publishing. Every other page of the app is blocked from the internet.

## 4. Using the studio

- **New creative campaign:** brand, tone, what you're promoting, photos, objective and details.
- **Concepts:** the director explores twice as many ideas as it shows you (you can see the rejected ones), and each concept uses a different layout.
- **Quality control:** every design goes through up to three creative reviews (creative direction, visual design, typography, brand, marketing, technical). Weak designs are refined or rethought before you see them.
- **Inspector:** regenerate, make a variation, improve the typography, change the headline, make it more professional, funnier or more premium, take a different direction, combine two concepts, recompose for another format, or describe any change. Only that design changes, and every version is kept.
- **Talk to your creative director:** a chat in each campaign that knows the whole campaign. Changes it suggests appear as buttons, and nothing runs until you click.
- **Brand library:** guidelines, logos, fonts and a **reference library** of past work for each brand. The director studies those references for principles and never copies them.
- **Usage:** every call is recorded, with text tokens and images tracked separately. Add current prices in `.env` to see cost estimates.

## 5. Brands

| Brand | Source | Notes |
|---|---|---|
| E.A.S.E. (Mental Math) | Official Master Brand Guidelines v1.0 | Calibri, navy, teal and white, portrait |
| GEC | Official GEC Brand Guidelines v1.0 | Calibri, Royal Navy and Championship Gold, square. The logos have white backgrounds, so upload transparent ones when you get them |
| EASE AI | **Draft** built from the Gap and Workshop campaign posters | Inter Tight, JetBrains Mono and Instrument Serif (free OFL fonts), signal orange on night black. The logo is a placeholder cropped from a poster, so replace it with the original file |

## 6. Files
| File | What it does |
|---|---|
| `app.py` | Web server, design pipeline, approvals, publishing, tests |
| `agent.py` | The creative director: every instruction sent to the AI |
| `llm.py` | Connects to OpenAI (or Claude) and records usage |
| `imagegen.py` | OpenAI image generation and editing, with caching so identical requests are never paid twice |
| `instagram.py` | Official Instagram publishing |
| `tunnel.py` | The temporary public link for publishing |
| `render.py` | Turns designs into exact-size PNGs |
| `usage.py`, `store.py` | Usage log, campaigns and brands on disk |
| `brands/` | Brand profiles, guidelines, logos, fonts and references |
| `data/` | Your campaigns, approvals and usage log |

## 7. If something goes wrong
- **Something isn't working:** run *Setup & tests* first. It says exactly which part fails and why.
- **"Organization Verification":** verify your OpenAI organization (section 2).
- **"out of credit":** add credit at platform.openai.com → Billing.
- **"token is invalid or expired":** generate a new Instagram token (section 3).
- **A design shows an error:** press **Retry** on that card. The other designs aren't affected.
- Error details are printed in the black window.
