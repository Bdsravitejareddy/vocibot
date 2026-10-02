# VociBot Enterprise — clinic server

One Windows PC runs VociBot; doctors use it from their own laptops, tablets
or phones in a browser on the clinic network. Each doctor signs in with their
own account and sees only their own patients and consultations.

## Requirements

- Windows 10/11 or Windows Server 2019+, 64-bit, **16 GB RAM** (8 GB works with
  the `windows-8gb` profile and weaker notes), 4+ CPU cores, ~15 GB free disk
  plus ~8 GB per doctor per year of audio.
- [Ollama](https://ollama.com) for the note model. An NVIDIA GPU is used
  automatically when present and makes notes several times faster.
- A fixed IP address or DNS name for the PC on the clinic network.

## Install

1. Install Ollama.
2. Unzip this package, open **PowerShell as administrator** in the folder and run:

       powershell -ExecutionPolicy Bypass -File .\install.ps1

   Options: `-Port 8443`, `-HardwareProfile windows-8gb`.
3. Open `https://<server-name>:8443` and create the administrator account.
4. In **Users & security**, add each doctor. They choose their own password at
   first sign-in.

## Trust the clinic certificate (once per device)

Browsers only allow the microphone over trusted HTTPS. Download
`https://<server-name>:8443/ca.crt` on each device (accept the one-time
warning) and install it as a trusted root:

- **Windows**: double-click → Install Certificate → Local Machine →
  "Trusted Root Certification Authorities".
- **macOS**: double-click → Keychain Access → set to "Always Trust".
- **iPhone/iPad**: open the file → Settings → Profile Downloaded → Install, then
  Settings → General → About → Certificate Trust Settings → enable it.
- **Android**: Settings → Security → Install a certificate → CA certificate.

## Operating

- Data: `C:\ProgramData\VociBot\clinic-server` (database, recordings, models,
  certificates), readable only by Administrators. Back it up regularly.
- Hardware profile: `C:\ProgramData\VociBot\clinic-server\vocibot.env`
  (restart the "VociBot Enterprise Server" scheduled task after editing).
- Locked-out administrator: in an elevated prompt run
  `"C:\Program Files\VociBot Enterprise Server\vocibot-server.exe" reset-admin-password --username <name>`.
- Uninstall: `uninstall.ps1` (keeps clinical data unless `-DeleteData`).

## Capacity (measured; see docs/ENTERPRISE.md)

On a 4-core CPU without a GPU, two doctors get live text at once (about 2–4 s
behind speech); others are recorded and get the full transcript after Stop.
The note model is loaded once and shared, so memory stays at ~8–9 GB however
many doctors use the server; extra doctors wait in a queue for their notes.
