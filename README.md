# Vinci-Cut AI Agent

**Your Intelligent Video Editor Assistant.** Upload a video, chat with an AI about it, and let it generate viral shorts, rough cuts, and professional color grades — ready to render or import straight into DaVinci Resolve.

**Status:** soft-launched with real Stripe billing — around 500 people tried the product.

## What it does

- **AI video analysis & chat** — upload a video, then chat with an AI (Google Gemini / OpenAI) about its content. The assistant can identify "viral clip" candidates inside a longer video.
- **Automated clip rendering** — render detected or custom clips in different styles (`viral`, `rough_cut`, or a custom AI-chosen style) via FFmpeg.
- **AI color grading for DaVinci Resolve** — an AI "colorist" persona generates a structured color grade (ASC CDL values: slope / offset / power / saturation, plus sliders) that can be imported into DaVinci Resolve (see `resolve_colorslice_guide.png`).
- **Accounts & billing** — email/password auth (JWT), a credits system, and Stripe Checkout + a billing portal for subscriptions.
- **Cloud storage** — uploaded videos are stored in Cloudflare R2 (S3-compatible) via presigned URLs, so large files never pass through the app server directly.
- **Transactional email** — signup verification and password reset emails sent via Resend.

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI |
| Database | PostgreSQL in production (via SQLAlchemy), falls back to local SQLite for development |
| Frontend | Vanilla HTML/CSS/JavaScript (`index.html`, `style.css`, `app.js`) — no build step |
| Auth | JWT (python-jose) + bcrypt password hashing |
| Payments | Stripe (Checkout Sessions, webhooks, billing portal) |
| Storage | Cloudflare R2 (via `boto3`, S3-compatible API) |
| AI | Google Gemini (`google-genai`) and OpenAI, used for chat, clip detection, and color grading |
| Email | Resend |
| Video processing | FFmpeg (via `imageio-ffmpeg`) |
| Deployment | Docker (see `Dockerfile`); designed to run on Railway |

## Project structure

```
.
├── main.py          # FastAPI app: all routes, auth, AI prompts, Stripe, R2, rendering
├── database.py       # SQLAlchemy models and DB session setup
├── index.html         # Single-page frontend
├── app.js              # Frontend logic
├── style.css            # Frontend styling
├── Dockerfile
├── requirements.txt
└── .env.example         # Template for required environment variables
```

## Getting started

### 1. Prerequisites

- Python 3.11+
- FFmpeg (installed automatically by `imageio-ffmpeg`, or via the Dockerfile)
- Accounts/API keys for: a Postgres database (or just use local SQLite), Google AI Studio and/or OpenAI, Stripe, Cloudflare R2, and Resend — depending on which features you want to run locally.

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Then fill in `.env` with real values. See the table below for what each variable does. **Never commit `.env`** — it's already covered by `.gitignore`.

| Variable | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | No (defaults to local SQLite) | PostgreSQL connection string |
| `GOOGLE_API_KEY` | For AI features | Google Gemini API key |
| `OPENAI_API_KEY` | Optional | OpenAI API key |
| `STRIPE_API_KEY` | For payments | Stripe secret key |
| `STRIPE_WEBHOOK_SECRET` | For payments | Stripe webhook signing secret |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY`, `R2_SECRET_KEY`, `R2_BUCKET_NAME` | For uploads | Cloudflare R2 storage credentials |
| `RESEND_API_KEY` | For emails | Resend API key |
| `SECRET_KEY` | **Yes** | Random secret used to sign JWT auth tokens. Generate your own: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `FRONTEND_URL` | No | Base URL used to build links in outgoing emails |

### 4. Run locally

```bash
python main.py
```

The app serves the API and the static frontend together, on the port from the `PORT` env var (defaults to `8000`).

### 5. Run with Docker

```bash
docker build -t vinci-cut-ai .
docker run -p 8000:8000 --env-file .env vinci-cut-ai
```

## Security notes

This repository was cleaned up from an earlier version that had API keys, a Stripe secret key, a database connection string, and the JWT signing secret **hardcoded directly in the source**. All of those have been moved to environment variables (see `.env.example`). If you're reusing credentials from an older deployment of this project, **rotate every one of them** (Stripe, the database password, R2, OpenAI, Google, Resend, and especially `SECRET_KEY`, which must be a fresh random value — not a placeholder) before redeploying.

## License

No license has been specified yet. All rights reserved by default until one is added.
