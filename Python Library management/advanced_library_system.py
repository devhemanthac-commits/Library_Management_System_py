# advanced_library_system.py

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import mysql.connector
from mysql.connector import errorcode
from PIL import Image, ImageTk
from datetime import date, timedelta
import hashlib

# --- Constants and Configuration ---
DB_HOST = 'localhost'
DB_USER = 'root'
DB_PASSWORD = 'your_password' # <-- IMPORTANT: Change this!
DB_NAME = 'advanced_library_db'

# --- Database Manager Class ---
# This class handles all direct interactions with the database.
# It helps separate the database logic from the GUI logic.
class DatabaseManager:
    """Manages all database operations for the library system."""

    def __init__(self, host, user, password, db_name):
        self.host = host
        self.user = user
        self.password = password
        self.db_name = db_name
        self.connection = None

    def connect(self):
        """Establishes a persistent connection to the database."""
        try:
            self.connection = mysql.connector.connect(
                host=self.host,
                user=self.user,
                password=self.password,
                database=self.db_name
            )
        except mysql.connector.Error as err:
            messagebox.showerror("Database Error", f"Failed to connect to database: {err}")
            self.connection = None
            return False
        return True

    def disconnect(self):
        """Closes the database connection if it's open."""
        if self.connection and self.connection.is_connected():
            self.connection.close()

    def execute_query(self, query, params=None, fetch=None):
        """
        Executes a given SQL query.
        :param query: The SQL query string.
        :param params: A tuple of parameters to be used with the query.
        :param fetch: Type of fetch ('one', 'all'). If None, it's a non-fetching query (INSERT, UPDATE, DELETE).
        :return: Fetched data or row count.
        """
        if not self.connect():
            return None if fetch else 0
        
        cursor = self.connection.cursor(dictionary=True)
        result = None
        try:
            cursor.execute(query, params or ())
            if fetch == 'one':
                result = cursor.fetchone()
            elif fetch == 'all':
                result = cursor.fetchall()
            else:
                self.connection.commit()
                result = cursor.rowcount
        except mysql.connector.Error as err:
            self.connection.rollback()
            messagebox.showerror("Query Error", f"An error occurred: {err}")
            result = None if fetch else 0
        finally:
            cursor.close()
            self.disconnect()
        return result

    # --- User Management ---
    def verify_user(self, username, password):
        """Verifies user credentials against the database."""
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        query = "SELECT * FROM users WHERE username = %s AND password_hash = %s"
        return self.execute_query(query, (username, password_hash), fetch='one')

    # --- Book Management ---
    def add_book(self, title, author, genre):
        query = "INSERT INTO books (title, author, genre) VALUES (%s, %s, %s)"
        return self.execute_query(query, (title, author, genre))

    def update_book(self, book_id, title, author, genre):
        query = "UPDATE books SET title = %s, author = %s, genre = %s WHERE book_id = %s"
        return self.execute_query(query, (title, author, genre, book_id))

    def delete_book(self, book_id):
        query = "DELETE FROM books WHERE book_id = %s"
        return self.execute_query(query, (book_id,))

    def search_books(self, title="", author="", status=""):
        query = "SELECT book_id, title, author, genre, status FROM books WHERE 1=1"
        params = []
        if title:
            query += " AND title LIKE %s"
            params.append(f"%{title}%")
        if author:
            query += " AND author LIKE %s"
            params.append(f"%{author}%")
        if status:
            query += " AND status = %s"
            params.append(status)
        query += " ORDER BY title"
        return self.execute_query(query, tuple(params), fetch='all')

    # --- Member Management ---
    def add_member(self, name, email, phone):
        query = "INSERT INTO members (name, email, phone) VALUES (%s, %s, %s)"
        return self.execute_query(query, (name, email, phone))

    def update_member(self, member_id, name, email, phone):
        query = "UPDATE members SET name = %s, email = %s, phone = %s WHERE member_id = %s"
        return self.execute_query(query, (name, email, phone, member_id))

    def delete_member(self, member_id):
        # Check if member has issued books first
        check_query = "SELECT COUNT(*) as count FROM issued_books WHERE member_id = %s AND return_date IS NULL"
        result = self.execute_query(check_query, (member_id,), fetch='one')
        if result and result['count'] > 0:
            messagebox.showerror("Error", "Cannot delete member. They have outstanding books.")
            return 0
        
        delete_query = "DELETE FROM members WHERE member_id = %s"
        return self.execute_query(delete_query, (member_id,))

    def search_members(self, name="", email=""):
        query = "SELECT member_id, name, email, phone FROM members WHERE 1=1"
        params = []
        if name:
            query += " AND name LIKE %s"
            params.append(f"%{name}%")
        if email:
            query += " AND email LIKE %s"
            params.append(f"%{email}%")
        query += " ORDER BY name"
        return self.execute_query(query, tuple(params), fetch='all')

    # --- Issue/Return Management ---
    def issue_book(self, book_id, member_id):
        # Transactional operation
        if not self.connect(): return 0

        try:
            cursor = self.connection.cursor()
            # 1. Check book status
            cursor.execute("SELECT status FROM books WHERE book_id = %s", (book_id,))
            status_result = cursor.fetchone()
            if not status_result or status_result[0] != 'Available':
                messagebox.showerror("Error", "Book is not available for issue.")
                return 0

            # 2. Get loan duration
            cursor.execute("SELECT setting_value FROM settings WHERE setting_key = 'loan_duration_days'")
            loan_days = int(cursor.fetchone()[0])
            
            issue_date = date.today()
            due_date = issue_date + timedelta(days=loan_days)

            # 3. Update book status
            cursor.execute("UPDATE books SET status = 'Issued' WHERE book_id = %s", (book_id,))
            
            # 4. Record the issue
            cursor.execute(
                "INSERT INTO issued_books (book_id, member_id, issue_date, due_date) VALUES (%s, %s, %s, %s)",
                (book_id, member_id, issue_date, due_date)
            )
            self.connection.commit()
            return 1
        except (mysql.connector.Error, ValueError) as err:
            self.connection.rollback()
            messagebox.showerror("Transaction Error", f"Failed to issue book: {err}")
            return 0
        finally:
            cursor.close()
            self.disconnect()

    def return_book(self, book_id):
        # Another transactional operation
        if not self.connect(): return None

        fine = 0
        try:
            cursor = self.connection.cursor(dictionary=True)
            # 1. Find the open issue record
            cursor.execute(
                "SELECT issue_id, due_date FROM issued_books WHERE book_id = %s AND return_date IS NULL",
                (book_id,)
            )
            issue_record = cursor.fetchone()
            if not issue_record:
                messagebox.showerror("Error", "This book is not currently issued.")
                return None

            # 2. Update book status
            cursor.execute("UPDATE books SET status = 'Available' WHERE book_id = %s", (book_id,))

            # 3. Update issue record with return date
            return_date = date.today()
            cursor.execute(
                "UPDATE issued_books SET return_date = %s WHERE issue_id = %s",
                (return_date, issue_record['issue_id'])
            )

            # 4. Calculate fine
            if return_date > issue_record['due_date']:
                days_overdue = (return_date - issue_record['due_date']).days
                cursor.execute("SELECT setting_value FROM settings WHERE setting_key = 'fine_per_day'")
                fine_per_day = float(cursor.fetchone()['setting_value'])
                fine = days_overdue * fine_per_day

            self.connection.commit()
            return fine
        except (mysql.connector.Error, ValueError) as err:
            self.connection.rollback()
            messagebox.showerror("Transaction Error", f"Failed to return book: {err}")
            return None
        finally:
            cursor.close()
            self.disconnect()

    # --- Statistics ---
    def get_dashboard_stats(self):
        stats = {
            'total_books': 0, 'total_members': 0, 
            'issued_books': 0, 'overdue_books': 0
        }
        query_books = "SELECT COUNT(*) as count FROM books"
        query_members = "SELECT COUNT(*) as count FROM members"
        query_issued = "SELECT COUNT(*) as count FROM books WHERE status = 'Issued'"
        query_overdue = "SELECT COUNT(*) as count FROM issued_books WHERE return_date IS NULL AND due_date < CURDATE()"
        
        stats['total_books'] = self.execute_query(query_books, fetch='one')['count']
        stats['total_members'] = self.execute_query(query_members, fetch='one')['count']
        stats['issued_books'] = self.execute_query(query_issued, fetch='one')['count']
        stats['overdue_books'] = self.execute_query(query_overdue, fetch='one')['count']
        
        return stats
    
    # --- Settings ---
    def get_setting(self, key):
        query = "SELECT setting_value FROM settings WHERE setting_key = %s"
        result = self.execute_query(query, (key,), fetch='one')
        return result['setting_value'] if result else None
    
    def update_setting(self, key, value):
        query = "UPDATE settings SET setting_value = %s WHERE setting_key = %s"
        return self.execute_query(query, (value, key))


# --- Login Window Class ---
class LoginWindow(tk.Toplevel):
    """Login window for the application."""

    def __init__(self, parent, db_manager):
        super().__init__(parent)
        self.parent = parent
        self.db_manager = db_manager
        self.user_info = None

        self.title("LMS Login")
        self.geometry("800x600")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.parent.destroy) # Close main app if login is closed

        # --- Background Image ---
        try:
            self.bg_image = Image.open("background.jpg")
            self.bg_photo = ImageTk.PhotoImage(self.bg_image.resize((800, 600)))
            bg_label = tk.Label(self, image=self.bg_photo)
            bg_label.place(x=0, y=0, relwidth=1, relheight=1)
        except FileNotFoundError:
            self.config(bg="#333")

        # --- Login Frame ---
        login_frame = tk.Frame(self, bg="rgba(0, 0, 0, 0.7)", bd=5)
        login_frame.place(relx=0.5, rely=0.5, anchor='center')

        title_label = tk.Label(login_frame, text="Library System Login", font=("Helvetica", 24, "bold"), fg="white", bg=login_frame['bg'])
        title_label.grid(row=0, column=0, columnspan=2, padx=20, pady=20)

        # --- Username ---
        tk.Label(login_frame, text="Username:", font=("Helvetica", 14), fg="white", bg=login_frame['bg']).grid(row=1, column=0, padx=10, pady=10, sticky='w')
        self.username_entry = tk.Entry(login_frame, font=("Helvetica", 14), width=25)
        self.username_entry.grid(row=1, column=1, padx=10, pady=10)

        # --- Password ---
        tk.Label(login_frame, text="Password:", font=("Helvetica", 14), fg="white", bg=login_frame['bg']).grid(row=2, column=0, padx=10, pady=10, sticky='w')
        self.password_entry = tk.Entry(login_frame, font=("Helvetica", 14), width=25, show="*")
        self.password_entry.grid(row=2, column=1, padx=10, pady=10)

        # --- Login Button ---
        login_button = tk.Button(login_frame, text="Login", font=("Helvetica", 14, "bold"), command=self.attempt_login, bg="#4CAF50", fg="white", width=15)
        login_button.grid(row=3, column=0, columnspan=2, pady=20)

        self.transient(self.parent)
        self.grab_set()
        self.parent.wait_window(self)

    def attempt_login(self):
        username = self.username_entry.get()
        password = self.password_entry.get()
        if not username or not password:
            messagebox.showwarning("Input Error", "Username and Password are required.")
            return

        user = self.db_manager.verify_user(username, password)
        if user:
            self.user_info = user
            self.destroy() # Close the login window
        else:
            messagebox.showerror("Login Failed", "Invalid username or password.")

# --- Main Application Class ---
class MainApp:
    """The main application GUI."""
    def __init__(self, root, db_manager, user_info):
        self.root = root
        self.db = db_manager
        self.user_info = user_info
        
        self.root.title(f"Library Management System - Welcome, {self.user_info['username']} ({self.user_info['role']})")
        self.root.geometry("1200x800")
        
        # --- Style Configuration ---
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TNotebook.Tab", font=('Helvetica', '12', 'bold'), padding=[10, 5])
        style.configure("TButton", font=('Helvetica', 10), padding=5)
        style.configure("Treeview.Heading", font=('Helvetica', 11, 'bold'))

        # --- Main Notebook (Tabs) ---
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(expand=True, fill='both', padx=10, pady=10)

        # Create tabs
        self.create_dashboard_tab()
        self.create_books_tab()
        self.create_members_tab()
        if self.user_info['role'] == 'admin':
            self.create_settings_tab()
        
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def on_closing(self):
        if messagebox.askokcancel("Quit", "Do you want to exit the application?"):
            self.db.disconnect()
            self.root.destroy()

    # --- Tab Creation Methods ---

    def create_dashboard_tab(self):
        self.dashboard_frame = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(self.dashboard_frame, text='Dashboard')
        self.populate_dashboard()

    def populate_dashboard(self):
        # Clear existing widgets before repopulating
        for widget in self.dashboard_frame.winfo_children():
            widget.destroy()
            
        stats = self.db.get_dashboard_stats()
        
        ttk.Label(self.dashboard_frame, text="Library Overview", font=("Helvetica", 24, "bold")).pack(pady=20)

        stats_frame = ttk.Frame(self.dashboard_frame)
        stats_frame.pack(pady=20)

        stat_items = [
            ("Total Books", stats['total_books'], "#3498DB"),
            ("Total Members", stats['total_members'], "#2ECC71"),
            ("Books Issued", stats['issued_books'], "#F39C12"),
            ("Books Overdue", stats['overdue_books'], "#E74C3C")
        ]

        for i, (text, value, color) in enumerate(stat_items):
            frame = tk.Frame(stats_frame, bg=color, width=200, height=120, relief='raised', bd=3)
            frame.grid(row=0, column=i, padx=20, pady=10)
            frame.pack_propagate(False)
            tk.Label(frame, text=text, font=("Helvetica", 14, "bold"), fg="white", bg=color).pack(pady=(15, 5))
            tk.Label(frame, text=str(value), font=("Helvetica", 28, "bold"), fg="white", bg=color).pack(pady=(5, 15))

        refresh_button = ttk.Button(self.dashboard_frame, text="Refresh Stats", command=self.populate_dashboard)
        refresh_button.pack(pady=30)
        
    def create_books_tab(self):
        frame = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(frame, text='Book Management')

        # --- Search/Filter Frame ---
        search_frame = ttk.LabelFrame(frame, text="Search & Filter Books", padding="10")
        search_frame.pack(fill='x', pady=5)
        
        ttk.Label(search_frame, text="Title:").grid(row=0, column=0, padx=5, pady=5)
        self.book_search_title = ttk.Entry(search_frame, width=30)
        self.book_search_title.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(search_frame, text="Author:").grid(row=0, column=2, padx=5, pady=5)
        self.book_search_author = ttk.Entry(search_frame, width=30)
        self.book_search_author.grid(row=0, column=3, padx=5, pady=5)

        ttk.Label(search_frame, text="Status:").grid(row=0, column=4, padx=5, pady=5)
        self.book_search_status = ttk.Combobox(search_frame, values=["", "Available", "Issued"])
        self.book_search_status.grid(row=0, column=5, padx=5, pady=5)

        ttk.Button(search_frame, text="Search", command=self.refresh_book_list).grid(row=0, column=6, padx=10, pady=5)
        
        # --- Treeview for Books ---
        tree_frame = ttk.Frame(frame)
        tree_frame.pack(expand=True, fill='both', pady=10)
        
        self.book_tree = ttk.Treeview(tree_frame, columns=("ID", "Title", "Author", "Genre", "Status"), show='headings')
        self.book_tree.heading("ID", text="ID")
        self.book_tree.heading("Title", text="Title")
        self.book_tree.heading("Author", text="Author")
        self.book_tree.heading("Genre", text="Genre")
        self.book_tree.heading("Status", text="Status")
        
        self.book_tree.column("ID", width=50, anchor='center')
        self.book_tree.column("Title", width=300)
        self.book_tree.column("Author", width=250)
        self.book_tree.column("Genre", width=150)
        self.book_tree.column("Status", width=100, anchor='center')

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.book_tree.yview)
        self.book_tree.configure(yscrollcommand=scrollbar.set)
        self.book_tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        # --- Button Frame ---
        button_frame = ttk.Frame(frame, padding="5")
        button_frame.pack(fill='x')
        ttk.Button(button_frame, text="Add New Book", command=self.open_add_book_dialog).pack(side='left', padx=5)
        ttk.Button(button_frame, text="Edit Selected", command=self.open_edit_book_dialog).pack(side='left', padx=5)
        ttk.Button(button_frame, text="Delete Selected", command=self.delete_selected_book).pack(side='left', padx=5)
        ttk.Separator(button_frame, orient='vertical').pack(side='left', padx=15, fill='y')
        ttk.Button(button_frame, text="Issue Selected Book", command=self.open_issue_book_dialog).pack(side='left', padx=5)
        ttk.Button(button_frame, text="Return Selected Book", command=self.return_selected_book).pack(side='left', padx=5)

        self.refresh_book_list()

    def create_members_tab(self):
        frame = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(frame, text='Member Management')

        # --- Search/Filter Frame ---
        search_frame = ttk.LabelFrame(frame, text="Search & Filter Members", padding="10")
        search_frame.pack(fill='x', pady=5)
        
        ttk.Label(search_frame, text="Name:").grid(row=0, column=0, padx=5, pady=5)
        self.member_search_name = ttk.Entry(search_frame, width=30)
        self.member_search_name.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(search_frame, text="Email:").grid(row=0, column=2, padx=5, pady=5)
        self.member_search_email = ttk.Entry(search_frame, width=30)
        self.member_search_email.grid(row=0, column=3, padx=5, pady=5)
        
        ttk.Button(search_frame, text="Search", command=self.refresh_member_list).grid(row=0, column=4, padx=10, pady=5)

        # --- Treeview for Members ---
        tree_frame = ttk.Frame(frame)
        tree_frame.pack(expand=True, fill='both', pady=10)

        self.member_tree = ttk.Treeview(tree_frame, columns=("ID", "Name", "Email", "Phone"), show='headings')
        self.member_tree.heading("ID", text="ID")
        self.member_tree.heading("Name", text="Name")
        self.member_tree.heading("Email", text="Email")
        self.member_tree.heading("Phone", text="Phone")

        self.member_tree.column("ID", width=50, anchor='center')
        self.member_tree.column("Name", width=250)
        self.member_tree.column("Email", width=250)
        self.member_tree.column("Phone", width=150)
        
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.member_tree.yview)
        self.member_tree.configure(yscrollcommand=scrollbar.set)
        self.member_tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        # --- Button Frame ---
        button_frame = ttk.Frame(frame, padding="5")
        button_frame.pack(fill='x')
        ttk.Button(button_frame, text="Add New Member", command=self.open_add_member_dialog).pack(side='left', padx=5)
        ttk.Button(button_frame, text="Edit Selected", command=self.open_edit_member_dialog).pack(side='left', padx=5)
        ttk.Button(button_frame, text="Delete Selected", command=self.delete_selected_member).pack(side='left', padx=5)
        
        self.refresh_member_list()
        
    def create_settings_tab(self):
        frame = ttk.Frame(self.notebook, padding="20")
        self.notebook.add(frame, text='Settings')
        
        ttk.Label(frame, text="Library Settings", font=("Helvetica", 18, "bold")).pack(pady=10)
        
        settings_frame = ttk.LabelFrame(frame, text="Fine & Loan Configuration", padding="15")
        settings_frame.pack(fill='x', pady=10)
        
        ttk.Label(settings_frame, text="Fine per Day (₹):").grid(row=0, column=0, padx=5, pady=10, sticky='w')
        self.fine_rate_var = tk.StringVar(value=self.db.get_setting('fine_per_day'))
        fine_entry = ttk.Entry(settings_frame, textvariable=self.fine_rate_var, width=10)
        fine_entry.grid(row=0, column=1, padx=5, pady=10)
        
        ttk.Label(settings_frame, text="Loan Duration (days):").grid(row=1, column=0, padx=5, pady=10, sticky='w')
        self.loan_duration_var = tk.StringVar(value=self.db.get_setting('loan_duration_days'))
        loan_entry = ttk.Entry(settings_frame, textvariable=self.loan_duration_var, width=10)
        loan_entry.grid(row=1, column=1, padx=5, pady=10)
        
        save_btn = ttk.Button(settings_frame, text="Save Settings", command=self.save_settings)
        save_btn.grid(row=2, column=0, columnspan=2, pady=20)

    # --- Data Refresh Methods ---
    def refresh_book_list(self):
        for i in self.book_tree.get_children():
            self.book_tree.delete(i)
        
        title = self.book_search_title.get()
        author = self.book_search_author.get()
        status = self.book_search_status.get()
        
        books = self.db.search_books(title, author, status)
        if books:
            for book in books:
                self.book_tree.insert("", "end", values=(
                    book['book_id'], book['title'], book['author'], book['genre'], book['status']
                ))

    def refresh_member_list(self):
        for i in self.member_tree.get_children():
            self.member_tree.delete(i)
        
        name = self.member_search_name.get()
        email = self.member_search_email.get()
            
        members = self.db.search_members(name, email)
        if members:
            for member in members:
                self.member_tree.insert("", "end", values=(
                    member['member_id'], member['name'], member['email'], member['phone']
                ))

    # --- Book Operations ---
    def open_add_book_dialog(self):
        BookDialog(self.root, "Add New Book", self.db, self.refresh_book_list)
        
    def open_edit_book_dialog(self):
        selected_item = self.book_tree.focus()
        if not selected_item:
            messagebox.showwarning("Selection Error", "Please select a book to edit.")
            return
        book_data = self.book_tree.item(selected_item)['values']
        BookDialog(self.root, "Edit Book", self.db, self.refresh_book_list, book_data=book_data)
        
    def delete_selected_book(self):
        selected_item = self.book_tree.focus()
        if not selected_item:
            messagebox.showwarning("Selection Error", "Please select a book to delete.")
            return
        book_id = self.book_tree.item(selected_item)['values'][0]
        if messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete Book ID {book_id}?"):
            if self.db.delete_book(book_id) > 0:
                messagebox.showinfo("Success", "Book deleted successfully.")
                self.refresh_book_list()
            else:
                messagebox.showerror("Error", "Could not delete the book. It may be currently issued or does not exist.")
    
    # --- Member Operations ---
    def open_add_member_dialog(self):
        MemberDialog(self.root, "Add New Member", self.db, self.refresh_member_list)

    def open_edit_member_dialog(self):
        selected_item = self.member_tree.focus()
        if not selected_item:
            messagebox.showwarning("Selection Error", "Please select a member to edit.")
            return
        member_data = self.member_tree.item(selected_item)['values']
        MemberDialog(self.root, "Edit Member", self.db, self.refresh_member_list, member_data=member_data)

    def delete_selected_member(self):
        selected_item = self.member_tree.focus()
        if not selected_item:
            messagebox.showwarning("Selection Error", "Please select a member to delete.")
            return
        member_id = self.member_tree.item(selected_item)['values'][0]
        if messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete Member ID {member_id}?"):
            if self.db.delete_member(member_id) > 0:
                messagebox.showinfo("Success", "Member deleted successfully.")
                self.refresh_member_list()

    # --- Issue/Return Operations ---
    def open_issue_book_dialog(self):
        selected_item = self.book_tree.focus()
        if not selected_item:
            messagebox.showwarning("Selection Error", "Please select a book to issue.")
            return
        book_values = self.book_tree.item(selected_item)['values']
        book_id, book_title, status = book_values[0], book_values[1], book_values[4]
        
        if status == 'Issued':
            messagebox.showerror("Error", f"'{book_title}' is already issued.")
            return

        member_id = simpledialog.askstring("Issue Book", f"Enter Member ID to issue '{book_title}':", parent=self.root)
        if member_id:
            try:
                member_id = int(member_id)
                if self.db.issue_book(book_id, member_id):
                    messagebox.showinfo("Success", f"Book issued successfully to Member ID {member_id}.")
                    self.refresh_book_list()
                    self.populate_dashboard() # Refresh stats
                else:
                    messagebox.showerror("Error", "Failed to issue book. Check if Member ID is valid.")
            except ValueError:
                messagebox.showerror("Invalid Input", "Member ID must be a number.")
    
    def return_selected_book(self):
        selected_item = self.book_tree.focus()
        if not selected_item:
            messagebox.showwarning("Selection Error", "Please select a book to return.")
            return
        book_values = self.book_tree.item(selected_item)['values']
        book_id, book_title, status = book_values[0], book_values[1], book_values[4]

        if status == 'Available':
            messagebox.showerror("Error", f"'{book_title}' is already available.")
            return

        fine_amount = self.db.return_book(book_id)
        if fine_amount is not None:
            self.refresh_book_list()
            self.populate_dashboard() # Refresh stats
            if fine_amount > 0:
                messagebox.showwarning("Fine Due", f"Book returned successfully.\nA fine of ₹{fine_amount:.2f} was due for being overdue.")
            else:
                messagebox.showinfo("Success", "Book returned successfully.")

    # --- Settings Operations ---
    def save_settings(self):
        try:
            fine_rate = float(self.fine_rate_var.get())
            loan_duration = int(self.loan_duration_var.get())
            
            self.db.update_setting('fine_per_day', str(fine_rate))
            self.db.update_setting('loan_duration_days', str(loan_duration))
            
            messagebox.showinfo("Success", "Settings have been updated.")
        except ValueError:
            messagebox.showerror("Input Error", "Please ensure fine rate is a number and loan duration is an integer.")
            
            
# --- Generic Dialog Classes for Add/Edit ---
class BookDialog(simpledialog.Dialog):
    """A dialog for adding or editing books."""
    def __init__(self, parent, title, db, callback, book_data=None):
        self.db = db
        self.callback = callback
        self.book_data = book_data # None for "Add", contains data for "Edit"
        super().__init__(parent, title)

    def body(self, master):
        ttk.Label(master, text="Title:").grid(row=0, sticky='w')
        ttk.Label(master, text="Author:").grid(row=1, sticky='w')
        ttk.Label(master, text="Genre:").grid(row=2, sticky='w')

        self.title_entry = ttk.Entry(master, width=40)
        self.author_entry = ttk.Entry(master, width=40)
        self.genre_entry = ttk.Entry(master, width=40)

        self.title_entry.grid(row=0, column=1, pady=5)
        self.author_entry.grid(row=1, column=1, pady=5)
        self.genre_entry.grid(row=2, column=1, pady=5)
        
        if self.book_data: # If editing, populate fields
            self.title_entry.insert(0, self.book_data[1])
            self.author_entry.insert(0, self.book_data[2])
            self.genre_entry.insert(0, self.book_data[3])
            
        return self.title_entry # initial focus

    def apply(self):
        title = self.title_entry.get()
        author = self.author_entry.get()
        genre = self.genre_entry.get()
        
        if not title or not author:
            messagebox.showwarning("Input Error", "Title and Author are required.", parent=self)
            return

        if self.book_data: # Editing existing book
            book_id = self.book_data[0]
            if self.db.update_book(book_id, title, author, genre):
                messagebox.showinfo("Success", "Book updated successfully.", parent=self)
        else: # Adding new book
            if self.db.add_book(title, author, genre):
                messagebox.showinfo("Success", "Book added successfully.", parent=self)
        
        self.callback() # Refresh the treeview in the main app


class MemberDialog(simpledialog.Dialog):
    """A dialog for adding or editing members."""
    def __init__(self, parent, title, db, callback, member_data=None):
        self.db = db
        self.callback = callback
        self.member_data = member_data
        super().__init__(parent, title)

    def body(self, master):
        ttk.Label(master, text="Name:").grid(row=0, sticky='w')
        ttk.Label(master, text="Email:").grid(row=1, sticky='w')
        ttk.Label(master, text="Phone:").grid(row=2, sticky='w')

        self.name_entry = ttk.Entry(master, width=40)
        self.email_entry = ttk.Entry(master, width=40)
        self.phone_entry = ttk.Entry(master, width=40)

        self.name_entry.grid(row=0, column=1, pady=5)
        self.email_entry.grid(row=1, column=1, pady=5)
        self.phone_entry.grid(row=2, column=1, pady=5)
        
        if self.member_data:
            self.name_entry.insert(0, self.member_data[1])
            self.email_entry.insert(0, self.member_data[2])
            self.phone_entry.insert(0, self.member_data[3])
            
        return self.name_entry

    def apply(self):
        name = self.name_entry.get()
        email = self.email_entry.get()
        phone = self.phone_entry.get()
        
        if not name or not email:
            messagebox.showwarning("Input Error", "Name and Email are required.", parent=self)
            return

        if self.member_data:
            member_id = self.member_data[0]
            if self.db.update_member(member_id, name, email, phone):
                messagebox.showinfo("Success", "Member updated successfully.", parent=self)
        else:
            if self.db.add_member(name, email, phone):
                messagebox.showinfo("Success", "Member added successfully.", parent=self)
        
        self.callback()

# --- Main Execution ---
if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw() # Hide the main window initially

    db_manager = DatabaseManager(DB_HOST, DB_USER, DB_PASSWORD, DB_NAME)
    
    # Check initial DB connection
    if not db_manager.connect():
        messagebox.showerror("Startup Error", "Cannot connect to the database. Please check your configuration and ensure the MySQL server is running.")
        root.destroy()
    else:
        db_manager.disconnect() # Close the test connection
        
        login = LoginWindow(root, db_manager)
        
        if login.user_info:
            root.deiconify() # Show the main window after successful login
            app = MainApp(root, db_manager, login.user_info)
            root.mainloop()
        else:
            # If login was cancelled or failed, destroy the root window
            root.destroy()
