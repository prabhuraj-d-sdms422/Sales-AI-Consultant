## Google Sheets integration — setup guide

This project can mirror each lead row into a **Google Sheet** for an easy, shareable lead tracker.

### 1. Create / configure a Google Cloud project

1. Go to [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project or pick an existing one.
3. In the left menu, go to **APIs & Services → Library**.
4. Search for **Google Sheets API** and click **Enable**.

### 2. Create a service account and JSON key

1. In the same project, go to **APIs & Services → Credentials**.
2. Click **Create Credentials → Service Account**.
3. Give it a name, e.g. `stark-ai-sheets-writer`.
4. Finish the wizard (no special roles needed beyond default for this use).
5. After the service account is created, open it and go to the **Keys** tab.
6. Click **Add Key → Create new key → JSON**.
7. Download the JSON file.

### 3. Place the JSON key in the repo (not in git)

1. On your machine, create the `credentials/` folder at the repo root if it doesn’t exist:

   ```bash
   mkdir -p credentials
   ```

2. Move the downloaded JSON file into `credentials/` and rename it (optional) to:

   ```text
   credentials/google_sheets_credentials.json
   ```

The `credentials/` folder is already **ignored by git**, so the key will not be committed.

### 4. Create the Google Sheet and get the Spreadsheet ID

1. Go to [Google Sheets](https://sheets.google.com/).
2. Create a new spreadsheet, e.g. `AI Sales Consultant Leads`.
3. The URL will look like:

   ```text
   https://docs.google.com/spreadsheets/d/<SPREADSHEET_ID>/edit#gid=0
   ```

4. Copy the `<SPREADSHEET_ID>` part for your `.env`.

### 5. Share the sheet with the service account

1. Open the JSON key file and copy the `"client_email"` value.
2. In the Google Sheet, click **Share**.
3. Paste the `client_email` as a collaborator.
4. Give it **Editor** access.

Without this step, the API calls will fail with `PERMISSION_DENIED`.

### 6. Configure `.env`

In the repo root `.env`, set:

```env
GOOGLE_SHEETS_ENABLED=true
GOOGLE_SHEETS_CREDENTIALS_FILE=credentials/google_sheets_credentials.json
GOOGLE_SHEETS_SPREADSHEET_ID=your_spreadsheet_id_here
GOOGLE_SHEETS_WORKSHEET_NAME=Leads
```

- `GOOGLE_SHEETS_ENABLED`: turns the integration on/off.
- `GOOGLE_SHEETS_CREDENTIALS_FILE`: path to the JSON key file (relative to repo root).
- `GOOGLE_SHEETS_SPREADSHEET_ID`: from the URL in step 4.
- `GOOGLE_SHEETS_WORKSHEET_NAME`: the tab name that should receive rows (default `Leads`).

### 7. How the integration behaves

On each lead delivery, the backend will:

1. Build a row with:
   - Timestamp
   - Lead temperature
   - Name, company, email, phone, industry
   - Problem summary
   - Budget signal, urgency, decision maker
   - Solutions discussed, objections raised
   - Stage, session id
   - HubSpot URL (if HubSpot is enabled)
2. Append the same row to:
   - `backend/data/leads.xlsx`
   - The configured Google Sheet (when enabled).

If the sheet is empty, the code writes a full header row. If it detects the older header set (before the `HubSpot URL` column), it automatically **upgrades** the header row to include that column.

Phone numbers that start with `+` are written as **text**, so Google Sheets does not misinterpret them as formulas.

### 8. Testing the integration

1. Ensure `.env` is configured and the backend has been restarted.
2. Start a new chat and go through a typical lead flow, including:
   - Name, company
   - Email and/or phone
   - A brief description of the problem
3. Trigger lead delivery (e.g. “Please have your team contact me”).
4. Open the Google Sheet and verify:
   - A new row appears with the correct cells populated.
   - The header row includes **HubSpot URL**.

If no row appears:

- Check backend logs for `append_lead_google_sheets` errors.
- Confirm the spreadsheet ID and worksheet name are correct.
- Make sure the service account email has **Editor** access on the sheet.

