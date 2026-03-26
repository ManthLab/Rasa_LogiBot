const mysql = require("mysql2");
const fs = require("fs");

// DB Connection
const db = mysql.createConnection({
  host: "localhost",
  user: "root",
  password: "12345",
  database: "logibot_db"
});

// Connect to DB
db.connect(err => {
  if (err) throw err;
  console.log("Connected to DB ✅");

  // ✅ Create session AFTER connection
  const sessionId = "sess_" + Date.now();

  db.query(
    "INSERT INTO sessions (session_id) VALUES (?)",
    [sessionId],
    (err) => {
      if (err) throw err;
      console.log("Session Created:", sessionId);
    }
  );

  // Load JSON
  const bookings = JSON.parse(fs.readFileSync("bookings.json"));

  // Insert bookings
  bookings.forEach(b => {
    const query = `
      INSERT INTO bookings 
      (booking_id, sender_name, sender_number, sender_email,
       receiver_name, receiver_number, delivery_address, cost, booked_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, NOW())
    `;

    db.query(query, [
      b.booking_id,
      b.sender,
      b.sender_number,
      b.sender_email,
      b.receiver,
      b.receiver_number,
      b.delivery_address || b.location || "",
      b.cost
    ]);
  });

  console.log("Bookings Imported ✅");
});