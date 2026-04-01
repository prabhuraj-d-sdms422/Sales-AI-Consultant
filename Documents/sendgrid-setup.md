## SendGrid integration — setup guide

This project uses SendGrid to email a **lead snapshot** to your sales inbox after every captured lead.

### 1. Create a SendGrid account and API key

1. Go to [SendGrid](https://sendgrid.com/) and create / log into your account.
2. In the left menu, go to **Settings → API Keys**.
3. Click **Create API Key**.
4. Choose a name like `stark-ai-sales-consultant`.
5. Permission: **Full Access** or at least **Mail Send**.
6. Click **Create & View** and **copy the key once** (you will not see it again).

### 2. Verify a sender identity

SendGrid will not send from arbitrary email addresses. You must verify at least one sender:

1. In the left menu, go to **Settings → Sender Authentication**.
2. Choose one:
   - **Single Sender Verification** (fastest for dev)
   - or **Domain Authentication** (recommended for production).
3. For **Single Sender**:
   - Click **Create New Sender**.
   - Fill in **From Name** (e.g. `Stark Digital AI Sales Consultant`).
   - **From Email** (e.g. `noreply@your-domain.com` or a Gmail address for testing).
   - Complete the verification email.

You need a **verified** email address for `SENDGRID_FROM_EMAIL`.

### 3. Configure `.env`

In the repo root `.env`, set:

```env
SENDGRID_API_KEY=your_sendgrid_api_key_here
SENDGRID_FROM_EMAIL=verified_sender@example.com
SENDGRID_FROM_NAME=Stark Digital AI Sales Consultant
SENDGRID_TO_EMAIL=sales@your-company.com
SENDGRID_SANDBOX_MODE=false
```

- `SENDGRID_API_KEY`: the key you created in step 1.
- `SENDGRID_FROM_EMAIL`: must match a **verified sender**.
- `SENDGRID_FROM_NAME`: label visible in the inbox.
- `SENDGRID_TO_EMAIL`: one or more recipients (comma-separated) who should receive lead notifications.
- `SENDGRID_SANDBOX_MODE=true` will send requests to SendGrid but **not deliver real emails** (useful for testing).

### 4. How the integration behaves

When a lead is delivered (conversion / escalation), the backend will:

1. Save a JSON snapshot in `backend/data/leads/{session_id}.json`.
2. Append a row to `backend/data/leads.xlsx` and optionally Google Sheets.
3. Call SendGrid with a summary of:
   - Session ID
   - Lead temperature and stage
   - Name, company, email, phone, industry
   - Problem summary
   - Budget signal and urgency
   - Solutions discussed and objections raised

If `SENDGRID_API_KEY`, `SENDGRID_FROM_EMAIL`, or `SENDGRID_TO_EMAIL` is missing, email sending is **silently disabled** (no exception).

### 5. Testing the integration

1. Ensure the backend is running with the `.env` values above.
2. Open the frontend (`npm run dev` from `frontend/`) and start a new session.
3. In a conversation, provide at least:
   - Name
   - Company
   - Email (must be valid)
   - Optional phone and problem description
4. Ask for human follow-up (e.g. “Please have your team contact me”).
5. You should see a new email in the inbox defined in `SENDGRID_TO_EMAIL`.

If no email arrives:

- Check backend logs for lines containing `SendGrid` for status codes.
- Verify the API key is correct and not restricted.
- Confirm `SENDGRID_FROM_EMAIL` is a verified sender.

