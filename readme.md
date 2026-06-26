# Local Stream Clipper Studio

A local, agentic workflow automation tool that uses yt-dlp, FFmpeg, and Gemini 2.5 Flash to automatically identify, slice, and upload high-retention viral clips from YouTube VODs and Live Streams to Google Drive, while logging metadata to Google Sheets.

This guide covers the necessary steps to configure your API keys, Google Cloud OAuth credentials, and local environment variables required to boot the application.

---

## 1. Setting up the Gemini API Key

The application uses Google's Gemini model to analyze transcripts and identify viral moments.

1. Navigate to [Google AI Studio](https://aistudio.google.com/).
2. Sign in with your Google account.
3. On the left sidebar, click **Get API key**.
4. Click **Create API key** and generate a key in a new or existing project.
5. Copy the generated string. You will need this for Step 4.

---

## 2. Setting up OAuth for Google Drive & Sheets

Because this application reads and writes data to your personal Google Sheets and Google Drive, it requires OAuth 2.0 verification.

### A. Create a Google Cloud Project
1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Click the project dropdown at the top left and select **New Project**. Name it something like "Stream Clipper App" and click **Create**.

### B. Enable Required APIs
1. In the Cloud Console search bar, search for **Google Drive API** and click **Enable**.
2. Search for **Google Sheets API** and click **Enable**.

### C. Configure the OAuth Consent Screen
1. Go to **APIs & Services > OAuth consent screen**.
2. Choose **External** (unless you have a Google Workspace org) and click **Create**.
3. Fill out the required fields (App Name, User Support Email, Developer Contact Info). You can skip the rest.
4. Click **Save and Continue** through the Scopes and Test Users screens (add your own email as a Test User to ensure you can log in).

### D. Generate Credentials
1. Go to **APIs & Services > Credentials**.
2. Click **Create Credentials** > **OAuth client ID**.
3. Set the Application type to **Desktop app**. Name it (e.g., "Clipper Desktop") and click **Create**.
4. Click the **Download JSON** button on the confirmation screen.
5. Rename the downloaded file to exactly `client_secrets.json`.
6. **Move this file into the root directory of this project.**

*(Note: On your first run, a browser window will open asking you to log in and grant permissions. A `token.pickle` file will be generated automatically so you don't have to log in every time).*

---

## 3. Getting your Google Drive Folder ID

The application needs a master folder in your Google Drive where it will dynamically create sub-folders for each VOD.

1. Open [Google Drive](https://drive.google.com/) in your browser.
2. Create a new folder (e.g., "Stream Clips Master") or open an existing one.
3. Look at the URL in your browser's address bar. It will look like this:
   `https://drive.google.com/drive/folders/1G9UwjtRUlkdFbiYY1x-i7qStoc4vSFKy`
4. The long string of characters at the end is your **Folder ID**.
5. Open `config/settings.py` in your code editor.
6. Locate the `master_drive_folder_id` variable and replace the default string with your specific Folder ID.

---

## 4. Initializing Environment Variables

The application's `config/settings.py` file requires certain variables to be available in your operating system's environment to boot securely. 

### Windows (Command Prompt)
To set the variable temporarily for the current session:
```cmd
set GEMINI_API_KEY=your_actual_api_key_here