# db_setup_advanced.py

import mysql.connector
from mysql.connector import errorcode
import hashlib

# --- Your MySQL Connection Details ---
DB_HOST = 'localhost'
DB_USER = 'root'
DB_PASSWORD = 'your_password'  # <-- IMPORTANT: Change this!
DB_NAME = 'advanced_library_db' # Using a new DB name to avoid conflicts

def hash_password(password):
    """Hashes the password using SHA-256."""
    return hashlib.sha256(password.encode()).hexdigest()

def create_database():
    """Creates the database and all necessary tables for the advanced system."""
    try:
        # Connect to MySQL Server
        db = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD
        )
        cursor = db.cursor()
        print("Successfully connected to MySQL server.")

        # Create the database
        try:
            cursor.execute(f"CREATE DATABASE {DB_NAME} DEFAULT CHARACTER SET 'utf8'")
            print(f"Database '{DB_NAME}' created successfully.")
        except mysql.connector.Error as err:
            if err.errno == errorcode.ER_DB_CREATE_EXISTS:
                print(f"Database '{DB_NAME}' already exists.")
            else:
                print(err)
                return

        cursor.execute(f"USE {DB_NAME}")
        print(f"Using database '{DB_NAME}'.")

        # --- Table Definitions ---
        TABLES = {}

        TABLES['users'] = (
            "CREATE TABLE `users` ("
            "  `user_id` INT AUTO_INCREMENT PRIMARY KEY,"
            "  `username` VARCHAR(50) NOT NULL UNIQUE,"
            "  `password_hash` VARCHAR(256) NOT NULL,"
            "  `role` VARCHAR(20) NOT NULL DEFAULT 'librarian'"
            ") ENGINE=InnoDB"
        )

        TABLES['members'] = (
            "CREATE TABLE `members` ("
            "  `member_id` INT AUTO_INCREMENT PRIMARY KEY,"
            "  `name` VARCHAR(255) NOT NULL,"
            "  `email` VARCHAR(255) UNIQUE,"
            "  `phone` VARCHAR(20)"
            ") ENGINE=InnoDB"
        )

        TABLES['books'] = (
            "CREATE TABLE `books` ("
            "  `book_id` INT AUTO_INCREMENT PRIMARY KEY,"
            "  `title` VARCHAR(255) NOT NULL,"
            "  `author` VARCHAR(255) NOT NULL,"
            "  `genre` VARCHAR(100),"
            "  `status` VARCHAR(20) NOT NULL DEFAULT 'Available'"
            ") ENGINE=InnoDB"
        )

        TABLES['issued_books'] = (
            "CREATE TABLE `issued_books` ("
            "  `issue_id` INT AUTO_INCREMENT PRIMARY KEY,"
            "  `book_id` INT NOT NULL,"
            "  `member_id` INT NOT NULL,"
            "  `issue_date` DATE NOT NULL,"
            "  `due_date` DATE NOT NULL,"
            "  `return_date` DATE,"
            "  FOREIGN KEY (`book_id`) REFERENCES `books`(`book_id`) ON DELETE CASCADE,"
            "  FOREIGN KEY (`member_id`) REFERENCES `members`(`member_id`) ON DELETE CASCADE"
            ") ENGINE=InnoDB"
        )
        
        TABLES['settings'] = (
            "CREATE TABLE `settings` ("
            "  `setting_key` VARCHAR(50) PRIMARY KEY,"
            "  `setting_value` VARCHAR(255) NOT NULL"
            ") ENGINE=InnoDB"
        )

        # --- Create Tables ---
        for table_name, table_description in TABLES.items():
            try:
                print(f"Creating table '{table_name}': ", end='')
                cursor.execute(table_description)
                print("OK")
            except mysql.connector.Error as err:
                if err.errno == errorcode.ER_TABLE_EXISTS_ERROR:
                    print("already exists.")
                else:
                    print(err.msg)
        
        # --- Insert Default Data ---
        print("Inserting default data...")
        try:
            # Add a default admin user (password: admin)
            admin_pass = hash_password('admin')
            cursor.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
                ('admin', admin_pass, 'admin')
            )
            # Add a default librarian user (password: librarian)
            librarian_pass = hash_password('librarian')
            cursor.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
                ('librarian', librarian_pass, 'librarian')
            )
            
            # Add default settings
            cursor.execute("INSERT INTO settings (setting_key, setting_value) VALUES ('fine_per_day', '5')")
            cursor.execute("INSERT INTO settings (setting_key, setting_value) VALUES ('loan_duration_days', '14')")
            
            db.commit()
            print("Default admin/librarian users and settings added.")
        except mysql.connector.Error as err:
            print(f"Error inserting default data: {err}")
            db.rollback()

        print("\nDatabase setup is complete!")
        print("Default users:")
        print("  - Username: admin, Password: admin")
        print("  - Username: librarian, Password: librarian")

    except mysql.connector.Error as err:
        print(f"Database connection error: {err}")
    finally:
        if 'db' in locals() and db.is_connected():
            cursor.close()
            db.close()
            print("MySQL connection closed.")

if __name__ == '__main__':
    create_database()
