# Cenflix app

The Cenflix homepage is served by `cenflix-server.js` and uses `shows_pl.csv`
from the repository root as its catalog source.

Run the app from this directory:

```powershell
node cenflix-server.js
```

Open `http://localhost:3000`. Set the `PORT` environment variable to use a
different port.

The API currently provides:

- `GET /api/health` — server and catalog status;
- `GET /api/filters` — available genres and platforms;
- `GET /api/series?q=...&sort=popular|new&genre=...&platform=...&limit=...` —
  catalog search and filtering;
- `GET /api/series/:id` — series metadata and platform availability;
- `GET /api/plans` — subscription plan data and source metadata;
- `GET /api/series/:id/compare?profile=binging|daily|weekly|custom&episodesPerWeek=...` —
  estimated cost and monthly billing cycles.

The catalog CSV does not contain subscription prices. The app and generated
GitHub Pages site read plan prices from `baza-seriali/plany.json`, transcribed
from `Plany_Streamingowe.xlsx`. The workbook does not include a verification
date, so the UI marks this metadata as missing.
