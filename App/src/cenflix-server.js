"use strict";

const fs = require("node:fs");
const path = require("node:path");
const express = require("express");

const app = express();
const port = Number(process.env.PORT) || 3000;
const publicDir = path.join(__dirname, "public");
const catalogPath = path.resolve(__dirname, "..", "..", "shows_pl.csv");

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;

  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];

    if (quoted) {
      if (char === '"' && text[i + 1] === '"') {
        field += '"';
        i += 1;
      } else if (char === '"') {
        quoted = false;
      } else {
        field += char;
      }
    } else if (char === '"') {
      quoted = true;
    } else if (char === ",") {
      row.push(field);
      field = "";
    } else if (char === "\n" || char === "\r") {
      if (char === "\r" && text[i + 1] === "\n") i += 1;
      row.push(field);
      if (row.some((value) => value !== "")) rows.push(row);
      row = [];
      field = "";
    } else {
      field += char;
    }
  }

  if (field !== "" || row.length > 0) {
    row.push(field);
    if (row.some((value) => value !== "")) rows.push(row);
  }

  return rows;
}

function splitList(value) {
  return value ? value.split(",").map((item) => item.trim()).filter(Boolean) : [];
}

function parseOptionalBoolean(value) {
  if (value.toLowerCase() === "yes") return true;
  if (value.toLowerCase() === "no") return false;
  return null;
}

function parseOptionalNumber(value) {
  if (value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function loadCatalog() {
  const csv = fs.readFileSync(catalogPath, "utf8").replace(/^\uFEFF/, "");
  const [header, ...records] = parseCsv(csv);
  const columns = new Map(header.map((name, index) => [name, index]));
  const requiredColumns = ["Service", "Title", "Years", "Seasons", "Episodes", "Type"];

  for (const name of requiredColumns) {
    if (!columns.has(name)) throw new Error(`Missing "${name}" column in ${catalogPath}`);
  }

  const value = (record, name) => record[columns.get(name)] || "";
  const seriesById = new Map();

  for (const record of records) {
    if (value(record, "Type").toLowerCase() !== "series") continue;

    const title = value(record, "Title").trim();
    if (!title) continue;

    const imdbId = value(record, "IMDb id").trim();
    const tmdbId = value(record, "TMDB id").trim();
    const years = value(record, "Years").trim();
    const key = imdbId || tmdbId || `${title.toLowerCase()}-${years}`;
    let series = seriesById.get(key);

    if (!series) {
      const premiereYear = Number((years.match(/\d{4}/) || [])[0]) || null;
      series = {
        id: imdbId || tmdbId || key,
        title,
        originalTitle: value(record, "Original title").trim() || null,
        years,
        premiereYear,
        seasons: parseOptionalNumber(value(record, "Seasons")),
        episodes: parseOptionalNumber(value(record, "Episodes")),
        genres: splitList(value(record, "Genres")),
        rating: parseOptionalNumber(value(record, "Rating (0-100)")),
        availabilities: [],
        platforms: [],
      };
      seriesById.set(key, series);
    }

    const service = value(record, "Service").trim();
    if (!service || series.availabilities.some((item) => item.service === service)) continue;

    series.availabilities.push({
      service,
      polishAudio: parseOptionalBoolean(value(record, "Polish audio")),
      polishSubtitles: parseOptionalBoolean(value(record, "Polish subtitles")),
      audioLanguages: splitList(value(record, "Audio languages")),
      subtitleLanguages: splitList(value(record, "Subtitle languages")),
      maxQuality: value(record, "Max quality").trim() || null,
      access: value(record, "Access").trim() || null,
      leavingOn: value(record, "Leaving on").trim() || null,
      url: value(record, "Link").trim() || null,
    });
    series.platforms.push(service);
  }

  return Array.from(seriesById.values());
}

const catalog = loadCatalog();

function compareText(left, right) {
  return left.localeCompare(right, "pl", { sensitivity: "base" });
}

function filteredCatalog({ query, sort, genre, platform }) {
  const normalizedQuery = query.toLocaleLowerCase("pl");
  let results = catalog.filter((series) => {
    const matchesQuery =
      !normalizedQuery ||
      series.title.toLocaleLowerCase("pl").includes(normalizedQuery) ||
      (series.originalTitle &&
        series.originalTitle.toLocaleLowerCase("pl").includes(normalizedQuery));
    const matchesGenre = !genre || series.genres.includes(genre);
    const matchesPlatform = !platform || series.platforms.includes(platform);
    return matchesQuery && matchesGenre && matchesPlatform;
  });

  if (sort === "new") {
    results = results.sort((a, b) => (b.premiereYear || 0) - (a.premiereYear || 0) || compareText(a.title, b.title));
  } else {
    results = results.sort((a, b) => (b.rating || 0) - (a.rating || 0) || compareText(a.title, b.title));
  }
  return results;
}

app.get("/api/health", (req, res) => {
  res.json({ status: "ok", catalogCount: catalog.length, dataSource: "shows_pl.csv" });
});

app.get("/api/filters", (req, res) => {
  const genres = new Set();
  const platforms = new Set();
  for (const series of catalog) {
    series.genres.forEach((genre) => genres.add(genre));
    series.platforms.forEach((platform) => platforms.add(platform));
  }
  res.json({
    genres: Array.from(genres).sort(compareText),
    platforms: Array.from(platforms).sort(compareText),
  });
});

app.get("/api/series", (req, res) => {
  const query = typeof req.query.q === "string" ? req.query.q.trim() : "";
  const sort = typeof req.query.sort === "string" ? req.query.sort : "popular";
  const genre = typeof req.query.genre === "string" ? req.query.genre : "";
  const platform = typeof req.query.platform === "string" ? req.query.platform : "";
  const limitValue = req.query.limit === undefined ? "12" : req.query.limit;
  const limit = Number(limitValue);

  if (query.length > 100) {
    return res.status(400).json({ error: "Search query must be 100 characters or fewer." });
  }
  if (sort !== "popular" && sort !== "new") {
    return res.status(400).json({ error: 'Sort must be "popular" or "new".' });
  }
  if (!Number.isInteger(limit) || limit < 1 || limit > 50) {
    return res.status(400).json({ error: "Limit must be an integer between 1 and 50." });
  }

  const results = filteredCatalog({ query, sort, genre, platform });
  res.json({ items: results.slice(0, limit), total: results.length });
});

app.get("/api/series/:id", (req, res) => {
  const series = catalog.find((item) => item.id === req.params.id);
  if (!series) return res.status(404).json({ error: "Series not found." });
  res.json(series);
});

app.use(express.static(publicDir));
app.get("/", (req, res) => {
  res.sendFile(path.join(publicDir, "index.html"));
});

app.listen(port, () => {
  console.log(`Cenflix is running at http://localhost:${port}`);
});
