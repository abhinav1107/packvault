# PackVault branding assets

All icons are generated from **`logo.png`** (1024×1024 master). Update that file, then regenerate:

```bash
python scripts/generate_branding_assets.py
```

## Files

| File | Use |
|------|-----|
| `logo.png` | Source of truth — edit this only |
| `icon-16.png` … `icon-512.png` | UI `<link rel="icon">`, docs, README, manifests |
| `favicon.ico` | Browser default (`/favicon.ico`); also copied to `../favicon.ico` |

## Sizes

- **16, 32, 48** — favicon / tab icons
- **180** — Apple touch icon
- **192, 512** — PWA / Open Graph–style references
