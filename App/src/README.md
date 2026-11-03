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
- `GET /api/series/:id` — series metadata and platform availability.

The source CSV has no current subscription plan prices, so the homepage does
not invent cost estimates. Price comparison will need a separate, verified
plan and pricing data source.
