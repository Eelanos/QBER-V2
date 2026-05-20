import os
import calendar
import pandas as pd
import numpy as np
from dotenv import load_dotenv
import os
load_dotenv()
from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from auth import setup_auth
from datetime import timedelta

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY")
setup_auth(app)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=3)  # or days=7, etc.
# ==========================================
# 1. DATABASE CONFIGURATION
# ==========================================
DB_CREDS = {
    "u": os.getenv("MYSQL_USER"),
    "p": os.getenv("MYSQL_PASSWORD"),
    "h": os.getenv("MYSQL_HOST"),
    "d": os.getenv("MYSQL_DB")
}

DB_CREDS_MATRIX = {
    "u": os.getenv("MYSQL_MATRIX_USER"),
    "p": os.getenv("MYSQL_MATRIX_PASSWORD"),
    "h": os.getenv("MYSQL_MATRIX_HOST"),
    "d": os.getenv("MYSQL_MATRIX_DB")
}

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///local_auth.db'
app.config['SQLALCHEMY_BINDS'] = {
    'external_mysql':        f"mysql+pymysql://{DB_CREDS['u']}:{DB_CREDS['p']}@{DB_CREDS['h']}/{DB_CREDS['d']}",
    'external_mysql_matrix': f"mysql+pymysql://{DB_CREDS_MATRIX['u']}:{DB_CREDS_MATRIX['p']}@{DB_CREDS_MATRIX['h']}/{DB_CREDS_MATRIX['d']}"
}
db = SQLAlchemy(app)


# ==========================================
# 2. HELPERS
# ==========================================
def fetch_data(sql, params=None):
    with app.app_context():
        with db.engines['external_mysql'].connect() as conn:
            return pd.read_sql_query(text(sql), conn, params=params)


def fetch_data_matrix(sql, params=None):
    """Read from pc_analysis_matrix database (old dataset – used for QBER Cost Matrix)."""
    with app.app_context():
        with db.engines['external_mysql_matrix'].connect() as conn:
            return pd.read_sql_query(text(sql), conn, params=params)


def get_fy_sort_key(month_name):
    try:
        if not month_name: return 99
        m = month_name.strip()[:3].lower()
        mapping = {
            'apr': 1, 'may': 2, 'jun': 3,
            'jul': 4, 'aug': 5, 'sep': 6,
            'oct': 7, 'nov': 8, 'dec': 9,
            'jan': 10, 'feb': 11, 'mar': 12
        }
        return mapping.get(m, 99)
    except:
        return 99


def build_global_where(req):
    sel_plant = req.get('plant', 'All')
    sel_bu = req.get('bu', 'All')
    sel_pg = req.get('product_group', 'All')
    sel_seg = req.get('segment', 'All')

    sel_years = req.get('years', [])
    sel_months = req.get('months', [])
    sel_quarters = req.get('quarters', [])

    quarter_map = {
        'Q1': ['APR', 'MAY', 'JUN'],
        'Q2': ['JUL', 'AUG', 'SEP'],
        'Q3': ['OCT', 'NOV', 'DEC'],
        'Q4': ['JAN', 'FEB', 'MAR']
    }

    final_months = set(sel_months)
    for q in sel_quarters:
        if q in quarter_map:
            final_months.update(quarter_map[q])

    final_months = list(final_months)

    conditions = ["1=1"]

    if sel_plant != 'All': conditions.append(f"plant = '{sel_plant}'")
    if sel_bu != 'All': conditions.append(f"bu = '{sel_bu}'")
    if sel_pg != 'All': conditions.append(f"product_group = '{sel_pg}'")
    if sel_seg != 'All': conditions.append(f"mkt_segment = '{sel_seg}'")

    if sel_years and 'All' not in sel_years:
        if isinstance(sel_years, list):
            years_str = "', '".join(sel_years)
            conditions.append(f"fy IN ('{years_str}')")
        else:
            conditions.append(f"fy = '{sel_years}'")

    if final_months:
        months_str = "', '".join(final_months)
        conditions.append(f"month IN ('{months_str}')")

    return " AND ".join(conditions)


# ==========================================
# 3. ROUTES
# ==========================================

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/ask-qber')
def ask_qber_page():
    return render_template('ask_qber.html')


@app.route('/api/get_filter_options', methods=['GET'])
def get_filter_options():
    try:
        df_plant = fetch_data("SELECT DISTINCT plant FROM pc_analysis_data ORDER BY plant")
        plants = df_plant['plant'].dropna().unique().tolist()

        df_bu = fetch_data("SELECT DISTINCT bu FROM pc_analysis_data ORDER BY bu")
        bus = df_bu['bu'].dropna().unique().tolist()

        df_pg = fetch_data("SELECT DISTINCT product_group FROM pc_analysis_data ORDER BY product_group")
        pgs = df_pg['product_group'].dropna().unique().tolist()

        df_seg = fetch_data("SELECT DISTINCT mkt_segment FROM pc_analysis_data ORDER BY mkt_segment")
        segs = df_seg['mkt_segment'].dropna().unique().tolist()

        df_cust = fetch_data("SELECT DISTINCT customers FROM pc_analysis_data ORDER BY customers")
        customers = df_cust['customers'].dropna().unique().tolist()

        df_prod = fetch_data("SELECT DISTINCT products FROM pc_analysis_data ORDER BY products")
        products = df_prod['products'].dropna().unique().tolist()

        df_fy = fetch_data("SELECT DISTINCT fy FROM pc_analysis_data ORDER BY fy DESC")
        years = df_fy['fy'].dropna().unique().tolist()

        df_mon = fetch_data("SELECT DISTINCT month FROM pc_analysis_data")
        months = sorted(df_mon['month'].dropna().unique().tolist(), key=get_fy_sort_key)

        df_fy_mon = fetch_data("SELECT DISTINCT fy, month FROM pc_analysis_data")
        fy_month_map = {}
        for index, row in df_fy_mon.iterrows():
            fy_val = row['fy']
            mon_val = row['month']
            if fy_val and mon_val:
                if fy_val not in fy_month_map:
                    fy_month_map[fy_val] = []
                if mon_val not in fy_month_map[fy_val]:
                    fy_month_map[fy_val].append(mon_val)

        return jsonify({
            'plants': plants,
            'bus': bus,
            'product_groups': pgs,
            'segments': segs,
            'customers': customers,
            'products': products,
            'years': years,
            'months': months,
            'fy_month_map': fy_month_map
        })
    except Exception as e:
        print(f"Filter Error: {e}")
        return jsonify(
            {'plants': [], 'bus': [], 'customers': [], 'products': [], 'years': [], 'months': [], 'fy_month_map': {}})


@app.route('/api/curve_dashboard_data', methods=['POST'])
def curve_dashboard_data():
    req = request.json
    global_where = build_global_where(req)

    customer_chart_filter = req.get('customer_chart_filter', 'All')
    product_chart_filter = req.get('product_chart_filter', 'All')

    def get_cumulative_data(group_col, target_filter_cust=None, target_filter_prod=None):
        col_to_use = group_col
        where_clause = global_where

        if target_filter_cust and target_filter_cust != 'All':
            where_clause += f" AND customers = '{target_filter_cust}'"

        if target_filter_prod and target_filter_prod != 'All':
            where_clause += f" AND products = '{target_filter_prod}'"

        sql = f"""
            SELECT {col_to_use} as label, 
                   SUM(CAST(REPLACE(ind_ebit, ',', '') AS DECIMAL(18,2))) as value
            FROM pc_analysis_data WHERE {where_clause}
            GROUP BY {col_to_use} ORDER BY value DESC
        """
        try:
            df = fetch_data(sql)
            if not df.empty:
                df['value'] = df['value'] / 100000  # Convert to Lakhs
                df['cumulative'] = df['value'].cumsum()
                return {
                    'labels': df['label'].tolist(),
                    'cumulative': df['cumulative'].round(2).tolist(),
                    'values': df['value'].round(2).tolist()
                }
        except Exception as e:
            print(f"Curve Error ({group_col}): {e}")

        return {'labels': [], 'cumulative': [], 'values': []}

    if customer_chart_filter != 'All':
        customer_chart_data = get_cumulative_data('products', target_filter_cust=customer_chart_filter)
    else:
        customer_chart_data = get_cumulative_data('customers', target_filter_cust='All')

    if product_chart_filter != 'All':
        product_chart_data = get_cumulative_data('customers', target_filter_prod=product_chart_filter)
    else:
        product_chart_data = get_cumulative_data('products', target_filter_prod='All')

    return jsonify({
        'product': product_chart_data,
        'customer': customer_chart_data
    })


@app.route('/api/matrix_data', methods=['POST'])
def matrix_data():
    req = request.json
    global_where = build_global_where(req)

    matrix_type = req.get('matrix_type', 'customer')
    group_col = 'products' if matrix_type == 'product' else 'customers'

    ebit_loss_thresh = float(req.get('ebit_loss', 0))
    ebit_profit_thresh = float(req.get('ebit_profit', 200000))

    manual_vol_low = req.get('vol_low')
    manual_vol_high = req.get('vol_high')

    vol_col = "qty_sqm"
    try:
        fetch_data("SELECT qty_sqm FROM pc_analysis_data LIMIT 1")
    except:
        vol_col = "qty_km"

    sql = f"""
        SELECT {group_col} as label, 
               SUM(CAST(REPLACE(ind_ebit, ',', '') AS DECIMAL(18,2))) as ebit,
               SUM(CAST(REPLACE({vol_col}, ',', '') AS DECIMAL(18,2))) as volume,
               SUM(CAST(REPLACE(sales, ',', '') AS DECIMAL(18,2))) as sales
        FROM pc_analysis_data
        WHERE {global_where}
        GROUP BY {group_col}
    """
    try:
        df = fetch_data(sql)
        if df.empty: return jsonify({'status': 'empty'})

        df['ebit'] = pd.to_numeric(df['ebit'], errors='coerce').fillna(0)
        df['volume'] = pd.to_numeric(df['volume'], errors='coerce').fillna(0)
        df['sales'] = pd.to_numeric(df['sales'], errors='coerce').fillna(0)

        if manual_vol_low is not None and manual_vol_high is not None and manual_vol_low != '' and manual_vol_high != '':
            v_low = float(manual_vol_low)
            v_high = float(manual_vol_high)
        else:
            v_low = df['volume'].quantile(0.33)
            v_high = df['volume'].quantile(0.66)

        def get_bucket(row):
            if row['ebit'] > ebit_profit_thresh:
                profit_type = 'Profit'
            elif row['ebit'] < ebit_loss_thresh:
                profit_type = 'Loss'
            else:
                profit_type = 'BE'

            if row['volume'] <= v_low:
                vol_type = 'Low'
            elif row['volume'] <= v_high:
                vol_type = 'Moderate'
            else:
                vol_type = 'High'
            return f"{vol_type}_{profit_type}"

        df['bucket'] = df.apply(get_bucket, axis=1)

        result = {}
        buckets = ['Low_Profit', 'Moderate_Profit', 'High_Profit', 'Low_BE', 'Moderate_BE', 'High_BE', 'Low_Loss',
                   'Moderate_Loss', 'High_Loss']

        for b in buckets:
            subset = df[df['bucket'] == b].copy()
            subset['ebit_val'] = subset['ebit'] / 100000  # In Lakhs

            details = []
            if not subset.empty:
                details = subset.apply(lambda r: {
                    'name': r['label'], 'vol': r['volume'], 'sales': r['sales'], 'ebit': r['ebit']
                }, axis=1).tolist()

            result[b] = {
                'labels': subset['label'].tolist(),
                'x': subset['volume'].tolist(),
                'y': subset['ebit_val'].tolist(),
                'details': details,
                'count': len(subset),
                'total_box_ebit': subset['ebit'].sum(),
                'total_box_vol': subset['volume'].sum(),
                'total_box_sales': subset['sales'].sum()
            }

        result['meta'] = {
            'total_ebit': df['ebit'].sum(),
            'total_vol': df['volume'].sum(),
            'total_sales': df['sales'].sum(),
            'thresholds': {'ebit_loss': ebit_loss_thresh, 'ebit_profit': ebit_profit_thresh, 'vol_low': v_low,
                           'vol_high': v_high}
        }

        return jsonify(result)
    except Exception as e:
        print(f"Matrix Error: {e}")
        return jsonify({'error': str(e)})


@app.route('/test-db')
def test_db():
    import os
    import mysql.connector
    results = {}

    try:
        conn = mysql.connector.connect(
            host=os.environ.get('MYSQL_HOST'),
            user=os.environ.get('MYSQL_USER'),
            password=os.environ.get('MYSQL_PASSWORD'),
            database=os.environ.get('MYSQL_DB'),
            connect_timeout=5
        )
        conn.close()
        results['main_db'] = '✅ Connected'
    except Exception as e:
        results['main_db'] = f'❌ Failed: {str(e)}'

    try:
        conn2 = mysql.connector.connect(
            host=os.environ.get('MYSQL_MATRIX_HOST'),
            user=os.environ.get('MYSQL_MATRIX_USER'),
            password=os.environ.get('MYSQL_MATRIX_PASSWORD'),
            database=os.environ.get('MYSQL_MATRIX_DB'),
            connect_timeout=5
        )
        conn2.close()
        results['matrix_db'] = '✅ Connected'
    except Exception as e:
        results['matrix_db'] = f'❌ Failed: {str(e)}'

    return results


@app.route('/test-db-read')
def test_db_read():
    import os, mysql.connector
    from flask import jsonify
    results = {}
    try:
        conn = mysql.connector.connect(
            host=os.environ.get('MYSQL_HOST'),
            user=os.environ.get('MYSQL_USER'),
            password=os.environ.get('MYSQL_PASSWORD'),
            database=os.environ.get('MYSQL_DB'),
            connect_timeout=5
        )
        cursor = conn.cursor()

        # Check what tables exist
        cursor.execute("SHOW TABLES;")
        tables = cursor.fetchall()
        results['tables'] = [t[0] for t in tables]

        # Check row count of first table if any
        if tables:
            cursor.execute(f"SELECT COUNT(*) FROM {tables[0][0]};")
            results['first_table_count'] = cursor.fetchone()[0]

        conn.close()
    except Exception as e:
        results['error'] = str(e)

    return jsonify(results)

@app.route('/api/curve_dashboard_data_matrix', methods=['POST'])
def curve_dashboard_data_matrix():
    """
    QBER tab whale-curve endpoint – reads from pc_analysis_matrix database.
    Identical logic to curve_dashboard_data but uses fetch_data_matrix helper.
    """
    req = request.json
    global_where = build_global_where(req)

    customer_chart_filter = req.get('customer_chart_filter', 'All')
    product_chart_filter  = req.get('product_chart_filter', 'All')

    def get_cumulative_data(group_col, target_filter_cust=None, target_filter_prod=None):
        where_clause = global_where

        if target_filter_cust and target_filter_cust != 'All':
            where_clause += f" AND customers = '{target_filter_cust}'"
        if target_filter_prod and target_filter_prod != 'All':
            where_clause += f" AND products = '{target_filter_prod}'"

        sql = f"""
            SELECT {group_col} as label,
                   SUM(CAST(REPLACE(ind_ebit, ',', '') AS DECIMAL(18,2))) as value
            FROM pc_analysis_matrix_data WHERE {where_clause}
            GROUP BY {group_col} ORDER BY value DESC
        """
        try:
            df = fetch_data_matrix(sql)
            if not df.empty:
                df['value'] = df['value'] / 100000  # Convert to Lakhs
                df['cumulative'] = df['value'].cumsum()
                return {
                    'labels':     df['label'].tolist(),
                    'cumulative': df['cumulative'].round(2).tolist(),
                    'values':     df['value'].round(2).tolist()
                }
        except Exception as e:
            print(f"Curve Matrix Error ({group_col}): {e}")

        return {'labels': [], 'cumulative': [], 'values': []}

    if customer_chart_filter != 'All':
        customer_chart_data = get_cumulative_data('products', target_filter_cust=customer_chart_filter)
    else:
        customer_chart_data = get_cumulative_data('customers', target_filter_cust='All')

    if product_chart_filter != 'All':
        product_chart_data = get_cumulative_data('customers', target_filter_prod=product_chart_filter)
    else:
        product_chart_data = get_cumulative_data('products', target_filter_prod='All')

    return jsonify({
        'product':  product_chart_data,
        'customer': customer_chart_data
    })


@app.route('/api/matrix_data_old', methods=['POST'])
def matrix_data_old():
    """
    QBER Cost Matrix endpoint – reads from the pc_analysis_matrix database
    (old dataset).  Columns are identical to pc_analysis_data so the same
    build_global_where / bucketing logic applies; only the fetch helper differs.
    """
    req = request.json
    global_where = build_global_where(req)

    matrix_type = req.get('matrix_type', 'customer')
    group_col = 'products' if matrix_type == 'product' else 'customers'

    ebit_loss_thresh   = float(req.get('ebit_loss', 0))
    ebit_profit_thresh = float(req.get('ebit_profit', 200000))

    manual_vol_low  = req.get('vol_low')
    manual_vol_high = req.get('vol_high')

    # Detect volume column (same logic as main matrix_data)
    # The table inside the pc_analysis_matrix database is called pc_analysis_matrix_data
    vol_col = "qty_sqm"
    try:
        fetch_data_matrix("SELECT qty_sqm FROM pc_analysis_matrix_data LIMIT 1")
    except:
        vol_col = "qty_km"

    sql = f"""
        SELECT {group_col} as label,
               SUM(CAST(REPLACE(ind_ebit, ',', '') AS DECIMAL(18,2))) as ebit,
               SUM(CAST(REPLACE({vol_col}, ',', '') AS DECIMAL(18,2))) as volume,
               SUM(CAST(REPLACE(sales, ',', '') AS DECIMAL(18,2))) as sales
        FROM pc_analysis_matrix_data
        WHERE {global_where}
        GROUP BY {group_col}
    """
    try:
        df = fetch_data_matrix(sql)
        if df.empty:
            return jsonify({'status': 'empty'})

        df['ebit']   = pd.to_numeric(df['ebit'],   errors='coerce').fillna(0)
        df['volume'] = pd.to_numeric(df['volume'],  errors='coerce').fillna(0)
        df['sales']  = pd.to_numeric(df['sales'],   errors='coerce').fillna(0)

        if (manual_vol_low is not None and manual_vol_high is not None
                and manual_vol_low != '' and manual_vol_high != ''):
            v_low  = float(manual_vol_low)
            v_high = float(manual_vol_high)
        else:
            v_low  = df['volume'].quantile(0.33)
            v_high = df['volume'].quantile(0.66)

        def get_bucket(row):
            if   row['ebit'] > ebit_profit_thresh: profit_type = 'Profit'
            elif row['ebit'] < ebit_loss_thresh:   profit_type = 'Loss'
            else:                                   profit_type = 'BE'

            if   row['volume'] <= v_low:  vol_type = 'Low'
            elif row['volume'] <= v_high: vol_type = 'Moderate'
            else:                          vol_type = 'High'
            return f"{vol_type}_{profit_type}"

        df['bucket'] = df.apply(get_bucket, axis=1)

        result  = {}
        buckets = ['Low_Profit', 'Moderate_Profit', 'High_Profit',
                   'Low_BE',     'Moderate_BE',     'High_BE',
                   'Low_Loss',   'Moderate_Loss',   'High_Loss']

        for b in buckets:
            subset = df[df['bucket'] == b].copy()
            subset['ebit_val'] = subset['ebit'] / 100000  # Lakhs

            details = []
            if not subset.empty:
                details = subset.apply(lambda r: {
                    'name': r['label'], 'vol': r['volume'],
                    'sales': r['sales'], 'ebit': r['ebit']
                }, axis=1).tolist()

            result[b] = {
                'labels':          subset['label'].tolist(),
                'x':               subset['volume'].tolist(),
                'y':               subset['ebit_val'].tolist(),
                'details':         details,
                'count':           len(subset),
                'total_box_ebit':  subset['ebit'].sum(),
                'total_box_vol':   subset['volume'].sum(),
                'total_box_sales': subset['sales'].sum()
            }

        result['meta'] = {
            'total_ebit':  df['ebit'].sum(),
            'total_vol':   df['volume'].sum(),
            'total_sales': df['sales'].sum(),
            'thresholds': {
                'ebit_loss':   ebit_loss_thresh,
                'ebit_profit': ebit_profit_thresh,
                'vol_low':     v_low,
                'vol_high':    v_high
            }
        }

        return jsonify(result)
    except Exception as e:
        print(f"Matrix (old) Error: {e}")
        return jsonify({'error': str(e)})


@app.route('/api/get_point_details', methods=['POST'])
def get_point_details():
    req = request.json
    global_where = build_global_where(req)

    target_name = req.get('target_name')
    view_type = req.get('view_type')

    vol_col = "qty_sqm"
    try:
        fetch_data("SELECT qty_sqm FROM pc_analysis_data LIMIT 1")
    except:
        vol_col = "qty_km"

    if view_type == 'customer':
        select_col = 'products'
        where_col = 'customers'
    else:
        select_col = 'customers'
        where_col = 'products'

    cost_cols = [
        'cost_printing', 'cost_lamination', 'cost_hotmelt',
        'cost_metalling', 'cost_embossing', 'cost_jobwork',
        'cost_slitting', 'cost_packing', 'cost_cost_to_serve'
    ]

    # Check which cost columns actually exist in the table
    try:
        col_check_df = fetch_data("SELECT * FROM pc_analysis_data LIMIT 1")
        existing_cols = list(col_check_df.columns)
    except:
        existing_cols = []

    cost_select_parts = []
    for c in cost_cols:
        if c in existing_cols:
            cost_select_parts.append(
                f"SUM(CAST(REPLACE({c}, ',', '') AS DECIMAL(18,2))) as {c}"
            )
        else:
            cost_select_parts.append(f"0 as {c}")

    cost_sql_fragment = ',\n               '.join(cost_select_parts)

    sql = f"""
        SELECT {select_col} as name,
               SUM(CAST(REPLACE({vol_col}, ',', '') AS DECIMAL(18,2))) as volume,
               SUM(CAST(REPLACE(sales, ',', '') AS DECIMAL(18,2))) as sales,
               SUM(CAST(REPLACE(ind_ebit, ',', '') AS DECIMAL(18,2))) as ebit,
               {cost_sql_fragment}
        FROM pc_analysis_data
        WHERE {global_where} AND {where_col} = '{target_name}'
        GROUP BY {select_col}
        ORDER BY sales DESC
    """
    try:
        df = fetch_data(sql)
        df = df.fillna(0)
        records = df.to_dict(orient='records')
        return jsonify({'data': records, 'type': select_col.capitalize(), 'cost_cols': cost_cols})
    except Exception as e:
        print(f"Detail Error: {e}")
        return jsonify({'data': [], 'error': str(e)})


@app.route('/api/analysis_dashboard_data', methods=['POST'])
def analysis_dashboard_data():
    req = request.json
    global_where = build_global_where(req)

    cost_cols = ['cost_printing', 'cost_lamination', 'cost_hotmelt',
                 'cost_metalling', 'cost_embossing', 'cost_jobwork',
                 'cost_slitting', 'cost_packing']

    # Check which cost columns exist
    try:
        col_check_df = fetch_data("SELECT * FROM pc_analysis_data LIMIT 1")
        existing_cols = list(col_check_df.columns)
    except:
        existing_cols = []

    cost_select_parts = []
    for c in cost_cols:
        if c in existing_cols:
            cost_select_parts.append(
                f"SUM(CAST(REPLACE({c}, ',', '') AS DECIMAL(18,6))) as {c}"
            )
        else:
            cost_select_parts.append(f"0 as {c}")

    cost_sql_fragment = ',\n            '.join(cost_select_parts)

    base_sql = f"""
        SELECT 
            month, 
            plant, 
            bu, 
            mkt_segment,
            SUM(CAST(REPLACE(sales, ',', '') AS DECIMAL(18,2))) as sales,
            SUM(CAST(REPLACE(ind_va, ',', '') AS DECIMAL(18,2))) as va,
            SUM(CAST(REPLACE(ind_ebit, ',', '') AS DECIMAL(18,2))) as ebit,
            {cost_sql_fragment}
        FROM pc_analysis_data
        WHERE {global_where}
        GROUP BY month, plant, bu, mkt_segment
    """

    try:
        df = fetch_data(base_sql)

        if df.empty:
            return jsonify({'empty': True})

        # Ensure numerics
        for col in ['sales', 'va', 'ebit'] + cost_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

        # Helper to aggregate and clean
        def agg_by(grp_col):
            cols_to_sum = ['sales', 'va', 'ebit'] + cost_cols
            d = df.groupby(grp_col)[cols_to_sum].sum().reset_index()
            if grp_col == 'month':
                d['sort_key'] = d['month'].apply(get_fy_sort_key)
                d = d.sort_values('sort_key').drop('sort_key', axis=1)
            else:
                d = d.sort_values('sales', ascending=False)  # Default sort by sales

            result = {
                'labels': d[grp_col].tolist(),
                'sales': (d['sales'] / 100000).tolist(),  # In Lakhs
                'va': (d['va'] / 100000).tolist(),  # In Lakhs
                'ebit': (d['ebit'] / 100000).tolist(),  # In Lakhs
                'raw_sales': d['sales'].tolist(),
                'raw_va': d['va'].tolist(),
                'raw_ebit': d['ebit'].tolist()
            }
            if grp_col == 'month':
                for c in cost_cols:
                    result[c] = (d[c] / 100000).tolist()  # In Lakhs
            return result

        by_month = agg_by('month')
        by_plant = agg_by('plant')
        by_bu = agg_by('bu')
        by_seg = agg_by('mkt_segment')

        # --- Calculations for Line Charts ---
        # 1. Month Cost Ratio = (Sales - VA) / Sales
        cost_ratio = []
        for s, v in zip(by_month['raw_sales'], by_month['raw_va']):
            val = ((s - v) / s * 100) if s != 0 else 0
            cost_ratio.append(val)

        # 2. Month EBIT % (Formula: EBIT / Sales)
        ebit_pct_va = []
        for e, s in zip(by_month['raw_ebit'], by_month['raw_sales']):
            val = (e / s * 100) if s != 0 else 0
            ebit_pct_va.append(val)

        # 3. Month Contribution Margin % = VA / Sales
        contrib_margin = []
        for s, v in zip(by_month['raw_sales'], by_month['raw_va']):
            val = (v / s * 100) if s != 0 else 0
            contrib_margin.append(val)

        # 4. Direct Cost = Sales - VA (in Lakhs)
        direct_cost = [(s - v) for s, v in zip(by_month['sales'], by_month['va'])]

        # 5. Fixed Cost = VA - EBIT (in Lakhs)
        fixed_cost = [(v - e) for v, e in zip(by_month['va'], by_month['ebit'])]

        # 6. Segment direct_cost and fixed_cost
        seg_direct_cost = [(s - v) for s, v in zip(by_seg['sales'], by_seg['va'])]
        seg_fixed_cost  = [(v - e) for v, e in zip(by_seg['va'],   by_seg['ebit'])]

        return jsonify({
            'month': {**by_month, 'cost_ratio': cost_ratio, 'ebit_pct_va': ebit_pct_va,
                      'contrib_margin': contrib_margin, 'direct_cost': direct_cost,
                      'fixed_cost': fixed_cost},
            'plant': by_plant,
            'bu': by_bu,
            'segment': {**by_seg, 'direct_cost': seg_direct_cost, 'fixed_cost': seg_fixed_cost}
        })

    except Exception as e:
        print(f"Analysis Data Error: {e}")
        return jsonify({'error': str(e)})


@app.route('/api/segment_month_data', methods=['POST'])
def segment_month_data():
    """Return month-wise fixed cost for a specific market segment."""
    req = request.json
    segment_name = req.get('segment_name', '')
    global_where = build_global_where(req)

    sql = f"""
        SELECT month,
            SUM(CAST(REPLACE(ind_va,   ',', '') AS DECIMAL(18,2))) as va,
            SUM(CAST(REPLACE(ind_ebit, ',', '') AS DECIMAL(18,2))) as ebit
        FROM pc_analysis_data
        WHERE {global_where} AND mkt_segment = '{segment_name}'
        GROUP BY month
    """
    try:
        df = fetch_data(sql)
        if df.empty:
            return jsonify({'empty': True})
        df['va']   = pd.to_numeric(df['va'],   errors='coerce').fillna(0)
        df['ebit'] = pd.to_numeric(df['ebit'], errors='coerce').fillna(0)
        df['sort_key'] = df['month'].apply(get_fy_sort_key)
        df = df.sort_values('sort_key').drop('sort_key', axis=1)
        fixed_cost = ((df['va'] - df['ebit']) / 100000).round(2).tolist()
        return jsonify({
            'labels': df['month'].tolist(),
            'fixed_cost': fixed_cost
        })
    except Exception as e:
        print(f"Segment Month Data Error: {e}")
        return jsonify({'error': str(e)})


@app.route('/api/bu_plant_distribution', methods=['POST'])
def bu_plant_distribution():
    """Return plant-wise VA distribution for a specific BU (for pie chart)."""
    req = request.json
    bu_name = req.get('bu_name', '')
    global_where = build_global_where(req)

    sql = f"""
        SELECT plant,
            SUM(CAST(REPLACE(ind_va, ',', '') AS DECIMAL(18,2))) as va
        FROM pc_analysis_data
        WHERE {global_where} AND bu = '{bu_name}'
        GROUP BY plant
        ORDER BY va DESC
    """
    try:
        df = fetch_data(sql)
        if df.empty:
            return jsonify({'empty': True})
        df['va'] = pd.to_numeric(df['va'], errors='coerce').fillna(0)
        df = df[df['va'] > 0]
        return jsonify({
            'plants': df['plant'].tolist(),
            'va_values': (df['va'] / 100000).round(2).tolist()
        })
    except Exception as e:
        print(f"BU Plant Distribution Error: {e}")
        return jsonify({'error': str(e)})


@app.route('/api/plant_month_data', methods=['POST'])
def plant_month_data():
    """Return month-wise direct cost and fixed cost for a specific plant."""
    req = request.json
    plant_name = req.get('plant_name', '')
    global_where = build_global_where(req)

    cost_cols = ['cost_printing', 'cost_lamination', 'cost_hotmelt',
                 'cost_metalling', 'cost_embossing', 'cost_jobwork',
                 'cost_slitting', 'cost_packing', 'cost_cost_to_serve']

    try:
        col_check_df = fetch_data("SELECT * FROM pc_analysis_data LIMIT 1")
        existing_cols = list(col_check_df.columns)
    except:
        existing_cols = []

    cost_select_parts = []
    for c in cost_cols:
        if c in existing_cols:
            cost_select_parts.append(f"SUM(CAST(REPLACE({c}, ',', '') AS DECIMAL(18,6))) as {c}")
        else:
            cost_select_parts.append(f"0 as {c}")
    cost_sql_fragment = ',\n            '.join(cost_select_parts)

    sql = f"""
        SELECT month,
            SUM(CAST(REPLACE(sales, ',', '') AS DECIMAL(18,2))) as sales,
            SUM(CAST(REPLACE(ind_va, ',', '') AS DECIMAL(18,2))) as va,
            SUM(CAST(REPLACE(ind_ebit, ',', '') AS DECIMAL(18,2))) as ebit,
            {cost_sql_fragment}
        FROM pc_analysis_data
        WHERE {global_where} AND plant = '{plant_name}'
        GROUP BY month
    """
    try:
        df = fetch_data(sql)
        if df.empty:
            return jsonify({'empty': True})
        for col in ['sales', 'va', 'ebit'] + cost_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        df['sort_key'] = df['month'].apply(get_fy_sort_key)
        df = df.sort_values('sort_key').drop('sort_key', axis=1)
        direct_cost = ((df['sales'] - df['va']) / 100000).round(2).tolist()
        fixed_cost = ((df['va'] - df['ebit']) / 100000).round(2).tolist()
        result = {
            'labels': df['month'].tolist(),
            'direct_cost': direct_cost,
            'fixed_cost': fixed_cost,
        }
        for c in cost_cols:
            result[c] = (df[c] / 100000).round(2).tolist()
        return jsonify(result)
    except Exception as e:
        print(f"Plant Month Data Error: {e}")
        return jsonify({'error': str(e)})

@app.route('/api/stock_analysis', methods=['POST'])
def stock_analysis():
    req = request.json
    sel_years    = req.get('years', [])
    sel_months   = req.get('months', [])
    sel_quarters = req.get('quarters', [])
    sel_plant    = req.get('plant', 'All')
    sel_bu       = req.get('bu', 'All')

    quarter_map = {
        'Q1': ['APR', 'MAY', 'JUN'],
        'Q2': ['JUL', 'AUG', 'SEP'],
        'Q3': ['OCT', 'NOV', 'DEC'],
        'Q4': ['JAN', 'FEB', 'MAR']
    }
    final_months = set(sel_months)
    for q in sel_quarters:
        if q in quarter_map:
            final_months.update(quarter_map[q])

    conditions = ["1=1"]
    if sel_plant and sel_plant != 'All':
        conditions.append(f"plant = '{sel_plant}'")
    if sel_bu and sel_bu != 'All':
        conditions.append(f"bu = '{sel_bu}'")
    if sel_years and 'All' not in sel_years:
        years_str = "', '".join(sel_years) if isinstance(sel_years, list) else sel_years
        conditions.append(f"fy IN ('{years_str}')")
    if final_months:
        months_str = "', '".join(final_months)
        conditions.append(f"month IN ('{months_str}')")

    where = " AND ".join(conditions)
    sql = f"""
        SELECT month,
            SUM(amount)      AS amount,
            SUM(non_moving)  AS non_moving,
            SUM(slow_moving) AS slow_moving
        FROM closing_stock
        WHERE {where}
        GROUP BY month
    """
    try:
        df = fetch_data(sql)
        print(f"[Stock Analysis] rows returned: {len(df)}, SQL: {sql}")
        if df.empty:
            return jsonify({'empty': True})
        for col in ['amount', 'non_moving', 'slow_moving']:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        df['sort_key'] = df['month'].apply(get_fy_sort_key)
        df = df.sort_values('sort_key').drop('sort_key', axis=1)
        return jsonify({
            'labels':      df['month'].tolist(),
            'amount':      (df['amount']      / 100000).round(2).tolist(),
            'non_moving':  (df['non_moving']  / 100000).round(2).tolist(),
            'slow_moving': (df['slow_moving'] / 100000).round(2).tolist(),
        })
    except Exception as e:
        print(f"[Stock Analysis] ERROR: {e}")
        return jsonify({'error': str(e)})


@app.route('/api/stock_ageing_analysis', methods=['POST'])
def stock_ageing_analysis():
    """Return month-wise stacked ageing buckets from stock_ageing table."""
    req          = request.json
    sel_years    = req.get('years', [])
    sel_months   = req.get('months', [])
    sel_quarters = req.get('quarters', [])
    sel_plant    = req.get('plant', 'All')
    sel_bu       = req.get('bu', 'All')

    quarter_map = {
        'Q1': ['APR','MAY','JUN'], 'Q2': ['JUL','AUG','SEP'],
        'Q3': ['OCT','NOV','DEC'], 'Q4': ['JAN','FEB','MAR']
    }
    final_months = set(sel_months)
    for q in sel_quarters:
        if q in quarter_map:
            final_months.update(quarter_map[q])

    conditions = ["1=1"]
    if sel_plant and sel_plant != 'All':
        conditions.append(f"plant = '{sel_plant}'")
    if sel_bu and sel_bu != 'All':
        conditions.append(f"bu = '{sel_bu}'")
    if sel_years and 'All' not in sel_years:
        years_str = "', '".join(sel_years) if isinstance(sel_years, list) else sel_years
        conditions.append(f"fy IN ('{years_str}')")
    if final_months:
        months_str = "', '".join(final_months)
        conditions.append(f"month IN ('{months_str}')")

    where = " AND ".join(conditions)
    sql = f"""
        SELECT month,
               SUM(below_30)      AS below_30,
               SUM(`30_to_60`)    AS `30_to_60`,
               SUM(`60_to_90`)    AS `60_to_90`,
               SUM(above_90)      AS above_90
        FROM stock_ageing
        WHERE {where}
        GROUP BY month
    """
    try:
        df = fetch_data(sql)
        if df.empty:
            return jsonify({'empty': True})
        for col in ['below_30','30_to_60','60_to_90','above_90']:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        df['sort_key'] = df['month'].apply(get_fy_sort_key)
        df = df.sort_values('sort_key').drop('sort_key', axis=1)
        scale = 100000  # convert to Lacs
        return jsonify({
            'labels':    df['month'].tolist(),
            'below_30':  (df['below_30']  / scale).round(2).tolist(),
            '30_to_60':  (df['30_to_60']  / scale).round(2).tolist(),
            '60_to_90':  (df['60_to_90']  / scale).round(2).tolist(),
            'above_90':  (df['above_90']  / scale).round(2).tolist(),
        })
    except Exception as e:
        print(f"[Stock Ageing] ERROR: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/inventory_analysis', methods=['POST'])
def inventory_analysis():
    req          = request.json
    sel_years    = req.get('years', [])
    sel_months   = req.get('months', [])
    sel_quarters = req.get('quarters', [])
    sel_plant    = req.get('plant', 'All')
    sel_bu       = req.get('bu', 'All')

    quarter_map = {
        'Q1': ['APR', 'MAY', 'JUN'],
        'Q2': ['JUL', 'AUG', 'SEP'],
        'Q3': ['OCT', 'NOV', 'DEC'],
        'Q4': ['JAN', 'FEB', 'MAR']
    }
    final_months = set(sel_months)
    for q in sel_quarters:
        if q in quarter_map:
            final_months.update(quarter_map[q])

    conditions = ["1=1"]
    if sel_plant and sel_plant != 'All':
        conditions.append(f"plant = '{sel_plant}'")
    if sel_bu and sel_bu != 'All':
        conditions.append(f"bu = '{sel_bu}'")
    if sel_years and 'All' not in sel_years:
        years_str = "', '".join(sel_years) if isinstance(sel_years, list) else sel_years
        conditions.append(f"fy IN ('{years_str}')")
    if final_months:
        months_str = "', '".join(final_months)
        conditions.append(f"month IN ('{months_str}')")

    where = " AND ".join(conditions)
    sql = f"""
        SELECT month,
               AVG(CAST(REPLACE(inventory_days, ',', '') AS DECIMAL(10,2))) AS avg_inv_days
        FROM closing_stock
        WHERE {where}
        GROUP BY month
    """
    try:
        df = fetch_data(sql)
        if df.empty:
            return jsonify({'empty': True})
        df['avg_inv_days'] = pd.to_numeric(df['avg_inv_days'], errors='coerce').fillna(0)
        df['sort_key'] = df['month'].apply(get_fy_sort_key)
        df = df.sort_values('sort_key').drop('sort_key', axis=1)
        return jsonify({
            'labels':       df['month'].tolist(),
            'avg_inv_days': df['avg_inv_days'].round(1).tolist(),
        })
    except Exception as e:
        print(f"[Inventory Analysis] ERROR: {e}")
        return jsonify({'error': str(e)})


@app.route('/api/inventory_month_breakdown', methods=['POST'])
def inventory_month_breakdown():
    """Return avg inventory days broken down by Plant and BU for a specific month."""
    req          = request.json
    month_name   = req.get('month_name', '')
    sel_years    = req.get('years', [])
    sel_plant    = req.get('plant', 'All')
    sel_bu       = req.get('bu', 'All')

    conditions = ["1=1"]
    if month_name:
        conditions.append(f"month = '{month_name}'")
    if sel_plant and sel_plant != 'All':
        conditions.append(f"plant = '{sel_plant}'")
    if sel_bu and sel_bu != 'All':
        conditions.append(f"bu = '{sel_bu}'")
    if sel_years and 'All' not in sel_years:
        years_str = "', '".join(sel_years) if isinstance(sel_years, list) else sel_years
        conditions.append(f"fy IN ('{years_str}')")

    where = " AND ".join(conditions)

    sql_plant = f"""
        SELECT plant,
               AVG(CAST(REPLACE(inventory_days, ',', '') AS DECIMAL(10,2))) AS avg_inv_days
        FROM closing_stock
        WHERE {where}
        GROUP BY plant
        ORDER BY avg_inv_days DESC
    """
    sql_bu = f"""
        SELECT bu,
               AVG(CAST(REPLACE(inventory_days, ',', '') AS DECIMAL(10,2))) AS avg_inv_days
        FROM closing_stock
        WHERE {where}
        GROUP BY bu
        ORDER BY avg_inv_days DESC
    """
    try:
        df_plant = fetch_data(sql_plant)
        df_bu    = fetch_data(sql_bu)

        if df_plant.empty and df_bu.empty:
            return jsonify({'empty': True})

        df_plant['avg_inv_days'] = pd.to_numeric(df_plant['avg_inv_days'], errors='coerce').fillna(0)
        df_bu['avg_inv_days']    = pd.to_numeric(df_bu['avg_inv_days'],    errors='coerce').fillna(0)

        return jsonify({
            'plants':     df_plant['plant'].tolist(),
            'plant_days': df_plant['avg_inv_days'].round(1).tolist(),
            'bus':        df_bu['bu'].tolist(),
            'bu_days':    df_bu['avg_inv_days'].round(1).tolist(),
        })
    except Exception as e:
        print(f"[Inventory Month Breakdown] ERROR: {e}")
        return jsonify({'error': str(e)})


@app.route('/api/stock_ageing_breakdown', methods=['POST'])
def stock_ageing_breakdown():
    """Return ageing bucket breakdown by Plant or BU for a specific month."""
    req          = request.json
    month_name   = req.get('month_name', '')
    group_by     = req.get('group_by', 'plant')   # 'plant' or 'bu'
    sel_years    = req.get('years', [])
    sel_plant    = req.get('plant', 'All')
    sel_bu       = req.get('bu', 'All')

    group_col = 'plant' if group_by == 'plant' else 'bu'

    conditions = ["1=1"]
    if month_name:
        conditions.append(f"month = '{month_name}'")
    if sel_plant and sel_plant != 'All':
        conditions.append(f"plant = '{sel_plant}'")
    if sel_bu and sel_bu != 'All':
        conditions.append(f"bu = '{sel_bu}'")
    if sel_years and 'All' not in sel_years:
        years_str = "', '".join(sel_years) if isinstance(sel_years, list) else sel_years
        conditions.append(f"fy IN ('{years_str}')")

    where = " AND ".join(conditions)
    sql = f"""
        SELECT {group_col},
               SUM(CAST(REPLACE(below_30,    ',', '') AS DECIMAL(18,2))) AS below_30,
               SUM(CAST(REPLACE(`30_to_60`,  ',', '') AS DECIMAL(18,2))) AS `30_to_60`,
               SUM(CAST(REPLACE(`60_to_90`,  ',', '') AS DECIMAL(18,2))) AS `60_to_90`,
               SUM(CAST(REPLACE(above_90,    ',', '') AS DECIMAL(18,2))) AS above_90
        FROM stock_ageing
        WHERE {where}
        GROUP BY {group_col}
        ORDER BY above_90 DESC
    """
    try:
        df = fetch_data(sql)
        if df.empty:
            return jsonify({'empty': True})
        scale = 100000
        for col in ['below_30', '30_to_60', '60_to_90', 'above_90']:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        return jsonify({
            'labels':    df[group_col].tolist(),
            'below_30':  (df['below_30']  / scale).round(2).tolist(),
            '30_to_60':  (df['30_to_60']  / scale).round(2).tolist(),
            '60_to_90':  (df['60_to_90']  / scale).round(2).tolist(),
            'above_90':  (df['above_90']  / scale).round(2).tolist(),
        })
    except Exception as e:
        print(f"[Stock Ageing Breakdown] ERROR: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/stock_month_matrix', methods=['POST'])
def stock_month_matrix():
    """Return Plant × BU closing stock matrix for a specific month."""
    req          = request.json
    month_name   = req.get('month_name', '')
    sel_years    = req.get('years', [])
    sel_plant    = req.get('plant', 'All')
    sel_bu       = req.get('bu', 'All')

    conditions = ["1=1"]
    if month_name:
        conditions.append(f"month = '{month_name}'")
    if sel_plant and sel_plant != 'All':
        conditions.append(f"plant = '{sel_plant}'")
    if sel_bu and sel_bu != 'All':
        conditions.append(f"bu = '{sel_bu}'")
    if sel_years and 'All' not in sel_years:
        years_str = "', '".join(sel_years) if isinstance(sel_years, list) else sel_years
        conditions.append(f"fy IN ('{years_str}')")

    where = " AND ".join(conditions)
    sql = f"""
        SELECT plant, bu,
               SUM(amount) AS amount
        FROM closing_stock
        WHERE {where}
        GROUP BY plant, bu
        ORDER BY plant, bu
    """
    try:
        df = fetch_data(sql)
        if df.empty:
            return jsonify({'empty': True})

        df['amount'] = pd.to_numeric(df['amount'], errors='coerce').fillna(0) / 100000

        plants  = sorted(df['plant'].unique().tolist())
        bus     = sorted(df['bu'].unique().tolist())

        # Build matrix dict: { BU: { Plant: value } }
        matrix = {bu: {} for bu in bus}
        for _, row in df.iterrows():
            matrix[row['bu']][row['plant']] = round(float(row['amount']), 2)

        # Column totals
        totals = {plant: round(float(df[df['plant'] == plant]['amount'].sum()), 2) for plant in plants}

        return jsonify({
            'plants': plants,
            'bus':    bus,
            'matrix': matrix,
            'totals': totals,
        })
    except Exception as e:
        print(f"[Stock Month Matrix] ERROR: {e}")
        return jsonify({'error': str(e)})


import ask_qber
ask_qber.init(app, fetch_data)

if __name__ == '__main__':
    app.run(debug=True)