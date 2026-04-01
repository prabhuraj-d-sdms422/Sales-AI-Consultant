## HubSpot CRM integration — setup guide

This project can send each captured lead into **HubSpot Contacts**, attach a **note** with problem/solutions, and store the **HubSpot contact URL** back into Excel, Google Sheets, JSON, and the notification email.

### 1. Create a HubSpot Private App

1. Log into your HubSpot account.
2. Click the **gear (Settings)** icon (top-right).
3. In the left menu, go to **Account Setup → Integrations → Private Apps**  
   (or search for “Private Apps” in settings search).
4. Click **Create private app**.
5. Give it a name, e.g. `Stark AI Sales Consultant`.

### 2. Set required scopes

On the **Scopes** tab of the private app:

1. Search for and enable (at minimum):
   - `crm.objects.contacts` — **Read and Write**
   - `crm.objects.notes` — **Read and Write**
2. Save the app.

These scopes allow the backend to:

- Create or update **Contacts**.
- Create **Notes** associated with those contacts.

### 3. Copy the access token

1. On the private app details page, go to the **Auth** tab.
2. Click **Show token** and copy the **Access Token**.
3. Store it securely — this is your **server-side** secret.

### 4. Find your Portal ID (Hub ID)

1. With HubSpot open, look at the URL bar on any Contacts page.
2. The URL looks like:

   ```text
   https://app.hubspot.com/contacts/<PORTAL_ID>/contact/...
   ```

3. Copy `<PORTAL_ID>` — this is the value you need for the `.env`.

### 5. Configure `.env`

In the repo root `.env`, set:

```env
HUBSPOT_ENABLED=true
HUBSPOT_ACCESS_TOKEN=pat-na1-...
HUBSPOT_PORTAL_ID=12345678
```

Notes:

- `HUBSPOT_ENABLED`: turns the integration on/off.
- `HUBSPOT_ACCESS_TOKEN`: the Private App access token from step 3.
- `HUBSPOT_PORTAL_ID`: the numeric Hub ID from the URL.
- The code also accepts a common typo `UBSPOT_PORTAL_ID` for safety, but **use `HUBSPOT_PORTAL_ID`** in new environments.

### 6. How the integration behaves

When a lead is delivered (conversion / escalation), the backend will:

1. Enrich the lead from the recent conversation using the LLM to get:
   - A short **problem summary**.
   - A short **solutions summary**.
2. Create or update a **Contact** in HubSpot:
   - `firstname`, `lastname` (from the user’s name, e.g. “Rohit Sharma”).
   - `email` (if available).
   - `phone` (if available).
   - `company` (if available).
3. Create a **Note** attached to that contact containing:
   - Session ID.
   - Problem / context summary.
   - Solutions discussed.
4. If `HUBSPOT_PORTAL_ID` is set, build the record URL:

   ```text
   https://app.hubspot.com/contacts/<PORTAL_ID>/record/0-1/<CONTACT_ID>
   ```

5. Store that URL as `hubspot_contact_url` in:
   - Lead JSON (`backend/data/leads/{session_id}.json`).
   - Excel and Google Sheets (column **HubSpot URL**).
   - Lead notification email (row **HubSpot**).

If **email and phone are both missing**, HubSpot sync is skipped (there’s nothing stable to upsert on).

### 7. Testing the integration

1. Ensure `.env` is configured and the backend is restarted.
2. Start a new chat in the frontend.
3. Provide, at some point in the conversation:
   - Your **name** (e.g. “I’m Rohit Sharma from Acme Logistics”).
   - **Email** (e.g. `rohit@example.com`).
   - Optional **phone**.
   - A short description of your **problem**.
4. Ask for human follow-up (e.g. “Please have your team contact me”).

Then verify:

#### A. HubSpot

- Go to **Contacts** and search for the email you used.
- Open the contact:
  - Confirm name, email, phone, company are populated (where provided).
  - Check there is a **Note** listing the problem and solutions.

#### B. Google Sheet / Excel

- Open the lead tracker (local Excel or Google Sheet).
- Confirm the new row has:
  - Problem column filled with a short summary.
  - Solutions Discussed filled with a short summary.
  - **HubSpot URL** column containing a clickable link.

### 8. Common troubleshooting tips

- **No contact appears in HubSpot**:
  - Check backend logs for `HubSpot contact create failed` or auth errors.
  - Confirm the access token is valid and not expired.
  - Verify the Private App has `crm.objects.contacts` write scope.

- **Contact is created but URL column is blank**:
  - Usually means `HUBSPOT_PORTAL_ID` is missing or wrong in `.env`.
  - Fix the env value and restart the backend.

- **Permission errors when creating notes**:
  - Ensure the Private App also has `crm.objects.notes` read/write scope.

