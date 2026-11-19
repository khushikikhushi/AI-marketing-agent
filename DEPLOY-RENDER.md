# Putting Studio online for free (Render + Supabase)

Your team opens one link (like `https://studio-xxxx.onrender.com`), signs in and makes posts. Nobody installs anything, and the hosting costs nothing. The only cost is OpenAI usage for the AI itself.

**How it works:** **Render** (free) runs the app. Free Render apps have no permanent storage, so the studio keeps everything (accounts, settings, campaigns, images) in **Supabase** (free), and nothing gets lost.

**Free-plan trade-offs:**
- The app **sleeps after 15 minutes** with no visitors. The next visit takes about a minute to wake it.
- Designs are made **one at a time**, and there are **no photo cut-outs** (type behind people). Everything else works.
- Supabase **pauses** a free project after about a week with no use. If the studio ever says it can't reach storage, open supabase.com → your project → **Restore**, wait a minute, and reload.
- Supabase's free storage is 1 GB, enough for thousands of posts.

The code is already on GitHub (`khushikikhushi/AI-marketing-agent`). Make that repository **Private**: GitHub → the repository → **Settings** → bottom of the page → **Change visibility → Private**.

---

## Part 1: Supabase (5 minutes, free, no card)

1. Go to https://supabase.com → **Start your project** → sign in with **GitHub**.
2. Click **New project**:
   - Name: `studio`
   - Database password: click **Generate a password** and save it somewhere (you won't need it for Studio)
   - Region: the one closest to you (e.g. *Central EU (Frankfurt)* or *South Asia (Mumbai)*)
   - Plan: **Free**
   - Click **Create new project** and wait about 2 minutes.
3. Click the **⚙ Project Settings** gear (bottom left) and copy two things into a note:
   - **Project URL:** under **Data API** (or **API**). It looks like `https://abcdefgh.supabase.co`.
   - **The secret key:** under **API Keys**. Open the **Legacy API keys** tab if there is one and click **Reveal** on **service_role**. If there's no such tab, use the **Secret key** (starts with `sb_secret_`).
   - ⚠️ This key gives full access to your storage. Never share it or put it in GitHub; it only goes into Render.

You don't need to create any tables or buckets. Studio sets up its own storage folder the first time it starts.

## Part 2: Render (5 minutes + about 10 minutes building)

1. Go to https://render.com. You're already signed in.
2. Left sidebar → **Blueprints** → **New Blueprint Instance**.
3. Pick **AI-marketing-agent** → **Connect**.
4. Render reads `render.yaml` and shows one **free** web service called **studio**. It asks for two values:
   - **SUPABASE_URL:** paste your Project URL
   - **SUPABASE_SERVICE_KEY:** paste the service_role (or secret) key
5. Name the Blueprint `studio` and click **Apply**. The free plan shouldn't ask for a card.
6. Wait for the first build (about 10 minutes, under **Logs**). When it says **Live**, click the link at the top.

> ⚠️ Render creates a `SECRET_KEY` automatically. Never change or delete it: it locks your saved keys and logins.

Your existing **psychological** service isn't touched.

## Part 3: Set up the studio (in the app)

1. Open your link → **Create the admin account** (that's you).
2. **Settings → Connections:**
   1. **Connect OpenAI:** paste your API key → *Save & test*.
   2. **Instagram app:** paste the Instagram app ID and secret from your Meta app (see Part 4), and add the redirect address Studio shows you to the Meta app.
   3. **Log in with Instagram:** click the button next to each brand.
   4. **Publishing mode:** leave it on **Test mode** for now.
3. **Setup & tests:** run each test.
4. Make a test campaign, approve a design, and press **APPROVE & PUBLISH (TEST)**. You should see *"Test run complete. NOTHING was posted."*
5. When you're happy: **Settings → Publishing mode → Turn off test mode** (type `GO LIVE`).
6. **Settings → Team → Add person** for each colleague, and send them the link and their temporary password privately.

You can skip Instagram entirely at first: download the images and post them yourself.

## Part 4: The Meta (Instagram) app (free, once)

1. https://developers.facebook.com → **My Apps → Create App** → name it `EASE Studio` → choose the use case for managing content on Instagram.
2. Open **Instagram → API setup with Instagram login**.
3. Make sure the permissions include **instagram_business_basic** and **instagram_business_content_publish**.
4. Find **Set up Instagram business login** → **OAuth redirect URIs**, then paste the address from Studio → Settings → step 2 (it ends in `/auth/instagram/callback`) and save.
5. Copy the **Instagram app ID** and **Instagram app secret** into Studio → Settings → step 2.
6. Under **App roles → Roles → Instagram testers**, add each brand's Instagram username, then accept the invite on Instagram (website → Settings → Apps and websites → Tester invites).
7. Leave the Meta app in **Development** mode.

Meta's labels change sometimes. If a button looks different, send a screenshot.

## Updating later

Changes pushed to the GitHub repository rebuild the app automatically. Your data is safe in Supabase.

## Want it faster later?

Use the paid setup instead: rename `render.paid.yaml` to `render.yaml` (Standard plan with a permanent disk). It doesn't sleep, makes several designs at once, and supports photo cut-outs.

## If something goes wrong

- **The build fails:** open the service → **Logs** and send me the last 20 lines.
- **"Can't reach your Supabase storage":** your Supabase project is paused or the URL or key is wrong. Restore the project, or fix the values under Render → studio → **Environment**.
- **It's slow to open:** it was asleep. Wait about a minute.
- **Instagram login failed:** the redirect address in the Meta app must match exactly, and each account must accept the tester invite.
