# Putting Studio online with Render

When you're done, your team opens one link (like `https://studio-xxxx.onrender.com`), signs in, and makes posts. Nobody installs anything. This takes about 30–45 minutes the first time.

You need:
- a **GitHub** account (yours: github.com/khushikikhushi, or one for E.A.S.E.)
- a **Render** account with a payment card (render.com)
- an **OpenAI** API key with credit (platform.openai.com)
- the **Instagram accounts** you want to publish to, set as Professional (Business or Creator) accounts

---

## Part 1: Put the code on GitHub (10 min)

1. Unzip `studio-ai-creative-agency.zip` on your computer.
2. Go to https://github.com/new
   - Repository name: `studio`
   - Choose **Private** (important: this keeps your code private)
   - Click **Create repository**
3. On the next page, click **"uploading an existing file"**.
4. Open the unzipped `creative-agency` folder, select **everything inside it** (Ctrl+A) and drag it into the GitHub page.
   - Drag the files *inside* the folder, not the folder itself.
   - If there is a `.env` file, **don't upload it**. The zip doesn't include one, but if you created one while running the app on your computer, leave it out.
5. Wait for the upload to finish, then click **Commit changes**.

## Part 2: Start it on Render (10 min + 10 min build)

1. Go to https://render.com and sign up with **GitHub**.
2. Click **New +** → **Blueprint**.
3. Choose your `studio` repository. Render reads the included `render.yaml` and shows:
   - a web service called **studio** (Docker, *Standard* plan, 2 GB memory)
   - a **5 GB disk** called *studio-data*, where your campaigns, images, accounts and settings are kept
   - a generated **SECRET_KEY**
4. Click **Apply**. Render asks for a payment card for the Standard plan and the disk. Check render.com/pricing for current prices. At the time of writing it's roughly $25/month plus a little for the disk.
5. The first build takes about 10 minutes. When the status says **Live**, click the link at the top (`https://studio-….onrender.com`).

> ⚠️ Never change or delete `SECRET_KEY` after the first deploy. It locks the saved keys and logins, and changing it means re-entering everything.

## Part 3: Set up the studio (10 min, in the app)

1. Open your link. You'll see **Create the admin account**: that's you. Use a strong password.
2. The app opens **Settings → Connections**:
   1. **Connect OpenAI:** paste your API key and press *Save & test*. ✓ means it works.
   2. **Connect your Instagram app:** follow Part 4 below, then paste the *Instagram app ID* and *secret*.
   3. **Log in with Instagram:** click the button next to each brand and log in to that brand's Instagram account.
   4. **Publishing mode** stays on **Test mode** for now.
3. Go to **Setup & tests** and run every test.
4. Make a test campaign, approve a design and press **APPROVE & PUBLISH (TEST)**. It should say *"Test run complete — NOTHING was posted"*.
5. When everything passes: **Settings → Publishing mode → Turn off test mode** (type `GO LIVE`).
6. **Settings → Team → Add person** for each colleague. Send them the link and their temporary password privately. They choose their own password the first time they sign in.

## Part 4: Create the Meta (Instagram) app (15 min, once)

Meta's screens change now and then, so labels may differ slightly.

1. Go to https://developers.facebook.com → log in → **My Apps** → **Create App**.
2. App name: e.g. `EASE Studio`. For the use case, choose the one for managing **content on Instagram** (Instagram API). Finish creating the app.
3. In the app, open **Instagram → API setup with Instagram login**.
   - You'll see the **Instagram app ID** and **Instagram app secret** (click *Show*). Paste both into Studio → Settings → step 2.
4. Find **Set up Instagram business login** (or *Business login settings*) → **OAuth redirect URIs**. Paste the address Studio shows you in step 2 (it ends with `/auth/instagram/callback`) and save.
5. Allow your brand accounts to connect while the app is in *development mode*:
   - **App roles → Roles → Instagram testers → Add**, and enter each brand's Instagram username.
   - Then, on each Instagram account (on the website): **Settings → Apps and websites → Tester invites → Accept**.
6. Leave the app in **Development** mode. That's enough for E.A.S.E.'s own accounts. Meta's App Review is only needed if outside people want to connect their own accounts.
7. Back in Studio, click **Log in with Instagram** for each brand.

## Everyday use

- **Your team** opens the link, signs in, and uses *New creative campaign*.
- **Anyone** can approve and press APPROVE & PUBLISH. Admins manage connections, brands, tests and the team.
- **Instagram connections renew themselves** every ~60 days. If one ever stops working, click *Reconnect* in Settings.
- **Usage** (admins) shows AI usage per person, per campaign, text and images separately. Exact billing is at platform.openai.com → Usage.

## Updating the app later

Upload the changed files to the same GitHub repository (**Add file → Upload files**, then *Commit*). Render rebuilds automatically, and your campaigns, accounts and settings on the disk are kept.

## If something goes wrong

- **The build fails on Render:** open the service → **Events / Logs** and send me the last 20 lines.
- **The page doesn't load right after a deploy:** wait 1–2 minutes, because the service is still starting.
- **"Instagram login failed":** check the redirect URI in the Meta app matches Studio's exactly, and that the account accepted the tester invite.
- **"Organization Verification":** verify your OpenAI organization (platform.openai.com → Settings → Organization).
- **Forgot your admin password:** another admin can reset it in Settings → Team. If you're the only admin, ask me how to reset it from Render's shell.
