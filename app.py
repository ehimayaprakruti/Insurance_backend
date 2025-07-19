from flask import Flask, request, jsonify
from flask_cors import CORS
import jwt
import datetime
from functools import wraps

app = Flask(__name__)
CORS(app)
app.config['SECRET_KEY'] = 'your_secret_key'

# Dummy users
users = {
    'admin': {'password': 'adminpass', 'role': 'admin'},
    'user1': {'password': 'user1pass', 'role': 'user'},
}

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            token = request.headers['Authorization'].split(" ")[1]
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            current_user = users.get(data['username'])
            if not current_user:
                return jsonify({'message': 'User not found!'}), 401
            request.user_role = current_user['role']
        except jwt.ExpiredSignatureError:
            return jsonify({'message': 'Token expired!'}), 401
        except Exception:
            return jsonify({'message': 'Token is invalid!'}), 401
        return f(*args, **kwargs)
    return decorated

@app.route('/api/login', methods=['POST'])
def login():
    auth = request.json
    print(auth)
    username = auth.get('username')
    password = auth.get('password')
    user = users.get(username)
    if not user or user['password'] != password:
        return jsonify({'message': 'Invalid credentials!'}), 401
    token = jwt.encode({
        'username': username,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=1)
    }, app.config['SECRET_KEY'], algorithm="HS256")
    return jsonify({'token': token, 'role': user['role']})

@app.route('/api/calculate', methods=['POST'])
@token_required
def calculate():
    # Only allow 'admin' and 'user' roles
    if request.user_role not in ['admin', 'user']:
        return jsonify({'message': 'Unauthorized role!'}), 403

    data = request.json
    age = int(data.get('age', 0))
    gender = str(data.get('gender', 'male')).lower()
    is_smoker = bool(data.get('isSmoker', False))
    pre_existing = bool(data.get('preExistingCondition', False))
    sum_insured = int(data.get('sumInsured', 100000))
    tenure = int(data.get('policyTenure', 1))
    add_ons = list(data.get('addOns', []))
    policy = str(data.get('policy', 'basic')).lower()

    # Base premium logic
    base = 0
    age_charge = 0
    gender_charge = 0
    smoker_charge = 0
    pre_existing_charge = 0
    sum_insured_charge = 0
    tenure_discount = 1
    add_on_charge = 0
    multiplier = 1
    
    # Fetch base premium logic from MySQL table based on policy type, age, gender, smoker, pre-existing
    import mysql.connector

    conn = mysql.connector.connect(
        host='localhost',
        port=3306,
        user='root',
        password='Admin123',
        database='insurance'
    )
    cursor = conn.cursor(dictionary=True)

    # Get base premium row for the selected policy
    # Fetch base premium from policies table
    cursor.execute("""
        SELECT base_price, multiplier FROM policies WHERE policy_name=%s
    """, (policy,))
    policy_row = cursor.fetchone()

    # Age charge
    age_condition = 'age>45' if age > 45 else 'age<=45'
    cursor.execute("""
        SELECT amount FROM charges WHERE policy_name=%s AND charge_type='age_charge' AND condition_on=%s
    """, (policy, age_condition))
    age_charge_row = cursor.fetchone()

    # Gender charge
    gender_condition = "gender='male'" if gender == 'male' else "gender!='male'"
    cursor.execute("""
        SELECT amount FROM charges WHERE policy_name=%s AND charge_type='gender_charge' AND condition_on=%s
    """, (policy, gender_condition))
    gender_charge_row = cursor.fetchone()

    # Smoker charge
    smoker_condition = 'is_smoker=true' if is_smoker else 'is_smoker=false'
    cursor.execute("""
        SELECT amount FROM charges WHERE policy_name=%s AND charge_type='smoker_charge' AND condition_on=%s
    """, (policy, smoker_condition))
    smoker_charge_row = cursor.fetchone()

    # Pre-existing condition charge
    pre_existing_condition = 'pre_existing=true' if pre_existing else 'pre_existing=false'
    cursor.execute("""
        SELECT amount FROM charges WHERE policy_name=%s AND charge_type='pre_existing_charge' AND condition_on=%s
    """, (policy, pre_existing_condition))
    pre_existing_charge_row = cursor.fetchone()

    # Compose rule dict for compatibility with rest of code
    rule = {
        'base': policy_row['base_price'] if policy_row else 0,
        'multiplier': policy_row['multiplier'] if policy_row else 1,
        'age_charge': age_charge_row['amount'] if age_charge_row else 0,
        'age_threshold': 45,
        'gender_male_charge': gender_charge_row['amount'] if gender == 'male' and gender_charge_row else 0,
        'gender_female_charge': gender_charge_row['amount'] if gender != 'male' and gender_charge_row else 0,
        'smoker_charge': smoker_charge_row['amount'] if smoker_charge_row else 0,
        'pre_existing_charge': pre_existing_charge_row['amount'] if pre_existing_charge_row else 0
    }

    if rule:
        base = rule['base']
        age_charge = rule['age_charge'] if age > rule['age_threshold'] else 0
        gender_charge = rule['gender_male_charge'] if gender == 'male' else rule['gender_female_charge']
        smoker_charge = rule['smoker_charge'] if is_smoker else 0
        pre_existing_charge = rule['pre_existing_charge'] if pre_existing else 0
        multiplier = rule['multiplier']
    else:
        base = 0
        age_charge = 0
        gender_charge = 0
        smoker_charge = 0
        pre_existing_charge = 0
        multiplier = 1

    # Sum insured logic
    if sum_insured > 500000:
        sum_insured_charge = (sum_insured - 500000) * 0.0005
    else:
        sum_insured_charge = 0

    # Tenure discount
    if tenure > 1:
        tenure_discount = 0.95  # 5% discount for multi-year

    # Add-on covers from MySQL
    add_on_charge = 0
    if add_ons:
        format_strings = ','.join(['%s'] * len(add_ons))
        cursor.execute(f"SELECT add_on_name, price FROM add_on_prices WHERE add_on_name IN ({format_strings})", tuple(add_ons))
        for row in cursor.fetchall():
            add_on_charge += row['price']

    cursor.close()
    conn.close()

    total_before_multiplier = base + age_charge + gender_charge + smoker_charge + pre_existing_charge + sum_insured_charge + add_on_charge
    total = total_before_multiplier * multiplier * tenure_discount

    breakdown = {
        'base': base,
        'age_charge': age_charge,
        'gender_charge': gender_charge,
        'smoker_charge': smoker_charge,
        'pre_existing_charge': pre_existing_charge,
        'sum_insured_charge': round(sum_insured_charge, 2),
        'add_on_charge': add_on_charge,
        'multiplier': multiplier,
        'tenure_discount': tenure_discount,
        'total_before_multiplier': round(total_before_multiplier, 2)
    }

    return jsonify({
        'premium': round(total, 2),
        'breakdown': breakdown
    })

if __name__ == '__main__':
    app.run(debug=True)
