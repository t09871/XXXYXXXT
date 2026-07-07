import sqlite3
conn = sqlite3.connect(r"output\database\mr-review.db")
print(conn.execute("SELECT COUNT(*) FROM crop_species").fetchone())
print(conn.execute("PRAGMA table_info(crop_species)").fetchall())
print(conn.execute("SELECT crop_path, species_guess, prediction_source FROM crop_species LIMIT 5").fetchall())