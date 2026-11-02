// use node in version 18
const express = require("express");
const Database = require("better-sqlite3");
const bcrypt = require("bcryptjs");
const session = require("express-session");
const path = require("path");

const app = express();
const db = new Database("main.sqlite");

db.exec(`
  CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    type TEXT NOT NULL,
    profile TEXT NOT NULL,
    language TEXT NOT NULL,
    list_id INT 
  )
`);

app.use(express.urlencoded({ extended: false }));

app.use(session({
  secret: process.env.SESSION_SECRET || "4",
  resave: false,
  saveUninitialized: false,
  cookie: {
    httpOnly: true,
    sameSite: "lax",
    secure: false,
    maxAge: 86400000
  }
}));

app.use(express.static(path.join(__dirname, "public")));

app.get('/login', (req, res) => {
  res.sendFile(__dirname + '/login.html');
});
app.get('/register', (req, res) => {
  res.sendFile(__dirname + '/login.html');
});

// Create user
if (process.argv[2] === "create-user") {
  const email = (process.argv[3] || "").trim().toLowerCase();
  const password = process.argv[4] || "";
  const type = process.argv[5] || "user";
  const profileType = process.argv[6] || "binging";
  const language = process.argv[7] || "en-US";
  const listID = db.prepare(
      "SELECT COUNT(*) as count FROM users"
  ).get();

  if (!email || password.length < 4) {
    console.log("Usage: node server.js create-user email password (user type) (profile type) (language)");
    process.exit(1);
  }
  const users = db.prepare(
      "SELECT * FROM users WHERE email = ?"
  ).get(email);
  if (users){
      console.log("User already exists");
      process.exit(1);
  }

  try {
    const hash = bcrypt.hashSync(password, 12);

    db.prepare(
      "INSERT INTO users (email, password,type, profile, language,list_id) VALUES (?, ?, ?, ?, ?, ?)"
    ).run(email, hash,type,profileType,language,listID.count+1);

    console.log("User created!");
  } catch (err) {
    console.log("Error:", err.message);
  }

  process.exit(0);
}

// Register
app.post("/register", async (req, res) => {
  const email = (req.body.email || "").trim().toLowerCase();
  const password = req.body.password || "";
  const header = req.headers["accept-language"] || "";
  const language = header.split(",")[0].split(";")[0].trim() || "en-US";
  
  if (!email|| password.length < 4) {
    return res.status(400).send("Email must be valid and password at least 4 characters.");
  }
  
  const exists = db.prepare("SELECT id FROM users WHERE email = ?").get(email);
  if (exists) {
    return res.status(409).send("An account with this email already exists.");
  }
  
  const hash = bcrypt.hashSync(password, 12);
  const listID = db.prepare("SELECT COUNT(*) as count FROM users").get().count;
  const result = db.prepare(
    "INSERT INTO users (email, password, type, profile, language, list_id) VALUES (?, ?, 'user', 'binging', ?, ?)"
  ).run(email, hash, language, listID + 1);
  
  req.session.regenerate((err) => {
    if (err) return res.status(500).send("Session error.");
    req.session.userId = result.lastInsertRowid;
    req.session.email = email;
    req.session.save(() => res.redirect("/dashboard"));
  });
});


// Login
app.post("/login", async (req, res) => {
  const email = (req.body.email || "").trim().toLowerCase();
  const password = req.body.password || "";

  const user = db.prepare(
    "SELECT * FROM users WHERE email = ?"
  ).get(email);

  if (!user || !(await bcrypt.compare(password, user.password))) {
    return res.status(401).send("Wrong email or password.");
  }

  req.session.regenerate((err) => {
    if (err) return res.status(500).send("Session error.");

    req.session.userId = user.id;
    req.session.email = user.email;

    req.session.save((err) => {
      if (err) return res.status(500).send("Session error.");
      res.redirect("/dashboard");
    });
  });
});

// Protected dashboard
app.get("/dashboard", (req, res) => {
  if (!req.session.userId) {
    return res.redirect("/");
  }

  res.send(`
    <h1>Welcome!</h1>
    <p>Logged in as: ${escapeHtml(req.session.email)}</p>
    <form action="/logout" method="POST">
      <button type="submit">Logout</button>
    </form>
  `);
});

// Logout
app.post("/logout", (req, res) => {
  req.session.destroy(() => {
    res.clearCookie("connect.sid");
    res.redirect("/");
  });
});

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, c => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  })[c]);
}

app.listen(3000, () => {
  console.log("Running at http://localhost:3000");
});
