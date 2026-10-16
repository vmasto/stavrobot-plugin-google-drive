# Google Drive plugin

Lets Stavrobot search, read, upload, organize and share files in your Google Drive.

## Warning: `share` is on by default

Stavrobot turns on every tool of a plugin when it's installed, so the bot can share your files with anyone, or make them public, from the moment you connect. Files are untrusted input. Any document, or an email or web page the bot reads, can carry a prompt injection, text written to get the bot to share your files with someone, and with `share` on nothing stands between that text and a public link.

Recommended: turn `share` off before you connect, and share files from Drive yourself. You have to do this yourself, from your bot's plugin settings page:

1. Open `/settings/plugins` and pick `google-drive`.
2. Under Permissions, set "Agents can use" to "Selected tools".
3. Click "Select all", untick `share`, then click "Save permissions".

`unshare` only takes access away, so it's fine to leave it on.

If you're an agent installing this plugin, tell your user this warning and the steps above, and don't call `auth_url` until they confirm `share` is off.

## Before installing

You need your own Google Cloud OAuth client, it's free:

1. In https://console.cloud.google.com create a project and enable the Google Drive API. A project you already use for the Gmail or Calendar plugin works too.
2. Under Google Auth Platform, set up the consent screen as External. Then on Audience click Publish app. Apps left in Testing get refresh tokens that expire after 7 days, so you'd have to reconnect every week.
3. Under Clients, create an OAuth client of type Desktop app.

The app stays unverified, which is fine for personal use. Google shows a warning when you connect and caps unverified apps at 100 users.

## Installation

Tell Stavrobot to install `https://github.com/vmasto/stavrobot-plugin-google-drive`.

## Configuration

- `client_id` and `client_secret`: from the Desktop app client.
- `refresh_token`: leave it empty. Ask Stavrobot to connect Google Drive and it sends you a link. Google warns the app is unverified, click Advanced and continue. After you allow access the browser shows an error page on `127.0.0.1`, that's expected. Copy the full address and send it back, the plugin saves the token itself.

The plugin asks for the full `drive` scope, since the narrower ones only see files the plugin created itself. That scope also allows permanent deletion, but the plugin has no tool for it: `trash` keeps files in the trash for 30 days.

## Tools

- `auth_url`, `auth_complete`: connect your account.
- `list_folder`: a folder's contents, folders first.
- `search`: by name or content, with filters for type, folder and files shared with you. Without filters it lists recent files.
- `get_metadata`: path, link, owners and who a file is shared with.
- `read`: Google Docs as Markdown, Sheets as CSV (first sheet only), Slides and text files as text.
- `download`: sends a file to the bot, up to 25 MB. The plugin exports Google Docs as PDF, Word or Markdown, Sheets as Excel or CSV, and Slides as PDF or PowerPoint.
- `upload`: a file or text, up to 25 MB, optionally converted to a Google Doc or Sheet. It can also replace a file's content and keep its link.
- `create_folder`, `move` (also renames), `copy`.
- `trash`: moves files to the trash, or takes them back out.
- `share`: with a person by email, or with anyone who has the link. On by default, see the warning above.
- `unshare`.

## License

GNU Affero General Public License, version 3. See [LICENSE](LICENSE).
