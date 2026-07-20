# Marginal — Free Cloud Deployment (Render + Groq)

This is a cloud-ready variant of your Marginal project, modified so it runs
entirely on **free** infrastructure — $0/month, no credit card, anywhere.

## What's different from your local (Ollama) version

| Component | Local version | This version |
|---|---|---|
| LLM | Ollama (local) | **Groq API** (free, no card, cloud-hosted) |
| Retrieval | sentence-transformers + FAISS | **Pure-Python TF-IDF** (no heavy ML libs) |
| Why | Full control, fully offline | Fits Render's free 512MB RAM limit |

Your local Ollama-based project is untouched — this is a separate copy for
deployment. `main.py` and `document_processor.py` are identical; only
`rag_engine.py` and `llm_service.py` were swapped for lighter alternatives
with the exact same interface.

## Step 1 — Get a free Groq API key

1. Go to **https://console.groq.com/keys**
2. Sign up (email or Google) — **no credit card required**
3. Click "Create API Key", copy it somewhere safe (you won't see it again)

## Step 2 — Push this project to GitHub

Render deploys from a Git repository.

1. Create a new repository on GitHub (public or private both work)
2. From this folder:
   ```bash
   git init
   git add .
   git commit -m "Marginal - free deploy variant"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
   git push -u origin main
   ```

## Step 3 — Deploy on Render

1. Go to **https://render.com** and sign up (no card required for free tier)
2. Click **New +** → **Web Service**
3. Connect your GitHub account and select this repository
4. Render should auto-detect `render.yaml` and pre-fill the settings. If not, set manually:
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r backend/requirements.txt`
   - **Start Command:** `cd backend && uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Instance Type:** Free
5. Under **Environment Variables**, add:
   - `GROQ_API_KEY` = *(paste the key from Step 1)*
   - `GROQ_MODEL` = `llama-3.1-8b-instant` (optional — this is the default)
6. Click **Create Web Service**

Render will build and deploy — takes 2-5 minutes the first time. You'll get
a live URL like `https://marginal-xxxx.onrender.com`.

## Known free-tier limitations

- **Cold starts:** the free instance spins down after 15 minutes of no traffic. The next visit takes ~30-60 seconds to wake up. Normal — just a free-tier trade-off, not a bug.
- **In-memory storage:** documents disappear on every restart/spin-down, same as your local version.
- **Groq rate limits:** free tier allows 30 requests/minute, 14,400/day — far more than a demo or viva needs.
- **TF-IDF vs embeddings:** retrieval matches on keyword overlap rather than true semantic meaning, so it's slightly less forgiving of paraphrased questions than your local embedding-based version. Worth mentioning as a documented trade-off if asked in your viva.

## Testing it locally before deploying (optional but recommended)

```bash
cd backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
export GROQ_API_KEY=your_key_here   # Windows PowerShell: $env:GROQ_API_KEY="your_key_here"
uvicorn main:app --port 8000
```
Then open `http://localhost:8000` — same app, same code that goes to Render, just running on your machine first so you can catch any issues before deploying.
