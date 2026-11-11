# NORA cinematic motion showcase

Standalone offline renderer using verified NORA design tokens and source-derived UI labels. No Telegram requests or production dependencies; fictional/demo-only numeric values.

**Base code:** `cursor/nora-2-update-d133`, audited 2026-11-11. Source references: `community_bot/web/intro.js` (original `NoraLogo.markup()` SVG), `style.css`, `home.js`, `community.js`, `cabinet.js`, `shop.js`, `interactive.js`, `nora-game.js`.

**Output:** 22.5 seconds at 60 fps, H.264/AAC MP4, landscape 1920x1080 and portrait 1080x1920. Offline synthesized original sound design. No audio from the reference video.

**Install:** Python 3.10+, FFmpeg in PATH and `pip install -r tools/nora_motion/requirements.txt`.

**Render from repo root:**
```bash
bash tools/nora_motion/render_all.sh
```
Windows:
```powershell
./tools/nora_motion/render_all.ps1
```

The scripts save resulting MP4 files at the repository root. The renderer uses default available operating-system fonts unless `NORA_FONT`, `NORA_FONT_BOLD`, `NORA_FONT_MONO` point to fonts installed locally. The project's font files are not redistributed here.

## Fidelity limitations

This is a 2.5D product motion graphic, **not a pixel-perfect live browser recording**. The UI is a source-guided recreation using verified screen labels, styling conventions, CSS color tokens, and safe dummy data. Therefore it is not a complete replacement for capturing actual DOM screens with production CSS and fixtures. The game scene is a menu rather than invented 3D gameplay; implementation for the 3D world exists in `nora-game.js` and related modules but it is not rendered in this showcase. All inputs in this repository tool are synthetic and no production data is modified.

Scene proof:
- Brand and official vector: `web/intro.js`.
- Home and events: `web/home.js`.
- Community, leaderboard and lobbies: `web/community.js`.
- Profile / wallet: `web/cabinet.js`.
- Reputation and discounts: `web/cabinet.js` and `web/shop.js`.
- Store and cookies: `web/shop.js`.
- Game navigation: `web/interactive.js`, `web/nora-game.js`.

All motion, demo state changes, simulated scrolling and sound cues are reproducible from `render.py`.
