from flask import Flask, request, jsonify, session, render_template, redirect, flash, Response
import mysql.connector
from datetime import datetime
from functools import wraps
import csv
import io
import hashlib
from fuzzywuzzy import fuzz  # <-- added for smarter text matching

app = Flask(__name__)
app.secret_key = 'API_SECRET_KEY'

db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': '',
    'database': 'expense-tracker'
}

def get_db_connection():
    return mysql.connector.connect(**db_config)

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


# ---------------- AUTH DECORATOR ----------------
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated


# ---------------- LANDING ----------------
@app.route('/')
def landing():
    session.clear()
    return render_template('landing.html')


# ---------------- REGISTER ----------------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        return render_template('register.html')

    if request.is_json:
        data = request.get_json()
    else:
        data = request.form
        
    full_name = data.get('full_name')
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    confirm_password = data.get('confirm_password')
    university = data.get('university', '')
    currency = data.get('currency', 'USD')

    if not all([full_name, username, email, password, confirm_password]):
        flash('Please fill all required fields', 'danger')
        return redirect('/register')
    if password != confirm_password:
        flash('Passwords do not match', 'danger')
        return redirect('/register')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE username=%s OR email=%s", (username, email))
    existing = cursor.fetchone()
    if existing:
        flash('Username or Email already exists', 'danger')
        cursor.close()
        conn.close()
        return redirect('/register')

    hashed_password = hash_password(password)
    cursor.execute(
        "INSERT INTO users (full_name, username, email, password, university, currency) VALUES (%s,%s,%s,%s,%s,%s)",
        (full_name, username, email, hashed_password, university, currency)
    )
    conn.commit()
    cursor.close()
    conn.close()
    
    if request.is_json:
        return jsonify({'message': 'Registration successful! Please login.'}), 200
    else:
        flash('Registration successful! Please login.', 'success')
        return redirect('/login')


# ---------------- LOGIN ----------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')

    if request.is_json:
        data = request.get_json()
    else:
        data = request.form
        
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        if request.is_json:
            return jsonify({'error': 'Username and password are required'}), 400
        else:
            flash('Username and password are required', 'danger')
            return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()

    if user and user['password'] == hash_password(password):
        session['user_id'] = user['user_id']
        if request.is_json:
            return jsonify({'message': 'Login successful!'}), 200
        else:
            return redirect('/dashboard')

    if request.is_json:
        return jsonify({'error': 'Invalid username or password'}), 401
    else:
        flash('Invalid username or password', 'danger')
        return redirect('/login')


# ---------------- PROFILE ----------------
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'GET':
        cursor.execute("SELECT * FROM users WHERE user_id = %s", (session['user_id'],))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        return render_template('profile.html', user=user)
    
    # POST request - update profile
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form
        
    full_name = data.get('full_name')
    email = data.get('email')
    university = data.get('university', '')
    currency = data.get('currency', 'USD')
    
    cursor.execute(
        "UPDATE users SET full_name = %s, email = %s, university = %s, currency = %s WHERE user_id = %s",
        (full_name, email, university, currency, session['user_id'])
    )
    conn.commit()
    cursor.close()
    conn.close()
    
    if request.is_json:
        return jsonify({'message': 'Profile updated successfully!'}), 200
    else:
        flash('Profile updated successfully!', 'success')
        return redirect('/profile')


# ---------------- LOGOUT ----------------
@app.route('/logout')
@login_required
def logout():
    session.clear()
    return redirect('/')


# ---------------- DASHBOARD ----------------
@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT id, category, description, amount, payment_method, transaction_time
        FROM expenses
        WHERE user_id=%s
        ORDER BY transaction_time DESC
    """, (session['user_id'],))
    expenses = cursor.fetchall()
    
    total_amount = 0
    monthly_amount = 0
    expenses_count = len(expenses)
    category_totals = {}
    
    current_month = datetime.now().month
    current_year = datetime.now().year
    
    for expense in expenses:
        total_amount += float(expense['amount'])
        expense_date = expense['transaction_time']
        if expense_date.month == current_month and expense_date.year == current_year:
            monthly_amount += float(expense['amount'])
        category = expense['category']
        if category in category_totals:
            category_totals[category] += float(expense['amount'])
        else:
            category_totals[category] = float(expense['amount'])
    
    top_category = "None"
    if category_totals:
        top_category = max(category_totals, key=category_totals.get)
    
    cursor.close()
    conn.close()
    
    return render_template('dashboard.html', 
                           expenses=expenses,
                           total_amount=total_amount,
                           monthly_amount=monthly_amount,
                           expenses_count=expenses_count,
                           top_category=top_category)


# ---------------- EXPENSES ROUTE ----------------
@app.route('/expenses')
@login_required
def expenses():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT id, category, description, amount, payment_method, transaction_time as created_at
        FROM expenses
        WHERE user_id=%s
        ORDER BY transaction_time DESC
    """, (session['user_id'],))
    expenses = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('expense.html', expenses=expenses)


# ---------------- ADD EXPENSE ----------------
@app.route('/add_expense', methods=['GET', 'POST'])
@login_required
def add_expense():
    if request.method == 'GET':
        return render_template('add_expense.html')

    category = request.form.get('category')
    description = request.form.get('description')
    amount = request.form.get('amount')
    payment_method = request.form.get('payment_method', 'N/A')
    transaction_time = datetime.now()

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO expenses (user_id, category, description, amount, payment_method, transaction_time)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (session['user_id'], category, description, amount, payment_method, transaction_time))
    conn.commit()
    cursor.close()
    conn.close()
    flash('Expense added successfully!', 'success')
    return redirect('/dashboard')


# ---------------- RECOMMENDER ----------------
@app.route('/recommender')
@login_required
def recommender():
    return render_template('recommender.html')


# ---------------- ANALYTICS ----------------
@app.route('/analytics')
@login_required
def analytics():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT category, amount, transaction_time
        FROM expenses
        WHERE user_id = %s
        ORDER BY transaction_time DESC
    """, (session['user_id'],))
    expenses = cursor.fetchall()
    cursor.close()
    conn.close()

    total_amount = sum(float(e['amount']) for e in expenses)
    expenses_count = len(expenses)
    now = datetime.now()
    current_month = now.month
    current_year = now.year
    monthly_amount = sum(
        float(e['amount']) for e in expenses
        if e['transaction_time'].month == current_month and e['transaction_time'].year == current_year
    )

    category_totals = {}
    for e in expenses:
        category = e['category'] or "Other"
        category_totals[category] = category_totals.get(category, 0) + float(e['amount'])

    sorted_categories = sorted(category_totals.items(), key=lambda x: x[1], reverse=True)
    top_categories = sorted_categories[:3]

    return render_template(
        'analytics.html',
        total_amount=total_amount,
        monthly_amount=monthly_amount,
        expenses_count=expenses_count,
        top_categories=top_categories,
        category_totals=category_totals,
    )


# ---------------- DOWNLOAD CSV ----------------
@app.route('/download_csv')
@login_required
def download_csv():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT id, category, description, amount, payment_method, transaction_time
        FROM expenses
        WHERE user_id=%s
        ORDER BY transaction_time DESC
    """, (session['user_id'],))
    expenses = cursor.fetchall()
    cursor.close()
    conn.close()

    def generate():
        data = io.StringIO()
        writer = csv.writer(data)
        writer.writerow(['ID','Category','Description','Amount','Payment Method','Transaction Time'])
        yield data.getvalue()
        data.seek(0)
        data.truncate(0)
        for exp in expenses:
            writer.writerow([exp['id'], exp['category'], exp['description'], exp['amount'], exp['payment_method'], exp['transaction_time']])
            yield data.getvalue()
            data.seek(0)
            data.truncate(0)

    headers = {
        "Content-Disposition": "attachment; filename=expenses.csv",
        "Content-type": "text/csv"
    }
    return Response(generate(), headers=headers)


# ---------------- CHATBOT ROUTE ----------------

# Simple memory per user (optional context)
user_context = {}

def get_bot_response(user_input, user_id):
    user_input = user_input.lower().strip()
    response = "I'm not sure I understood that. Could you please rephrase?"

    prev_message = user_context.get(user_id, "")

    # ---- GREETING ----
    if any(word in user_input for word in ["hello", "hi", "hey", "good morning", "good evening"]):
        response = "👋 Hello there! How can I help you today? You can ask me about adding, viewing, or analyzing your expenses."

    # ---- ADD EXPENSE ----
    elif "add" in user_input and "expense" in user_input:
        response = '💰 To add a new expense, <a href="/add_expense">click here</a>.'

    # ---- VIEW EXPENSES ----
    elif any(word in user_input for word in ["view", "show", "see"]) and "expense" in user_input:
        response = '📂 You can view your expenses on your <a href="/dashboard" class="text-blue-600 hover:underline">Dashboard</a>.'

    # ---- ANALYTICS / REPORT ----
    elif any(word in user_input for word in ["report", "analytics", "chart", "insight", "analysis"]):
        response = '📊 You can explore detailed insights on your <a href="/analytics" class="text-blue-600 hover:underline">Analytics</a> page.'

    # ---- DOWNLOAD CSV ----
    elif "download" in user_input and "csv" in user_input:
        response = '📥 You can download all your expense records from <a href="/download_csv" class="text-blue-600 hover:underline">here</a>.'

    # ---- PROFILE ----
    elif any(word in user_input for word in ["profile", "account", "settings"]):
        response = '👤 You can view or update your profile <a href="/profile" class="text-blue-600 hover:underline">here</a>.'

    # ---- HELP ----
    elif "help" in user_input or "what can you do" in user_input:
        response = (
            "🤖 I can help you with these tasks:<br>"
            "💰 Add or view expenses<br>"
            "📈 Show analytics and reports<br>"
            "📥 Download expense CSV<br>"
            "👤 Manage your profile<br>"
            "Just tell me what you'd like to do!"
        )

    # ---- THANKS ----
    elif any(word in user_input for word in ["thank", "thanks", "thank you"]):
        response = "You're very welcome! 😊 Anything else you'd like help with?"

    # ---- EXIT ----
    elif any(word in user_input for word in ["bye", "goodbye", "see you"]):
        response = "Goodbye! 👋 Remember to track your expenses regularly to stay financially smart!"

    # ---- FUZZY MATCH (fallback) ----
    else:
        options = {
            "add": 'To add a new expense, <a href="/add_expense" class="text-blue-600 hover:underline">click here</a>.',
            "view": 'View all your expenses on <a href="/dashboard" class="text-blue-600 hover:underline">Dashboard</a>.',
            "analytics": 'Check analytics at <a href="/analytics" class="text-blue-600 hover:underline">Analytics</a>.',
            "csv": 'Download your data <a href="/download_csv" class="text-blue-600 hover:underline">here</a>.',
            "profile": 'Manage your profile <a href="/profile" class="text-blue-600 hover:underline">here</a>.'
        }
        best_match = None
        best_score = 0
        for key, msg in options.items():
            score = fuzz.partial_ratio(key, user_input)
            if score > best_score:
                best_score = score
                best_match = msg
        if best_score > 60:
            response = best_match

    user_context[user_id] = user_input
    return response


@app.route('/chatbot')
@login_required
def chatbot():
    return render_template('chatbot.html')


@app.route('/chatbot/message', methods=['POST'])
@login_required
def chatbot_message():
    user_message = request.json.get('message', '')
    reply = get_bot_response(user_message, session['user_id'])
    return jsonify({'response': reply})

# ---------------- RUN APP ----------------
if __name__ == '__main__':
    app.run(debug=True)
