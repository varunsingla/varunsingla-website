# varunsingla.com — GitHub Pages Setup Guide

One-time setup to get your AI learning blog live at varunsingla.com.
Estimated time: ~15 minutes.

---

## Step 1 — Create a GitHub Repository

1. Go to https://github.com and sign in (or create a free account)
2. Click **New repository** (green button, top-right)
3. Name it anything — e.g. `varunsingla-website` or `site`
4. Set it to **Public** (required for free GitHub Pages)
5. Leave everything else default and click **Create repository**

Note your: **GitHub username** and **repo name** — you'll need them in Step 4.

---

## Step 2 — Create a Personal Access Token (for auto-push)

This lets the daily script push updates without a password.

1. Go to: https://github.com/settings/tokens?type=beta
   *(Settings → Developer settings → Personal access tokens → Fine-grained tokens)*
2. Click **Generate new token**
3. Give it a name like `varunsingla-site-deploy`
4. Set expiration: **1 year** (or "No expiration")
5. Under **Repository access** → select your new repo
6. Under **Permissions** → set **Contents: Read and write**
7. Click **Generate token**
8. **Copy the token** (you won't see it again!)

---

## Step 3 — Configure config.json

In the `varunsingla-website` folder, copy `config.json.template` to `config.json`:

```bash
cp config.json.template config.json
```

Then open `config.json` and fill in your values:

```json
{
  "github_token":  "ghp_your_token_here",
  "github_user":   "your_github_username",
  "github_repo":   "varunsingla-website",
  "github_branch": "main"
}
```

⚠️  **config.json is in .gitignore** so your token is never uploaded to GitHub.

---

## Step 4 — Push the Website Files to GitHub

Open Terminal (or a command prompt) and run these commands,
replacing `YOUR_USERNAME` and `YOUR_REPO` with your values:

```bash
# Navigate to the website folder
cd ~/Documents/Claude/Personal\ Files/varunsingla-website

# Initialise git (if not already done)
git init
git branch -M main

# Connect to your GitHub repo
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git

# Push everything
git add index.html learnings.json CNAME .gitignore
git commit -m "Initial site launch 🚀"
git push -u origin main
```

---

## Step 5 — Enable GitHub Pages

1. Go to your repo on GitHub
2. Click **Settings** → **Pages** (left sidebar)
3. Under **Source** → select **Deploy from a branch**
4. Branch: `main` / Folder: `/ (root)` → click **Save**
5. GitHub will show: *"Your site is ready to be published at https://YOUR_USERNAME.github.io/YOUR_REPO"*

---

## Step 6 — Point varunsingla.com to GitHub Pages

In your domain registrar (wherever you bought varunsingla.com):

**Add these DNS records:**

| Type  | Name | Value                  |
|-------|------|------------------------|
| A     | @    | 185.199.108.153        |
| A     | @    | 185.199.109.153        |
| A     | @    | 185.199.110.153        |
| A     | @    | 185.199.111.153        |
| CNAME | www  | YOUR_USERNAME.github.io |

DNS changes take 10 min – 48 hrs to propagate.

**Back in GitHub Pages settings:**
- Under **Custom domain** → type `varunsingla.com` → click **Save**
- Enable **Enforce HTTPS** (appears after DNS propagates)

---

## Step 7 — Test the Auto-Publish Script

Once git is set up, run the update script once manually to confirm it works:

```bash
cd ~/Documents/Claude/Personal\ Files/varunsingla-website
python3 update_site.py
```

You should see:
```
🤖  AI Learning Blog Updater — 2026-03-22 21:00
────────────────────────────────────────────────────
📖  Parsing ai-learnings.md …
   Found 2 learning entries
📝  Updating learnings.json …
   ✅  learnings.json — 2 total entries (+0 new, 2 updated)
🚀  Pushing to GitHub …
   ✅  Pushed to github.com/YOUR_USERNAME/YOUR_REPO (branch: main)
       Live at: https://varunsingla.com
────────────────────────────────────────────────────
✅  Done!
```

---

## What Happens Daily (Automated)

Every evening at **9:10 PM**, the scheduled task in Cowork:

1. Reads your latest `memory/context/ai-learnings.md`
2. Parses all date sections and updates `learnings.json`
3. Commits and pushes to GitHub
4. GitHub Pages auto-deploys in ~1 minute
5. **varunsingla.com is live** with today's learnings ✅

You can also trigger it manually anytime from the **Scheduled** tab in Cowork.

---

## File Structure

```
varunsingla-website/
├── index.html          ← The website (reads learnings.json)
├── learnings.json      ← Your AI learning data
├── update_site.py      ← Daily update script
├── CNAME               ← Custom domain config
├── .gitignore          ← Excludes config.json from git
├── config.json         ← Your GitHub token (DO NOT COMMIT)
└── config.json.template ← Safe template to copy from
```

---

## Need Help?

Just ask Claude in Cowork — it has access to all your files and can
re-run the update, debug issues, or add a new learning entry manually.
